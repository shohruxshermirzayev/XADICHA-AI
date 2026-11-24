"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { AlertCircle, ArrowDown, ArrowUp, Check, ChevronDown, Copy, ExternalLink, FileText, Octagon, Pencil, Plus, RotateCcw, X as XIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { detectCommandLanguage, LOCALE, type Lang, type MsgKey } from "@/lib/i18n";
import { fmtMs, orbState, outcomeFlash, revealWords, taskLatencyMs, timeline, type OrbState, type RowState } from "@/lib/presence";
import type { T } from "@/lib/use-lang";
import { cn } from "@/lib/utils";
import { describeAction, type ChatMessage, type Mode, type PendingVoice, type Task, type useXadicha } from "@/lib/xadicha";
import { AIOrb } from "./ai-orb";
import { GlassInput, GlassPanel, PanelTitle } from "./glass";
import { TaskTimeline, TraceList } from "./task-timeline";
import { Button, TaskStatus } from "./ui";
import { VoiceControl } from "./voice-control";

type X = ReturnType<typeof useXadicha>;
interface L { lang: Lang; setLang: (l: Lang) => void; t: T }

const MODES: Mode[] = ["C", "B", "A"];
const GROUP_MS = 2 * 60 * 1000;

/** Orb holati: haqiqiy backend holati + tugagan vazifa natijasining qisqa (5 s) ko'rinishi. */
export function usePresence(x: X): { orb: OrbState; segments: RowState[] } {
  const [flash, setFlash] = useState<"error" | "interrupted" | null>(null);
  const key = x.current ? `${x.current.id}:${x.current.status}` : "";
  const current = x.current;
  useEffect(() => {
    const f = outcomeFlash(current);
    if (!f) return;
    const on = setTimeout(() => setFlash(f), 0);
    const off = setTimeout(() => setFlash(null), 5000);
    return () => { clearTimeout(on); clearTimeout(off); setFlash(null); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    if (!x.error) return;
    const on = setTimeout(() => setFlash("error"), 0);
    const off = setTimeout(() => setFlash(null), 5000);
    return () => { clearTimeout(on); clearTimeout(off); };
  }, [x.error]);
  const orb = orbState({ online: x.online, listening: x.listening, phase: x.phase, busy: x.busy, current: x.current, flash });
  const { activeStep } = x;
  const segments = useMemo(() => (current ? timeline(current, { activeStep })
    .filter((r) => r.step).map((r) => r.state) : []), [current, activeStep]);
  return { orb, segments };
}

/* ---------------- Asosiy ish maydoni ---------------- */

export function AssistantView({ x, l, onOpenScreen, screenSummary }: {
  x: X; l: L; onOpenScreen: () => void; screenSummary?: React.ReactNode;
}) {
  const { lang, t } = l;
  const [mode, setMode] = useState<Mode>("C");
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = x.busy;
  const offline = x.online === false;
  const { orb, segments } = usePresence(x);
  const pending = x.clarify;
  const awaiting = x.phase === "awaiting_confirmation" && x.confirmation?.task_id === x.current?.id;

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const v = text.trim();
    if (!v || busy || offline) return;
    setText("");
    x.clearClarify();
    // Kirill yozuvi: o'zbek kirill (ў, қ, ғ, ҳ yoki o'zbekcha so'zlar) — uz, aks holda — ru
    x.run(v, detectCommandLanguage(v, lang), mode);
  };

  const toggleVoice = async () => {
    if (x.listening === "transcribing") return;
    if (x.listening === "recording") {
      // Erta to'xtatish. Natija (bajarish / aniqlashtirish / "eshitilmadi") backend hodisalari orqali keladi
      await x.stopListening();
    } else {
      x.clearClarify();
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

  const lastUser = [...x.messages].reverse().find((m) => m.role === "user");
  const retry = lastUser && !busy && !offline
    ? () => x.run(lastUser.text, (lastUser.lang as Lang) ?? lang, mode) : undefined;
  const voiceDisabled = offline || (busy && x.listening !== "recording");

  return (
    <div className="grid min-h-0 gap-4 xl:h-[calc(100dvh-7rem)] xl:grid-cols-[minmax(0,1fr)_360px]">
      <GlassPanel as="section" aria-label={t("nav.assistant")} className="flex min-h-[560px] min-w-0 flex-col overflow-hidden xl:min-h-0">
        <div className="flex items-center justify-end gap-2 px-4 pt-3">
          <Button variant="ghost" className="h-8 px-3 text-xs" disabled={busy || !x.messages.length} onClick={x.newConversation}>
            <Plus className="size-3.5" />{t("chat.new")}
          </Button>
        </div>

        <Conversation x={x} lang={lang} t={t} orb={orb} onToggleVoice={voiceDisabled ? undefined : toggleVoice}
          onExample={(ex) => !busy && !offline && x.run(ex, lang, mode)} onRetry={retry} />

        <AnimatePresence>
          {pending && (
            <Clarification key="clar" p={pending} t={t}
              onRun={(cmd) => { x.clearClarify(); x.push({ role: "user", text: cmd, lang: pending.language }); x.run(cmd, pending.language, mode, true); }}
              onEdit={() => { setText(pending.analysis.suggestion ?? pending.transcript); x.clearClarify(); setTimeout(() => inputRef.current?.focus(), 0); }}
              onCancel={() => x.clearClarify()} />
          )}
        </AnimatePresence>

        {/* Ovoz va matn — bitta suzuvchi kapsula */}
        <div className="px-3 pb-3 sm:px-4 sm:pb-4">
          <div className="glass-strong flex items-center gap-2 rounded-[26px] p-2 pr-2.5 transition-[border-color,box-shadow] duration-200 focus-within:border-primary/45 focus-within:shadow-[inset_0_1px_0_rgb(255_255_255/0.14),0_0_0_4px_rgb(119_117_255/0.12),var(--shadow-float)]">
            <VoiceControl orb={orb} listening={x.listening} level={x.micLevel} segments={segments} t={t}
              disabled={voiceDisabled} onToggle={toggleVoice} size={48} />
            <form onSubmit={submit} className="flex min-w-0 flex-1 items-center gap-2">
              <label htmlFor="cmd" className="sr-only">{t("input.label")}</label>
              <GlassInput id="cmd" ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} disabled={offline} lang={lang}
                placeholder={t("input.placeholder")} autoComplete="off"
                className="h-11 flex-1 border-transparent bg-transparent px-2 focus:border-transparent focus:bg-transparent focus-visible:ring-0" />
              <label className="hidden items-center sm:flex">
                <span className="sr-only">{t("mode.label")}</span>
                <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} title={`${t("mode.label")}: ${t(`mode.${mode}.hint`)}`}
                  className="h-8 cursor-pointer appearance-none rounded-full border border-white/10 bg-white/[0.05] px-3 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
                  {MODES.map((m) => <option key={m} value={m} className="bg-[#10162b]">{m} · {t(`mode.${m}`)}</option>)}
                </select>
              </label>
              {/* Faol vazifa paytida — faqat To'xtatish; bo'sh paytda — faqat Yuborish */}
              {busy ? (
                <Button type="button" variant="danger" onClick={x.stop} className="h-10 px-4"><Octagon className="size-4" />{t("input.stop")}</Button>
              ) : (
                <Button type="submit" disabled={!text.trim() || offline} className="size-10 p-0" aria-label={t("input.send")}>
                  <ArrowUp className="size-[18px]" />
                </Button>
              )}
            </form>
          </div>
          <div className="mt-2 flex items-center justify-between gap-3 px-3 text-xs">
            <p className="flex min-w-0 items-center gap-2 text-muted-foreground" aria-live="polite">
              <span className={cn("size-1.5 shrink-0 rounded-full", ORB_DOT[orb])} />
              <span className="truncate">{t(`orb.${orb}` as MsgKey)}</span>
            </p>
            <p className="hidden shrink-0 text-faint sm:block">{t("chat.hint")}</p>
          </div>
        </div>
      </GlassPanel>

      <div className="flex min-h-0 min-w-0 flex-col gap-4">
        <CurrentTaskPanel task={x.current} lang={lang} t={t} activeStep={x.activeStep} awaiting={awaiting} />
        <GlassPanel className="p-4">
          <button type="button" onClick={onOpenScreen}
            className="flex w-full items-center justify-between gap-3 text-left focus-visible:outline-2 focus-visible:outline-ring"
            aria-label={t("panel.screenOpen")}>
            <span className="text-[13px] font-medium tracking-wide text-muted-foreground">{t("panel.screen")}</span>
            <ChevronDown className="size-4 -rotate-90 text-muted-foreground" aria-hidden />
          </button>
          <div className="mt-2 text-sm">{screenSummary}</div>
        </GlassPanel>
      </div>
    </div>
  );
}

