"""LLM call layer: one client / model per role, transport retries, schema retries, call records.

Roles:
  vision     - reads invoice pages. Goes through the OpenAI SDK directly (VLM exception to pydantic-ai);
               schema validation is done by hand with model_validate_json + error-in-context retry.
  generator  - pydantic-ai agent; resolves vendor / PO / line mapping when the deterministic fast path cannot.
  critique   - pydantic-ai agent on a different model family; answers fresh, only when the generator is unsure.

Sampling: Claude Opus 5.5 rejects temperature/top_p (400), so depth is controlled with reasoning effort only.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx2 as httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.providers.openrouter import OpenRouterProvider
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential

from app import prompts, settings
from app.pdf import Page
from app.schemas import InvoiceExtraction, MatchDecision


class NonRetryableLLMError(RuntimeError):
    pass


@dataclass
class CallRecord:
    role: str
    model: str
    prompt_ref: str
    params: dict[str, Any]
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    attempts: int = 0
    validation_errors: list[str] = field(default_factory=list)
    output: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, httpx.TimeoutException, httpx.TransportError)):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(exc, (APIStatusError, ModelHTTPError)) and status is not None:
        return status == 429 or status >= 500
    return False


def _retrying() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception(_is_transient),
        wait=wait_random_exponential(multiplier=settings.RETRY_BACKOFF_BASE_SECONDS, max=settings.RETRY_BACKOFF_MAX_SECONDS),
        stop=stop_after_attempt(settings.LLM_TRANSPORT_RETRIES),
        reraise=True,
    )


def _require_key() -> None:
    if not settings.LLM_API_KEY:
        raise NonRetryableLLMError("OPENROUTER_API_KEY is not set in backend/.env")


# --------------------------------------------------------------------- vision (OpenAI SDK)
_vision_client: AsyncOpenAI | None = None


def _client() -> AsyncOpenAI:
    global _vision_client
    if _vision_client is None:
        _require_key()
        # SDK retries off: tenacity owns transport retries with jitter.
        _vision_client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL, max_retries=0)
    return _vision_client


def _page_blocks(pages: list[Page]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for p in pages:
        b64 = base64.b64encode(p.image_path.read_bytes()).decode()
        layer = p.text.strip() if p.has_text_layer else "(no embedded text layer - scanned page; read the image)"
        blocks.append({"type": "text", "text": f'<page number="{p.number}">\n<text_layer>\n{layer}\n</text_layer>'})
        blocks.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        blocks.append({"type": "text", "text": "</page>"})
    return blocks


async def extract_invoice(pages: list[Page]) -> tuple[InvoiceExtraction, CallRecord]:
    tpl = prompts.EXTRACT_SYSTEM
    params = {"reasoning_effort": settings.VISION_REASONING_EFFORT, "max_tokens": settings.VISION_MAX_TOKENS,
              "timeout_s": settings.VISION_TIMEOUT_SECONDS}
    rec = CallRecord(role="vision", model=settings.VISION_MODEL_NAME, prompt_ref=tpl.ref, params=params)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": tpl.text},
        {"role": "user", "content": [*_page_blocks(pages), {"type": "text", "text": prompts.EXTRACT_TASK}]},
    ]
    schema = InvoiceExtraction.model_json_schema()
    started = time.monotonic()
    for _ in range(settings.OUTPUT_VALIDATION_RETRIES + 1):
        rec.attempts += 1
        async with settings.VISION_SEMAPHORE:
            async for attempt in _retrying():
                with attempt:
                    resp = await _client().chat.completions.create(
                        model=settings.VISION_MODEL_NAME,
                        messages=messages,
                        max_tokens=settings.VISION_MAX_TOKENS,
                        timeout=settings.VISION_TIMEOUT_SECONDS,
                        response_format={"type": "json_schema",
                                         "json_schema": {"name": "InvoiceExtraction", "schema": schema}},
                        extra_body={"reasoning": {"effort": settings.VISION_REASONING_EFFORT}},
                    )
        choice = resp.choices[0]
        rec.finish_reason = choice.finish_reason
        if resp.usage:
            rec.input_tokens = (rec.input_tokens or 0) + resp.usage.prompt_tokens
            rec.output_tokens = (rec.output_tokens or 0) + resp.usage.completion_tokens
        content = choice.message.content or ""
        try:
            result = InvoiceExtraction.model_validate_json(content)
            rec.latency_ms = int((time.monotonic() - started) * 1000)
            rec.output = result.model_dump()
            return result, rec
        except ValidationError as e:
            # Error-in-context retry: the model sees its exact validation error (new information).
            rec.validation_errors.append(str(e)[:2000])
            messages += [{"role": "assistant", "content": content or "(empty)"},
                         {"role": "user", "content": f"That output failed schema validation:\n{e}\nReturn the corrected JSON."}]
    rec.latency_ms = int((time.monotonic() - started) * 1000)
    raise NonRetryableLLMError(f"vision output failed schema validation after {rec.attempts} attempts")


# --------------------------------------------------------------------- matcher (pydantic-ai)
_agents: dict[str, Agent] = {}

ROLE_CFG = {
    "generator": (lambda: settings.GENERATOR_MODEL_NAME, lambda: settings.GENERATOR_REASONING_EFFORT,
                  lambda: settings.GENERATOR_MAX_TOKENS, lambda: settings.GENERATOR_TIMEOUT_SECONDS,
                  lambda: settings.GENERATOR_SEMAPHORE),
    "critique": (lambda: settings.CRITIQUE_MODEL_NAME, lambda: settings.CRITIQUE_REASONING_EFFORT,
                 lambda: settings.CRITIQUE_MAX_TOKENS, lambda: settings.CRITIQUE_TIMEOUT_SECONDS,
                 lambda: settings.CRITIQUE_SEMAPHORE),
}


def _role_params(role: str) -> dict[str, Any]:
    _, effort, max_tokens, timeout, _ = ROLE_CFG[role]
    return {"reasoning_effort": effort(), "max_tokens": max_tokens(), "timeout_s": timeout()}


def _match_agent(role: str) -> Agent:
    if role not in _agents:
        _require_key()
        name, effort, max_tokens, timeout, _ = ROLE_CFG[role]
        model = OpenRouterModel(name(), provider=OpenRouterProvider(api_key=settings.LLM_API_KEY))
        _agents[role] = Agent(
            model,
            output_type=NativeOutput(MatchDecision),
            instructions=prompts.MATCH_SYSTEM.text,
            retries=settings.OUTPUT_VALIDATION_RETRIES,
            model_settings=OpenRouterModelSettings(
                max_tokens=max_tokens(), timeout=timeout(),
                openrouter_reasoning={"effort": effort()},
            ),
        )
    return _agents[role]


async def match_invoice(role: str, invoice_json: str, vendors_block: str, pos_block: str,
                        doubt: str | None = None) -> tuple[MatchDecision, CallRecord]:
    name = ROLE_CFG[role][0]()
    sem = ROLE_CFG[role][4]()
    rec = CallRecord(role=role, model=name, prompt_ref=prompts.MATCH_SYSTEM.ref, params=_role_params(role))
    user = prompts.render_match_user(invoice_json, vendors_block, pos_block, doubt)
    started = time.monotonic()
    async with sem:
        async for attempt in _retrying():
            with attempt:
                rec.attempts += 1
                run = await _match_agent(role).run(user)
    usage = run.usage
    rec.input_tokens, rec.output_tokens = usage.input_tokens, usage.output_tokens
    rec.latency_ms = int((time.monotonic() - started) * 1000)
    rec.output = run.output.model_dump()
    return run.output, rec


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1, default=str)
