"use client";

import { AnimatePresence, motion } from "motion/react";
import { Activity, FlaskConical, History, LayoutDashboard, Mic, Monitor, Settings } from "lucide-react";
import { useState } from "react";
import { ConfirmDialog } from "@/components/xadicha/confirm-dialog";
import { XadichaWordmark } from "@/components/xadicha/logo";
import { Dot } from "@/components/xadicha/ui";
import { AssistantView, DashboardView, HistoryView, ResearchView, ScreenView, SettingsView } from "@/components/xadicha/views";
import { cn } from "@/lib/utils";
import { useXadicha } from "@/lib/xadicha";

const NAV = [
  { id: "assistant", label: "Yordamchi", icon: Mic },
  { id: "dashboard", label: "Boshqaruv paneli", icon: LayoutDashboard },
  { id: "screen", label: "Ekran tahlili", icon: Monitor },
  { id: "history", label: "Tarix", icon: History },
  { id: "research", label: "Tadqiqot", icon: FlaskConical },
  { id: "settings", label: "Sozlamalar", icon: Settings },
] as const;

type View = (typeof NAV)[number]["id"];

export default function Home() {
  const x = useXadicha();
  const [view, setView] = useState<View>("assistant");
  const title = NAV.find((n) => n.id === view)!.label;

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-sidebar p-4 md:flex">
        <div className="mb-8 px-1">
          <XadichaWordmark />
        </div>
        <nav aria-label="Asosiy menyu" className="flex flex-col gap-1">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setView(id)} aria-current={view === id ? "page" : undefined}
              className={cn(
                "relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-ring",
                view === id ? "text-foreground" : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}>
              {view === id && (
                <motion.span layoutId="nav-active" className="absolute inset-0 rounded-lg bg-accent" transition={{ type: "spring", stiffness: 400, damping: 34 }} />
              )}
              <Icon className="relative size-4" />
              <span className="relative">{label}</span>
            </button>
          ))}
        </nav>
        <div className="mt-auto rounded-xl border border-border bg-card/60 p-3 text-xs">
          <div className="flex items-center gap-2"><Dot ok={x.online} />
            <span>{x.online ? "Backend ulangan" : x.online === false ? "Backend o'chiq" : "Ulanmoqda…"}</span>
          </div>
          {x.status && (
            <p className="mt-1.5 truncate text-muted-foreground">{x.status.os} · {x.status.provider.name}</p>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-border bg-background/80 px-6 py-4 backdrop-blur">
          <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Activity className="size-3.5" />
            {x.status?.busy ? "Vazifa bajarilmoqda" : "Kutish rejimi"}
          </div>
          {/* mobil menyu */}
          <select value={view} onChange={(e) => setView(e.target.value as View)} aria-label="Bo'lim"
            className="rounded-md border border-border bg-muted px-2 py-1 text-sm md:hidden">
            {NAV.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
          </select>
        </header>

        <main className="flex-1 p-6">
          {x.online === false && (
            <div role="alert" className="mb-5 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
              Backend ishlamayapti. Terminal&apos;da ishga tushiring:{" "}
              <code className="rounded bg-black/30 px-1.5 py-0.5 font-mono text-xs">cd backend && source .venv/bin/activate && python -m xadicha serve</code>
            </div>
          )}
          <AnimatePresence mode="wait">
            <motion.div key={view} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
              {view === "assistant" && <AssistantView x={x} />}
              {view === "dashboard" && <DashboardView x={x} />}
              {view === "screen" && <ScreenView x={x} />}
              {view === "history" && <HistoryView x={x} />}
              {view === "research" && <ResearchView x={x} />}
              {view === "settings" && <SettingsView status={x.status} />}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <ConfirmDialog confirmation={x.confirmation} onAnswer={x.answer} />
    </div>
  );
}