const ORB_DOT: Record<OrbState, string> = {
  idle: "bg-success", listening: "animate-pulse bg-secondary", processing: "animate-pulse bg-secondary",
  thinking: "animate-pulse bg-primary", executing: "animate-pulse bg-blue", speaking: "animate-pulse bg-primary",
  awaiting: "bg-warning", interrupted: "bg-warning", error: "bg-destructive", offline: "bg-destructive",
};

/* ---------------- Aniqlashtirish ---------------- */

/** Noaniq ovozli buyruq: asl matn ko'rsatiladi, hech narsa o'zicha bajarilmaydi. */
function Clarification({ p, t, onRun, onEdit, onCancel }: {
  p: PendingVoice; t: T; onRun: (cmd: string) => void; onEdit: () => void; onCancel: () => void;
}) {
  const a = p.analysis;
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => { first.current?.focus(); }, []);
  const reason = (`clar.reason.${a.reason}` as MsgKey);
  return (
    <motion.section role="region" aria-labelledby="clar-title" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 6 }} className="mx-4 mb-3 rounded-[22px] border border-warning/25 bg-warning/[0.06] p-4">
      <h3 id="clar-title" className="text-sm font-semibold">{t("clar.title")}</h3>
      <p className="mt-1 text-sm"><span className="text-muted-foreground">{t("clar.heard")}</span>{" "}
        <q lang={p.language} className="font-medium">{p.transcript}</q></p>
      <p className="mt-1 text-xs text-muted-foreground">
        {t(reason)}
        {p.asr != null && <> · {t("clar.asr", { p: Math.round(p.asr * 100) })}</>}
        {" · "}{t("clar.intent", { p: Math.round(a.intent_confidence * 100) })}
      </p>
      {a.suggestion && a.suggestion !== p.transcript && <p className="mt-2 text-sm">{t("clar.suggest", { s: a.suggestion })}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {a.suggestion && <Button ref={first} onClick={() => onRun(a.suggestion!)}><Check className="size-4" />{t("clar.runSuggestion", { s: a.suggestion })}</Button>}
        {(!a.suggestion || a.suggestion !== p.transcript) && (
          <Button ref={a.suggestion ? undefined : first} variant="outline" onClick={() => onRun(p.transcript)}>{t("clar.runOriginal")}</Button>
        )}
        <Button variant="outline" onClick={onEdit}><Pencil className="size-4" />{t("clar.edit")}</Button>
        <Button variant="ghost" onClick={onCancel}><XIcon className="size-4" />{t("clar.cancel")}</Button>
      </div>
    </motion.section>
  );
}

