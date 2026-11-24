"use client";

import { AnimatePresence, motion } from "motion/react";
import { Activity, FlaskConical, History, LayoutDashboard, Mic, Monitor, Settings } from "lucide-react";
import { useState } from "react";
import { ConfirmDialog } from "@/components/xadicha/confirm-dialog";
import { XadichaWordmark } from "@/components/xadicha/logo";
import { Dot } from "@/components/xadicha/ui";
import { AssistantView, DashboardView, HistoryView, ResearchView, ScreenView, SettingsView } from "@/components/xadicha/views";
import { cn } from "@/lib/utils";
import { useLang } from "@/lib/use-lang";
import { useXadicha } from "@/lib/xadicha";

const NAV = [
  { id: "assistant", icon: Mic },
  { id: "dashboard", icon: LayoutDashboard },
  { id: "screen", icon: Monitor },
  { id: "history", icon: History },
  { id: "research", icon: FlaskConical },
  { id: "settings", icon: Settings },
] as const;

type View = (typeof NAV)[number]["id"];

const PHASE_STYLE = {
  idle: "text-muted-foreground",
  running: "text-secondary",
  awaiting_confirmation: "text-warning",
  speaking: "text-primary",
} as const;

export default function Home() {
  const l = useLang();
  const { t } = l;
  const x = useXadicha(l.lang);
  const [view, setView] = useState<View>("assistant");
  const title = t(`nav.${view}`);
  // Sarlavha, yordamchi, panel va dashboard — barchasi bitta manbadan: x.phase / x.busy
  const phase = x.online === false ? "idle" : x.phase;

  return (
    <div className="flex min-h-screen text-foreground">
      <a href="#main" className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3">
        {t("skip.main")}
      </a>
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-sidebar/90 p-4 backdrop-blur md:flex">
        <div className="mb-8 px-1">
          <XadichaWordmark />
        </div>
        <nav aria-label={t("nav.menu")} className="flex flex-col gap-1">
          {NAV.map(({ id, icon: Icon }) => (
            <button key={id} onClick={() => setView(id)} aria-current={view === id ? "page" : undefined}
              className={cn(
                "relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-ring",
                view === id ? "text-foreground" : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}>
              {view === id && (
                <motion.span layoutId="nav-active" className="absolute inset-0 rounded-lg bg-accent ring-1 ring-primary/30 shadow-[0_0_24px_-8px_rgb(99_102_241/0.6)]"
                  transition={{ type: "spring", stiffness: 400, damping: 34 }} />
              )}
              <Icon className={cn("relative size-4", view === id && "text-primary")} aria-hidden />
              <span className="relative">{t(`nav.${id}`)}</span>
            </button>
          ))}
        </nav>
        <div className="mt-auto rounded-xl border border-border bg-card/60 p-3 text-xs" role="status" aria-live="polite">
          <div className="flex items-center gap-2"><Dot ok={x.online} />
            <span>{x.online === false ? t("backend.offline") : x.online && x.wsOpen ? t("backend.connected")
              : x.online ? t("backend.reconnecting") : t("backend.connecting")}</span>
          </div>
          {x.status && (
            <p className="mt-1.5 truncate text-muted-foreground">{x.status.os} · {x.status.provider.name}</p>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col pb-16 md:pb-0">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-border bg-background/70 px-4 py-3 backdrop-blur md:px-6 md:py-4">
          <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
          <div className={cn("flex items-center gap-2 text-xs", PHASE_STYLE[phase])} role="status" aria-live="polite">
            <Activity className={cn("size-3.5", phase !== "idle" && "animate-pulse")} aria-hidden />
            {t(`phase.${phase}`)}
          </div>
        </header>

        <main id="main" tabIndex={-1} className="flex-1 p-4 md:p-6">
          {x.online === false && (
            <div role="alert" className="mb-5 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
              {t("backend.offlineBanner")}{" "}
              <code className="rounded bg-black/30 px-1.5 py-0.5 font-mono text-xs">cd backend && source .venv/bin/activate && python -m xadicha serve</code>
            </div>
          )}
          <AnimatePresence mode="wait">
            <motion.div key={view} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
              {view === "assistant" && <AssistantView x={x} l={l} />}
              {view === "dashboard" && <DashboardView x={x} l={l} />}
              {view === "screen" && <ScreenView x={x} l={l} />}
              {view === "history" && <HistoryView x={x} l={l} />}
              {view === "research" && <ResearchView x={x} l={l} />}
              {view === "settings" && <SettingsView status={x.status} l={l} />}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      {/* Mobil navigatsiya — pastki panel */}
      <nav aria-label={t("nav.menu")} className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-6 border-t border-border bg-sidebar/95 backdrop-blur md:hidden">
        {NAV.map(({ id, icon: Icon }) => (
          <button key={id} onClick={() => setView(id)} aria-current={view === id ? "page" : undefined} aria-label={t(`nav.${id}`)}
            className={cn("flex flex-col items-center gap-0.5 py-2 text-[10px] focus-visible:outline-2 focus-visible:outline-ring",
              view === id ? "text-primary" : "text-muted-foreground")}>
            <Icon className="size-5" aria-hidden />
            <span className="max-w-full truncate px-0.5">{t(`nav.${id}`)}</span>
          </button>
        ))}
      </nav>

      <ConfirmDialog confirmation={x.confirmation} busy={x.confirmBusy} error={x.confirmError} onAnswer={x.answer} t={t} />
    </div>
  );
}
