"use client";

import { cn } from "@/lib/utils";
import type { Risk, Step, Task } from "@/lib/xadicha";
import { CheckCircle2, CircleDashed, Loader2, ShieldAlert, XCircle, MinusCircle } from "lucide-react";

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <section className={cn("rounded-2xl border border-border bg-card/80 p-5 shadow-[0_1px_0_0_rgb(255_255_255/0.03)_inset]", className)}>
      {children}
    </section>
  );
}

export function CardTitle({ children, hint }: { children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-baseline justify-between gap-3">
      <h2 className="text-sm font-medium tracking-wide text-muted-foreground uppercase">{children}</h2>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}

const riskStyle: Record<Risk, string> = {
  low: "bg-success/10 text-success ring-success/25",
  medium: "bg-warning/10 text-warning ring-warning/25",
  high: "bg-destructive/10 text-destructive ring-destructive/30",
};
const riskLabel: Record<Risk, string> = { low: "Past xavf", medium: "O'rta xavf", high: "Yuqori xavf" };

export function RiskBadge({ risk }: { risk: Risk }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1", riskStyle[risk])}>
      {riskLabel[risk]}
    </span>
  );
}

const taskStyle: Record<Task["status"], [string, string]> = {
  running: ["text-secondary", "Bajarilmoqda"],
  success: ["text-success", "Muvaffaqiyatli"],
  failed: ["text-destructive", "Bajarilmadi"],
  cancelled: ["text-muted-foreground", "To'xtatildi"],
};

export function TaskStatus({ status }: { status: Task["status"] }) {
  const [c, label] = taskStyle[status];
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

export function StepIcon({ step }: { step: Step }) {
  switch (step.status) {
    case "verified":
      return <CheckCircle2 className="size-4 text-success" aria-label="tasdiqlandi" />;
    case "executed":
      return <CircleDashed className="size-4 text-secondary" aria-label="bajarildi, tekshirilmoqda" />;
    case "failed":
    case "error":
      return <XCircle className="size-4 text-destructive" aria-label="xato" />;
    case "denied":
      return <ShieldAlert className="size-4 text-warning" aria-label="rad etildi" />;
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
        "inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3.5 text-sm font-medium transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-50",
        variant === "default" && "bg-primary text-primary-foreground hover:bg-primary/90",
        variant === "ghost" && "text-muted-foreground hover:bg-accent hover:text-foreground",
        variant === "outline" && "border border-border text-foreground hover:bg-accent",
        variant === "danger" && "bg-destructive text-white hover:bg-destructive/90",
        className,
      )}
    />
  );
}

export function formatTime(ts: number) {
  return new Date(ts * 1000).toLocaleString("uz-UZ", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
}

export function latency(t: Task) {
  if (!t.finished_at) return "—";
  const ms = (t.finished_at - t.started_at) * 1000;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
