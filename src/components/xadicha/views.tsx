"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, Monitor, Octagon, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { detectCommandLanguage, LANG_LABEL, LANGS, type Lang } from "@/lib/i18n";
import type { T } from "@/lib/use-lang";
import { describeAction, type ChatMessage, type Mode, type Status, type Task, type useXadicha } from "@/lib/xadicha";
import { Button, Card, CardTitle, Dot, RiskBadge, StepIcon, TaskStatus, formatTime, latency } from "./ui";
import { VoiceOrb } from "./voice-orb";

type X = ReturnType<typeof useXadicha>;
interface L { lang: Lang; setLang: (l: Lang) => void; t: T }

const MODES: Mode[] = ["C", "B", "A"];

export function LangSwitch({ lang, setLang, t }: L) {
  return (
    <div role="radiogroup" aria-label={t("lang.label")} className="flex gap-1 rounded-lg bg-muted p-1">
      {LANGS.map((id) => (
        <button key={id} type="button" role="radio" aria-checked={lang === id} onClick={() => setLang(id)} lang={id}
          className={cn("rounded-md px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring",
            lang === id ? "bg-card text-foreground shadow" : "text-muted-foreground hover:text-foreground")}>
          {LANG_LABEL[id]}
        </button>
      ))}
    </div>
  );
}

/* ---------------- Ovozli yordamchi (asosiy ekran) ---------------- */

export function AssistantView({ x, l }: { x: X; l: L }) {
  const { lang, t } = l;
  const [mode, setMode] = useState<Mode>("C");
  const [text, setText] = useState("");
  const busy = !!x.status?.busy || x.current?.status === "running";
  const offline = x.online === false;

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || busy || offline) return;
    setText("");
    // Kirill yozuvi: o'zbek kirill (ў, қ, ғ, ҳ yoki o'zbekcha so'zlar) — uz, aks holda — ru
    x.run(t, detectCommandLanguage(t, lang), mode);
  };

  const toggleVoice = async () => {
    if (x.listening === "transcribing") return;
    if (x.listening === "recording") {
      const r = await x.stopListening();
      if (!r) return;
      if (!r.supported) x.push({ role: "system", text: l.t("voice.unsupported") });
      else if (!r.text) x.push({ role: "system", text: l.t("voice.nothingHeard") });
      else x.run(r.text, r.language, mode, true);
    } else {
      x.startListening(lang);
    }
  };

  // Space — gapirishni boshlash/to'xtatish (matn maydonida yozayotganda emas)
  const toggleRef = useRef(toggleVoice);
  useEffect(() => {
    toggleRef.current = toggleVoice;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.code !== "Space" || e.repeat || el.closest("input, textarea, select, button, [contenteditable]")) return;
      e.preventDefault();
      if (!offline && (!busy || x.listening === "recording")) toggleRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [offline, busy, x.listening]);

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card className="flex min-h-[560px] flex-col p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
          <LangSwitch {...l} />
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            {t("mode.label")}
            <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} title={t(`mode.${mode}.hint`)}
              className="rounded-md border border-border bg-muted px-2 py-1 text-xs text-foreground focus-visible:outline-2 focus-visible:outline-ring">
              {MODES.map((m) => <option key={m} value={m}>{m} — {t(`mode.${m}`)}</option>)}
            </select>
          </label>
        </div>

        <Conversation messages={x.messages} lang={lang} t={t} onExample={(ex) => !busy && !offline && x.run(ex, lang, mode)} />

        <div className="flex flex-col items-center gap-2 px-5 pb-2">
          {/* Yozuv davom etayotganda tugma o'chirilmaydi — aks holda to'xtatib bo'lmay qolardi */}
          <VoiceOrb state={x.listening} level={x.micLevel} busy={busy} t={t}
            disabled={offline || (busy && x.listening !== "recording")} onToggle={toggleVoice} />
          <p className="h-5 text-xs text-muted-foreground" aria-live="polite">
            {offline ? t("voice.offline") : x.listening === "recording" ? t("voice.recording")
              : x.listening === "transcribing" ? t("voice.transcribing") : busy ? t("voice.busy") : t("voice.idle")}
          </p>
        </div>

        <form onSubmit={submit} className="flex gap-2 border-t border-border p-3">
          <label htmlFor="cmd" className="sr-only">{t("input.label")}</label>
          <input id="cmd" value={text} onChange={(e) => setText(e.target.value)} disabled={offline} lang={lang}
            placeholder={t("input.placeholder")}
            className="h-10 flex-1 rounded-lg border border-input bg-muted/60 px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring" />
          {busy ? (
            <Button type="button" variant="danger" onClick={x.stop} className="h-10"><Octagon className="size-4" />{t("input.stop")}</Button>
          ) : (
            <Button type="submit" disabled={!text.trim() || offline} className="h-10" aria-label={t("input.send")}><ArrowUp className="size-4" /></Button>
          )}
        </form>
      </Card>

      <LiveTask task={x.current} lang={lang} t={t} />
    </div>
  );
}

