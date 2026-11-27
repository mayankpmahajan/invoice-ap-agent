import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BadgeCheck, ExternalLink } from "lucide-react";
import { api, unwrap, type Check, type Extraction, type RunDetail, type RunEvent, type RunResult } from "../api/client";
import { config } from "../config";
import { Confidence, Empty, ErrorNote, FormBox, OutcomeMark, Skeleton, Stamp, StampButton, cx, money, stampKey } from "../components/ui";

/** Detail is fetched once (refresh-safe), then live stage events stream in over SSE and are appended. */
function useRun(id: string) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["run", id],
    queryFn: () => unwrap(api.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } })),
    // Fallback while live: if the event stream drops, polling still moves the page to the final state.
    refetchInterval: (q) => (q.state.data && !["completed", "failed"].includes(q.state.data.status) ? config.liveRunPollMs : false),
  });
  const live = query.data && !["completed", "failed"].includes(query.data.status);
  const lastId = query.data?.events.at(-1)?.id ?? 0;
  useEffect(() => {
    if (!live) return;
    const es = new EventSource(`${config.apiBaseUrl}/api/runs/${id}/events?after=${lastId}`);
    es.addEventListener("stage", (m) => {
      const ev = JSON.parse((m as MessageEvent).data) as RunEvent;
      qc.setQueryData<RunDetail>(["run", id], (old) =>
        old && !old.events.some((e) => e.id === ev.id) ? { ...old, status: "running", current_stage: ev.stage, events: [...old.events, ev] } : old);
    });
    es.addEventListener("done", () => { es.close(); qc.invalidateQueries({ queryKey: ["run", id] }); });
    // No close on error: the browser reconnects the stream by itself, duplicates are dropped above, and the
    // poll keeps the page moving meanwhile.
    es.onerror = () => { qc.invalidateQueries({ queryKey: ["run", id] }); };
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reconnect only when liveness changes, resuming after lastId
  }, [id, live]);
  return query;
}

const COPIES = [
  { key: "checks", label: "Voucher checks", stock: "bg-paper" },
  { key: "fields", label: "Invoice copy", stock: "bg-canary" },
  { key: "po", label: "PO match", stock: "bg-pink" },
  { key: "doc", label: "Source", stock: "bg-goldenrod" },
  { key: "audit", label: "Audit file", stock: "bg-manila" },
] as const;

export default function RunView() {
  const { id = "" } = useParams();
  const run = useRun(id);
  const [tab, setTab] = useState<(typeof COPIES)[number]["key"]>("checks");
  // The stamp strikes only when the decision arrives while the reviewer is watching.
  const sawLive = useRef(false);
  if (run.data && run.data.status !== "completed" && run.data.status !== "failed") sawLive.current = true;

  if (run.isLoading) return <div className="space-y-5"><Skeleton className="h-44" /><Skeleton className="h-96" /></div>;
  if (run.isError || !run.data) return <ErrorNote message={(run.error as Error)?.message ?? "voucher not found"} onRetry={() => run.refetch()} />;

  const r = run.data;
  const result = r.result as unknown as RunResult | null;
  const ex = result?.extraction ?? (r.events.find((e) => e.stage === "extract" && e.data?.extraction)?.data?.extraction as Extraction | undefined);
  const copy = COPIES.find((c) => c.key === tab)!;

  return (
    <div className="space-y-6">
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> Voucher register
      </Link>

      <VoucherCover run={r} ex={ex} strike={sawLive.current} />

      <LiveRead run={r} />

      <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
        <RoutingSlip run={r} />
        <div className="min-w-0">
          <div className="flex overflow-x-auto pl-1 pt-1" role="tablist" aria-label="Packet copies">
            {COPIES.map((c, i) => (
              <button key={c.key} role="tab" aria-selected={tab === c.key} onClick={() => setTab(c.key)}
                style={{ zIndex: tab === c.key ? 20 : COPIES.length - i }}
                className={cx("relative whitespace-nowrap border border-b-0 border-rule px-4 pb-2 pt-2 text-sm font-semibold shadow-[2px_-1px_3px_-2px_rgb(27_34_32/.25)] transition-[transform,color] duration-150",
                  i > 0 && "-ml-2", c.stock, tab === c.key ? "-mb-px text-ink" : "translate-y-1 text-muted hover:translate-y-0 hover:text-ink")}>
                {c.label}
              </button>
            ))}
          </div>
          <div className={cx("sheet z-10 p-4 md:p-5", copy.stock)} role="tabpanel">
            {tab === "checks" && <ChecksCopy run={r} />}
            {tab === "fields" && (ex ? <InvoiceCopy ex={ex} checks={allChecks(r)} /> : <Waiting what="the invoice is read" />)}
            {tab === "po" && <PoCopy run={r} ex={ex} />}
            {tab === "doc" && <SourceCopy run={r} pages={result?.page_count ?? (r.events.find((e) => e.stage === "ingest" && e.data)?.data?.pages as number | undefined)} />}
            {tab === "audit" && <AuditCopy run={r} result={result} />}
          </div>
        </div>
      </div>
    </div>
  );
}

