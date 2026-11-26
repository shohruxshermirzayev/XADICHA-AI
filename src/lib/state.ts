/**
 * Interfeysning yagona holat modeli (sof funksiyalar — `node --test` bilan sinaladi).
 *
 * Qoidalar:
 *  - Backend — haqiqat manbai. Har bir WebSocket hodisasi va /api/status javobi `seq` raqamiga ega.
 *  - Eskirgan HTTP javobi (seq kichik) band/tasdiq/tinglash holatini bosib qo'ymaydi.
 *  - Backend qayta ishga tushsa (`instance` o'zgarsa) — seq qayta boshlanadi, yangi holat qabul qilinadi.
 *  - Sarlavha, yordamchi, vazifa paneli va dashboard — barchasi shu `phase`/`busy` dan o'qiydi.
 */
import type { BackendEvent } from "./events";
import type { Confirmation, Listening, LiveState, Phase, Status, Step, Task } from "./types";

export interface UiState {
  status: Status | null;
  seq: number;
  instance: string | null;
  busy: boolean;
  phase: Phase;
  currentTaskId: string | null;
  current: Task | null;
  confirmation: Confirmation | null;
  listening: Listening;
  micLevel: number;
  /** Hozir bajarilayotgan qadam (step_started → step_finished oralig'i); vaqt chizig'i uchun. */
  activeStep: number | null;
  /** Gemini Live: haqiqiy sessiya holati va jonli (tugallanmagan) transkripsiya. */
  live: { state: LiveState; user: string; assistant: string };
  /** Buyruq rejimi: gapirilayotgan paytdagi oraliq matn (backend stt_partial). */
  partial: string;
  /** Oxirgi ovozli so'rovning haqiqiy kechikishlari (ms, mikrofon boshidan). */
  latency: VoiceLatency | null;
  /** Model javobi yozilmoqda (oqim): qaysi vazifa va hozirgacha kelgan haqiqiy matn. */
  streaming: { taskId: string; text: string } | null;
}

export interface VoiceLatency {
  ttf_partial: number | null; ttf_final: number | null; tt_first_action: number | null;
  tt_response_text: number | null; tt_response_audio: number | null; e2e: number | null; stt: string;
}

const LIVE_ON = new Set<LiveState>(["connecting", "reconnecting", "listening", "thinking", "speaking", "interrupted"]);
export function liveActive(st: Pick<UiState, "live">): boolean {
  return LIVE_ON.has(st.live.state);
}

export const initialState: UiState = {
  status: null, seq: 0, instance: null, busy: false, phase: "idle", currentTaskId: null,
  current: null, confirmation: null, listening: "idle", micLevel: 0, activeStep: null,
  live: { state: "idle", user: "", assistant: "" },
  partial: "", latency: null, streaming: null,
};

const PHASES = new Set<Phase>(["idle", "running", "awaiting_confirmation", "speaking"]);

function confirmKey(c: Confirmation | null): string | null {
  return c ? (c.id ?? c.task_id) : null;
}

/** Bir xil tasdiq bo'lsa eski obyektni qaytaradi (dialogdagi xato matni va fokus saqlanadi). */
function keepSameConfirmation(prev: Confirmation | null, next: Confirmation | null): Confirmation | null {
  return prev && next && confirmKey(prev) === confirmKey(next) ? prev : next;
}

/** /api/status javobini qo'llaydi. Eskirgan bo'lsa faqat statistika/sozlamalar yangilanadi. */
export function applyStatus(st: UiState, s: Status): UiState {
  const restarted = !!s.instance && s.instance !== st.instance;
  const fresh = restarted || typeof s.seq !== "number" || s.seq >= st.seq;
  if (!fresh) return { ...st, status: s };
  const listening = s.listening ?? st.listening;
  // Live: backend aktiv emas desa — interfeys ham "jonli" deb ko'rsatmaydi (soxta holat yo'q)
  const live = s.live && !s.live.active && LIVE_ON.has(st.live.state)
    ? { state: "idle" as LiveState, user: "", assistant: "" }
    : s.live?.active && s.live.state !== st.live.state ? { ...st.live, state: s.live.state } : st.live;
  return {
    ...st,
    live,
    status: s,
    seq: typeof s.seq === "number" ? s.seq : st.seq,
    instance: s.instance ?? st.instance,
    busy: s.busy,
    phase: s.phase && PHASES.has(s.phase) ? s.phase : s.busy ? "running" : "idle",
    currentTaskId: s.current_task,
    confirmation: keepSameConfirmation(st.confirmation, s.pending_confirmation ?? null),
    listening,
    micLevel: listening === "recording" || LIVE_ON.has(live.state) ? st.micLevel : 0,
  };
}

