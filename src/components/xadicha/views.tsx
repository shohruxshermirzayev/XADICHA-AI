"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, Check, ChevronDown, ExternalLink, FileText, Loader2, Monitor, Octagon, Pencil, Plus, Trash2, X as XIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { detectCommandLanguage, LANG_LABEL, LANGS, LOCALE, type Lang, type MsgKey } from "@/lib/i18n";
import type { T } from "@/lib/use-lang";
import {
  describeAction, type Capability, type ChatMessage, type Mode, type PendingVoice, type Status, type Task,
  type useXadicha,
} from "@/lib/xadicha";
import { Button, Card, CardTitle, Dot, RiskBadge, StepIcon, TaskStatus, formatTime, latency } from "./ui";
import { VoiceOrb } from "./voice-orb";

type X = ReturnType<typeof useXadicha>;
interface L { lang: Lang; setLang: (l: Lang) => void; t: T }

const MODES: Mode[] = ["C", "B", "A"];

export function LangSwitch({ lang, setLang, t }: L) {
  return (
    <div role="radiogroup" aria-label={t("lang.label")} className="flex w-fit max-w-full flex-wrap gap-1 rounded-lg bg-muted p-1">
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

/** Hozir nima bo'layotgani — bitta manbadan (backend phase + tinglash holati + joriy qadam). */
export function activity(x: X): { key: MsgKey; tone: "idle" | "live" | "warn" | "ok" } {
  if (x.listening === "recording") return { key: "activity.recording", tone: "live" };
  if (x.listening === "transcribing") return { key: "activity.transcribing", tone: "live" };
  if (x.phase === "awaiting_confirmation") return { key: "activity.awaiting", tone: "warn" };
  if (x.phase === "speaking") return { key: "activity.speaking", tone: "live" };
  if (x.busy) {
    const executing = x.current?.status === "running" && x.current.steps.length > 0;
    return { key: executing ? "activity.executing" : "activity.thinking", tone: "live" };
  }
  if (x.current && x.current.status !== "running") return { key: "activity.done", tone: "ok" };
  return { key: "voice.idle", tone: "idle" };
}

/* ---------------- Ovozli yordamchi (asosiy ekran) ---------------- */

type Pending = PendingVoice;

export function AssistantView({ x, l }: { x: X; l: L }) {
  const { lang, t } = l;
  const [mode, setMode] = useState<Mode>("C");
  const [text, setText] = useState("");
  const pending = x.clarify;
  const setPending = (p: Pending | null) => { if (!p) x.clearClarify(); };
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = x.busy;
  const offline = x.online === false;
  const act = activity(x);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const v = text.trim();
    if (!v || busy || offline) return;
    setText("");
    setPending(null);
    // Kirill yozuvi: o'zbek kirill (ў, қ, ғ, ҳ yoki o'zbekcha so'zlar) — uz, aks holda — ru
    x.run(v, detectCommandLanguage(v, lang), mode);
  };

  const toggleVoice = async () => {
    if (x.listening === "transcribing") return;
    if (x.listening === "recording") {
      // Erta to'xtatish. Natija (bajarish / aniqlashtirish / "eshitilmadi") backend hodisalari orqali keladi
      await x.stopListening();
    } else {
      setPending(null);
      // Gapirib bo'linganini backend o'zi sezadi va aniq buyruqni darhol bajaradi
      x.startListening(lang, mode, true);
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
      if (e.code !== "Space" || e.repeat || el.closest("input, textarea, select, button, [contenteditable], [role=dialog], [role=alertdialog]")) return;
      e.preventDefault();
      if (!offline && (!busy || x.listening === "recording")) toggleRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [offline, busy, x.listening]);

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
      <Card className="glass flex min-h-[520px] flex-col p-0 xl:h-[calc(100vh-8.5rem)]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
          <LangSwitch {...l} />
          <div className="flex items-center gap-2">
          <Button variant="ghost" className="h-7 px-2 text-xs" disabled={busy || !x.messages.length} onClick={x.newConversation}>
            <Plus className="size-3.5" />{t("chat.new")}
          </Button>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            {t("mode.label")}
            <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} title={t(`mode.${mode}.hint`)}
              className="rounded-md border border-border bg-muted px-2 py-1 text-xs text-foreground focus-visible:outline-2 focus-visible:outline-ring">
              {MODES.map((m) => <option key={m} value={m}>{m} — {t(`mode.${m}`)}</option>)}
            </select>
          </label>
          </div>
        </div>

        <Conversation messages={x.messages} lang={lang} t={t} scrollKey={(pending ? 1 : 0) + (busy ? 2 : 0)}
          tasks={x.tasks} current={x.current} thinking={busy && x.phase !== "awaiting_confirmation"}
          onExample={(ex) => !busy && !offline && x.run(ex, lang, mode)} />

        <AnimatePresence>
          {pending && (
            <Clarification key="clar" p={pending} t={t}
              onRun={(cmd) => { setPending(null); x.push({ role: "user", text: cmd, lang: pending.language }); x.run(cmd, pending.language, mode, true); }}
              onEdit={() => { setText(pending.analysis.suggestion ?? pending.transcript); setPending(null); setTimeout(() => inputRef.current?.focus(), 0); }}
              onCancel={() => setPending(null)} />
          )}
        </AnimatePresence>

        <div className="flex items-center gap-4 border-t border-border px-4 py-3">
          {/* Yozuv davom etayotganda tugma o'chirilmaydi — aks holda to'xtatib bo'lmay qolardi */}
          <VoiceOrb state={x.listening} level={x.micLevel} busy={busy} t={t}
            disabled={offline || (busy && x.listening !== "recording")} onToggle={toggleVoice} />
          <div className="min-w-0 flex-1 space-y-2">
            <p className="flex h-5 items-center gap-2 text-xs" aria-live="polite">
              <span className={cn("size-1.5 rounded-full", act.tone === "live" ? "animate-pulse bg-secondary"
                : act.tone === "warn" ? "bg-warning" : act.tone === "ok" ? "bg-success" : "bg-muted-foreground")} />
              <span className="text-muted-foreground">{offline ? t("voice.offline") : t(act.key)}</span>
            </p>
            <form onSubmit={submit} className="flex gap-2">
              <label htmlFor="cmd" className="sr-only">{t("input.label")}</label>
              <input id="cmd" ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} disabled={offline} lang={lang}
                placeholder={t("input.placeholder")} autoComplete="off"
                className="h-10 min-w-0 flex-1 rounded-lg border border-input bg-muted/60 px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring" />
              {/* Faol vazifa paytida — faqat To'xtatish; bo'sh paytda — faqat Yuborish */}
              {busy ? (
                <Button type="button" variant="danger" onClick={x.stop} className="h-10"><Octagon className="size-4" />{t("input.stop")}</Button>
              ) : (
                <Button type="submit" disabled={!text.trim() || offline} className="h-10" aria-label={t("input.send")}><ArrowUp className="size-4" /></Button>
              )}
            </form>
          </div>
        </div>
      </Card>

      <LiveTask task={x.current} lang={lang} t={t} awaiting={x.phase === "awaiting_confirmation" && x.confirmation?.task_id === x.current?.id} />
    </div>
  );
}

