"""Central settings: every tunable, model id, and shared resource lives here.

Environment variables (all optional except OPENROUTER_API_KEY):
  OPENROUTER_API_KEY            key used for every model role (OpenRouter, OpenAI-compatible)
  LLM_BASE_URL                  default https://openrouter.ai/api/v1
  VISION_MODEL_NAME             reads invoice pages (images + text layer)
  GENERATOR_MODEL_NAME          resolves vendor / PO / line mapping when the fast path cannot
  CRITIQUE_MODEL_NAME           a different model family; answers fresh only when the generator is unsure
  *_REASONING_EFFORT            low | medium | high | xhigh | max
  *_TIMEOUT_SECONDS             per-call timeout
  *_MAX_TOKENS                  runaway-generation safety net, not a content cap
  GIT_SHA                       pipeline code version stamped into every provenance record
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


# ---------------------------------------------------------------- storage
DATA_DIR = Path(_str("DATA_DIR", str(BACKEND_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
PAGE_IMAGE_DIR = DATA_DIR / "pages"
SEED_DIR = BACKEND_DIR / "seed"
DATABASE_URL = _str("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR / 'ap.db'}")
for _d in (DATA_DIR, UPLOAD_DIR, PAGE_IMAGE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- models
LLM_BASE_URL = _str("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY = _str("OPENROUTER_API_KEY")

VISION_MODEL_NAME = _str("VISION_MODEL_NAME", "anthropic/claude-opus-5.5")
VISION_REASONING_EFFORT = _str("VISION_REASONING_EFFORT", "high")
VISION_TIMEOUT_SECONDS = _float("VISION_TIMEOUT_SECONDS", 90)
# One invoice extraction is ~1-3k output tokens; 16k only catches a runaway loop.
VISION_MAX_TOKENS = _int("VISION_MAX_TOKENS", 16000)

GENERATOR_MODEL_NAME = _str("GENERATOR_MODEL_NAME", "anthropic/claude-opus-5.5")
GENERATOR_REASONING_EFFORT = _str("GENERATOR_REASONING_EFFORT", "high")
GENERATOR_TIMEOUT_SECONDS = _float("GENERATOR_TIMEOUT_SECONDS", 90)
GENERATOR_MAX_TOKENS = _int("GENERATOR_MAX_TOKENS", 16000)

CRITIQUE_MODEL_NAME = _str("CRITIQUE_MODEL_NAME", "openai/gpt-5.6-sol")
CRITIQUE_REASONING_EFFORT = _str("CRITIQUE_REASONING_EFFORT", "high")
CRITIQUE_TIMEOUT_SECONDS = _float("CRITIQUE_TIMEOUT_SECONDS", 90)
CRITIQUE_MAX_TOKENS = _int("CRITIQUE_MAX_TOKENS", 16000)

# Schema-validation retries (model output was wrong) - owned by the call layer.
OUTPUT_VALIDATION_RETRIES = _int("OUTPUT_VALIDATION_RETRIES", 2)
# Transport retries (429 / 5xx / timeouts) - exponential backoff with jitter.
LLM_TRANSPORT_RETRIES = _int("LLM_TRANSPORT_RETRIES", 3)
RETRY_BACKOFF_BASE_SECONDS = _float("RETRY_BACKOFF_BASE_SECONDS", 2)
RETRY_BACKOFF_MAX_SECONDS = _float("RETRY_BACKOFF_MAX_SECONDS", 30)

MAX_VISION_CONCURRENCY = _int("MAX_VISION_CONCURRENCY", 4)
MAX_GENERATOR_CONCURRENCY = _int("MAX_GENERATOR_CONCURRENCY", 4)
MAX_CRITIQUE_CONCURRENCY = _int("MAX_CRITIQUE_CONCURRENCY", 2)
VISION_SEMAPHORE = asyncio.Semaphore(MAX_VISION_CONCURRENCY)
GENERATOR_SEMAPHORE = asyncio.Semaphore(MAX_GENERATOR_CONCURRENCY)
CRITIQUE_SEMAPHORE = asyncio.Semaphore(MAX_CRITIQUE_CONCURRENCY)
# Concurrent pipeline runs (uploads queue beyond this).
MAX_CONCURRENT_RUNS = _int("MAX_CONCURRENT_RUNS", 3)
RUN_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_RUNS)

# ---------------------------------------------------------------- ingestion
PDF_RENDER_DPI = _int("PDF_RENDER_DPI", 150)
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_BYTES", 20 * 1024 * 1024)
# A page whose text layer has fewer characters than this is treated as image-only (scanned).
TEXT_LAYER_MIN_CHARS_PER_PAGE = _int("TEXT_LAYER_MIN_CHARS_PER_PAGE", 40)

# ---------------------------------------------------------------- AP policy
# Price / amount tolerance: a variance is accepted only within BOTH bounds (the tighter one wins).
TOLERANCE_PCT = _float("TOLERANCE_PCT", 2.0)
TOLERANCE_ABS = _float("TOLERANCE_ABS", 50.0)
# Arithmetic checks on the invoice itself (rounding slack, in currency units).
ARITHMETIC_SLACK = _float("ARITHMETIC_SLACK", 0.02)
# Same vendor + same total within this many days, different invoice number -> possible duplicate.
NEAR_DUPLICATE_WINDOW_DAYS = _int("NEAR_DUPLICATE_WINDOW_DAYS", 30)
# Invoice dates: further in the future than this (time zones, early issue) or older than the max age -> review.
INVOICE_FUTURE_GRACE_DAYS = _int("INVOICE_FUTURE_GRACE_DAYS", 2)
INVOICE_MAX_AGE_DAYS = _int("INVOICE_MAX_AGE_DAYS", 365)
# Fields whose extraction confidence must be "sure" (or verified against the text layer).
CRITICAL_FIELDS = ("vendor_name", "invoice_number", "invoice_date", "total", "currency")

# ---------------------------------------------------------------- SSE
SSE_POLL_INTERVAL_SECONDS = _float("SSE_POLL_INTERVAL_SECONDS", 0.4)
# Pause after each fast post-read stage so the live view shows them one by one (display only; 0 disables).
STAGE_MIN_VISIBLE_SECONDS = _float("STAGE_MIN_VISIBLE_SECONDS", 0.6)

# ---------------------------------------------------------------- provenance
def _git_sha() -> str:
    env_sha = _str("GIT_SHA") or _str("RENDER_GIT_COMMIT")[:12]
    if env_sha:
        return env_sha
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=BACKEND_DIR, stderr=subprocess.DEVNULL
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "uncommitted"


PIPELINE_GIT_SHA = _git_sha()

CORS_ORIGINS = [o for o in _str("CORS_ORIGINS", "http://localhost:5173").split(",") if o]
