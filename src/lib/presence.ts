/**
 * XADICHA "borligi": orb holati va vazifa vaqt chizig'i — faqat haqiqiy backend holatidan.
 * Sof TypeScript (React'siz) — `node --test` bilan sinaladi. Hech qanday soxta faollik yoki vaqt yo'q.
 */
import type { Listening, LiveState, Phase, Step, Task } from "./types";

export type OrbState =
  | "idle" | "listening" | "processing" | "thinking" | "searching" | "executing" | "speaking"
  | "awaiting" | "interrupted" | "recovering" | "connecting" | "error" | "offline";

export interface PresenceInput {
  online: boolean | null;
  listening: Listening;
  phase: Phase;
  busy: boolean;
  current: Task | null;
  /** Vazifa tugaganidan keyin qisqa vaqt ko'rsatiladigan natija (komponent taymer bilan o'chiradi). */
  flash?: "error" | "interrupted" | null;
  /** Gemini Live sessiyasi holati (bo'lsa). */
  live?: LiveState;
  /** Hozir bajarilayotgan qadam raqami (qidiruv qadamini aniqlash uchun). */
  activeStep?: number | null;
  /** AI provayder zaxiraga o'tgan (masalan, Gemini → Ollama). */
  usingFallback?: boolean;
}

/** Orb holati. Ustuvorlik: aloqa → mikrofon → tasdiq → ovoz → bajarish → qisqa natija → kutish. */
export function orbState(s: PresenceInput): OrbState {
  if (s.online === false) return "offline";
  if (s.listening === "recording") return "listening";
  if (s.listening === "transcribing") return "processing";
  if (s.phase === "awaiting_confirmation") return "awaiting";
  if (s.live === "connecting") return "connecting";
  if (s.live === "reconnecting") return "recovering";
  if (s.live === "interrupted") return "interrupted";
  if (s.phase === "speaking" || s.live === "speaking") return "speaking";
  if (s.busy) {
    const running = s.current?.status === "running";
    const active = running ? s.current?.steps.find((st) => st.index === s.activeStep) : undefined;
    if (active && active.action.type === "web_search") return "searching";
    if (s.usingFallback && running) return "recovering";
    return running && (s.current?.steps.length ?? 0) > 0 ? "executing" : "thinking";
  }
  if (s.live === "thinking") return "thinking";
  if (s.live === "listening") return "listening";
  if (s.flash) return s.flash;
  return "idle";
}

/** Tugagan vazifa natijasi orbda qisqa ko'rsatilishi kerakmi. */
export function outcomeFlash(task: Task | null): "error" | "interrupted" | null {
  if (!task) return null;
  if (task.status === "failed") return "error";
  if (task.status === "cancelled") return "interrupted";
  return null;
}

export type RowState = "done" | "active" | "failed" | "warn" | "pending";

export interface TimelineRow {
  key: string;
  kind: "received" | "planning" | "step" | "verifying" | "awaiting" | "final";
  state: RowState;
  step?: Step;
  /** Haqiqiy davomiylik (ms) — faqat backend bergan bo'lsa. */
  ms?: number;
}

export function taskLatencyMs(t: Task): number | null {
  return t.finished_at ? Math.max(0, Math.round((t.finished_at - t.started_at) * 1000)) : null;
}

function stepRow(s: Step, task: Task, activeStep: number | null): TimelineRow {
  const running = task.status === "running";
  const ms = s.duration_ms > 0 ? s.duration_ms : undefined;
  if (running && activeStep === s.index) return { key: `s${s.index}`, kind: "step", state: "active", step: s };
  switch (s.status) {
    case "verified":
      return { key: `s${s.index}`, kind: "step", state: "done", step: s, ms };
    case "executed":
      // Bajarildi; tekshiruvi hali kelmagan bo'lsa (vazifa davom etmoqda) — "tekshirilmoqda"
      return { key: `s${s.index}`, kind: running ? "verifying" : "step", state: running ? "active" : "done", step: s, ms };
    case "denied":
      return { key: `s${s.index}`, kind: "step", state: "warn", step: s, ms };
    default:
      return { key: `s${s.index}`, kind: "step", state: "failed", step: s, ms };
  }
}

/** Vazifa vaqt chizig'i: qabul → tushunish/rejalash → har bir qadam (bajarish/tekshirish) → tasdiq → yakun. */
export function timeline(task: Task, opts: { activeStep?: number | null; awaiting?: boolean } = {}): TimelineRow[] {
  const running = task.status === "running";
  const rows: TimelineRow[] = [{ key: "received", kind: "received", state: "done" }];
  const planned = task.steps.length > 0 || !running;
  rows.push({
    key: "planning", kind: "planning",
    state: planned ? (task.steps.length === 0 && task.status === "failed" ? "failed" : "done") : "active",
  });
  for (const s of task.steps) rows.push(stepRow(s, task, opts.activeStep ?? null));
  if (running && opts.awaiting) rows.push({ key: "awaiting", kind: "awaiting", state: "warn" });
  const final: RowState = task.status === "success" ? "done" : task.status === "failed" ? "failed"
    : task.status === "cancelled" ? "warn" : "pending";
  rows.push({ key: "final", kind: "final", state: final, ms: taskLatencyMs(task) ?? undefined });
  return rows;
}

/** Ko'rsatish uchun davomiylik: 850 ms, 1.4 s. */
export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** Yangi kelgan javob matnini bosqichma-bosqich ko'rsatish uchun so'zlar soni (haqiqiy matn, to'qilmaydi). */
export function revealWords(text: string): string[] {
  return text.split(/(\s+)/).filter((w) => w.length > 0);
}
