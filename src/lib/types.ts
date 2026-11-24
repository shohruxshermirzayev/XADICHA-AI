/** Backend bilan almashinadigan turlar (sof — React'siz, testlarda ham ishlatiladi). */
import type { Lang } from "./i18n";

export type Mode = "A" | "B" | "C";
export type Risk = "low" | "medium" | "high";

export interface Action {
  type: string;
  app?: string | null;
  url?: string | null;
  x?: number | null;
  y?: number | null;
  text?: string | null;
  keys?: string[] | null;
  path?: string | null;
  control?: string | null;   // type="system": volume_up | volume_down | volume_set | mute | unmute | brightness_up | brightness_down
  amount?: number | null;
}

export interface Step {
  index: number;
  action: Action;
  expected_outcome: string;
  risk: Risk;
  status: "executed" | "verified" | "failed" | "denied" | "error";
  detail: string;
  verified: boolean | null;
  verification?: string;     // qaysi usul bilan tekshiriladi (backend TOOL_REGISTRY)
  duration_ms: number;
}

export interface Task {
  id: string;
  instruction: string;
  language: string;
  mode: Mode;
  intent: string;
  planner?: "rules" | "llm";
  steps: Step[];
  risk: Risk;
  status: "running" | "success" | "failed" | "cancelled";
  final_message: string;
  retries: number;
  recoveries: number;
  llm_calls: number;
  timings?: { screen_ms: number; llm_ms: number; exec_ms: number };
  started_at: number;
  finished_at: number | null;
  data?: { query?: string; results?: SearchItem[]; search_provider?: string; errors?: string[] };
  trace?: TraceSpan[];
  resolved_from?: string;
}

export interface SearchItem {
  title: string;
  url?: string;
  path?: string;
  snippet?: string;
  source?: string;
  date?: string | null;
}

export interface TraceSpan {
  stage: string;
  ms: number;
  ok: boolean;
  provider?: string;
  model?: string;
  path?: string;
  reason?: string;
}

export interface Turn {
  ts: number;
  role: "user" | "assistant";
  text: string;
  lang?: string;
  task_id?: string | null;
  status?: Task["status"] | null;
}

export type Listening = "idle" | "recording" | "transcribing";
/** Backend'ning yagona holati: barcha ekranlar shundan foydalanadi. */
export type Phase = "idle" | "running" | "awaiting_confirmation" | "speaking";

export interface Status {
  os: string;
  adapter: string;
  provider: { name: string; ok: boolean; detail: string; vision: boolean };
  config: Record<string, string | number | boolean>;
  stats: { total: number; success: number; failed: number; cancelled: number; success_rate: number | null };
  busy: boolean;
  phase?: Phase;
  seq?: number;
  instance?: string;
  current_task: string | null;
  pending_confirmation: Confirmation | null;
  listening?: Listening;
  capabilities?: Record<string, Capability | boolean>;
  permissions: Record<string, boolean | null>;
  tts: Record<Lang, boolean>;
  stt_engine?: string;
}

export interface Confirmation {
  id?: string;            // eski backend versiyalarida bo'lmasligi mumkin
  task_id: string;
  description: string;
  risk: Risk;
  reason: string;
  expires_at?: number;    // unix soniya
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  lang?: string;
  status?: Task["status"];
  ts: number;            // ms — xabar vaqti
  taskId?: string;       // javob qaysi vazifaga tegishli (kartochka uchun)
}

/** Imkoniyat holati: halol to'rt daraja. */
export type CapabilityState = "available" | "unavailable" | "not_tested" | "not_implemented";
export interface Capability {
  state: CapabilityState;
  detail?: string;
}

/** Buyruqni tushunish natijasi (ASR ishonchidan alohida). */
export interface CommandAnalysis {
  original: string;
  normalized: string;
  intent: string;
  intent_confidence: number;          // 0..1 — niyat qanchalik aniq
  needs_clarification: boolean;
  reason: string;                     // kod: low_asr_confidence | unknown_app | ambiguous | unknown_intent | ok
  suggestion: string | null;          // taklif qilingan aniq buyruq (foydalanuvchi tasdiqlasa)
  candidates: string[];
}

export interface Transcript {
  text: string;
  language: Lang;
  probability: number;               // til ehtimolligi
  asr_confidence: number | null;     // nutq tanish ishonchi (0..1), noma'lum bo'lsa null
  supported: boolean;
  analysis?: CommandAnalysis;
}

/** Ekran holati (foydalanuvchi so'raganda olinadi; surat faqat javobda, saqlanmaydi). */
export interface ScreenSnapshot {
  available: boolean;
  captured_at: number;
  app: string | null;
  window: string | null;
  preview: string | null;              // data:image/jpeg;base64,… — faqat xotirada
  size: [number, number] | null;
  timings: { capture_ms?: number; ocr_ms?: number; ax_ms?: number };
  error: string | null;
  ocr: { state: CapabilityState; lines: { text: string; confidence: number }[]; error?: string };
  ax: { state: CapabilityState; elements: { role: string; name: string; enabled: boolean }[]; error?: string };
}

/** Aniqlashtirish kutilayotgan ovozli buyruq (backend `clarify` hodisasi). */
export interface PendingVoice {
  transcript: string;
  language: Lang;
  asr: number | null;
  analysis: CommandAnalysis;
}
