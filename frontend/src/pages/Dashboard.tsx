import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowRight, RotateCcw, Search } from "lucide-react";
import { api, unwrap } from "../api/client";
import { config } from "../config";
import { Empty, ErrorNote, Skeleton, Stamp, cx, money, moneyByCur, stampKey } from "../components/ui";

const FILTERS = [
  { key: "", label: "All" },
  { key: "approved", label: "Approved" },
  { key: "needs_review", label: "On hold" },
  { key: "rejected", label: "Void" },
];

const prettySample = (n: string) => n.replace(/\.pdf$/, "").replace(/^\d+_/, "").replace(/_/g, " ");

export default function Dashboard() {
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  const nav = useNavigate();
  const qc = useQueryClient();

  const stats = useQuery({ queryKey: ["stats"], refetchInterval: config.dashboardRefreshMs, queryFn: () => unwrap(api.GET("/api/stats")) });
  const runs = useQuery({
    queryKey: ["runs", filter, q], refetchInterval: config.dashboardRefreshMs,
    queryFn: () => unwrap(api.GET("/api/runs", { params: { query: { decision: filter || undefined, q: q || undefined, limit: config.runsPageSize } } })),
  });
  const reset = useMutation({ mutationFn: () => unwrap(api.POST("/api/reset")), onSuccess: () => qc.invalidateQueries() });
  const s = stats.data;

  return (
    <div className="space-y-7">
      {/* Batch control: the adding-machine control tape an AP desk reconciles each batch against. */}
      <section aria-label="Batch control totals" className="flex flex-wrap items-stretch gap-x-6 gap-y-3">
        <div className="flex flex-col justify-center">
          <h1 className="title text-[28px] leading-none">Voucher register</h1>
          <button onClick={() => reset.mutate()} disabled={reset.isPending}
            className="mt-2 inline-flex items-center gap-1.5 self-start text-xs font-semibold text-muted hover:text-ink disabled:opacity-50">
            <RotateCcw className="size-3.5" /> Clear demo history
          </button>
        </div>
        <div className="relative flex min-w-0 basis-full flex-wrap items-center gap-x-1 bg-paper md:basis-0 md:flex-1 py-2 pl-3 pr-4 shadow-[0_1px_1px_rgb(27_34_32/.06),0_8px_18px_-12px_rgb(27_34_32/.4)] [clip-path:polygon(0_0,100%_0,calc(100%-6px)_50%,100%_100%,0_100%)]">
          {stats.isLoading ? <Skeleton className="h-10 flex-1" /> : (
            <>
              <Tally n={s?.total} label="received" />
              <Tally n={s?.approved} label="approved" amount={moneyByCur(s?.approved_amounts)} tone="text-stamp-ok" />
              <Tally n={s?.needs_review} label="on hold" amount={moneyByCur(s?.held_amounts)} tone="text-stamp-hold" />
              <Tally n={s?.rejected} label="void" tone="text-stamp-void" />
              {!!s?.running && <Tally n={s.running} label="in process" tone="text-carbon" />}
              {!!s?.failed && <Tally n={s.failed} label="errors" />}
            </>
          )}
        </div>
      </section>
      {(stats.isError || reset.isError) && <ErrorNote message={((stats.error ?? reset.error) as Error).message} onRetry={() => stats.refetch()} />}

      <Intake onStarted={(id) => nav(`/runs/${id}`)} />

      <section className="sheet grid grid-cols-[22px_minmax(0,1fr)_22px]">
        <div aria-hidden className="tractor border-r border-dashed border-rule" />
        <div className="min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-4 py-2.5">
          <h2 className="title text-lg">Register</h2>
          <div className="flex flex-wrap items-center gap-3">
            <label className="relative">
              <span className="sr-only">Search register</span>
              <Search className="pointer-events-none absolute left-2 top-2 size-3.5 text-form" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search"
                className="typed w-44 border-b border-rule bg-transparent py-1 pl-7 pr-1 text-sm outline-none placeholder:text-muted focus:border-carbon" />
            </label>
            <div className="flex border border-rule" role="group" aria-label="Filter by stamp">
              {FILTERS.map((f) => (
                <button key={f.key} onClick={() => setFilter(f.key)} aria-pressed={filter === f.key}
                  className={cx("px-2.5 py-1 text-xs font-semibold", filter === f.key ? "bg-ink text-paper" : "text-muted hover:text-ink")}>
                  {f.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        {runs.isLoading ? (
          <div className="space-y-px p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-11" />)}</div>
        ) : runs.isError ? (
          <div className="p-4"><ErrorNote message="the register could not be loaded." onRetry={() => runs.refetch()} /></div>
        ) : !runs.data?.length ? (
          <div className="p-4"><Empty title={filter || q ? "No vouchers match" : "The register is empty"}>
            {filter || q ? "Clear the search or filter to see every voucher." : "Drop an invoice in the in-tray, or run the test batch above."}</Empty></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="greenbar w-full min-w-[860px] text-sm">
              <thead>
                <tr className="border-b border-rule text-left">
                  {["Voucher", "Vendor / invoice", "PO", "Amount", "Stamp", "Reason", "Received"].map((h, i) => (
                    <th key={h} className={cx("label px-4 py-2 font-semibold", i === 3 && "text-right")}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => {
                  const k = stampKey(r.status, r.decision, r.reviewer_action);
                  return (
                    <tr key={r.id} onClick={() => nav(`/runs/${r.id}`)}
                      className="cursor-pointer hover:!bg-canary/60">
                      <td className="typed px-4 py-2.5 text-xs text-muted">
                        <a href={`/runs/${r.id}`} onClick={(e) => { e.preventDefault(); nav(`/runs/${r.id}`); }} className="hover:underline">{r.id.slice(0, 6).toUpperCase()}</a>
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="font-semibold">{r.vendor_name ?? r.filename}</div>
                        <div className="typed text-xs">{r.invoice_number ?? "—"}{r.pdf_kind === "scanned" && <span className="ml-2 text-muted">scanned</span>}</div>
                      </td>
                      <td className="typed px-4 py-2.5 text-xs">{r.po_number ?? "—"}</td>
                      <td className="typed tnum px-4 py-2.5 text-right">{money(r.total, r.currency)}</td>
                      <td className="px-4 py-2.5"><Stamp k={k} size="sm" rot={-3} /></td>
                      <td className="max-w-[320px] px-4 py-2.5 text-xs text-muted">
                        <span className="line-clamp-2">{r.status === "completed" ? (r.reviewer_action ? `Reviewer ${r.reviewer_action}. ${r.reviewer_note ?? ""}` : r.decision_summary) : r.error ?? `At: ${r.current_stage ?? "queued"}`}</span>
                      </td>
                      <td className="typed whitespace-nowrap px-4 py-2.5 text-xs text-muted">{fmtTime(r.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        </div>
        <div aria-hidden className="tractor border-l border-dashed border-rule" />
      </section>
    </div>
  );
}

const fmtTime = (iso: string) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function Tally({ n, label, amount, tone }: { n?: number; label: string; amount?: string; tone?: string }) {
  return (
    <div className="flex items-baseline gap-2 whitespace-nowrap border-r border-dotted border-rule px-3 py-1 last:border-r-0">
      <span className={cx("typed tnum text-[22px] leading-none", tone)}>{n ?? 0}</span>
      <span className="text-xs font-semibold">{label}</span>
      {amount && <span className="typed tnum text-xs text-muted">{amount}</span>}
    </div>
  );
}

function Intake({ onStarted }: { onStarted: (id: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const samples = useQuery({ queryKey: ["samples"], queryFn: () => unwrap(api.GET("/api/samples")) });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return unwrap(api.POST("/api/runs", { body: body as unknown as { file: string }, bodySerializer: (b) => b as unknown as FormData }));
    },
    onSuccess: (r) => onStarted(r.id),
  });
  const sample = useMutation({
    mutationFn: (name: string) => unwrap(api.POST("/api/samples/{name}/run", { params: { path: { name } } })),
    onSuccess: (r) => onStarted(r.id),
  });
  const err = (upload.error ?? sample.error) as Error | null;

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <button type="button"
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) upload.mutate(f); }}
        onClick={() => input.current?.click()}
        className={cx("group relative flex min-h-[120px] flex-col justify-between gap-4 border-2 border-dashed p-5 text-left transition-colors",
          drag ? "border-carbon bg-paper" : "border-form/40 bg-blotter-deep/40 hover:border-form hover:bg-paper/60")}>
        <span className="title text-2xl leading-tight">In-tray</span>
        <span>
          <span className="block text-sm font-semibold">{upload.isPending ? "Taking the invoice…" : "Drop a vendor invoice here, or choose a file"}</span>
          <span className="mt-0.5 block text-xs text-muted">PDF, digital or scanned, up to 20 MB. It opens straight into its voucher.</span>
        </span>
        <input ref={input} type="file" accept="application/pdf" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
      </button>

      <section className="sheet bg-manila">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 border-b border-[#cdbf96] px-4 py-2.5">
          <h2 className="title text-lg">Test batch</h2>
          <span className="text-xs text-[#5e5230]">Run in order: later invoices depend on earlier ones</span>
        </div>
        {samples.isLoading ? <div className="p-4"><Skeleton className="h-28" /></div> : samples.isError ? (
          <div className="p-4"><ErrorNote message="sample invoices could not be listed." onRetry={() => samples.refetch()} /></div>
        ) : !samples.data?.length ? <div className="p-4"><Empty title="No sample invoices">Add PDFs to the samples folder.</Empty></div> : (
          <ol className="grid sm:grid-cols-2">
            {samples.data.map((n, i) => (
              <li key={n} className={cx("border-[#d9cca6]", i % 2 === 0 && "sm:border-r", i >= 2 && "sm:border-t", i >= 1 && "max-sm:border-t")}>
                <button onClick={() => sample.mutate(n)} disabled={sample.isPending}
                  className="group flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-paper/60 disabled:opacity-50">
                  <span className="typed w-5 text-xs text-[#5e5230]">{String(i + 1).padStart(2, "0")}</span>
                  <span className="min-w-0 flex-1 truncate text-sm font-medium first-letter:uppercase">{prettySample(n)}</span>
                  <ArrowRight className="size-4 text-rule group-hover:text-carbon" />
                </button>
              </li>
            ))}
          </ol>
        )}
      </section>
      {err && <div className="lg:col-span-2"><ErrorNote message={err.message} /></div>}
    </div>
  );
}

