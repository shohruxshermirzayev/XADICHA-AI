/**
 * Backend WebSocket hodisalarini xavfsiz o'qish va qayta ulanish siyosati.
 * Sof TypeScript (React'siz) — `node --test` bilan sinaladi.
 */

export interface StepLike {
  index: number;
}

export interface TaskLike<S extends StepLike = StepLike> {
  id: string;
  status: string;
  steps: S[];
}

/** Ma'lum hodisa turlari; boshqalari e'tiborsiz qoldiriladi. */
export const EVENT_TYPES = [
  "hello", "pong", "warm", "task_started", "step_started", "step_finished", "step_verified", "task_finished",
  "confirm_request", "confirm_resolved", "listening", "mic_level", "transcript", "error", "stopped", "spoken",
  "state", "clarify", "voice_result", "conversation_reset", "live_state", "live_transcript", "live_turn", "settings",
  "stt_partial", "voice_latency", "response_partial",
] as const;

export const LIVE_STATES = ["idle", "connecting", "reconnecting", "listening", "thinking", "speaking", "interrupted",
  "error", "closed"] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export interface BackendEvent {
  type: EventType;
  [key: string]: unknown;
}

const KNOWN = new Set<string>(EVENT_TYPES);

/**
 * Xom WebSocket ma'lumotini hodisaga aylantiradi. Noto'g'ri JSON, massiv, turi yo'q yoki
 * noma'lum turdagi xabar — null (ilova yiqilmaydi). Har bir turning majburiy maydonlari tekshiriladi.
 */
export function parseEvent(raw: unknown): BackendEvent | null {
  if (typeof raw !== "string" || raw.length > 5_000_000) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const e = data as Record<string, unknown>;
  if (typeof e.type !== "string" || !KNOWN.has(e.type)) return null;
  if (e.seq !== undefined && (typeof e.seq !== "number" || !Number.isFinite(e.seq))) return null;
  const isObj = (v: unknown) => !!v && typeof v === "object" && !Array.isArray(v);
  switch (e.type) {
    case "task_started":
    case "task_finished":
      if (!isObj(e.task) || typeof (e.task as Record<string, unknown>).id !== "string") return null;
      if (!Array.isArray((e.task as Record<string, unknown>).steps)) return null;
      break;
    case "step_started":
    case "step_finished":
    case "step_verified":
      if (typeof e.task_id !== "string" || !isObj(e.step)) return null;
      if (typeof (e.step as Record<string, unknown>).index !== "number") return null;
      break;
    case "confirm_request":
      if (typeof e.task_id !== "string" || typeof e.description !== "string") return null;
      break;
    case "listening":
      if (e.state !== "idle" && e.state !== "recording" && e.state !== "transcribing") return null;
      break;
    case "mic_level":
      if (typeof e.level !== "number" || !Number.isFinite(e.level)) return null;
      break;
    case "error":
      if (typeof e.message !== "string") return null;
      break;
    case "hello":
      if (!isObj(e.status)) return null;
      break;
    case "state":
      if (typeof e.busy !== "boolean") return null;
      break;
    case "clarify":
      if (typeof e.text !== "string" || !isObj(e.analysis)) return null;
      break;
    case "voice_result":
      if (e.status !== "empty" && e.status !== "unsupported" && e.status !== "started") return null;
      break;
    case "live_state":
      if (typeof e.state !== "string" || !(LIVE_STATES as readonly string[]).includes(e.state)) return null;
      break;
    case "live_transcript":
      if ((e.role !== "user" && e.role !== "assistant") || typeof e.text !== "string") return null;
      break;
    case "live_turn":
      if (typeof e.user !== "string" || typeof e.assistant !== "string") return null;
      break;
    case "stt_partial":
      if (typeof e.text !== "string") return null;
      break;
    case "response_partial":
      if (typeof e.text !== "string" || typeof e.task_id !== "string") return null;
      break;
  }
  return e as BackendEvent;
}

/** Qadamni vazifaga qo'shadi yoki yangilaydi (tartib bo'yicha); boshqa vazifaning qadami — o'zgarishsiz. */
export function upsertStep<S extends StepLike, T extends TaskLike<S>>(task: T | null, taskId: string, step: S): T | null {
  if (!task || task.id !== taskId) return task;
  const steps = task.steps.filter((s) => s.index !== step.index);
  return { ...task, steps: [...steps, step].sort((a, b) => a.index - b.index) };
}

/**
 * Qayta ulanish kutish vaqti: 1s, 2s, 4s … 30s gacha (eksponensial), ±20% tasodifiy siljish bilan —
 * backend o'chiq bo'lsa ham brauzer uni har 2.5 soniyada "bombardimon" qilmaydi.
 */
export function reconnectDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(30_000, 1000 * 2 ** Math.max(0, Math.min(attempt, 10)));
  const jitter = base * 0.2 * (random() * 2 - 1);
  return Math.round(base + jitter);
}

/** Tasdiq qancha soniyadan keyin tugashi (backend expires_at — unix soniya). */
export function secondsLeft(expiresAt: number | undefined, nowMs: number): number | null {
  if (typeof expiresAt !== "number" || !Number.isFinite(expiresAt)) return null;
  return Math.max(0, Math.ceil(expiresAt - nowMs / 1000));
}