const Waiting = ({ what }: { what: string }) => (
  <div className="flex h-64 items-center justify-center text-sm text-muted">This copy is filled in once {what}.</div>
);

function allChecks(r: RunDetail): Check[] {
  const res = r.result as unknown as RunResult | null;
  return res?.checks ?? r.events.flatMap((e) => (e.data?.checks as Check[] | undefined) ?? []);
}

/* ------------------------------------------------------------------ voucher cover */
function VoucherCover({ run, ex, strike }: { run: RunDetail; ex?: Extraction; strike: boolean }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [pressed, setPressed] = useState(false);
  const review = useMutation({
    mutationFn: (action: "approved" | "rejected") =>
      unwrap(api.POST("/api/runs/{run_id}/review", { params: { path: { run_id: run.id } }, body: { action, note } })),
    onSuccess: () => { setPressed(true); qc.invalidateQueries(); },
  });
  const k = stampKey(run.status, run.decision, run.reviewer_action);
  const flagged = allChecks(run).filter((c) => c.outcome === "review" || c.outcome === "reject");
  const done = run.status === "completed";
  const headline = (run.result as unknown as RunResult | null)?.headline;

  return (
    <div className="relative mr-2.5 mt-2.5">
    {/* Carbon copies stapled behind the voucher: canary (invoice) and pink (PO). */}
    <div aria-hidden className="absolute inset-0 translate-x-2.5 -translate-y-2.5 border border-rule bg-pink" />
    <div aria-hidden className="absolute inset-0 translate-x-[5px] -translate-y-[5px] border border-rule bg-canary" />
    <section className="sheet">
      <svg aria-hidden className="absolute -top-1.5 left-8 z-10" width="54" height="14" viewBox="0 0 54 14">
        <path d="M3 11 V4 Q3 2 5 2 H49 Q51 2 51 4 V11" fill="none" stroke="#5f6b68" strokeWidth="3" strokeLinecap="round" />
        <path d="M5 3 H49" stroke="#d7dddb" strokeWidth="1" />
      </svg>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-rule px-4 pb-3 pt-4">
        <div className="min-w-0">
          <h1 className="title truncate text-[26px] leading-tight">{run.vendor_name ?? ex?.vendor_name.value ?? run.filename}</h1>
          <div className="mt-0.5 text-sm text-muted">Payment voucher <span className="typed text-carbon">{run.id.slice(0, 6).toUpperCase()}</span> · {run.filename}</div>
        </div>
      </div>
      <div className="grid md:grid-cols-[minmax(0,1fr)_260px]">
        <div className="grid grid-cols-2 [grid-template-rows:auto_auto_1fr] sm:grid-cols-4 sm:[grid-template-rows:auto_1fr] [&>*]:border-b [&>*]:border-r">
          <FormBox label="Invoice no.">{run.invoice_number ?? ex?.invoice_number.value ?? "—"}</FormBox>
          <FormBox label="Invoice date">{ex?.invoice_date.value ?? "—"}</FormBox>
          <FormBox label="Purchase order">{run.po_number ?? ex?.po_reference.value ?? "—"}</FormBox>
          <FormBox label="Amount due">{money(run.total ?? ex?.total.value, run.currency ?? ex?.currency.value)}</FormBox>
          <div className="col-span-2 !border-b-0 !border-r-0 px-3 pb-3 pt-1.5 sm:col-span-4">
            <div className="label">Disposition</div>
            {!done ? (
              <p className="mt-1 text-sm text-muted">{run.status === "failed" ? `The run stopped: ${run.error}` : "The packet is still moving through the desks. Watch the routing slip."}</p>
            ) : (
              <>
                {headline && <p className="mt-1 text-base font-semibold">{headline}</p>}
                {flagged.length ? (
                  <ul className="mt-1.5 space-y-1.5">
                    {flagged.map((c) => (
                      <li key={c.id} className="flex gap-2 text-sm"><OutcomeMark outcome={c.outcome} /><span><b className="font-semibold">{c.title}.</b> {c.detail}
                        {typeof c.evidence?.original_run === "string" && (
                          <> <Link to={`/runs/${c.evidence.original_run}`} className="font-semibold underline underline-offset-2">Open the original</Link></>
                        )}</span></li>
                    ))}
                  </ul>
                ) : <p className="mt-1 text-sm">{(run.result as unknown as RunResult | null)?.summary ?? run.decision_summary}</p>}
              </>
            )}
          {run.decision === "needs_review" && !run.reviewer_action && (
              <div className="mt-4 grid max-w-xl gap-3 border-t border-dashed border-rule pt-3 sm:grid-cols-[1fr_auto] sm:items-end">
                <label className="block">
                  <span className="label">Reviewer note</span>
                  <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional"
                    className="typed mt-1 w-full border-b border-rule bg-transparent py-1 text-sm outline-none placeholder:text-muted focus:border-carbon" />
                </label>
                <div className="flex gap-2">
                  <StampButton k="approved" label="Pay this invoice" onPress={() => review.mutate("approved")} disabled={review.isPending} />
                  <StampButton k="rejected" label="Do not pay" onPress={() => review.mutate("rejected")} disabled={review.isPending} />
                </div>
                {review.isError && <p className="text-xs text-stamp-void">{(review.error as Error).message}</p>}
              </div>
            )}
          </div>
        </div>
        <div className="flex flex-col items-center justify-center gap-4 border-rule px-4 py-6 max-md:border-t md:border-l">
          <div className="grid min-h-[104px] place-items-center">
            {done || run.status === "failed" ? <Stamp k={k} strike={strike || pressed} /> : <Stamp k="running" rot={-4} />}
          </div>
          {run.reviewer_action && (
            <p className="text-center text-xs text-muted">Held by the agent, then <b className="text-ink">{run.reviewer_action}</b> by a reviewer{run.reviewer_note ? `: “${run.reviewer_note}”` : "."}</p>
          )}
        </div>
      </div>
    </section>
    </div>
  );
}