/** Noaniq ovozli buyruq: asl matn ko'rsatiladi, hech narsa o'zicha bajarilmaydi. */
function Clarification({ p, t, onRun, onEdit, onCancel }: {
  p: Pending; t: T; onRun: (cmd: string) => void; onEdit: () => void; onCancel: () => void;
}) {
  const a = p.analysis;
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => { first.current?.focus(); }, []);
  const reason = (`clar.reason.${a.reason}` as MsgKey);
  return (
    <motion.section role="region" aria-labelledby="clar-title" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
      className="mx-4 mb-3 rounded-xl border border-warning/30 bg-warning/5 p-4">
      <h3 id="clar-title" className="text-sm font-semibold">{t("clar.title")}</h3>
      <p className="mt-1 text-sm"><span className="text-muted-foreground">{t("clar.heard")}</span>{" "}
        <q lang={p.language} className="font-medium">{p.transcript}</q></p>
      <p className="mt-1 text-xs text-muted-foreground">
        {t(reason)}
        {p.asr != null && <> · {t("clar.asr", { p: Math.round(p.asr * 100) })}</>}
        {" · "}{t("clar.intent", { p: Math.round(a.intent_confidence * 100) })}
      </p>
      {a.suggestion && a.suggestion !== p.transcript && (
        <p className="mt-2 text-sm">{t("clar.suggest", { s: a.suggestion })}</p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {a.suggestion && (
          <Button ref={first} onClick={() => onRun(a.suggestion!)}><Check className="size-4" />{t("clar.runSuggestion", { s: a.suggestion })}</Button>
        )}
        {(!a.suggestion || a.suggestion !== p.transcript) && (
          <Button ref={a.suggestion ? undefined : first} variant="outline" onClick={() => onRun(p.transcript)}>{t("clar.runOriginal")}</Button>
        )}
        <Button variant="outline" onClick={onEdit}><Pencil className="size-4" />{t("clar.edit")}</Button>
        <Button variant="ghost" onClick={onCancel}><XIcon className="size-4" />{t("clar.cancel")}</Button>
      </div>
    </motion.section>
  );
}

const EXAMPLES: Record<Lang, string[]> = {
  uz: ["Safari ni och", "Samarqand haqida qidir", "Ovozini ko'tar", "hisobot faylini top", "Ekranda nima turganini ayt"],
  ru: ["Открой Notes", "Найди информацию о Самарканде", "Сделай тише", "Опиши, что на экране"],
  en: ["Open Calculator", "Search for Samarkand", "Volume up", "Describe what is on the screen"],
};

const GROUP_MS = 2 * 60 * 1000;

function Conversation({ messages, lang, t, onExample, scrollKey = 0, tasks, current, thinking }: {
  messages: ChatMessage[]; lang: Lang; t: T; onExample: (text: string) => void; scrollKey?: number;
  tasks: Task[]; current: Task | null; thinking: boolean;
}) {
  const byId = useMemo(() => {
    const m = new Map(tasks.map((k) => [k.id, k]));
    if (current) m.set(current.id, current);
    return m;
  }, [tasks, current]);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Yangi xabar yoki aniqlashtirish kartasi chiqqanda oxirgi xabar ko'rinib tursin
    const id = setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" }), 60);
    return () => clearTimeout(id);
  }, [messages.length, scrollKey]);

  if (!messages.length) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-8 text-center">
        <p className="text-lg font-medium">{t("chat.greeting")}</p>
        <p className="max-w-sm text-sm text-muted-foreground">{t("chat.intro")}</p>
        <p className="mt-4 text-xs text-muted-foreground">{t("chat.examplesTitle")}</p>
        <div className="flex max-w-lg flex-wrap justify-center gap-2">
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
  const fmt = (ts: number) => new Date(ts).toLocaleTimeString(LOCALE[lang], { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="flex-1 overflow-y-auto px-5 py-4" role="log" aria-live="polite" aria-relevant="additions">
      <AnimatePresence initial={false}>
        {messages.map((m, i) => {
          const prev = messages[i - 1];
          const next = messages[i + 1];
          const startsGroup = !prev || prev.role !== m.role || m.ts - prev.ts > GROUP_MS;
          const endsGroup = !next || next.role !== m.role || next.ts - m.ts > GROUP_MS;
          const who = m.role === "user" ? t("chat.you") : m.role === "assistant" ? "XADICHA" : t("chat.system");
          return (
            <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              className={cn("flex flex-col", m.role === "user" ? "items-end" : "items-start", startsGroup ? "mt-4 first:mt-0" : "mt-1")}>
              {startsGroup && <span className="mb-1 px-1 text-[11px] font-medium text-muted-foreground">{who}</span>}
              <div lang={m.lang} className={cn("max-w-[82%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap",
                m.role === "user" && "rounded-br-md bg-primary text-primary-foreground",
                m.role === "assistant" && "rounded-bl-md bg-muted",
                m.role === "system" && "border border-destructive/30 bg-destructive/10 text-destructive")}>
                {m.text}
                {m.role === "assistant" && m.status && m.status !== "success" && (
                  <div className="mt-1"><TaskStatus status={m.status} t={t} /></div>
                )}
              </div>
              {m.role === "assistant" && m.taskId && byId.get(m.taskId) && (
                <TaskCard task={byId.get(m.taskId)!} lang={lang} t={t} />
              )}
              {endsGroup && <time className="mt-1 px-1 text-[10px] text-muted-foreground" dateTime={new Date(m.ts).toISOString()}>{fmt(m.ts)}</time>}
            </motion.div>
          );
        })}
      </AnimatePresence>
      {thinking && (
        <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground" role="status" aria-live="polite">
          <span className="inline-flex gap-1 rounded-2xl rounded-bl-md bg-muted px-3 py-2.5" aria-hidden>
            <span className="size-1.5 animate-bounce rounded-full bg-secondary [animation-delay:-0.3s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-secondary [animation-delay:-0.15s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-secondary" />
          </span>
          {t("chat.thinking")}
        </div>
      )}
      <div ref={end} />
    </div>
  );
}