const EXAMPLES: Record<Lang, string[]> = {
  uz: ["Safari ni och", "YouTube'da o'zbek musiqasini qidir", "Desktopda \"Hisobot\" papka yarat", "Ekranda nima bor?"],
  ru: ["Открой Notes", "Найди погоду в Ташкенте", "Открой kun.uz"],
  en: ["Open Calculator", "Search Google for Tashkent weather", "What is on my screen?"],
};

function Conversation({ messages, lang, t, onExample }: {
  messages: ChatMessage[]; lang: Lang; t: T; onExample: (text: string) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  if (!messages.length) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
        <p className="text-lg font-medium">{t("chat.greeting")}</p>
        <p className="max-w-sm text-sm text-muted-foreground">{t("chat.intro")}</p>
        <div className="mt-4 flex max-w-lg flex-wrap justify-center gap-2">
          {EXAMPLES[lang].map((ex) => (
            <button key={ex} lang={lang} onClick={() => onExample(ex)}
              className="rounded-full border border-border bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
              {ex}
            </button>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4" aria-live="polite">
      <AnimatePresence initial={false}>
        {messages.map((m) => (
          <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} lang={m.lang}
            className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cn("max-w-[80%] rounded-2xl px-4 py-2.5 text-sm",
              m.role === "user" && "rounded-br-md bg-primary text-primary-foreground",
              m.role === "assistant" && "rounded-bl-md bg-muted",
              m.role === "system" && "border border-destructive/30 bg-destructive/10 text-destructive")}>
              {m.text}
              {m.role === "assistant" && m.status && m.status !== "success" && (
                <div className="mt-1"><TaskStatus status={m.status} t={t} /></div>
              )}
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
      <div ref={end} />
    </div>
  );
}

/* ---------------- Joriy vazifa (Task Manager) ---------------- */

export function LiveTask({ task, lang, t }: { task: Task | null; lang: Lang; t: T }) {
  return (
    <Card className="h-fit">
      <CardTitle hint={task ? <TaskStatus status={task.status} t={t} /> : null}>{t("task.title")}</CardTitle>
      {!task ? (
        <p className="py-10 text-center text-sm text-muted-foreground">{t("task.empty")}</p>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="text-sm font-medium">{task.instruction}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("task.mode")} {task.mode} · {task.language.toUpperCase()} {task.intent && `· ${task.intent}`}
              {task.planner === "rules" && ` · ${t("task.fastPath")}`}
            </p>
          </div>
          <ol className="relative space-y-3 border-l border-border pl-5">
            {task.steps.length === 0 && task.status === "running" && (
              <li className="text-xs text-muted-foreground">{t("task.planning")}</li>
            )}
            {task.steps.map((s) => (
              <motion.li key={s.index} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} className="relative">
                <span className="absolute top-0.5 -left-[27px] rounded-full bg-card"><StepIcon step={s} t={t} /></span>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm break-words">{describeAction(s.action, lang)}</p>
                  <RiskBadge risk={s.risk} t={t} />
                </div>
                {s.expected_outcome && <p className="mt-0.5 text-xs text-muted-foreground">{t("task.expected")} {s.expected_outcome}</p>}
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {s.status === "verified" ? t("step.verified") : s.status === "executed" ? t("step.checking")
                    : s.status === "denied" ? `${t("step.denied")} ${s.detail}` : `${t("step.error")} ${s.detail}`} · {s.duration_ms} ms
                </p>
              </motion.li>
            ))}
          </ol>
          {task.status !== "running" && (
            <div className="space-y-3 border-t border-border pt-3">
              <dl className="grid grid-cols-3 gap-2 text-center">
                <Metric label={t("metric.latency")} value={latency(task)} />
                <Metric label={t("metric.llmCalls")} value={String(task.llm_calls)} />
                <Metric label={t("metric.recoveries")} value={String(task.recoveries)} />
              </dl>
              {task.timings && <TimingBar timings={task.timings} t={t} />}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/** Kechikish qayerga ketganini ko'rsatadi: ekran surati, model, bajarish. */
function TimingBar({ timings: tm, t }: { timings: { screen_ms: number; llm_ms: number; exec_ms: number }; t: T }) {
  const total = tm.screen_ms + tm.llm_ms + tm.exec_ms;
  if (!total) return null;
  const parts = [
    { k: t("timing.model"), v: tm.llm_ms, c: "bg-primary" },
    { k: t("timing.screen"), v: tm.screen_ms, c: "bg-secondary" },
    { k: t("timing.exec"), v: tm.exec_ms, c: "bg-success" },
  ];
  const fmt = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
  return (
    <div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-muted" role="img"
        aria-label={parts.map((p) => `${p.k} ${fmt(p.v)}`).join(", ")}>
        {parts.map((p) => p.v > 0 && <div key={p.k} className={p.c} style={{ width: `${(p.v / total) * 100}%` }} />)}
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-muted-foreground">
        {parts.map((p) => (
          <span key={p.k} className="inline-flex items-center gap-1"><span className={cn("size-1.5 rounded-full", p.c)} />{p.k} {fmt(p.v)}</span>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}

/* ---------------- Dashboard ---------------- */

export function DashboardView({ x, l }: { x: X; l: L }) {
  const { t, lang } = l;
  const s = x.status;
  const recent = x.tasks.slice(0, 6);
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label={t("dash.assistant")} value={x.online ? (s?.busy ? t("dash.busy") : t("dash.ready")) : t("dash.offline")} ok={x.online} />
        <StatCard label={t("dash.model")} value={s ? `${s.provider.name}` : "—"} sub={s?.provider.detail !== "ok" ? s?.provider.detail : String(s?.config.model ?? "")} ok={s?.provider.ok} />
        <StatCard label={t("dash.os")} value={s?.os ?? "—"} sub={s ? `${t("dash.adapter")}: ${s.adapter}` : undefined} ok={!!s} />
        <StatCard label={t("dash.tsr")} value={s?.stats.success_rate != null ? `${s.stats.success_rate}%` : "—"}
          sub={s ? t("dash.tasksOf", { a: s.stats.success, b: s.stats.success + s.stats.failed }) : undefined} ok={s ? (s.stats.success_rate ?? 0) >= 50 : null} />
      </div>
      <Card>
        <CardTitle hint={t("dash.count", { n: x.tasks.length })}>{t("dash.recent")}</CardTitle>
        <TaskTable tasks={recent} lang={lang} t={t} />
      </Card>
    </div>
  );
}

function StatCard({ label, value, sub, ok }: { label: string; value: string; sub?: string; ok?: boolean | null }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-xs text-muted-foreground">{label}<Dot ok={ok} /></div>
      <p className="mt-2 truncate text-xl font-semibold tracking-tight">{value}</p>
      {sub && <p className="mt-0.5 truncate text-xs text-muted-foreground">{sub}</p>}
    </Card>
  );
}

/* ---------------- Tarix ---------------- */

export function TaskTable({ tasks, onSelect, lang, t }: { tasks: Task[]; onSelect?: (task: Task) => void; lang: Lang; t: T }) {
  if (!tasks.length) return <p className="py-8 text-center text-sm text-muted-foreground">{t("table.empty")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="pb-2 font-medium">{t("table.command")}</th><th className="pb-2 font-medium">{t("table.mode")}</th>
            <th className="pb-2 font-medium">{t("table.status")}</th><th className="pb-2 font-medium">{t("table.steps")}</th>
            <th className="pb-2 font-medium">{t("table.time")}</th><th className="pb-2 text-right font-medium">{t("table.date")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {tasks.map((task) => (
            <tr key={task.id} onClick={() => onSelect?.(task)} className={cn(onSelect && "cursor-pointer hover:bg-accent/40")}>
              <td className="max-w-[320px] truncate py-2.5 pr-3" lang={task.language}>{task.instruction}</td>
              <td className="py-2.5 font-mono text-xs">{task.mode}</td>
              <td className="py-2.5"><TaskStatus status={task.status} t={t} /></td>
              <td className="py-2.5 tabular-nums">{task.steps.length}</td>
              <td className="py-2.5 tabular-nums">{latency(task)}</td>
              <td className="py-2.5 text-right text-xs text-muted-foreground">{formatTime(task.started_at, lang)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HistoryView({ x, l }: { x: X; l: L }) {
  const { t, lang } = l;
  const [selected, setSelected] = useState<Task | null>(null);
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card>
        <CardTitle hint={
          <Button variant="ghost" className="h-7 px-2 text-xs" onClick={() => { if (confirm(t("history.clearConfirm"))) x.clearHistory(); }}>
            <Trash2 className="size-3.5" />{t("history.clear")}
          </Button>}>{t("history.title")}</CardTitle>
        <TaskTable tasks={x.tasks} onSelect={setSelected} lang={lang} t={t} />
      </Card>
      <LiveTask task={selected} lang={lang} t={t} />
    </div>
  );
}

/* ---------------- Tadqiqot va baholash ---------------- */

export function ResearchView({ x, l }: { x: X; l: L }) {
  const { t } = l;
  const rows = useMemo(() => (["A", "B", "C"] as Mode[]).map((m) => {
    const ts = x.tasks.filter((t) => t.mode === m && t.status !== "running");
    const done = ts.filter((t) => t.status === "success" || t.status === "failed");
    const ok = ts.filter((t) => t.status === "success").length;
    const lat = ts.filter((t) => t.finished_at).map((t) => (t.finished_at! - t.started_at) * 1000);
    const rec = ts.reduce((a, t) => a + t.recoveries, 0);
    const failedSteps = ts.reduce((a, t) => a + t.steps.filter((s) => s.status === "failed").length, 0);
    return {
      m, n: ts.length,
      tsr: done.length ? (ok / done.length) * 100 : null,
      lat: lat.length ? lat.reduce((a, b) => a + b, 0) / lat.length : null,
      recovery: failedSteps ? (Math.min(rec, failedSteps) / failedSteps) * 100 : null,
    };
  }), [x.tasks]);

  return (
    <div className="space-y-5">
      <Card>
        <CardTitle hint={t("research.hint")}>{t("research.title")}</CardTitle>
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th className="pb-2 font-medium">{t("research.mode")}</th><th className="pb-2 font-medium">{t("research.tasks")}</th>
              <th className="pb-2 font-medium">TSR</th><th className="pb-2 font-medium">{t("research.latency")}</th>
              <th className="pb-2 font-medium">{t("research.recovery")}</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((r) => (
              <tr key={r.m}>
                <td className="py-2.5">{r.m} — {t(`mode.${r.m}`)}</td>
                <td className="py-2.5 tabular-nums">{r.n}</td>
                <td className="py-2.5 tabular-nums">{r.tsr == null ? "—" : `${r.tsr.toFixed(1)}%`}</td>
                <td className="py-2.5 tabular-nums">{r.lat == null ? "—" : `${(r.lat / 1000).toFixed(2)} s`}</td>
                <td className="py-2.5 tabular-nums">{r.recovery == null ? "—" : `${r.recovery.toFixed(0)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-4 text-xs text-muted-foreground">{t("research.note")}</p>
      </Card>
    </div>
  );
}

/* ---------------- Sozlamalar ---------------- */

export function SettingsView({ status, l }: { status: Status | null; l: L }) {
  const { t } = l;
  if (!status) return <Card><p className="text-sm text-muted-foreground">{t("settings.noBackend")}</p></Card>;
  const c = status.config;
  const caps = status.capabilities;
  const yesNo = (v: boolean | undefined) => (v ? t("common.yes") : t("common.no"));
  const confirmRisk = (["low", "medium", "high"] as const).includes(c.confirm_risk as "low")
    ? t(`risk.${c.confirm_risk as "low" | "medium" | "high"}`) : String(c.confirm_risk);
  const rows: [string, React.ReactNode][] = [
    [t("settings.uiLang"), <LangSwitch key="lang" {...l} />],
    [t("settings.provider"), `${status.provider.name} — ${c.model}`],
    [t("settings.modelHealth"), <span key="h" className="inline-flex items-center gap-2"><Dot ok={status.provider.ok} />{status.provider.detail}</span>],
    [t("settings.vision"), yesNo(caps ? caps.screenshot_vision : status.provider.vision)],
    [t("settings.ocr"), caps?.ocr ? t("common.yes") : t("common.notImplemented")],
    [t("settings.ax"), caps?.accessibility_tree ? t("common.yes") : t("common.notImplemented")],
    [t("settings.stt"), `${c.whisper_model} · ${status.stt_engine === "mlx" ? "MLX (Apple GPU)" : status.stt_engine ?? "—"}`],
    [t("settings.fastPath"), c.fast_path ? t("settings.fastPathOn") : t("common.off")],
    [t("settings.tts"), `${c.tts_engine} · ${c.tts_enabled ? t("common.on") : t("common.off")}`],
    [t("settings.ttsAvail"), LANGS.map((lg) => `${lg}: ${status.tts[lg] ? "✓" : "—"}`).join("  ")],
    [t("settings.confirm"), t("settings.confirmFrom", { risk: confirmRisk })],
    [t("settings.maxSteps"), String(c.max_steps)],
    [t("settings.workspace"), String(c.workspace)],
    [t("settings.accessibility"), status.permissions.accessibility == null ? t("common.unknown")
      : status.permissions.accessibility ? t("common.granted") : t("common.notGranted")],
  ];
  return (
    <Card className="max-w-3xl">
      <CardTitle hint={t("settings.hint")}>{t("settings.title")}</CardTitle>
      <dl className="divide-y divide-border">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[200px_1fr] gap-4 py-2.5 text-sm">
            <dt className="text-muted-foreground">{k}</dt><dd className="break-words">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/* ---------------- Ekran tahlili ---------------- */

export function ScreenView({ x, l }: { x: X; l: L }) {
  const { lang, t } = l;
  const prompt = t("screen.prompt");
  const busy = !!x.status?.busy;
  const vision = x.status?.capabilities ? x.status.capabilities.screenshot_vision : x.status?.provider.vision;
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card>
        <CardTitle>{t("screen.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("screen.desc")}</p>
        <p className="mt-2 text-xs text-muted-foreground">{t("screen.limits")}</p>
        {x.status && vision === false && (
          <p role="alert" className="mt-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">{t("screen.noVision")}</p>
        )}
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <LangSwitch {...l} />
          <Button disabled={busy || x.online === false} onClick={() => x.run(prompt, lang, "C")}>
            <Monitor className="size-4" />{t("screen.button")}
          </Button>
        </div>
        {x.current?.instruction === prompt && x.current.status !== "running" && (
          <p className="mt-5 rounded-xl bg-muted p-4 text-sm leading-relaxed" lang={x.current.language}>{x.current.final_message}</p>
        )}
      </Card>
      <LiveTask task={x.current} lang={lang} t={t} />
    </div>
  );
}
