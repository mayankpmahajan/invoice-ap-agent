import type { ReactNode } from "react";
import { AlertTriangle, Check, Info, RefreshCw, X } from "lucide-react";
import type { Field, Outcome } from "../api/client";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export const money = (v: number | null | undefined, cur?: string | null) =>
  v == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD" }).format(v);

/** Stamp vocabulary: the decision as the rubber stamp an AP desk would use. */
export const STAMP: Record<string, { word: string; sub: string; color: string }> = {
  approved: { word: "Approved", sub: "for payment", color: "var(--color-stamp-ok)" },
  needs_review: { word: "Hold", sub: "for review", color: "var(--color-stamp-hold)" },
  rejected: { word: "Void", sub: "do not pay", color: "var(--color-stamp-void)" },
  running: { word: "In process", sub: "", color: "var(--color-stamp-run)" },
  failed: { word: "Error", sub: "run failed", color: "var(--color-muted)" },
};

export function stampKey(status: string, decision?: string | null, reviewer?: string | null) {
  if (status === "failed") return "failed";
  if (status !== "completed") return "running";
  if (reviewer) return reviewer === "approved" ? "approved" : "rejected";
  return decision ?? "failed";
}

/** Money totals per currency: amounts in different currencies are never added together. */
export const moneyByCur = (m: Record<string, number> | undefined) =>
  !m || !Object.keys(m).length ? money(0) : Object.entries(m).map(([c, v]) => money(v, c)).join(" + ");

/** A rubber-stamp impression: raster ink rendered from scripts/gen_stamps.py. */
export function Stamp({ k, size = "lg", strike = false, rot = -7 }: { k: string; size?: "sm" | "lg"; strike?: boolean; rot?: number }) {
  const s = STAMP[k] ?? STAMP.failed;
  const key = STAMP[k] ? k : "failed";
  return (
    <img src={`/stamps/${key}${size === "sm" ? "-sm" : ""}.png`} alt={`${s.word} ${s.sub}`.trim()} draggable={false}
      className={cx("pointer-events-none select-none mix-blend-multiply", strike && "stamp-strike", size === "sm" ? "h-7 w-auto" : "h-[96px] w-auto")}
      style={{ transform: `rotate(${rot}deg)`, ["--rot" as string]: `${rot}deg` }} />
  );
}

/** The commit gesture is the stamp itself: a rubber stamp face the reviewer presses. */
export function StampButton({ k, label, onPress, disabled }: { k: "approved" | "rejected"; label: string; onPress: () => void; disabled?: boolean }) {
  const color = STAMP[k].color;
  return (
    <button onClick={onPress} disabled={disabled}
      className="group flex min-w-[124px] flex-col items-center gap-1 border-2 px-4 pb-2 pt-1.5 transition-[transform,background-color] duration-150 hover:-translate-y-0.5 active:translate-y-0.5 disabled:opacity-50"
      style={{ borderColor: color, color }}>
      <span className="text-lg font-extrabold uppercase leading-none tracking-[.08em]" style={{ fontVariationSettings: '"wdth" 118' }}>{STAMP[k].word}</span>
      <span className="text-[11px] font-semibold text-ink">{label}</span>
    </button>
  );
}

/** A ruled box on a printed form: label in the corner, typed value inside. */
export function FormBox({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cx("min-w-0 border-rule px-3 pb-2 pt-1.5", className)}>
      <div className="label">{label}</div>
      <div className="typed mt-1 truncate text-[15px] tnum">{children}</div>
    </div>
  );
}

const OUTCOME: Record<Outcome, { icon: ReactNode; mark: string; tone: string }> = {
  pass: { icon: <Check className="size-3.5" strokeWidth={3} />, mark: "Clear", tone: "text-stamp-ok" },
  info: { icon: <Info className="size-3.5" strokeWidth={2.5} />, mark: "Note", tone: "text-form" },
  review: { icon: <AlertTriangle className="size-3.5" strokeWidth={2.5} />, mark: "Hold", tone: "text-stamp-hold" },
  reject: { icon: <X className="size-3.5" strokeWidth={3} />, mark: "Void", tone: "text-stamp-void" },
};

export function OutcomeMark({ outcome }: { outcome: Outcome }) {
  const o = OUTCOME[outcome];
  return (
    <span className={cx("inline-flex w-14 shrink-0 items-center gap-1 text-[11px] font-bold uppercase tracking-wider", o.tone)}
      style={{ fontVariationSettings: '"wdth" 80' }}>{o.icon}{o.mark}</span>
  );
}

const CONF: Record<Field["confidence"], { label: string; cls: string }> = {
  sure: { label: "sure", cls: "bg-stamp-ok" },
  leaning: { label: "leaning", cls: "bg-stamp-hold" },
  torn: { label: "torn", cls: "bg-stamp-void" },
};
/** Reader confidence: a pencil tick bar of three, filled to the level. */
export function Confidence({ level }: { level: Field["confidence"] }) {
  const n = level === "sure" ? 3 : level === "leaning" ? 2 : 1;
  return (
    <span className="inline-flex items-center gap-[2px]" title={`Reader confidence: ${CONF[level].label}`}>
      {[0, 1, 2].map((i) => <span key={i} className={cx("h-2.5 w-[3px]", i < n ? CONF[level].cls : "bg-rule-soft")} />)}
      <span className="sr-only">{CONF[level].label}</span>
    </span>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-4 border border-stamp-void/40 bg-paper px-4 py-3 text-sm text-stamp-void">
      <span><b className="font-bold">Could not complete:</b> {message}</span>
      {onRetry && (
        <button onClick={onRetry} className="inline-flex items-center gap-1 font-semibold underline-offset-4 hover:underline">
          <RefreshCw className="size-3.5" /> Try again
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse bg-rule-soft", className)} />;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="border border-dashed border-rule px-6 py-10 text-center">
      <div className="title text-base text-ink">{title}</div>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export const btn = {
  primary: "inline-flex items-center justify-center gap-1.5 bg-carbon px-4 py-2 text-sm font-semibold text-white hover:bg-[#241f6b] disabled:opacity-50",
  quiet: "inline-flex items-center justify-center gap-1.5 border border-rule bg-paper px-3 py-2 text-sm font-semibold text-ink hover:border-form disabled:opacity-50",
};
