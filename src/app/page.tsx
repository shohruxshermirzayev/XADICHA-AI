"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";
import { ConfirmDialog } from "@/components/xadicha/confirm-dialog";
import { AssistantView } from "@/components/xadicha/conversation";
import { GlassNavigation, type View } from "@/components/xadicha/navigation";
import { ScreenSummary, ScreenView } from "@/components/xadicha/screen-context";
import { LangSwitch, SettingsView } from "@/components/xadicha/settings-view";
import { DashboardView, HistoryView, ResearchView } from "@/components/xadicha/views";
import { cn } from "@/lib/utils";
import { useLang } from "@/lib/use-lang";
import { useUiPrefs } from "@/lib/use-ui-prefs";
import { useXadicha, type ScreenSnapshot } from "@/lib/xadicha";

const PHASE_DOT = {
  idle: "bg-success",
  running: "bg-secondary animate-pulse",
  awaiting_confirmation: "bg-warning animate-pulse",
  speaking: "bg-primary animate-pulse",
} as const;

/** Fon yorug'ligi: ikki yumshoq manba, bittasi juda sekin siljiydi (faqat transform; harakat kamaytirilsa — to'xtaydi). */
function AmbientLight() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="animate-orb-drift absolute -top-[20%] right-[-10%] h-[70vh] w-[60vw] rounded-full bg-[radial-gradient(closest-side,rgb(119_117_255/0.16),transparent)] blur-3xl" />
      <div className="absolute bottom-[-25%] left-[-10%] h-[60vh] w-[50vw] rounded-full bg-[radial-gradient(closest-side,rgb(55_217_245/0.10),transparent)] blur-3xl" />
    </div>
  );
}

export default function Home() {
  const l = useLang();
  const { t } = l;
  const x = useXadicha(l.lang);
  const { prefs, setPrefs } = useUiPrefs();
  const reduce = useReducedMotion();
  const [view, setView] = useState<View>("assistant");
  const [snap, setSnap] = useState<ScreenSnapshot | null>(null);
  const compact = prefs.nav === "compact";
  const { getSettings, saveSettings } = x;
  const settingsApi = useMemo(() => ({ getSettings, saveSettings }), [getSettings, saveSettings]);
  // Sarlavha, yordamchi, panel va dashboard — barchasi bitta manbadan: x.phase / x.busy
  const phase = x.online === false ? "idle" : x.phase;
  // Ulanish o'rnatilmaguncha "Kutish rejimi" (tayyor) deb ko'rsatilmaydi — yon paneldagi holat bilan bir xil
  const connecting = x.online === null || (x.online === true && !x.wsOpen && !x.status);
  const headerLabel = x.online === false ? t("backend.offline") : connecting ? t("backend.connecting") : t(`phase.${phase}`);
  const headerDot = x.online === false ? "bg-destructive" : connecting ? "bg-warning animate-pulse" : PHASE_DOT[phase];
  const detail = x.status ? `${x.status.os} · ${x.status.provider.name}` : undefined;

  return (
    <div className="relative min-h-screen text-foreground">
      <a href="#main" className="sr-only z-50 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3">
        {t("skip.main")}
      </a>
      <AmbientLight />
      <GlassNavigation view={view} onChange={setView} compact={compact} onToggleCompact={() => setPrefs({ nav: compact ? "expanded" : "compact" })}
        online={x.online} wsOpen={x.wsOpen} detail={detail} t={t} />

      <div className={cn("transition-[padding] duration-300", compact ? "md:pl-[108px]" : "md:pl-[268px]")}>
        <header className="sticky top-0 z-20 px-3 pt-3 md:px-6 md:pt-4">
          <div className="glass-strong flex items-center justify-between gap-3 rounded-full py-2 pr-2 pl-5">
            <h1 className="truncate text-[15px] font-semibold tracking-tight">{t(`nav.${view}`)}</h1>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground" role="status" aria-live="polite">
                <span className={cn("size-1.5 rounded-full", headerDot)} aria-hidden />
                <span>{headerLabel}</span>
              </div>
              <div className="hidden sm:block">
                <LangSwitch {...l} layoutId="lang-header" />
              </div>
            </div>
          </div>
        </header>

        <main id="main" tabIndex={-1} className="px-3 pt-4 pb-28 md:px-6 md:pb-6">
          {x.online === false && (
            <div role="alert" className="mb-4 rounded-[20px] border border-warning/25 bg-warning/[0.08] px-4 py-3 text-sm text-warning">
              {t("backend.offlineBanner")}{" "}
              <code className="rounded-md bg-black/30 px-1.5 py-0.5 font-mono text-xs">cd backend && source .venv/bin/activate && python -m xadicha serve</code>
            </div>
          )}
          <AnimatePresence mode="wait">
            <motion.div key={view}
              initial={reduce ? false : { opacity: 0, y: 10, filter: "blur(6px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={reduce ? { opacity: 0 } : { opacity: 0, y: -4, filter: "blur(4px)" }}
              transition={{ duration: 0.24, ease: [0.2, 0.7, 0.2, 1] }}>
              {view === "assistant" && (
                <AssistantView x={x} l={l} onOpenScreen={() => setView("screen")} screenSummary={<ScreenSummary snap={snap} t={t} />} />
              )}
              {view === "dashboard" && <DashboardView x={x} l={l} />}
              {view === "screen" && <ScreenView x={x} l={l} snap={snap} setSnap={setSnap} />}
              {view === "history" && <HistoryView x={x} l={l} />}
              {view === "research" && <ResearchView x={x} l={l} />}
              {view === "settings" && <SettingsView status={x.status} l={l} prefs={prefs} setPrefs={setPrefs} api={settingsApi} />}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <ConfirmDialog confirmation={x.confirmation} busy={x.confirmBusy} error={x.confirmError} onAnswer={x.answer} t={t} />
    </div>
  );
}
