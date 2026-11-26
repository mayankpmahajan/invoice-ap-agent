import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, RefreshCw, XCircle } from "lucide-react";
import type { Field, Outcome } from "../api/client";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export const money = (v: number | null | undefined, cur?: string | null) =>
  v == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD" }).format(v);

export const DECISION: Record<string, { label: string; cls: string; dot: string }> = {
  approved: { label: "Approved", cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/20", dot: "bg-emerald-500" },
  needs_review: { label: "Needs review", cls: "bg-amber-50 text-amber-800 ring-amber-600/25", dot: "bg-amber-500" },
  rejected: { label: "Rejected", cls: "bg-rose-50 text-rose-700 ring-rose-600/20", dot: "bg-rose-500" },
  running: { label: "Running", cls: "bg-indigo-50 text-indigo-700 ring-indigo-600/20", dot: "bg-indigo-500" },
  failed: { label: "Failed", cls: "bg-slate-100 text-slate-700 ring-slate-500/20", dot: "bg-slate-500" },
};

export function DecisionBadge({ status, decision, reviewer }: { status: string; decision?: string | null; reviewer?: string | null }) {
  const key = status === "completed" ? decision ?? "failed" : status === "failed" ? "failed" : "running";
  const d = DECISION[key];
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", d.cls)}>
        {key === "running" ? <Loader2 className="size-3 animate-spin" /> : <span className={cx("size-1.5 rounded-full", d.dot)} />}
        {d.label}
      </span>
      {reviewer && (
        <span className="text-xs text-slate-500">→ {reviewer === "approved" ? "approved by reviewer" : "rejected by reviewer"}</span>
      )}
    </span>
  );
}

const OUTCOME: Record<Outcome, { icon: ReactNode; cls: string; label: string }> = {
  pass: { icon: <CheckCircle2 className="size-4 text-emerald-600" />, cls: "", label: "Pass" },
  info: { icon: <Info className="size-4 text-sky-600" />, cls: "", label: "Note" },
  review: { icon: <AlertTriangle className="size-4 text-amber-600" />, cls: "bg-amber-50/60", label: "Review" },
  reject: { icon: <XCircle className="size-4 text-rose-600" />, cls: "bg-rose-50/60", label: "Reject" },
};

export function CheckRow({ title, outcome, detail }: { title: string; outcome: Outcome; detail: string }) {
  const o = OUTCOME[outcome];
  return (
    <div className={cx("flex gap-3 rounded-lg px-3 py-2.5", o.cls)}>
      <div className="mt-0.5 shrink-0">{o.icon}</div>
      <div className="min-w-0">
        <div className="text-sm font-medium text-slate-800">{title}</div>
        <div className="text-sm text-slate-600">{detail}</div>
      </div>
    </div>
  );
}

const CONF: Record<Field["confidence"], string> = { sure: "bg-emerald-500", leaning: "bg-amber-400", torn: "bg-rose-500" };
export function ConfidenceDot({ level }: { level: Field["confidence"] }) {
  return <span title={`Model confidence: ${level}`} className={cx("inline-block size-2 rounded-full", CONF[level])} />;
}

export function Card({ title, action, children, className }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {title && (
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      <span>{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="inline-flex items-center gap-1 font-medium hover:underline">
          <RefreshCw className="size-3.5" /> Retry
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-md bg-slate-200/70", className)} />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">{children}</div>;
}