/* ---------------- Suhbat ---------------- */

const EXAMPLES: Record<Lang, string[]> = {
  uz: ["Safari ni och", "Samarqand haqida qidir", "Ovozini ko'tar", "hisobot faylini top", "Ekranda nima turganini ayt"],
  ru: ["Открой Notes", "Найди информацию о Самарканде", "Сделай тише", "Опиши, что на экране"],
  en: ["Open Calculator", "Search for Samarkand", "Volume up", "Describe what is on the screen"],
};

/** Yangi kelgan javobning haqiqiy matnini so'zma-so'z ochish (backend matnni bir yo'la yuboradi; matn to'qilmaydi). */
function RevealText({ text, animate }: { text: string; animate: boolean }) {
  const reduce = useReducedMotion();
  const words = useMemo(() => revealWords(text), [text]);
  const [n, setN] = useState(animate && !reduce ? 0 : words.length);
  useEffect(() => {
    if (!animate || reduce) return;
    const step = Math.max(12, Math.min(40, 1100 / Math.max(1, words.length)));
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setN(i);
      if (i >= words.length) clearInterval(id);
    }, step);
    return () => clearInterval(id);
  }, [animate, reduce, words]);
  if (n >= words.length) return <>{text}</>;
  return (
    <>
      <span className="sr-only">{text}</span>
      <span aria-hidden>{words.slice(0, n).join("")}<span className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] animate-pulse bg-secondary" /></span>
    </>
  );
}

