import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { FileText, Play, RotateCcw, Search, Upload } from "lucide-react";
import { api, unwrap } from "../api/client";
import { config } from "../config";
import { Card, DecisionBadge, Empty, ErrorPanel, Skeleton, cx, money } from "../components/ui";

const FILTERS = [
  { key: "", label: "All" },
  { key: "approved", label: "Approved" },
  { key: "needs_review", label: "Needs review" },
  { key: "rejected", label: "Rejected" },
];

export default function Dashboard() {
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  const qc = useQueryClient();

  const stats = useQuery({
    queryKey: ["stats"], refetchInterval: config.dashboardRefreshMs,
    queryFn: () => unwrap(api.GET("/api/stats")),
  });
  const runs = useQuery({
    queryKey: ["runs", filter, q], refetchInterval: config.dashboardRefreshMs,
    queryFn: () => unwrap(api.GET("/api/runs", { params: { query: {
      decision: filter || undefined, q: q || undefined, limit: config.runsPageSize } } })),
  });
  const reset = useMutation({
    mutationFn: () => unwrap(api.POST("/api/reset")),
    onSuccess: () => qc.invalidateQueries(),
  });

  const s = stats.data;
  const tiles = [
    { label: "Processed", value: s?.total, sub: s ? `${s.running} running · ${s.failed} failed` : "" },
    { label: "Approved", value: s?.approved, sub: s ? money(s.approved_amount) : "", tone: "text-emerald-700" },
    { label: "Needs review", value: s?.needs_review, sub: s ? `${money(s.held_amount)} on hold` : "", tone: "text-amber-700" },
    { label: "Rejected", value: s?.rejected, sub: "duplicates, unknown vendors", tone: "text-rose-700" },
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Invoices</h1>
          <p className="text-sm text-slate-500">Drop a vendor invoice PDF; the agent reads it, matches it to a PO and decides.</p>
        </div>
        <button onClick={() => reset.mutate()} disabled={reset.isPending}
          className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100">
          <RotateCcw className="size-3.5" /> Reset demo history
        </button>
      </div>
      {reset.isError && <ErrorPanel message={(reset.error as Error).message} />}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <div className="text-xs font-medium text-slate-500">{t.label}</div>
            {stats.isLoading ? <Skeleton className="mt-2 h-7 w-12" /> :
              <div className={cx("mt-1 text-2xl font-semibold tabular-nums", t.tone)}>{t.value ?? "—"}</div>}
            <div className="truncate text-xs text-slate-500">{t.sub}</div>
          </div>
        ))}
      </div>
      {stats.isError && <ErrorPanel message="Could not load stats." onRetry={() => stats.refetch()} />}

      <Launcher />

      <Card title="History" action={
        <div className="flex items-center gap-2">
          <div className="relative hidden sm:block">
            <Search className="absolute left-2 top-1.5 size-3.5 text-slate-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Vendor, invoice #, file"
              className="w-48 rounded-md border border-slate-200 py-1 pl-7 pr-2 text-xs outline-none focus:border-slate-400" />
          </div>
          <div className="flex rounded-md bg-slate-100 p-0.5">
            {FILTERS.map((f) => (
              <button key={f.key} onClick={() => setFilter(f.key)}
                className={cx("rounded px-2 py-1 text-xs font-medium", filter === f.key ? "bg-white shadow-sm" : "text-slate-500")}>
                {f.label}
              </button>
            ))}
          </div>
        </div>
      }>
        {runs.isLoading ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : runs.isError ? (
          <ErrorPanel message="Could not load invoice history." onRetry={() => runs.refetch()} />
        ) : !runs.data?.length ? (
          <Empty>No invoices yet. Upload a PDF or run a demo sample above.</Empty>
        ) : (
          <div className="-mx-4 -my-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500">
                <tr className="border-b border-slate-100">
                  {["Invoice", "Vendor", "PO", "Total", "Status", "Reason", "Received"].map((h) => (
                    <th key={h} className="px-4 py-2.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id} className="border-b border-slate-50 hover:bg-slate-50">
                    <td className="px-4 py-2.5">
                      <Link to={`/runs/${r.id}`} className="font-medium text-slate-900 hover:underline">
                        {r.invoice_number ?? r.filename}
                      </Link>
                      <div className="text-xs text-slate-400">{r.filename}{r.pdf_kind === "scanned" ? " · scanned" : ""}</div>
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">{r.vendor_name ?? "—"}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-slate-600">{r.po_number ?? "—"}</td>
                    <td className="px-4 py-2.5 tabular-nums">{money(r.total, r.currency)}</td>
                    <td className="px-4 py-2.5"><DecisionBadge status={r.status} decision={r.decision} reviewer={r.reviewer_action} /></td>
                    <td className="max-w-xs truncate px-4 py-2.5 text-xs text-slate-500" title={r.decision_summary ?? r.error ?? ""}>
                      {r.status === "completed" ? r.decision_summary : r.error ?? r.current_stage}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-500">{new Date(r.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Launcher() {
  const nav = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const samples = useQuery({ queryKey: ["samples"], queryFn: () => unwrap(api.GET("/api/samples")) });

  const upload = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return unwrap(api.POST("/api/runs", { body: body as unknown as { file: string }, bodySerializer: (b) => b as unknown as FormData }));
    },
    onSuccess: (r) => nav(`/runs/${r.id}`),
  });
  const sample = useMutation({
    mutationFn: (name: string) => unwrap(api.POST("/api/samples/{name}/run", { params: { path: { name } } })),
    onSuccess: (r) => nav(`/runs/${r.id}`),
  });

  const err = (upload.error ?? sample.error) as Error | null;
  return (
    <div className="grid gap-3 lg:grid-cols-5">
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) upload.mutate(f); }}
        onClick={() => input.current?.click()}
        className={cx("flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed bg-white px-6 py-8 text-center lg:col-span-2",
          drag ? "border-indigo-400 bg-indigo-50/50" : "border-slate-300 hover:border-slate-400")}>
        <Upload className="size-6 text-slate-400" />
        <div className="text-sm font-medium">{upload.isPending ? "Uploading…" : "Drop an invoice PDF or click to browse"}</div>
        <div className="text-xs text-slate-500">Digital or scanned · up to 20 MB</div>
        <input ref={input} type="file" accept="application/pdf" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
      </div>
      <Card title="Demo invoices" className="lg:col-span-3">
        {samples.isLoading ? <Skeleton className="h-24" /> : samples.isError ? (
          <ErrorPanel message="Could not load samples." onRetry={() => samples.refetch()} />
        ) : !samples.data?.length ? <Empty>No sample PDFs found.</Empty> : (
          <ul className="grid gap-1.5 sm:grid-cols-2">
            {samples.data.map((n) => (
              <li key={n}>
                <button onClick={() => sample.mutate(n)} disabled={sample.isPending}
                  className="group flex w-full items-center gap-2 rounded-md border border-slate-200 px-2.5 py-1.5 text-left text-xs hover:border-slate-300 hover:bg-slate-50">
                  <FileText className="size-3.5 shrink-0 text-slate-400" />
                  <span className="truncate font-mono">{n.replace(".pdf", "")}</span>
                  <Play className="ml-auto size-3.5 shrink-0 text-slate-300 group-hover:text-indigo-600" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {err && <div className="lg:col-span-5"><ErrorPanel message={err.message} /></div>}
    </div>
  );
}