/* ------------------------------------------------------------------ live read */
/** While the model reads the invoice (most of a run), show the page it is reading and how long it has taken. */
function LiveRead({ run }: { run: RunDetail }) {
  const ingest = run.events.find((e) => e.stage === "ingest" && e.status === "completed");
  const started = run.events.find((e) => e.stage === "extract" && e.status === "started");
  const finished = run.events.some((e) => e.stage === "extract" && e.status !== "started");
  const reading = !!ingest && !!started && !finished && run.status !== "failed" && run.status !== "completed";
  const secs = useElapsed(reading ? started?.ts : undefined);
  if (!reading) return null;
  const pages = (ingest?.data?.pages as number | undefined) ?? 1;
  return (
    <section className="sheet grid gap-4 p-4 md:grid-cols-[minmax(0,320px)_1fr] md:items-center" aria-live="polite">
      <img src={`${config.apiBaseUrl}/api/runs/${run.id}/pages/1`} alt="Invoice page being read"
        className="max-h-72 w-full border border-rule object-contain object-top" />
      <div>
        <div className="label animate-pulse text-carbon">Reading the invoice</div>
        <p className="mt-1 text-sm">{started?.title}. The model reads {pages > 1 ? `all ${pages} pages` : "the page"} and
          the PDF's own text, and quotes where each value came from so it can be checked next.</p>
        <p className="typed tnum mt-2 text-2xl">{secs} s</p>
        {secs >= config.slowReadSeconds && (
          <p className="mt-1 text-sm text-stamp-hold">Taking longer than usual. The model provider may be slow; the run carries on.</p>
        )}
      </div>
    </section>
  );
}