function CopyButton({ text, t }: { text: string; t: T }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {}
  };
  return (
    <button type="button" onClick={copy} aria-label={done ? t("chat.copied") : t("chat.copy")} title={done ? t("chat.copied") : t("chat.copy")}
      className="rounded-full p-1.5 text-faint transition-colors hover:bg-white/[0.06] hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
      {done ? <Check className="size-3.5 text-success" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
    </button>
  );
}

function Conversation({ x, lang, t, orb, onExample, onRetry, onToggleVoice }: {
  x: X; lang: Lang; t: T; orb: OrbState; onExample: (text: string) => void; onRetry?: () => void; onToggleVoice?: () => void;
}) {
  const { messages, tasks, current } = x;
  const thinking = x.busy && x.phase !== "awaiting_confirmation" && x.phase !== "speaking";
  const byId = useMemo(() => {
    const m = new Map(tasks.map((k) => [k.id, k]));
    if (current) m.set(current.id, current);
    return m;
  }, [tasks, current]);

  // Faqat shu sessiyada jonli kelgan javoblar animatsiya bilan ochiladi (tiklangan tarix — darhol)
  const [initialIds] = useState(() => new Set(messages.map((m) => m.id)));
  const isLive = (m: ChatMessage) => m.role === "assistant" && !initialIds.has(m.id) && !m.id.startsWith("turn-");

  // Foydalanuvchi yuqoriga aylantirgan bo'lsa — joyidan siljitilmaydi; "Yangi xabarlar" tugmasi chiqadi
  const box = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const [unseen, setUnseen] = useState(false);
  const toBottom = useCallback((smooth = true) => {
    const el = box.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);
  const onScroll = () => {
    const el = box.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
    if (atBottom.current) setUnseen(false);
  };
  const signal = `${messages.length}:${thinking ? 1 : 0}:${x.clarify ? 1 : 0}`;
  useEffect(() => {
    const id = setTimeout(() => {
      if (atBottom.current) toBottom();
      else setUnseen(true);
    }, 60);
    return () => clearTimeout(id);
  }, [signal, toBottom]);

  if (!messages.length) {
    return (
      <div className="relative flex flex-1 flex-col items-center justify-center gap-3 overflow-y-auto px-6 py-6 text-center">
        <div aria-hidden onClick={onToggleVoice} className={cn("mb-3", onToggleVoice && "cursor-pointer")}>
          <AIOrb state={orb} level={x.micLevel} size={156} />
        </div>
        <h2 className="text-gradient text-2xl font-semibold tracking-tight sm:text-[28px]">{t("chat.greeting")}</h2>
        <p className="max-w-md text-[15px] leading-relaxed text-muted-foreground">{t("chat.intro")}</p>
        <p className="mt-4 text-xs text-faint">{t("chat.examplesTitle")}</p>
        <div className="flex max-w-xl flex-wrap justify-center gap-2">
          {EXAMPLES[lang].map((ex) => (
            <button key={ex} lang={lang} onClick={() => onExample(ex)}
              className="glass-subtle glass-hover rounded-full px-3.5 py-1.5 text-[13px] text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
              {ex}
            </button>
          ))}
        </div>
      </div>
    );
  }

  const fmt = (ts: number) => new Date(ts).toLocaleTimeString(LOCALE[lang], { hour: "2-digit", minute: "2-digit" });
  const lastSystem = [...messages].reverse().find((m) => m.role !== "user");
  return (
    <div className="relative min-h-0 flex-1">
      <div ref={box} onScroll={onScroll} className="scroll-soft absolute inset-0 overflow-y-auto px-4 py-4 sm:px-6"
        role="log" aria-live="polite" aria-relevant="additions">
        <div className="mx-auto max-w-3xl">
          <AnimatePresence initial={false}>
            {messages.map((m, i) => {
              const prev = messages[i - 1];
              const next = messages[i + 1];
              const startsGroup = !prev || prev.role !== m.role || m.ts - prev.ts > GROUP_MS;
              const endsGroup = !next || next.role !== m.role || next.ts - m.ts > GROUP_MS;
              const task = m.taskId ? byId.get(m.taskId) : undefined;
              return (
                <motion.div key={m.id} initial={{ opacity: 0, y: 8, filter: "blur(4px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  transition={{ duration: 0.32, ease: [0.2, 0.7, 0.2, 1] }}
                  className={cn("group flex flex-col", m.role === "user" ? "items-end" : "items-start", startsGroup ? "mt-5 first:mt-0" : "mt-1.5")}>
                  {startsGroup && m.role === "assistant" && (
                    <span className="mb-1.5 flex items-center gap-2 px-1 text-[11px] font-medium tracking-wide text-muted-foreground">
                      <span aria-hidden className="size-3.5 rounded-full bg-[radial-gradient(circle_at_35%_30%,#fff_0%,#a5a4ff_25%,#4f4de0_60%,#1b1f4a_100%)] shadow-[0_0_10px_rgb(119_117_255/0.6)]" />
                      XADICHA
                    </span>
                  )}
                  {startsGroup && m.role === "user" && <span className="sr-only">{t("chat.you")}</span>}
                  <MessageBubble m={m} t={t} animate={isLive(m)}
                    onRetry={m.role === "system" && m === lastSystem ? onRetry : undefined} />
                  {m.role === "assistant" && task && <TaskCard task={task} lang={lang} t={t} />}
                  {endsGroup && (
                    <time className="mt-1 px-1.5 text-[10px] text-faint" dateTime={new Date(m.ts).toISOString()}>{fmt(m.ts)}</time>
                  )}
                </motion.div>
              );
            })}
          </AnimatePresence>
          {thinking && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-5 flex items-center gap-3 text-xs text-muted-foreground"
              role="status" aria-live="polite">
              <span className="glass-subtle inline-flex items-center gap-1.5 rounded-[18px] rounded-bl-md px-3.5 py-3" aria-hidden>
                {[0, 0.15, 0.3].map((d) => (
                  <span key={d} className="size-1.5 animate-bounce rounded-full bg-gradient-to-br from-primary to-secondary"
                    style={{ animationDelay: `${d - 0.3}s` }} />
                ))}
              </span>
              {t(x.current?.steps.length ? "activity.executing" : "chat.thinking")}
            </motion.div>
          )}
        </div>
      </div>
      <AnimatePresence>
        {unseen && (
          <motion.button type="button" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
            onClick={() => { toBottom(); setUnseen(false); }}
            className="glass-strong absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs text-foreground">
            <ArrowDown className="size-3.5" aria-hidden />{t("chat.jumpLatest")}
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

function MessageBubble({ m, t, animate, onRetry }: { m: ChatMessage; t: T; animate: boolean; onRetry?: () => void }) {
  if (m.role === "system") {
    return (
      <div role="alert" data-msg="system"
        className="flex max-w-[88%] items-start gap-2.5 rounded-[18px] border border-destructive/25 bg-destructive/[0.08] px-4 py-2.5 text-sm text-[#ffc2cc]">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
        <div className="min-w-0">
          <p className="break-words whitespace-pre-wrap" lang={m.lang}>{m.text}</p>
          {onRetry && (
            <button type="button" onClick={onRetry}
              className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-foreground/90 hover:text-white focus-visible:outline-2 focus-visible:outline-ring">
              <RotateCcw className="size-3.5" aria-hidden />{t("chat.retry")}
            </button>
          )}
        </div>
      </div>
    );
  }
  if (m.role === "user") {
    return (
      <div lang={m.lang} data-msg="user"
        className="max-w-[82%] rounded-[20px] rounded-br-md bg-[linear-gradient(135deg,rgb(129_127_255/0.95),rgb(80_118_255/0.85))] px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_12px_30px_-16px_rgb(119_117_255/0.9)]">
        {m.text}
      </div>
    );
  }
  return (
    <div className="flex max-w-[88%] items-end gap-1">
      <div lang={m.lang} data-msg="assistant"
        className="glass-subtle rounded-[20px] rounded-bl-md px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-foreground">
        <RevealText text={m.text} animate={animate} />
        {m.status && m.status !== "success" && <div className="mt-1.5"><TaskStatus status={m.status} t={t} /></div>}
      </div>
      <div className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <CopyButton text={m.text} t={t} />
      </div>
    </div>
  );
}

/** Suhbat ichidagi vazifa kartochkasi: manbalar / fayllar va ochiladigan bajarilish tafsilotlari. */
function TaskCard({ task, lang, t }: { task: Task; lang: Lang; t: T }) {
  const [open, setOpen] = useState(false);
  const results = task.data?.results ?? [];
  const isSearch = results.some((r) => r.url);
  const isFiles = results.some((r) => r.path);
  return (
    <div className="mt-2 w-full max-w-[88%] space-y-2">
      {task.resolved_from && (
        <p className="px-1 text-[11px] text-muted-foreground">
          {t("card.resolved", { from: task.resolved_from })} {task.steps[0] ? describeAction(task.steps[0].action, lang) : ""}
        </p>
      )}
      {isSearch && (
        <div className="glass-subtle rounded-[18px] p-3.5">
          <p className="mb-2.5 text-[11px] font-medium tracking-wide text-muted-foreground">
            {t("card.sources")}{task.data?.search_provider ? ` · ${t("card.via", { p: task.data.search_provider })}` : ""}
          </p>
          <ol className="space-y-2.5">
            {results.slice(0, 5).map((r, i) => (
              <li key={r.url ?? i} className="text-[13px]">
                <a href={r.url} target="_blank" rel="noreferrer noopener"
                  className="inline-flex items-start gap-1.5 font-medium text-foreground hover:text-secondary focus-visible:outline-2 focus-visible:outline-ring">
                  <span className="rounded-md bg-white/[0.06] px-1.5 text-[10px] leading-5 text-muted-foreground">{i + 1}</span>
                  <span>{r.title}</span><ExternalLink className="mt-0.5 size-3 shrink-0 opacity-60" aria-hidden />
                </a>
                {r.snippet && <p className="mt-0.5 line-clamp-2 pl-7 text-xs text-muted-foreground">{r.snippet}</p>}
                <p className="truncate pl-7 text-[10px] text-faint">{r.url}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
      {isFiles && (
        <div className="glass-subtle rounded-[18px] p-3.5">
          <p className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground">{t("card.files")}</p>
          <ul className="space-y-1.5">
            {results.slice(0, 8).map((r) => (
              <li key={r.path} className="flex items-center gap-2 truncate text-[13px]" title={r.path}>
                <FileText className="size-3.5 shrink-0 text-secondary" aria-hidden />{r.title}
                <span className="truncate text-[10px] text-faint">{r.path}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(task.steps.length > 0 || (task.trace?.length ?? 0) > 0) && (
        <div>
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-white/[0.05] hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
            <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} aria-hidden />
            {open ? t("card.hide") : t("card.details")} · {t("card.steps", { n: task.steps.length })} · {fmtMs(taskLatencyMs(task))}
          </button>
          <AnimatePresence initial={false}>
            {open && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden">
                <div className="glass-subtle mt-1.5 space-y-3 rounded-[18px] p-3.5">
                  <TaskTimeline task={task} lang={lang} t={t} />
                  <TraceList trace={task.trace ?? []} t={t} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

/* ---------------- Joriy vazifa paneli ---------------- */

export function CurrentTaskPanel({ task, lang, t, activeStep, awaiting = false, title }: {
  task: Task | null; lang: Lang; t: T; activeStep?: number | null; awaiting?: boolean; title?: string;
}) {
  return (
    <GlassPanel className="flex min-h-0 flex-col p-5">
      <PanelTitle hint={task ? (awaiting
        ? <span className="inline-flex items-center gap-1.5 text-xs font-medium text-warning">{t("task.awaiting")}</span>
        : <TaskStatus status={task.status} t={t} />) : null}>{title ?? t("task.title")}</PanelTitle>
      {!task ? (
        <p className="py-8 text-center text-sm leading-relaxed text-muted-foreground">{t("task.empty")}</p>
      ) : (
        <div className="scroll-soft -mr-2 min-h-0 space-y-4 overflow-y-auto pr-2">
          <p className="text-[15px] font-medium leading-snug" lang={task.language}>{task.instruction}</p>
          <TaskTimeline task={task} lang={lang} t={t} activeStep={activeStep} awaiting={awaiting} />
          {task.status !== "running" && (
            <div className="space-y-3 border-t border-white/[0.06] pt-3">
              <dl className="grid grid-cols-2 gap-2 text-center">
                <Metric label={t("metric.latency")} tip={t("tip.latency")} value={fmtMs(taskLatencyMs(task))} />
                <Metric label={t("metric.llmCalls")} tip={t("tip.llmCalls")} value={String(task.llm_calls)} />
                <Metric label={t("metric.retries")} tip={t("tip.retries")} value={String(task.retries)} />
                <Metric label={t("metric.recoveries")} tip={t("tip.recoveries")} value={String(task.recoveries)} />
              </dl>
              {task.timings && <TimingBar timings={task.timings} t={t} />}
            </div>
          )}
        </div>
      )}
    </GlassPanel>
  );
}

function Metric({ label, value, tip }: { label: string; value: string; tip?: string }) {
  return (
    <div title={tip} className="rounded-xl bg-white/[0.03] px-1 py-2">
      <dt className="truncate text-[11px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}

/** Kechikish qayerga ketganini ko'rsatadi: model, ekran surati, bajarish (backend o'lchagan qiymatlar). */
function TimingBar({ timings: tm, t }: { timings: { screen_ms: number; llm_ms: number; exec_ms: number }; t: T }) {
  const total = tm.screen_ms + tm.llm_ms + tm.exec_ms;
  if (!total) return null;
  const parts = [
    { k: t("timing.model"), v: tm.llm_ms, c: "bg-primary" },
    { k: t("timing.screen"), v: tm.screen_ms, c: "bg-secondary" },
    { k: t("timing.exec"), v: tm.exec_ms, c: "bg-success" },
  ];
  return (
    <div title={t("tip.timing")}>
      <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-white/[0.05]" role="img"
        aria-label={`${t("tip.timing")}: ${parts.map((p) => `${p.k} ${fmtMs(p.v)}`).join(", ")}`}>
        {parts.map((p) => p.v > 0 && <div key={p.k} className={cn(p.c, "rounded-full")} style={{ width: `${(p.v / total) * 100}%` }} />)}
      </div>
      <div className="mt-1.5 flex flex-wrap justify-between gap-x-2 text-[11px] text-muted-foreground">
        {parts.map((p) => (
          <span key={p.k} className="inline-flex items-center gap-1"><span className={cn("size-1.5 rounded-full", p.c)} />{p.k} {fmtMs(p.v)}</span>
        ))}
      </div>
    </div>
  );
}
