"use client";

import { motion } from "motion/react";
import { FlaskConical, History, LayoutDashboard, type LucideIcon, Monitor, PanelLeftClose, PanelLeftOpen, Settings, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { T } from "@/lib/use-lang";
import { XadichaMark } from "./logo";

export const NAV = [
  { id: "assistant", icon: Sparkles },
  { id: "dashboard", icon: LayoutDashboard },
  { id: "screen", icon: Monitor },
  { id: "history", icon: History },
  { id: "research", icon: FlaskConical },
  { id: "settings", icon: Settings },
] as const satisfies readonly { id: string; icon: LucideIcon }[];

export type View = (typeof NAV)[number]["id"];

function Connection({ online, wsOpen, detail, compact, t }: {
  online: boolean | null; wsOpen: boolean; detail?: string; compact: boolean; t: T;
}) {
  const label = online === false ? t("backend.offline") : online && wsOpen ? t("backend.connected")
    : online ? t("backend.reconnecting") : t("backend.connecting");
  const color = online === false ? "bg-destructive" : online && wsOpen ? "bg-success" : "bg-warning";
  return (
    <div role="status" aria-live="polite" title={compact ? label : undefined}
      className={cn("flex items-center gap-2.5 rounded-2xl px-2.5 py-2 text-xs", compact && "justify-center")}>
      <span className="relative inline-flex size-2 shrink-0">
        {online && wsOpen && <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-40" />}
        <span className={cn("relative inline-flex size-2 rounded-full", color)} />
      </span>
      <span className={cn("min-w-0", compact && "sr-only")}>
        <span className="block truncate text-foreground/90">{label}</span>
        {detail && <span className="block truncate text-[11px] text-muted-foreground">{detail}</span>}
      </span>
    </div>
  );
}

/** Suzuvchi shisha navigatsiya: kompyuterda — chap tomonda (ixcham / kengaytirilgan), telefonda — pastda. */
export function GlassNavigation({ view, onChange, compact, onToggleCompact, online, wsOpen, detail, t }: {
  view: View; onChange: (v: View) => void; compact: boolean; onToggleCompact: () => void;
  online: boolean | null; wsOpen: boolean; detail?: string; t: T;
}) {
  return (
    <>
      <motion.aside
        className="glass-strong fixed top-4 bottom-4 left-4 z-30 hidden flex-col rounded-[28px] p-3 md:flex"
        animate={{ width: compact ? 76 : 236 }} transition={{ type: "spring", stiffness: 320, damping: 34 }}
        initial={false}
      >
        <div className={cn("mb-6 flex items-center gap-2.5 px-1 pt-1", compact && "justify-center px-0")}>
          <XadichaMark size={compact ? 44 : 40} aura={false} />
          {!compact && (
            <div className="min-w-0 leading-none">
              <p className="text-[15px] font-semibold tracking-[0.08em]">XADICHA <span className="text-gradient">AI</span></p>
              <p className="mt-1.5 text-[10px] tracking-[0.18em] text-muted-foreground uppercase">Desktop assistant</p>
            </div>
          )}
        </div>
        <nav aria-label={t("nav.menu")} className="flex flex-col gap-1">
          {NAV.map(({ id, icon: Icon }) => {
            const active = view === id;
            return (
              <button key={id} type="button" onClick={() => onChange(id)} aria-current={active ? "page" : undefined}
                title={compact ? t(`nav.${id}`) : undefined} aria-label={compact ? t(`nav.${id}`) : undefined}
                className={cn(
                  "group relative flex h-11 items-center gap-3 rounded-2xl text-sm transition-colors focus-visible:outline-2 focus-visible:outline-ring",
                  compact ? "justify-center px-0" : "px-3.5",
                  active ? "text-foreground" : "text-muted-foreground hover:bg-white/[0.05] hover:text-foreground",
                )}>
                {active && (
                  <motion.span layoutId="nav-active" className="glass-active absolute inset-0 rounded-2xl"
                    transition={{ type: "spring", stiffness: 420, damping: 36 }} />
                )}
                <Icon className={cn("relative size-[18px] shrink-0 transition-colors", active ? "text-white" : "group-hover:text-foreground")}
                  strokeWidth={1.75} aria-hidden />
                {!compact && <span className="relative truncate">{t(`nav.${id}`)}</span>}
              </button>
            );
          })}
        </nav>
        <div className="mt-auto space-y-1">
          <div className="glass-subtle rounded-2xl">
            <Connection online={online} wsOpen={wsOpen} detail={detail} compact={compact} t={t} />
          </div>
          <button type="button" onClick={onToggleCompact} aria-label={compact ? t("nav.expand") : t("nav.collapse")}
            title={compact ? t("nav.expand") : t("nav.collapse")}
            className={cn("flex h-9 w-full items-center gap-2 rounded-xl text-xs text-muted-foreground transition-colors hover:bg-white/[0.05] hover:text-foreground",
              compact ? "justify-center" : "px-3")}>
            {compact ? <PanelLeftOpen className="size-4" aria-hidden /> : <PanelLeftClose className="size-4" aria-hidden />}
            {!compact && <span>{t("nav.collapse")}</span>}
          </button>
        </div>
      </motion.aside>

      {/* Telefon / tor oyna: pastki shisha panel */}
      <nav aria-label={t("nav.menu")}
        className="glass-strong fixed inset-x-3 bottom-3 z-30 grid grid-cols-6 rounded-[22px] p-1 md:hidden">
        {NAV.map(({ id, icon: Icon }) => {
          const active = view === id;
          return (
            <button key={id} type="button" onClick={() => onChange(id)} aria-current={active ? "page" : undefined} aria-label={t(`nav.${id}`)}
              className={cn("relative flex flex-col items-center gap-0.5 rounded-2xl py-2 text-[10px] focus-visible:outline-2 focus-visible:outline-ring",
                active ? "text-foreground" : "text-muted-foreground")}>
              {active && <motion.span layoutId="nav-active-m" className="glass-active absolute inset-0 rounded-2xl" />}
              <Icon className="relative size-5" strokeWidth={1.75} aria-hidden />
              <span className="relative max-w-full truncate px-0.5">{t(`nav.${id}`)}</span>
            </button>
          );
        })}
      </nav>
    </>
  );
}