/** Suhbat ichidagi ixcham vazifa kartochkasi: natijalar (manbalar / fayllar) va ochiladigan tafsilotlar. */
function TaskCard({ task, lang, t }: { task: Task; lang: Lang; t: T }) {
  const [open, setOpen] = useState(false);
  const results = task.data?.results ?? [];
  const isSearch = results.some((r) => r.url);
  const isFiles = results.some((r) => r.path);
  const total = (task.trace ?? []).reduce((a, s) => a + s.ms, 0);
  return (
    <div className="mt-1.5 w-full max-w-[82%] space-y-2">
      {task.resolved_from && (
        <p className="px-1 text-[11px] text-muted-foreground">
          {t("card.resolved", { from: task.resolved_from })} {task.steps[0] ? describeAction(task.steps[0].action, lang) : ""}
        </p>
      )}
      {isSearch && (
        <div className="rounded-xl border border-border bg-card/60 p-3">
          <p className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            {t("card.sources")}{task.data?.search_provider ? ` · ${t("card.via", { p: task.data.search_provider })}` : ""}
          </p>
          <ol className="space-y-2">
            {results.slice(0, 5).map((r, i) => (
              <li key={r.url ?? i} className="text-xs">
                <a href={r.url} target="_blank" rel="noreferrer noopener"
                  className="inline-flex items-start gap-1 font-medium text-foreground hover:text-primary focus-visible:outline-2 focus-visible:outline-ring">
                  <span className="text-muted-foreground">[{i + 1}]</span>{r.title}<ExternalLink className="mt-0.5 size-3 shrink-0" aria-hidden />
                </a>
                {r.snippet && <p className="mt-0.5 line-clamp-2 text-muted-foreground">{r.snippet}</p>}
                <p className="truncate text-[10px] text-muted-foreground/80">{r.url}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
      {isFiles && (
        <div className="rounded-xl border border-border bg-card/60 p-3">
          <p className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{t("card.files")}</p>
          <ul className="space-y-1">
            {results.slice(0, 8).map((r) => (
              <li key={r.path} className="flex items-center gap-1.5 truncate text-xs" title={r.path}>
                <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />{r.title}
                <span className="truncate text-[10px] text-muted-foreground">{r.path}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(task.steps.length > 0 || (task.trace?.length ?? 0) > 0) && (
        <div>
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
            className="inline-flex items-center gap-1 px-1 text-[11px] text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
            <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} aria-hidden />
            {open ? t("card.hide") : t("card.details")} · {t("card.steps", { n: task.steps.length })} · {latency(task)}
          </button>
          {open && (
            <div className="mt-1.5 space-y-2 rounded-xl border border-border bg-card/60 p-3 text-xs">
              <ol className="space-y-1">
                {task.steps.map((s) => (
                  <li key={s.index} className="flex items-start gap-2">
                    <StepIcon step={s} t={t} />
                    <span className="min-w-0 flex-1 break-words">{describeAction(s.action, lang)}
                      {s.detail && <span className="text-muted-foreground"> — {s.detail}</span>}</span>
                    <RiskBadge risk={s.risk} t={t} />
                  </li>
                ))}
              </ol>
              {(task.trace?.length ?? 0) > 0 && (
                <div>
                  <p className="mb-1 text-[11px] text-muted-foreground">{t("card.trace")}</p>
                  <ul className="space-y-0.5">
                    {(task.trace ?? []).map((sp, i) => (
                      <li key={i} className="grid grid-cols-[110px_1fr_56px] items-center gap-2 text-[11px]">
                        <span className={cn("truncate", !sp.ok && "text-destructive")}>{sp.stage}</span>
                        <span className="h-1 rounded-full bg-muted"><span className="block h-full rounded-full bg-primary/70"
                          style={{ width: `${total ? Math.max(2, (sp.ms / total) * 100) : 2}%` }} /></span>
                        <span className="text-right tabular-nums text-muted-foreground">{sp.ms} ms</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------- Joriy vazifa (Task Manager) ---------------- */

export function LiveTask({ task, lang, t, awaiting = false }: { task: Task | null; lang: Lang; t: T; awaiting?: boolean }) {
  return (
    <Card className="glass h-fit">
      <CardTitle hint={task ? (awaiting
        ? <span className="inline-flex items-center gap-1.5 text-xs font-medium text-warning"><Loader2 className="size-3.5 animate-spin" />{t("task.awaiting")}</span>
        : <TaskStatus status={task.status} t={t} />) : null}>{t("task.title")}</CardTitle>
      {!task ? (
        <p className="py-10 text-center text-sm text-muted-foreground">{t("task.empty")}</p>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="text-sm font-medium" lang={task.language}>{task.instruction}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("task.mode")} {task.mode} · {task.language.toUpperCase()} {task.intent && `· ${task.intent}`}
              {task.planner === "rules" && ` · ${t("task.fastPath")}`}
            </p>
          </div>
          <ol className="relative space-y-3 border-l border-border pl-5" aria-label={t("task.title")}>
            {task.steps.length === 0 && task.status === "running" && (
              <li className="text-xs text-muted-foreground">{t("task.planning")}</li>
            )}
            {task.steps.map((s) => (
              <motion.li key={s.index} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} className="relative">
                <span className="absolute top-0.5 -left-[27px] rounded-full bg-card"><StepIcon step={s} t={t} /></span>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm break-words"><span className="mr-1 text-muted-foreground tabular-nums">{s.index}.</span>{describeAction(s.action, lang)}</p>
                  <RiskBadge risk={s.risk} t={t} />
                </div>
                {s.expected_outcome && <p className="mt-0.5 text-xs text-muted-foreground">{t("task.expected")} {s.expected_outcome}</p>}
                <p className={cn("mt-0.5 text-[11px]", s.status === "failed" || s.status === "error" ? "text-destructive"
                  : s.status === "denied" ? "text-warning" : "text-muted-foreground")}>
                  {s.status === "verified" ? t("step.verified") : s.status === "executed" ? t("step.checking")
                    : s.status === "denied" ? `${t("step.denied")} ${s.detail}` : `${t("step.error")} ${s.detail}`}
                  {s.detail && (s.status === "verified" || s.status === "executed") && <> · {t("task.actual")} {s.detail}</>}
                  {" · "}{s.duration_ms} ms
                </p>
              </motion.li>
            ))}
          </ol>
          {task.status !== "running" && (
            <div className="space-y-3 border-t border-border pt-3">
              <dl className="grid grid-cols-4 gap-2 text-center">
                <Metric label={t("metric.latency")} tip={t("tip.latency")} value={latency(task)} />
                <Metric label={t("metric.llmCalls")} tip={t("tip.llmCalls")} value={String(task.llm_calls)} />
                <Metric label={t("metric.retries")} tip={t("tip.retries")} value={String(task.retries)} />
                <Metric label={t("metric.recoveries")} tip={t("tip.recoveries")} value={String(task.recoveries)} />
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
    <div title={t("tip.timing")}>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-muted" role="img"
        aria-label={`${t("tip.timing")}: ${parts.map((p) => `${p.k} ${fmt(p.v)}`).join(", ")}`}>
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

function Metric({ label, value, tip }: { label: string; value: string; tip?: string }) {
  return (
    <div title={tip}>
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}

/* ---------------- Dashboard ---------------- */

function breakdown(tasks: Task[], key: (t: Task) => string) {
  const m = new Map<string, { n: number; ok: number; done: number }>();
  for (const t of tasks) {
    if (t.status === "running") continue;
    const k = key(t) || "—";
    const r = m.get(k) ?? { n: 0, ok: 0, done: 0 };
    r.n++;
    if (t.status === "success") r.ok++;
    if (t.status === "success" || t.status === "failed") r.done++;
    m.set(k, r);
  }
  return [...m.entries()].sort((a, b) => b[1].n - a[1].n);
}

function Breakdown({ title, rows, t, label }: { title: string; rows: ReturnType<typeof breakdown>; t: T; label?: (k: string) => string }) {
  const max = Math.max(1, ...rows.map(([, r]) => r.n));
  return (
    <Card className="glass">
      <CardTitle>{title}</CardTitle>
      {!rows.length ? <p className="text-sm text-muted-foreground">{t("dash.noData")}</p> : (
        <ul className="space-y-2.5">
          {rows.map(([k, r]) => (
            <li key={k} className="text-sm">
              <div className="flex justify-between gap-2"><span>{label ? label(k) : k}</span>
                <span className="text-xs tabular-nums text-muted-foreground">{r.n} · TSR {r.done ? `${Math.round((r.ok / r.done) * 100)}%` : "—"}</span></div>
              <div className="mt-1 h-1.5 rounded-full bg-muted"><div className="h-full rounded-full bg-primary/70" style={{ width: `${(r.n / max) * 100}%` }} /></div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function DashboardView({ x, l }: { x: X; l: L }) {
  const { t, lang } = l;
  const s = x.status;
  const recent = x.tasks.slice(0, 6);
  const byLang = useMemo(() => breakdown(x.tasks, (k) => k.language.toUpperCase()), [x.tasks]);
  const byMode = useMemo(() => breakdown(x.tasks, (k) => k.mode), [x.tasks]);
  return (
    <div className="space-y-5">
      <p className="text-xs text-muted-foreground">{t("dash.live")}</p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label={t("dash.assistant")} value={x.online ? t(`phase.${x.phase}`) : t("dash.offline")} ok={x.online} />
        <StatCard label={t("dash.model")} value={s ? `${s.provider.name}` : "—"} sub={s?.provider.detail !== "ok" ? s?.provider.detail : String(s?.config.model ?? "")} ok={s?.provider.ok} />
        <StatCard label={t("dash.platform")} value={s?.os ?? "—"} sub={s ? `${t("dash.adapter")}: ${s.adapter}` : undefined} ok={!!s} />
        <StatCard label={t("dash.tsr")} value={s?.stats.success_rate != null ? `${s.stats.success_rate}%` : "—"}
          sub={s ? t("dash.tasksOf", { a: s.stats.success, b: s.stats.success + s.stats.failed }) : undefined} ok={s ? (s.stats.success_rate ?? 0) >= 50 : null} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Breakdown title={t("dash.byLang")} rows={byLang} t={t} />
        <Breakdown title={t("dash.byMode")} rows={byMode} t={t} label={(k) => (["A", "B", "C"].includes(k) ? `${k} — ${t(`mode.${k as Mode}`)}` : k)} />
      </div>
      <Card className="glass">
        <CardTitle hint={t("dash.count", { n: x.tasks.length })}>{t("dash.recent")}</CardTitle>
        <TaskTable tasks={recent} lang={lang} t={t} />
      </Card>
    </div>
  );
}

function StatCard({ label, value, sub, ok }: { label: string; value: string; sub?: string; ok?: boolean | null }) {
  return (
    <Card className="glass p-4">
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
            <th scope="col" className="pb-2 font-medium">{t("table.command")}</th><th scope="col" className="pb-2 font-medium">{t("table.mode")}</th>
            <th scope="col" className="pb-2 font-medium">{t("table.status")}</th><th scope="col" className="pb-2 font-medium">{t("table.steps")}</th>
            <th scope="col" className="pb-2 font-medium">{t("table.time")}</th><th scope="col" className="pb-2 text-right font-medium">{t("table.date")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {tasks.map((task) => (
            <tr key={task.id} className={cn(onSelect && "hover:bg-accent/40")}>
              <td className="max-w-[320px] truncate py-2.5 pr-3" lang={task.language}>
                {onSelect ? (
                  <button type="button" onClick={() => onSelect(task)} className="max-w-full truncate text-left hover:underline focus-visible:outline-2 focus-visible:outline-ring">{task.instruction}</button>
                ) : task.instruction}
              </td>
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
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
      <Card className="glass">
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
    const ts = x.tasks.filter((k) => k.mode === m && k.status !== "running");
    const done = ts.filter((k) => k.status === "success" || k.status === "failed");
    const ok = ts.filter((k) => k.status === "success").length;
    const lat = ts.filter((k) => k.finished_at).map((k) => (k.finished_at! - k.started_at) * 1000);
    const rec = ts.reduce((a, k) => a + k.recoveries, 0);
    const failedSteps = ts.reduce((a, k) => a + k.steps.filter((s) => s.status === "failed").length, 0);
    return {
      m, n: ts.length,
      tsr: done.length ? (ok / done.length) * 100 : null,
      lat: lat.length ? lat.reduce((a, b) => a + b, 0) / lat.length : null,
      recovery: failedSteps ? (Math.min(rec, failedSteps) / failedSteps) * 100 : null,
    };
  }), [x.tasks]);

  return (
    <div className="space-y-5">
      <Card className="glass">
        <CardTitle hint={t("research.hint")}>{t("research.title")}</CardTitle>
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th scope="col" className="pb-2 font-medium">{t("research.mode")}</th><th scope="col" className="pb-2 font-medium">{t("research.tasks")}</th>
              <th scope="col" className="pb-2 font-medium">TSR</th><th scope="col" className="pb-2 font-medium">{t("research.latency")}</th>
              <th scope="col" className="pb-2 font-medium">{t("research.recovery")}</th></tr>
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

const CAP_ORDER = ["os_adapter", "screenshot", "vision_model", "ocr", "accessibility_tree", "microphone", "stt", "tts", "windows_ui_automation"] as const;
const CAP_STYLE: Record<Capability["state"], string> = {
  available: "bg-success/10 text-success ring-success/25",
  not_tested: "bg-warning/10 text-warning ring-warning/25",
  unavailable: "bg-destructive/10 text-destructive ring-destructive/30",
  not_implemented: "bg-muted text-muted-foreground ring-border",
};

function capOf(status: Status, key: string): Capability | null {
  const c = status.capabilities?.[key];
  return c && typeof c === "object" ? c : null;
}

export function SettingsView({ status, l }: { status: Status | null; l: L }) {
  const { t } = l;
  if (!status) return <Card><p className="text-sm text-muted-foreground">{t("settings.noBackend")}</p></Card>;
  const c = status.config;
  const confirmRisk = (["low", "medium", "high"] as const).includes(c.confirm_risk as "low")
    ? t(`risk.${c.confirm_risk as "low" | "medium" | "high"}`) : String(c.confirm_risk);
  const rows: [string, React.ReactNode][] = [
    [t("settings.uiLang"), <LangSwitch key="lang" {...l} />],
    [t("settings.provider"), `${status.provider.name} — ${c.model}`],
    [t("settings.modelHealth"), <span key="h" className="inline-flex items-center gap-2"><Dot ok={status.provider.ok} />{status.provider.detail}</span>],
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
    <div className="grid max-w-5xl min-w-0 gap-5 lg:grid-cols-2">
      <Card className="glass min-w-0">
        <CardTitle hint={t("settings.hint")}>{t("settings.title")}</CardTitle>
        <dl className="divide-y divide-border">
          {rows.map(([k, v]) => (
            <div key={k} className="grid grid-cols-1 gap-1 py-2.5 text-sm sm:grid-cols-[170px_minmax(0,1fr)] sm:gap-4">
              <dt className="text-muted-foreground">{k}</dt><dd className="break-words">{v}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <Card className="glass h-fit min-w-0">
        <CardTitle>{t("settings.capabilities")}</CardTitle>
        <p className="-mt-2 mb-3 text-xs text-muted-foreground">{t("settings.capHint")}</p>
        <ul className="divide-y divide-border">
          {CAP_ORDER.map((key) => {
            const cap = capOf(status, key);
            if (!cap) return null;
            return (
              <li key={key} className="flex items-start justify-between gap-3 py-2.5 text-sm">
                <div className="min-w-0">
                  <p>{t(`cap.${key}`)}</p>
                  {cap.detail && <p className="mt-0.5 break-words text-xs text-muted-foreground">{cap.detail}</p>}
                </div>
                <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1", CAP_STYLE[cap.state])}>
                  {t(`cap.${cap.state}`)}
                </span>
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}

/* ---------------- Ekran tahlili ---------------- */

export function ScreenView({ x, l }: { x: X; l: L }) {
  const { lang, t } = l;
  const prompt = t("screen.prompt");
  const vision = x.status ? capOf(x.status, "vision_model") : null;
  const noVision = !!x.status && (vision ? vision.state === "unavailable" : !x.status.provider.vision);
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
      <Card className="glass">
        <CardTitle>{t("screen.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("screen.desc")}</p>
        <p className="mt-2 text-xs text-muted-foreground">{t("screen.limits")}</p>
        {noVision && (
          <p role="alert" className="mt-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">{t("screen.noVision")}</p>
        )}
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <LangSwitch {...l} />
          <Button disabled={x.busy || x.online === false} onClick={() => x.run(prompt, lang, "C")}>
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