function useElapsed(since?: string) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!since) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [since]);
  return since ? Math.max(0, Math.round((now - new Date(since).getTime()) / 1000)) : 0;
}

/* ------------------------------------------------------------------ routing slip */
function RoutingSlip({ run }: { run: RunDetail }) {
  const byStage = useMemo(() => {
    const m = new Map<string, RunEvent[]>();
    run.events.forEach((e) => m.set(e.stage, [...(m.get(e.stage) ?? []), e]));
    return m;
  }, [run.events]);
  return (
    <aside className="sheet self-start bg-slip">
      <div className="flex items-baseline justify-between border-b border-rule px-4 py-2.5">
        <h2 className="title text-lg">Routing slip</h2>
        <span className="label">{run.status === "completed" || run.status === "failed" ? "closed" : "live"}</span>
      </div>
      <ol>
        {run.stages.map(([key, label]) => {
          const evs = byStage.get(key) ?? [];
          const last = evs.at(-1);
          const start = evs.find((e) => e.status === "started");
          const failedHere = run.status === "failed" && run.current_stage === key;
          const state = failedHere ? "failed" : last?.status ?? "pending";
          const ms = start && last && last !== start ? new Date(last.ts).getTime() - new Date(start.ts).getTime() : null;
          return (
            <li key={key} className="grid grid-cols-[1fr_auto] gap-x-3 border-b border-[#e3c6b2] px-4 py-2.5 last:border-b-0">
              <div className="min-w-0">
                <div className={cx("text-sm font-semibold", state === "pending" && "text-muted")}>{label}</div>
                {last && <div className="mt-0.5 text-xs text-muted">{last.title}</div>}
                <SlipNotes data={last?.data} />
              </div>
              <div className="text-right">
                {state === "completed" || state === "skipped" ? (
                  <div className="punch-in typed tnum text-xs leading-tight">
                    {new Date(last!.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    <div className="text-[10px] text-muted">{state === "skipped" ? "skipped" : ms != null ? (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`) : ""}</div>
                  </div>
                ) : state === "started" ? (
                  <span className="label animate-pulse text-carbon">at desk</span>
                ) : state === "failed" ? (
                  <span className="label text-stamp-void">stopped</span>
                ) : <span className="inline-block h-4 w-14 border-b border-rule" aria-label="not reached" />}
              </div>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}

function SlipNotes({ data }: { data: Record<string, unknown> | null | undefined }) {
  if (!data) return null;
  const flagged = (data.checks as Check[] | undefined)?.filter((c) => c.outcome === "review" || c.outcome === "reject") ?? [];
  const call = data.call as { model?: string } | undefined;
  const how = data.llm === true ? (data.settled_by === "critique" ? "matched by model, confirmed by a second model" : "matched by model")
    : data.llm === false ? "matched on exact identifiers" : null;
  return (
    <div className="mt-1 space-y-0.5 text-[11px]">
      {call?.model && <div className="typed text-muted">{call.model}</div>}
      {how && <div className="text-form">{how}</div>}
      {flagged.map((c) => <div key={c.id} className={c.outcome === "reject" ? "text-stamp-void" : "text-stamp-hold"}>{c.title}</div>)}
    </div>
  );
}

/* ------------------------------------------------------------------ copies */
function ChecksCopy({ run }: { run: RunDetail }) {
  const checks = allChecks(run);
  if (!checks.length) return <Waiting what="the first checks run" />;
  const order = { reject: 0, review: 1, info: 2, pass: 3 } as const;
  const done = run.status === "completed";
  const flagged = checks.filter((c) => c.outcome === "review" || c.outcome === "reject").length;
  const shown = done ? checks.filter((c) => c.outcome === "pass" || c.outcome === "info") : checks;
  return (
    <>
    <div className="mb-1 flex items-baseline justify-between gap-3">
      <h3 className="title text-lg">{done ? `${shown.length} checks cleared` : "Checks so far"}</h3>
      {done && flagged > 0 && <span className="text-sm text-muted">{flagged} held on the voucher cover above</span>}
    </div>
    <ol className="divide-y divide-rule-soft">
      {[...shown].sort((a, b) => order[a.outcome] - order[b.outcome]).map((c) => (
        <li key={c.id} className="flex gap-3 py-2.5">
          <OutcomeMark outcome={c.outcome} />
          <div className="min-w-0">
            <div className="text-sm font-semibold">{c.title}</div>
            <div className="text-sm text-muted">{c.detail}</div>
          </div>
        </li>
      ))}
    </ol>
    </>
  );
}

const FIELDS: [keyof Extraction, string][] = [
  ["vendor_name", "Vendor"], ["vendor_tax_id", "Tax ID"], ["invoice_number", "Invoice no."], ["invoice_date", "Invoice date"],
  ["due_date", "Due date"], ["currency", "Currency"], ["po_reference", "PO reference"], ["vendor_bank_account", "Remit-to account"],
  ["subtotal", "Subtotal"], ["tax_amount", "Tax"], ["total", "Total"],
];

function InvoiceCopy({ ex, checks }: { ex: Extraction; checks: Check[] }) {
  const grounding = checks.find((c) => c.id === "grounding");
  const verified = (grounding?.evidence?.verified ?? {}) as Record<string, boolean>;
  const scanned = grounding?.title.startsWith("Scanned");
  return (
    <div className="space-y-5">
      <p className="text-sm text-[#5b4b12]">
        {scanned ? "Scanned invoice: no printed text to cross-check, so the reader's confidence decides what needs a person."
          : <>Values marked <BadgeCheck className="inline size-4 text-stamp-ok" aria-label="verified" /> were found character for character in the PDF's own text.</>}
      </p>
      <div className="grid border-l border-t border-[#d9c873] sm:grid-cols-2 xl:grid-cols-3">
        {FIELDS.map(([k, label]) => {
          const f = ex[k] as { value: unknown; confidence: "sure" | "leaning" | "torn"; page: number | null; quote: string | null };
          return (
            <div key={k} className="min-w-0 border-b border-r border-[#d9c873] px-3 pb-2 pt-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="label text-[#6b5a14]">{label}</span>
                <span className="flex items-center gap-1.5">
                  {verified[k as string] && <BadgeCheck className="size-3.5 text-stamp-ok" aria-label="verified against the PDF text" />}
                  <Confidence level={f.confidence} />
                </span>
              </div>
              <div className={cx("typed mt-1 truncate text-[15px] tnum", f.value == null && "italic text-muted")}>{f.value == null ? "not printed" : String(f.value)}</div>
              {f.quote && <div className="mt-0.5 truncate text-[11px] text-[#6b5a14]" title={f.quote}>p.{f.page} “{f.quote}”</div>}
            </div>
          );
        })}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead><tr className="border-b border-[#d9c873] text-left">
            {["Line", "Qty", "Unit price", "Amount", ""].map((h, i) => <th key={i} className={cx("label px-2 py-1.5 text-[#6b5a14]", i > 0 && i < 4 && "text-right")}>{h}</th>)}
          </tr></thead>
          <tbody>
            {ex.line_items.map((li, i) => (
              <tr key={i} className="border-b border-[#e6d895]">
                <td className="px-2 py-1.5">{li.description}{li.sku && <span className="typed ml-2 text-xs text-[#6b5a14]">{li.sku}</span>}</td>
                <td className="typed tnum px-2 py-1.5 text-right">{li.quantity ?? "—"}</td>
                <td className="typed tnum px-2 py-1.5 text-right">{money(li.unit_price, ex.currency.value)}</td>
                <td className="typed tnum px-2 py-1.5 text-right">{money(li.amount, ex.currency.value)}</td>
                <td className="px-2 py-1.5 text-right"><Confidence level={li.confidence} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ex.doubts && <p className="border-t border-[#d9c873] pt-3 text-sm"><span className="label mr-2 text-[#6b5a14]">Reader's note</span>{ex.doubts}</p>}
    </div>
  );
}

interface PoLine { id: string; sku: string | null; description: string; quantity: number; unit_price: number }

function PoCopy({ run, ex }: { run: RunDetail; ex?: Extraction }) {
  const poEv = run.events.find((e) => e.stage === "po_checks" && e.status !== "started");
  const matchEv = run.events.find((e) => e.stage === "match" && e.status === "completed");
  if (!poEv || !ex) return <Waiting what="the invoice is compared with its PO" />;
  const po = poEv.data?.po as { po_number: string; total: number; currency: string; lines: PoLine[] } | null;
  if (poEv.data?.duplicate) return <Empty title="Not compared with the PO">This invoice is a duplicate, so it is void whatever the PO says. Its original is the one that counts against the PO.</Empty>;
  if (!po) return <Empty title="No purchase order matched">There is nothing to compare this invoice against, so it is held for a person.</Empty>;
  const map = (matchEv?.data?.line_map as (string | null)[] | undefined) ?? [];
  const bal = ((poEv.data?.checks as Check[]) ?? []).find((c) => c.id === "po_balance")?.evidence as
    { po_total: number; billed_before: number; this_invoice: number; prior_invoices: string[] } | undefined;
  const cur = po.currency;
  const how = matchEv?.data?.po_how === "inferred" ? "No PO was printed; matched from the vendor and the line items." : "PO number printed on the invoice.";
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="title text-lg">Invoice against <span className="typed text-carbon">{po.po_number}</span></h3>
        <span className="text-sm text-[#6e2f3c]">{how}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] text-sm">
          <thead><tr className="border-b border-[#e2a9b5] text-left">
            {["Invoice line", "PO line", "Qty  invoice / PO", "Unit price  invoice / PO"].map((h, i) => <th key={h} className={cx("label px-2 py-1.5 text-[#7a3343]", i > 1 && "text-right")}>{h}</th>)}
          </tr></thead>
          <tbody>
            {ex.line_items.map((li, i) => {
              const pl = po.lines.find((l) => l.id === map[i]);
              const priceOff = pl && li.unit_price != null && li.unit_price !== pl.unit_price;
              return (
                <tr key={i} className="border-b border-[#ecc2cb]">
                  <td className="px-2 py-2">{li.description}</td>
                  <td className="px-2 py-2">{pl ? pl.description : <span className="font-semibold text-stamp-hold">Not on the PO</span>}</td>
                  <td className="typed tnum px-2 py-2 text-right">{li.quantity ?? "—"} / {pl?.quantity ?? "—"}</td>
                  <td className={cx("typed tnum px-2 py-2 text-right", priceOff && "text-stamp-hold")}>{money(li.unit_price, cur)} / {pl ? money(pl.unit_price, cur) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {bal && <PoLedger {...bal} cur={cur} />}
    </div>
  );
}

/** The PO as a ledger strip: what was billed before, what this invoice adds, where the PO ends. */
function PoLedger({ po_total, billed_before, this_invoice, prior_invoices, cur }: { po_total: number; billed_before: number; this_invoice: number; prior_invoices: string[]; cur: string }) {
  const max = Math.max(po_total, billed_before + this_invoice);
  const pct = (v: number) => `${(v / max) * 100}%`;
  const over = billed_before + this_invoice - po_total;
  return (
    <div>
      <div className="label mb-2 text-[#7a3343]">PO balance</div>
      <div className="relative h-9 border border-[#d48b9b] bg-paper">
        <div className="absolute inset-y-0 left-0 bg-[repeating-linear-gradient(135deg,#9aa8a3_0_2px,transparent_2px_7px)]" style={{ width: pct(billed_before) }} />
        <div className={cx("absolute inset-y-0", over > 0.005 ? "bg-stamp-void/85" : "bg-stamp-ok/85")} style={{ left: pct(billed_before), width: pct(this_invoice) }} />
        <div className="absolute -inset-y-2 w-[2px] bg-ink" style={{ left: `calc(${pct(po_total)} - 1px)` }} />
        <span className="label absolute -top-5 -translate-x-full bg-pink pr-1 text-ink" style={{ left: pct(po_total) }}>PO limit</span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        <div><dt className="label text-[#7a3343]">Invoiced before</dt><dd className="typed tnum">{money(billed_before, cur)}</dd></div>
        <div><dt className="label text-[#7a3343]">This invoice</dt><dd className="typed tnum">{money(this_invoice, cur)}</dd></div>
        <div><dt className="label text-[#7a3343]">PO total</dt><dd className="typed tnum">{money(po_total, cur)}</dd></div>
        <div><dt className="label text-[#7a3343]">{over > 0.005 ? "Over by" : "Left after"}</dt>
          <dd className={cx("typed tnum font-semibold", over > 0.005 ? "text-stamp-void" : "text-stamp-ok")}>{money(Math.abs(over), cur)}</dd></div>
      </dl>
      {prior_invoices?.length > 0 && <p className="mt-2 text-xs text-[#6e2f3c]">Approved earlier against this PO: <span className="typed">{prior_invoices.join(", ")}</span></p>}
    </div>
  );
}

function SourceCopy({ run, pages }: { run: RunDetail; pages?: number }) {
  if (!pages) return <Waiting what="the PDF is read" />;
  return (
    <div className="space-y-4">
      <a href={`${config.apiBaseUrl}/api/runs/${run.id}/pdf`} target="_blank" rel="noreferrer"
        className="inline-flex items-center gap-1.5 text-sm font-semibold underline-offset-4 hover:underline">
        Open the original PDF <ExternalLink className="size-3.5" />
      </a>
      {Array.from({ length: pages }, (_, i) => (
        <figure key={i} className="sheet mx-auto max-w-3xl">
          <img src={`${config.apiBaseUrl}/api/runs/${run.id}/pages/${i + 1}`} alt={`Invoice page ${i + 1}`} className="w-full" />
          <figcaption className="label border-t border-rule px-3 py-1.5">Page {i + 1} of {pages}</figcaption>
        </figure>
      ))}
    </div>
  );
}

function AuditCopy({ run, result }: { run: RunDetail; result: RunResult | null }) {
  if (!result) return <Waiting what="the voucher is stamped" />;
  const p = result.provenance;
  return (
    <div className="space-y-6">
      <div>
        <h3 className="title text-lg">Model calls</h3>
        {!p.llm_calls.length ? <p className="mt-1 text-sm text-muted">No model calls were made.</p> : (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead><tr className="border-b border-[#cdbf96] text-left">
                {["Role", "Model", "Prompt version", "Effort", "Tokens in / out", "Time", "Tries"].map((h) => <th key={h} className="label px-2 py-1.5 text-[#5e5230]">{h}</th>)}
              </tr></thead>
              <tbody>
                {p.llm_calls.map((c, i) => (
                  <tr key={i} className="border-b border-[#ddd2b1]">
                    <td className="px-2 py-1.5 font-semibold capitalize">{c.role}</td>
                    <td className="typed px-2 py-1.5 text-xs">{c.model}</td>
                    <td className="typed px-2 py-1.5 text-xs">{c.prompt_ref}</td>
                    <td className="px-2 py-1.5">{String(c.params.reasoning_effort ?? "")}</td>
                    <td className="typed tnum px-2 py-1.5 text-xs">{c.input_tokens ?? "—"} / {c.output_tokens ?? "—"}</td>
                    <td className="typed tnum px-2 py-1.5 text-xs">{(c.latency_ms / 1000).toFixed(1)} s</td>
                    <td className="typed tnum px-2 py-1.5 text-xs">{c.attempts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
        {[
          ["Voucher", run.id], ["File SHA-256", p.file_sha256], ["Pipeline version", p.pipeline_git_sha],
          ["Match method", `${result.match.how}${result.match.settled_by ? `, settled by ${result.match.settled_by}` : ""}`],
          ["Started", new Date(p.started_at).toLocaleString()], ["Stamped", new Date(p.finished_at).toLocaleString()],
        ].map(([k, v]) => (
          <div key={k} className="min-w-0"><dt className="label text-[#5e5230]">{k}</dt><dd className="typed mt-0.5 break-all text-sm">{v}</dd></div>
        ))}
      </dl>
    </div>
  );
}
