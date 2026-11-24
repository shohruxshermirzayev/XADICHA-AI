"use client";

import { cn } from "@/lib/utils";
import { LOCALE, type Lang } from "@/lib/i18n";
import type { T } from "@/lib/use-lang";
import type { Risk, Step, Task } from "@/lib/xadicha";
import { CheckCircle2, CircleDashed, Loader2, ShieldAlert, XCircle, MinusCircle } from "lucide-react";

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <section className={cn("glass rounded-[24px] p-5", className)}>{children}</section>;
}

export function CardTitle({ children, hint }: { children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <h2 className="text-[13px] font-medium tracking-wide text-muted-foreground">{children}</h2>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}

const riskStyle: Record<Risk, string> = {
  low: "bg-success/10 text-success ring-success/20",
  medium: "bg-warning/10 text-warning ring-warning/20",
  high: "bg-destructive/12 text-destructive ring-destructive/25",
};
export function RiskBadge({ risk, t }: { risk: Risk; t: T }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1", riskStyle[risk])}>
      {t(`risk.${risk}`)}
    </span>
  );
}

const taskStyle: Record<Task["status"], string> = {
  running: "text-secondary",
  success: "text-success",
  failed: "text-destructive",
  cancelled: "text-muted-foreground",
};

export function TaskStatus({ status, t }: { status: Task["status"]; t: T }) {
  const c = taskStyle[status];
  const label = t(`status.${status}`);
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", c)}>
      {status === "running" && <Loader2 className="size-3.5 animate-spin" />}
      {status === "success" && <CheckCircle2 className="size-3.5" />}
      {status === "failed" && <XCircle className="size-3.5" />}
      {status === "cancelled" && <MinusCircle className="size-3.5" />}
      {label}
    </span>
  );
}

export function StepIcon({ step, t }: { step: Step; t: T }) {
  switch (step.status) {
    case "verified":
      return <CheckCircle2 className="size-4 text-success" aria-label={t("stepIcon.verified")} />;
    case "executed":
      return <CircleDashed className="size-4 text-secondary" aria-label={t("stepIcon.executed")} />;
    case "failed":
    case "error":
      return <XCircle className="size-4 text-destructive" aria-label={t("stepIcon.failed")} />;
    case "denied":
      return <ShieldAlert className="size-4 text-warning" aria-label={t("stepIcon.denied")} />;
  }
}

export function Dot({ ok }: { ok: boolean | null | undefined }) {
  return (
    <span className="relative inline-flex size-2">
      {ok && <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-40" />}
      <span className={cn("relative inline-flex size-2 rounded-full", ok ? "bg-success" : ok === false ? "bg-destructive" : "bg-muted-foreground")} />
    </span>
  );
}

export function Button({
  variant = "default", className, ...props
}: React.ComponentProps<"button"> & { variant?: "default" | "ghost" | "danger" | "outline" }) {
  return (
    <button
      {...props}
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 rounded-full px-4 text-sm font-medium transition-[background,box-shadow,color,border-color] duration-200",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-45",
        variant === "default" && "bg-[linear-gradient(180deg,#8987ff,#6c6af5)] text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.28),0_10px_28px_-12px_rgb(119_117_255/0.8)] hover:brightness-110",
        variant === "ghost" && "text-muted-foreground hover:bg-white/[0.06] hover:text-foreground",
        variant === "outline" && "border border-white/10 bg-white/[0.04] text-foreground hover:border-white/20 hover:bg-white/[0.08]",
        variant === "danger" && "bg-[linear-gradient(180deg,#fb7f93,#e85571)] text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_10px_28px_-12px_rgb(251_113_133/0.7)] hover:brightness-110",
        className,
      )}
    />
  );
}

export function formatTime(ts: number, lang: Lang = "uz") {
  return new Date(ts * 1000).toLocaleString(LOCALE[lang], { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
}

export function latency(t: Task) {
  if (!t.finished_at) return "—";
  const ms = (t.finished_at - t.started_at) * 1000;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
