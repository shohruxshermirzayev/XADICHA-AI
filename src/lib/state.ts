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
import type { Confirmation, Listening, Phase, Status, Step, Task } from "./types";

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
}

export const initialState: UiState = {
  status: null, seq: 0, instance: null, busy: false, phase: "idle", currentTaskId: null,
  current: null, confirmation: null, listening: "idle", micLevel: 0, activeStep: null,
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
  return {
    ...st,
    status: s,
    seq: typeof s.seq === "number" ? s.seq : st.seq,
    instance: s.instance ?? st.instance,
    busy: s.busy,
    phase: s.phase && PHASES.has(s.phase) ? s.phase : s.busy ? "running" : "idle",
    currentTaskId: s.current_task,
    confirmation: keepSameConfirmation(st.confirmation, s.pending_confirmation ?? null),
    listening,
    micLevel: listening === "recording" ? st.micLevel : 0,
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
      return next;
    case "mic_level":
      next.micLevel = next.listening === "recording" ? (e.level as number) : 0;
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
