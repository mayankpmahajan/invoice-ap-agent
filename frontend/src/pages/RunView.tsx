import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check as CheckIcon, CircleDashed, Loader2, ShieldCheck, X } from "lucide-react";
import { api, unwrap, type Check, type Extraction, type RunDetail, type RunEvent, type RunResult } from "../api/client";
import { config } from "../config";
import { Card, CheckRow, ConfidenceDot, DECISION, DecisionBadge, Empty, ErrorPanel, Skeleton, cx, money } from "../components/ui";

/** Detail is fetched once (refresh-safe), then live stage events stream in over SSE and are appended. */
function useRun(id: string) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["run", id], queryFn: () => unwrap(api.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } })) });
  const live = query.data && !["completed", "failed"].includes(query.data.status);
  const lastId = query.data?.events.at(-1)?.id ?? 0;

  useEffect(() => {
    if (!live) return;
    const es = new EventSource(`${config.apiBaseUrl}/api/runs/${id}/events?after=${lastId}`);
    es.addEventListener("stage", (m) => {
      const ev = JSON.parse((m as MessageEvent).data) as RunEvent;
      qc.setQueryData<RunDetail>(["run", id], (old) =>
        old && !old.events.some((e) => e.id === ev.id)
          ? { ...old, status: "running", current_stage: ev.stage, events: [...old.events, ev] } : old);
    });
    es.addEventListener("done", () => { es.close(); qc.invalidateQueries({ queryKey: ["run", id] }); });
    es.onerror = () => { es.close(); setTimeout(() => qc.invalidateQueries({ queryKey: ["run", id] }), 1500); };
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reconnect only when liveness changes, resuming after lastId
  }, [id, live]);
  return query;
}

export default function RunView() {
  const { id = "" } = useParams();
  const run = useRun(id);
  const [tab, setTab] = useState("checks");

  if (run.isLoading) return <div className="mx-auto max-w-6xl space-y-4"><Skeleton className="h-16" /><Skeleton className="h-96" /></div>;
  if (run.isError || !run.data) return <div className="mx-auto max-w-6xl"><ErrorPanel message={(run.error as Error)?.message ?? "Run not found"} onRetry={() => run.refetch()} /></div>;

  const r = run.data;
  const result = r.result as unknown as RunResult | null;
  const ex = result?.extraction ?? (r.events.find((e) => e.stage === "extract" && e.data?.extraction)?.data?.extraction as Extraction | undefined);

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div>
        <Link to="/" className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800">
          <ArrowLeft className="size-3.5" /> All invoices
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{r.invoice_number ?? ex?.invoice_number.value ?? r.filename}</h1>
          <DecisionBadge status={r.status} decision={r.decision} reviewer={r.reviewer_action} />
        </div>
        <div className="mt-1 text-sm text-slate-500">
          {[r.vendor_name ?? ex?.vendor_name.value, r.po_number, r.total != null ? money(r.total, r.currency) : null, r.filename]
            .filter(Boolean).join(" · ")}
        </div>
      </div>

      {r.status === "completed" && r.decision && <DecisionPanel run={r} />}
      {r.status === "failed" && <ErrorPanel message={`Run failed: ${r.error}`} />}

      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        <Timeline run={r} />
        <div className="min-w-0">
          <div className="mb-3 flex gap-1 overflow-x-auto border-b border-slate-200">
            {[["checks", "Checks"], ["fields", "Extracted fields"], ["po", "Invoice vs PO"], ["doc", "Document"], ["audit", "Audit trail"]].map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)}
                className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
                  tab === k ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-700")}>{l}</button>
            ))}
          </div>
          {tab === "checks" && <ChecksTab run={r} />}
          {tab === "fields" && (ex ? <FieldsTab ex={ex} checks={allChecks(r)} /> : <Pending />)}
          {tab === "po" && <PoTab run={r} ex={ex} />}
          {tab === "doc" && <DocTab run={r} pages={result?.page_count ?? (r.events.find((e) => e.stage === "ingest" && e.data)?.data?.pages as number | undefined)} />}
          {tab === "audit" && <AuditTab run={r} result={result} />}
        </div>
      </div>
    </div>
  );
}

const Pending = () => <Empty>Waiting for this stage to finish…</Empty>;

function allChecks(r: RunDetail): Check[] {
  const res = r.result as unknown as RunResult | null;
  if (res?.checks) return res.checks;
  return r.events.flatMap((e) => (e.data?.checks as Check[] | undefined) ?? []);
}

