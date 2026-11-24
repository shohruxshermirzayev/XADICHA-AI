"use client";

import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, Check, Circle, Loader2, X } from "lucide-react";
import type { Lang } from "@/lib/i18n";
import { fmtMs, timeline, type RowState, type TimelineRow } from "@/lib/presence";
import type { T } from "@/lib/use-lang";
import { cn } from "@/lib/utils";
import { describeAction, type Task, type TraceSpan } from "@/lib/xadicha";
import { RiskBadge } from "./ui";

const DOT: Record<RowState, string> = {
  done: "bg-secondary/15 text-secondary ring-secondary/30",
  active: "bg-primary/20 text-white ring-primary/50",
  failed: "bg-destructive/15 text-destructive ring-destructive/35",
  warn: "bg-warning/15 text-warning ring-warning/35",
  pending: "bg-white/[0.04] text-faint ring-white/10",
};

function RowIcon({ state }: { state: RowState }) {
  const c = "size-3";
  return (
    <span className={cn("relative z-10 flex size-6 shrink-0 items-center justify-center rounded-full ring-1", DOT[state])}>
      {state === "done" && <Check className={c} strokeWidth={2.5} aria-hidden />}
      {state === "active" && <Loader2 className={cn(c, "animate-spin")} aria-hidden />}
      {state === "failed" && <X className={c} strokeWidth={2.5} aria-hidden />}
      {state === "warn" && <AlertTriangle className={c} aria-hidden />}
      {state === "pending" && <Circle className="size-2" aria-hidden />}
      {state === "active" && <span aria-hidden className="absolute inset-0 animate-ping rounded-full ring-1 ring-primary/40" />}
    </span>
  );
}

function rowLabel(r: TimelineRow, task: Task, lang: Lang, t: T): { title: string; sub?: string } {
  switch (r.kind) {
    case "received":
      return { title: t("tl.received"), sub: task.mode ? `${t("task.mode")} ${task.mode} · ${task.language.toUpperCase()}` : undefined };
    case "planning":
      return {
        title: t("tl.planning"),
        sub: r.state === "done" && task.planner
          ? (task.planner === "rules" ? t("tl.fast") : task.planner === "llm" ? t("tl.model") : t("tl.tool")) + (task.intent ? ` · ${task.intent}` : "")
          : r.state === "active" ? t("task.planning") : undefined,
      };
    case "awaiting":
      return { title: t("tl.awaiting") };
    case "final":
      return { title: t(`tl.final.${task.status}`) };
    default: {
      const s = r.step!;
      const verify = s.verification;
      const parts: string[] = [];
      if (r.kind === "verifying") parts.push(t("tl.verifying"));
      else if (s.status === "verified") parts.push(t("tl.verified"));
      else if (s.status === "executed" && task.status !== "running") parts.push(t("tl.unverified"));
      if (s.detail && (s.status === "failed" || s.status === "error" || s.status === "denied")) parts.push(s.detail);
      else if (s.detail && s.status === "verified") parts.push(s.detail);
      if (verify) parts.push(t("tl.verifiedBy", { m: verify }));
      return { title: describeAction(s.action, lang), sub: parts.join(" · ") || undefined };
    }
  }
}

/** Jonli bajarilish vaqt chizig'i — har bir qator haqiqiy backend hodisasidan (task_started, step_*, confirm_*). */
export function TaskTimeline({ task, lang, t, activeStep, awaiting, compact = false }: {
  task: Task; lang: Lang; t: T; activeStep?: number | null; awaiting?: boolean; compact?: boolean;
}) {
  const rows = timeline(task, { activeStep, awaiting });
  return (
    <ol className="relative space-y-0.5" aria-label={t("tl.title")}>
      <span aria-hidden className="absolute top-3 bottom-3 left-[11.5px] w-px bg-gradient-to-b from-white/15 via-white/10 to-transparent" />
      <AnimatePresence initial={false}>
        {rows.map((r) => {
          const { title, sub } = rowLabel(r, task, lang, t);
          return (
            <motion.li key={r.key} layout="position" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
              className="relative flex items-start gap-3 py-1.5">
              <RowIcon state={r.state} />
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex items-start justify-between gap-2">
                  <p className={cn("text-sm leading-snug break-words",
                    r.state === "pending" ? "text-faint" : r.state === "failed" ? "text-destructive" : "text-foreground")}>{title}</p>
                  <span className="flex shrink-0 items-center gap-1.5">
                    {r.step && !compact && r.step.risk !== "low" && <RiskBadge risk={r.step.risk} t={t} />}
                    {r.ms != null && <span className="text-[11px] tabular-nums text-muted-foreground">{fmtMs(r.ms)}</span>}
                  </span>
                </div>
                {sub && !compact && <p className="mt-0.5 text-xs break-words text-muted-foreground">{sub}</p>}
              </div>
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}

/** Texnik tafsilot: bosqichlar vaqti (backend trace). Faqat yakunlangan vazifada mavjud. */
export function TraceList({ trace, t }: { trace: TraceSpan[]; t: T }) {
  const total = trace.reduce((a, s) => a + s.ms, 0);
  if (!trace.length) return null;
  return (
    <div>
      <p className="mb-1.5 text-[11px] text-muted-foreground">{t("card.trace")}</p>
      <ul className="space-y-1">
        {trace.map((sp, i) => (
          <li key={i} className="grid grid-cols-[120px_1fr_60px] items-center gap-2 text-[11px]">
            <span className={cn("truncate font-mono", sp.ok ? "text-foreground/80" : "text-destructive")}>{sp.stage}</span>
            <span className="h-1 rounded-full bg-white/[0.06]">
              <span className="block h-full rounded-full bg-gradient-to-r from-primary to-secondary"
                style={{ width: `${total ? Math.max(2, (sp.ms / total) * 100) : 2}%` }} />
            </span>
            <span className="text-right tabular-nums text-muted-foreground">{sp.ms} ms</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