/** Bitta WebSocket hodisasini qo'llaydi. Takroriy/eskirgan (seq <= oxirgi) hodisa e'tiborsiz. */
export function applyEvent(st: UiState, e: BackendEvent): UiState {
  if (e.type === "hello") return applyStatus({ ...st, seq: 0 }, e.status as Status);
  const seq = typeof e.seq === "number" ? e.seq : null;
  if (seq !== null && seq <= st.seq) return st;
  const next: UiState = seq !== null ? { ...st, seq } : { ...st };
  switch (e.type) {
    case "state": {
      const phase = e.phase as Phase;
      next.busy = !!e.busy;
      next.phase = PHASES.has(phase) ? phase : next.busy ? "running" : "idle";
      next.currentTaskId = (e.current_task as string | null) ?? null;
      if (e.listening === "idle" || e.listening === "recording" || e.listening === "transcribing") {
        next.listening = e.listening;
        if (e.listening !== "recording") next.micLevel = 0;
      }
      return next;
    }
    case "task_started": {
      const task = e.task as Task;
      next.current = task;
      next.currentTaskId = task.id;
      next.activeStep = null;
      next.busy = true;
      if (next.phase === "idle") next.phase = "running";
      return next;
    }
    case "step_started":
    case "step_finished":
    case "step_verified": {
      const t = next.current;
      const step = e.step as Step;
      if (t && t.id === e.task_id) {
        next.current = { ...t, steps: [...t.steps.filter((s) => s.index !== step.index), step].sort((a, b) => a.index - b.index) };
        if (e.type === "step_started") next.activeStep = step.index;
        else if (next.activeStep === step.index) next.activeStep = null;
      }
      return next;
    }
    case "task_finished":
      next.streaming = null;
      // Vazifa tugadi; "band" holati esa backend `state` hodisasi bilan yopiladi (ovoz gapirib bo'lgach)
      next.current = e.task as Task;
      next.activeStep = null;
      return next;
    case "confirm_request":
      next.confirmation = keepSameConfirmation(st.confirmation, e as unknown as Confirmation);
      next.phase = "awaiting_confirmation";
      return next;
    case "confirm_resolved": {
      const c = st.confirmation;
      if (c && (e.id && c.id ? c.id === e.id : c.task_id === e.task_id)) next.confirmation = null;
      return next;
    }
    case "listening":
      next.listening = e.state as Listening;
      if (e.state !== "recording") next.micLevel = 0;
      if (e.state === "recording") next.partial = "";
      return next;
    case "response_partial":
      next.streaming = { taskId: e.task_id as string, text: e.text as string };
      return next;
    case "stt_partial":
      next.partial = next.listening === "recording" || next.listening === "transcribing" ? (e.text as string) : "";
      return next;
    case "transcript":
      next.partial = "";
      return next;
    case "voice_latency": {
      const n = (k: string) => (typeof e[k] === "number" ? (e[k] as number) : null);
      next.latency = { ttf_partial: n("ttf_partial"), ttf_final: n("ttf_final"), tt_first_action: n("tt_first_action"),
        tt_response_text: n("tt_response_text"), tt_response_audio: n("tt_response_audio"), e2e: n("e2e"),
        stt: typeof e.stt === "string" ? e.stt : "" };
      return next;
    }
    case "mic_level":
      next.micLevel = next.listening === "recording" || liveActive(next) ? (e.level as number) : 0;
      return next;
    case "live_state": {
      const state = e.state as LiveState;
      const ended = state === "idle" || state === "closed" || state === "error";
      next.live = { state, user: ended ? "" : next.live.user, assistant: ended || state === "interrupted" ? "" : next.live.assistant };
      if (ended) next.micLevel = next.listening === "recording" ? next.micLevel : 0;
      return next;
    }
    case "live_transcript":
      next.live = { ...next.live, [e.role === "user" ? "user" : "assistant"]: e.text as string };
      return next;
    case "live_turn":
      next.live = { ...next.live, user: "", assistant: "" };
      return next;
    default:
      return next;
  }
}

/** Panelda "bajarilmoqda" turibdi, lekin backend bo'sh — vazifani qayta so'rash kerak. */
export function staleRunningTask(st: UiState): string | null {
  if (st.current && st.current.status === "running" && !st.busy) return st.current.id;
  if (st.currentTaskId && st.current?.id !== st.currentTaskId) return st.currentTaskId;
  return null;
}

/** Barcha ekranlar uchun bitta "band" belgisi. */
export function isBusy(st: UiState): boolean {
  return st.busy || st.phase !== "idle";
}