function DecisionPanel({ run }: { run: RunDetail }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const review = useMutation({
    mutationFn: (action: "approved" | "rejected") =>
      unwrap(api.POST("/api/runs/{run_id}/review", { params: { path: { run_id: run.id } }, body: { action, note } })),
    onSuccess: () => qc.invalidateQueries(),
  });
  const d = DECISION[run.decision!];
  const flagged = allChecks(run).filter((c) => c.outcome === "review" || c.outcome === "reject");
  return (
    <div className={cx("rounded-xl px-5 py-4 ring-1 ring-inset", d.cls)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold uppercase tracking-wide opacity-80">Decision</div>
          <div className="text-lg font-semibold">{d.label}</div>
          {flagged.length ? (
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">{flagged.map((c) => <li key={c.id}><b>{c.title}:</b> {c.detail}</li>)}</ul>
          ) : <p className="mt-1 text-sm">{run.decision_summary}</p>}
        </div>
        {run.decision === "needs_review" && !run.reviewer_action && (
          <div className="flex w-full flex-col gap-2 sm:w-72">
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reviewer note (optional)"
              className="rounded-md border border-amber-300 bg-white px-2.5 py-1.5 text-sm text-slate-800 outline-none" />
            <div className="flex gap-2">
              <button onClick={() => review.mutate("approved")} disabled={review.isPending}
                className="flex-1 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700">Approve</button>
              <button onClick={() => review.mutate("rejected")} disabled={review.isPending}
                className="flex-1 rounded-md bg-white px-3 py-1.5 text-sm font-medium text-rose-700 ring-1 ring-rose-300 hover:bg-rose-50">Reject</button>
            </div>
            {review.isError && <span className="text-xs text-rose-700">{(review.error as Error).message}</span>}
          </div>
        )}
        {run.reviewer_action && (
          <div className="text-sm">Reviewer <b>{run.reviewer_action}</b>{run.reviewer_note ? `: “${run.reviewer_note}”` : ""}</div>
        )}
      </div>
    </div>
  );
}

function Timeline({ run }: { run: RunDetail }) {
  const byStage = useMemo(() => {
    const m = new Map<string, RunEvent[]>();
    run.events.forEach((e) => m.set(e.stage, [...(m.get(e.stage) ?? []), e]));
    return m;
  }, [run.events]);
  return (
    <Card title="Pipeline" action={<span className="text-xs text-slate-400">live</span>}>
      <ol className="relative space-y-4">
        {run.stages.map(([key, label], i) => {
          const evs = byStage.get(key) ?? [];
          const last = evs.at(-1);
          const start = evs.find((e) => e.status === "started");
          const state = !last ? "pending" : last.status;
          const ms = start && last && last !== start ? new Date(last.ts).getTime() - new Date(start.ts).getTime() : null;
          const failedHere = run.status === "failed" && run.current_stage === key;
          return (
            <li key={key} className="flex gap-3">
              <div className="flex flex-col items-center">
                <StageIcon state={failedHere ? "failed" : state} />
                {i < run.stages.length - 1 && <div className="mt-1 w-px flex-1 bg-slate-200" />}
              </div>
              <div className="min-w-0 pb-1">
                <div className="flex items-baseline gap-2">
                  <span className={cx("text-sm font-medium", state === "pending" ? "text-slate-400" : "text-slate-800")}>{label}</span>
                  {ms != null && <span className="text-xs tabular-nums text-slate-400">{ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`}</span>}
                </div>
                {last && <div className="text-xs text-slate-500">{last.title}</div>}
                <StageNotes data={last?.data} />
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

function StageNotes({ data }: { data: Record<string, unknown> | null | undefined }) {
  if (!data) return null;
  const checks = (data.checks as Check[] | undefined)?.filter((c) => c.outcome !== "pass") ?? [];
  const call = data.call as { model?: string; output_tokens?: number } | undefined;
  const llm = data.llm === true ? `model call · ${data.settled_by === "critique" ? "settled by second model" : "generator"} · ${data.confidence}` :
    data.llm === false ? "exact identifiers · no model call" : null;
  return (
    <div className="mt-1 space-y-0.5">
      {call?.model && <div className="font-mono text-[11px] text-slate-400">{call.model}</div>}
      {llm && <div className="text-[11px] text-indigo-600">{llm}</div>}
      {checks.map((c) => (
        <div key={c.id} className={cx("text-[11px]", c.outcome === "reject" ? "text-rose-600" : c.outcome === "review" ? "text-amber-700" : "text-sky-700")}>
          • {c.title}
        </div>
      ))}
    </div>
  );
}

function StageIcon({ state }: { state: string }) {
  const base = "grid size-6 shrink-0 place-items-center rounded-full";
  if (state === "completed") return <div className={cx(base, "bg-emerald-100 text-emerald-700")}><CheckIcon className="size-3.5" /></div>;
  if (state === "started") return <div className={cx(base, "bg-indigo-100 text-indigo-700")}><Loader2 className="size-3.5 animate-spin" /></div>;
  if (state === "failed") return <div className={cx(base, "bg-rose-100 text-rose-700")}><X className="size-3.5" /></div>;
  if (state === "skipped") return <div className={cx(base, "bg-slate-100 text-slate-400")}><CircleDashed className="size-3.5" /></div>;
  return <div className={cx(base, "border border-slate-200 bg-white")} />;
}

function ChecksTab({ run }: { run: RunDetail }) {
  const checks = allChecks(run);
  if (!checks.length) return <Pending />;
  const order = { reject: 0, review: 1, info: 2, pass: 3 } as const;
  return (
    <Card>
      <div className="space-y-1">
        {[...checks].sort((a, b) => order[a.outcome] - order[b.outcome]).map((c) => <CheckRow key={c.id} {...c} />)}
      </div>
    </Card>
  );
}

const FIELDS: [keyof Extraction, string][] = [
  ["vendor_name", "Vendor"], ["vendor_tax_id", "Tax ID"], ["invoice_number", "Invoice #"], ["invoice_date", "Invoice date"],
  ["due_date", "Due date"], ["currency", "Currency"], ["po_reference", "PO reference"], ["vendor_bank_account", "Bank account"],
  ["subtotal", "Subtotal"], ["tax_amount", "Tax"], ["total", "Total"],
];

function FieldsTab({ ex, checks }: { ex: Extraction; checks: Check[] }) {
  const grounding = checks.find((c) => c.id === "grounding");
  const verified = (grounding?.evidence?.verified ?? {}) as Record<string, boolean>;
  const scanned = grounding?.title.startsWith("Scanned");
  return (
    <div className="space-y-4">
      <Card title="Header fields" action={<span className="text-xs text-slate-500">
        {scanned ? "Scanned: no embedded text to cross-check" : "✓ = value found verbatim in the PDF's own text"}</span>}>
        <div className="-mx-4 -my-4 overflow-x-auto">
          <table className="w-full text-sm">
            <tbody>
              {FIELDS.map(([k, label]) => {
                const f = ex[k] as { value: unknown; confidence: "sure" | "leaning" | "torn"; page: number | null; quote: string | null };
                return (
                  <tr key={k} className="border-b border-slate-50 align-top">
                    <td className="w-36 px-4 py-2 text-xs font-medium text-slate-500">{label}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <ConfidenceDot level={f.confidence} />
                        <span className={cx(f.value == null && "italic text-slate-400")}>{f.value == null ? "not printed" : String(f.value)}</span>
                        {verified[k as string] && <ShieldCheck className="size-3.5 text-emerald-600" aria-label="verified against text layer" />}
                      </div>
                      {f.quote && <div className="mt-0.5 font-mono text-[11px] text-slate-400">p.{f.page} “{f.quote}”</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      {ex.doubts && <div className="rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-600"><b>Reader's doubts:</b> {ex.doubts}</div>}
      <div className="flex items-center gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><ConfidenceDot level="sure" /> sure</span>
        <span className="flex items-center gap-1.5"><ConfidenceDot level="leaning" /> leaning</span>
        <span className="flex items-center gap-1.5"><ConfidenceDot level="torn" /> torn</span>
      </div>
    </div>
  );
}

interface PoLine { id: string; sku: string | null; description: string; quantity: number; unit_price: number }

function PoTab({ run, ex }: { run: RunDetail; ex?: Extraction }) {
  const poEv = run.events.find((e) => e.stage === "po_checks" && e.status !== "started");
  const matchEv = run.events.find((e) => e.stage === "match" && e.status === "completed");
  if (!poEv || !ex) return <Pending />;
  const po = poEv.data?.po as { po_number: string; total: number; currency: string; lines: PoLine[] } | null;
  if (!po) return <Empty>No purchase order was matched, so there is nothing to compare.</Empty>;
  const map = (matchEv?.data?.line_map as (string | null)[] | undefined) ?? [];
  const bal = ((poEv.data?.checks as Check[]) ?? []).find((c) => c.id === "po_balance")?.evidence as
    { po_total: number; billed_before: number; this_invoice: number; prior_invoices: string[] } | undefined;
  const cur = po.currency;
  return (
    <div className="space-y-4">
      <Card title={`Lines vs ${po.po_number}`}>
        <div className="-mx-4 -my-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr className="border-b border-slate-100">
                {["Invoice line", "Matched PO line", "Qty (inv / PO)", "Unit price (inv / PO)"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {ex.line_items.map((li, i) => {
                const pl = po.lines.find((l) => l.id === map[i]);
                const priceOff = pl && li.unit_price != null && li.unit_price !== pl.unit_price;
                return (
                  <tr key={i} className="border-b border-slate-50">
                    <td className="px-4 py-2">{li.description}{li.sku && <div className="font-mono text-[11px] text-slate-400">{li.sku}</div>}</td>
                    <td className="px-4 py-2">{pl ? pl.description : <span className="text-amber-700">not on PO</span>}</td>
                    <td className="px-4 py-2 tabular-nums">{li.quantity ?? "—"} / {pl?.quantity ?? "—"}</td>
                    <td className={cx("px-4 py-2 tabular-nums", priceOff && "text-amber-700")}>{money(li.unit_price, cur)} / {pl ? money(pl.unit_price, cur) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      {bal && (
        <Card title="PO balance">
          <BalanceBar total={bal.po_total} before={bal.billed_before} now={bal.this_invoice} cur={cur} />
          {bal.prior_invoices?.length > 0 && <div className="mt-2 text-xs text-slate-500">Previously approved against this PO: {bal.prior_invoices.join(", ")}</div>}
        </Card>
      )}
    </div>
  );
}

function BalanceBar({ total, before, now, cur }: { total: number; before: number; now: number; cur: string }) {
  const max = Math.max(total, before + now);
  const pct = (v: number) => `${(v / max) * 100}%`;
  const over = before + now > total;
  return (
    <div>
      <div className="relative h-3 overflow-hidden rounded-full bg-slate-100">
        <div className="absolute inset-y-0 left-0 bg-slate-400" style={{ width: pct(before) }} />
        <div className={cx("absolute inset-y-0", over ? "bg-rose-500" : "bg-emerald-500")} style={{ left: pct(before), width: pct(now) }} />
        <div className="absolute inset-y-0 w-0.5 bg-slate-900" style={{ left: pct(total) }} title="PO total" />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-slate-400" />Invoiced before {money(before, cur)}</span>
        <span><span className={cx("mr-1 inline-block size-2 rounded-sm", over ? "bg-rose-500" : "bg-emerald-500")} />This invoice {money(now, cur)}</span>
        <span>PO total {money(total, cur)}</span>
        {over && <span className="font-medium text-rose-700">Over by {money(before + now - total, cur)}</span>}
      </div>
    </div>
  );
}

function DocTab({ run, pages }: { run: RunDetail; pages?: number }) {
  if (!pages) return <Pending />;
  return (
    <div className="space-y-3">
      <a href={`${config.apiBaseUrl}/api/runs/${run.id}/pdf`} target="_blank" rel="noreferrer" className="text-xs font-medium text-indigo-600 hover:underline">Open original PDF</a>
      {Array.from({ length: pages }, (_, i) => (
        <img key={i} src={`${config.apiBaseUrl}/api/runs/${run.id}/pages/${i + 1}`} alt={`Page ${i + 1}`}
          className="w-full rounded-lg border border-slate-200 bg-white shadow-sm" />
      ))}
    </div>
  );
}

function AuditTab({ run, result }: { run: RunDetail; result: RunResult | null }) {
  if (!result) return <Pending />;
  const p = result.provenance;
  return (
    <div className="space-y-4">
      <Card title="Model calls">
        {!p.llm_calls.length ? <Empty>No model calls.</Empty> : (
          <div className="-mx-4 -my-4 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-slate-500"><tr className="border-b border-slate-100">
                {["Role", "Model", "Prompt", "Effort", "Tokens in / out", "Latency", "Attempts"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>
                {p.llm_calls.map((c, i) => (
                  <tr key={i} className="border-b border-slate-50">
                    <td className="px-4 py-2 font-medium">{c.role}</td>
                    <td className="px-4 py-2 font-mono">{c.model}</td>
                    <td className="px-4 py-2 font-mono">{c.prompt_ref}</td>
                    <td className="px-4 py-2">{String(c.params.reasoning_effort ?? "")}</td>
                    <td className="px-4 py-2 tabular-nums">{c.input_tokens ?? "—"} / {c.output_tokens ?? "—"}</td>
                    <td className="px-4 py-2 tabular-nums">{(c.latency_ms / 1000).toFixed(1)} s</td>
                    <td className="px-4 py-2 tabular-nums">{c.attempts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Provenance">
        <dl className="grid grid-cols-[140px_1fr] gap-y-1.5 text-xs">
          <dt className="text-slate-500">Run id</dt><dd className="font-mono">{run.id}</dd>
          <dt className="text-slate-500">File SHA-256</dt><dd className="break-all font-mono">{p.file_sha256}</dd>
          <dt className="text-slate-500">Pipeline version</dt><dd className="font-mono">{p.pipeline_git_sha}</dd>
          <dt className="text-slate-500">Started / finished</dt><dd>{new Date(p.started_at).toLocaleString()} → {new Date(p.finished_at).toLocaleTimeString()}</dd>
          <dt className="text-slate-500">Match method</dt><dd>{result.match.how}{result.match.settled_by ? ` (${result.match.settled_by})` : ""}</dd>
        </dl>
      </Card>
    </div>
  );
}
