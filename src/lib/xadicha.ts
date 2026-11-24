"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { parseEvent, reconnectDelay, upsertStep } from "./events";
import { translate, type Lang, type MsgKey } from "./i18n";

export type { Lang } from "./i18n";

export const API = process.env.NEXT_PUBLIC_XADICHA_API ?? "http://127.0.0.1:8765";

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
}

export interface Step {
  index: number;
  action: Action;
  expected_outcome: string;
  risk: Risk;
  status: "executed" | "verified" | "failed" | "denied" | "error";
  detail: string;
  verified: boolean | null;
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
}

export type Listening = "idle" | "recording" | "transcribing";

export interface Status {
  os: string;
  adapter: string;
  provider: { name: string; ok: boolean; detail: string; vision: boolean };
  config: Record<string, string | number | boolean>;
  stats: { total: number; success: number; failed: number; cancelled: number; success_rate: number | null };
  busy: boolean;
  current_task: string | null;
  pending_confirmation: Confirmation | null;
  listening?: Listening;
  capabilities?: { screenshot_vision: boolean; ocr: boolean; accessibility_tree: boolean };
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
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${API}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (e) {
    throw new ApiError((e as Error).message || "network error", 0);   // backend ishlamayapti / tarmoq
  }
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {}
    throw new ApiError(msg, r.status);
  }
  return r.json() as Promise<T>;
}

export function describeAction(a: Action, lang: Lang = "uz"): string {
  const v = (() => {
    switch (a.type) {
      case "open_app": return a.app ?? "";
      case "open_url": return a.url ?? "";
      case "click":
      case "double_click": return `(${a.x}, ${a.y})`;
      case "type_text": return a.text ?? "";
      case "hotkey": return (a.keys ?? []).join(" + ");
      case "create_folder":
      case "create_file":
      case "delete_path": return a.path ?? "";
      default: return "";
    }
  })();
  const key = `action.${a.type}` as MsgKey;
  const s = translate(lang, key, { v });
  return s === key ? a.type : s;
}

/** Backend bilan butun aloqa: holat, vazifalar, WebSocket hodisalari, amallar. */
export function useXadicha(uiLang: Lang = "uz") {
  const [status, setStatus] = useState<Status | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [wsOpen, setWsOpen] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [current, setCurrent] = useState<Task | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [listening, setListening] = useState<Listening>("idle");
  const [micLevel, setMicLevel] = useState(0);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const currentRef = useRef<Task | null>(null);
  const announced = useRef(new Set<string>());     // javobi chatga qo'shilgan vazifalar (takrorlanmasin)
  const confirmBusyRef = useRef(false);
  // Har bir WebSocket tasdiq/tinglash hodisasi "davr"ni oshiradi. Undan oldin boshlangan HTTP so'rov
  // natijasi eskirgan hisoblanadi va yangi holatni bosib qo'ymaydi (polling ↔ WebSocket ziddiyati).
  const confirmEpoch = useRef(0);
  const listenEpoch = useRef(0);
  const langRef = useRef(uiLang);

  useEffect(() => {
    currentRef.current = current;
  }, [current]);
  useEffect(() => {
    langRef.current = uiLang;
  }, [uiLang]);

  const push = useCallback((m: Omit<ChatMessage, "id">) => {
    setMessages((prev) => [...prev, { ...m, id: `${Date.now()}-${Math.random()}` }]);
  }, []);

  const announce = useCallback((t: Task) => {
    if (t.status === "running" || announced.current.has(t.id)) return;
    announced.current.add(t.id);
    push({ role: "assistant", text: t.final_message || "—", status: t.status, lang: t.language });
  }, [push]);

  const confirmRef = useRef<Confirmation | null>(null);
  useEffect(() => {
    confirmRef.current = confirmation;
  }, [confirmation]);

  const applyConfirmation = useCallback((p: Confirmation | null) => {
    const prev = confirmRef.current;
    if (prev && p && (prev.id ?? prev.task_id) === (p.id ?? p.task_id)) return;   // o'sha dialog — xato matni saqlanadi
    confirmRef.current = p;
    setConfirmation(p);
    setConfirmError(null);
  }, []);

  /** Holatni HTTP orqali tiklaydi: qayta ulanganda, WebSocket o'chiq bo'lganda va vazifa tugaganda. */
  const refresh = useCallback(async (): Promise<boolean> => {
    const ce = confirmEpoch.current;
    const le = listenEpoch.current;
    try {
      const [s, t] = await Promise.all([call<Status>("/api/status"), call<Task[]>("/api/tasks?limit=100")]);
      setStatus(s);
      setTasks(t);
      setOnline(true);
      if (ce === confirmEpoch.current) applyConfirmation(s.pending_confirmation);
      if (le === listenEpoch.current && s.listening) {
        setListening(s.listening);
        if (s.listening !== "recording") setMicLevel(0);
      }
      // Joriy vazifani tiklash: uzilish paytida boshlangan yoki tugagan bo'lishi mumkin
      const cur = currentRef.current;
      const id = s.current_task ?? (cur?.status === "running" ? cur.id : null);
      if (id) {
        const task = await call<Task>(`/api/tasks/${id}`).catch(() => null);
        if (task) {
          setCurrent((prev) => (prev && prev.id === task.id && prev.status !== "running" ? prev : task));
          announce(task);
        }
      }
      return true;
    } catch {
      setOnline(false);
      return false;
    }
  }, [announce, applyConfirmation]);

  // WebSocket — bitta ulanish, eksponensial qayta ulanish, noto'g'ri xabarlarga chidamli
  useEffect(() => {
    let disposed = false;
    let attempt = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ping: ReturnType<typeof setInterval> | undefined;

    const handle = (raw: unknown) => {
      const e = parseEvent(raw);
      if (!e) return;   // noto'g'ri yoki noma'lum xabar — e'tiborsiz
      switch (e.type) {
        case "hello": {
          const s = e.status as Status;
          setStatus(s);
          confirmEpoch.current++;
          applyConfirmation(s.pending_confirmation ?? null);
          if (s.listening) {
            listenEpoch.current++;
            setListening(s.listening);
          }
          refresh();   // tarix va joriy vazifani tiklash
          break;
        }
        case "task_started":
          setCurrent(e.task as Task);
          setStatus((s) => (s ? { ...s, busy: true, current_task: (e.task as Task).id } : s));
          break;
        case "step_started":
        case "step_finished":
        case "step_verified":
          setCurrent((t) => upsertStep(t, e.task_id as string, e.step as Step));
          break;
        case "task_finished": {
          const task = e.task as Task;
          setCurrent(task);
          announce(task);
          refresh();
          break;
        }
        case "confirm_request":
          confirmEpoch.current++;
          applyConfirmation(e as unknown as Confirmation);
          break;
        case "confirm_resolved": {
          confirmEpoch.current++;
          const c = confirmRef.current;
          if (c && (e.id && c.id ? c.id === e.id : c.task_id === e.task_id)) applyConfirmation(null);
          break;
        }
        case "listening":
          listenEpoch.current++;
          setListening(e.state as Listening);
          if (e.state !== "recording") setMicLevel(0);
          break;
        case "mic_level":
          setMicLevel(e.level as number);
          break;
        case "transcript":
          if (typeof e.text === "string" && e.text) push({ role: "user", text: e.text, lang: e.language as string });
          break;
        case "error":
          setError(e.message as string);
          push({ role: "system", text: e.message as string });
          break;
      }
    };

    const connect = () => {
      if (disposed) return;
      const prev = wsRef.current;
      if (prev && (prev.readyState === WebSocket.OPEN || prev.readyState === WebSocket.CONNECTING)) return;   // takroriy ulanish yo'q
      let ws: WebSocket;
      try {
        ws = new WebSocket(API.replace(/^http/, "ws") + "/api/ws");
      } catch {
        retry = setTimeout(connect, reconnectDelay(attempt++));
        return;
      }
      wsRef.current = ws;
      ws.onopen = () => {
        if (wsRef.current !== ws) return;
        attempt = 0;
        setOnline(true);
        setWsOpen(true);
        clearInterval(ping);
        ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
        }, 20_000);
      };
      ws.onmessage = (ev) => {
        if (wsRef.current === ws) handle(ev.data);
      };
      ws.onerror = () => ws.close();
      ws.onclose = () => {
        if (wsRef.current !== ws) return;   // eski ulanish — e'tiborsiz
        wsRef.current = null;
        clearInterval(ping);
        setWsOpen(false);
        if (disposed) return;
        refresh();   // WebSocket uzilsa ham HTTP ishlashi mumkin
        clearTimeout(retry);
        retry = setTimeout(connect, reconnectDelay(attempt++));
      };
    };

    connect();
    // Zaxira: WebSocket ochiq bo'lmasa, holatni HTTP orqali yangilab turamiz (WebSocket ochiq bo'lsa — so'rov yo'q)
    const poll = setInterval(async () => {
      if (wsRef.current) return;   // ulanish ochiq yoki ulanmoqda — HTTP so'rov kerak emas
      if (await refresh() && !disposed && !wsRef.current) {
        // Backend qaytdi — WebSocket'ni navbatdagi kutish vaqtini kutmasdan darhol ulaymiz
        clearTimeout(retry);
        attempt = 0;
        connect();
      }
    }, 3000);
    return () => {
      disposed = true;
      clearInterval(poll);
      clearInterval(ping);
      clearTimeout(retry);
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
    };
  }, [refresh, push, announce, applyConfirmation]);

  const run = useCallback(async (instruction: string, language: Lang, mode: Mode = "C", fromVoice = false) => {
    setError(null);
    if (!fromVoice) push({ role: "user", text: instruction, lang: language });
    try {
      await call("/api/tasks", { method: "POST", body: JSON.stringify({ instruction, language, mode }) });
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      push({ role: "system", text: msg });
    }
  }, [push]);

  /** language — tanlangan til (o'zbek nutqi boshqa til deb adashib aniqlanmasligi uchun). */
  const startListening = useCallback(async (language?: Lang) => {
    setError(null);
    try {
      const r = await call<{ ok: boolean; state?: Listening }>(
        `/api/listen/start${language ? `?language=${language}` : ""}`, { method: "POST" });
      // WebSocket uzilgan bo'lsa ham tugma holati haqiqiy yozuv bilan mos bo'lsin
      listenEpoch.current++;
      setListening(r.state ?? "recording");
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      push({ role: "system", text: msg });
      setListening("idle");
    }
  }, [push]);

  /** Tinglashni to'xtatadi va aniqlangan matnni qaytaradi (xato bo'lsa null). */
  const stopListening = useCallback(async () => {
    listenEpoch.current++;
    setListening("transcribing");
    setMicLevel(0);
    try {
      return await call<{ text: string; language: Lang; supported: boolean }>("/api/listen/stop", { method: "POST" });
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      // Mikrofon xatosi WebSocket "error" hodisasi orqali ham keladi — chatda ikki marta chiqmasin
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) push({ role: "system", text: msg });
      return null;
    } finally {
      listenEpoch.current++;
      setListening("idle");
    }
  }, [push]);

  /** Tasdiq javobi. Xato bo'lsa dialog ochiq qoladi va xato ko'rsatiladi; takroriy bosish e'tiborsiz. */
  const answer = useCallback(async (approve: boolean) => {
    const c = confirmation;
    if (!c || confirmBusyRef.current) return;
    confirmBusyRef.current = true;
    setConfirmBusy(true);
    setConfirmError(null);
    try {
      await call(`/api/tasks/${c.task_id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ approve, confirmation_id: c.id ?? null }),
      });
      confirmEpoch.current++;
      if (confirmRef.current === c) applyConfirmation(null);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 404 || err.status === 409) {
        // Tasdiq endi mavjud emas (muddati tugagan / allaqachon javob berilgan) — dialogni yopamiz va aytamiz
        confirmEpoch.current++;
        if (confirmRef.current === c) applyConfirmation(null);
        push({ role: "system", text: translate(langRef.current, err.status === 404 ? "confirm.expired" : "confirm.already") });
      } else {
        setConfirmError(translate(langRef.current, "confirm.failed", { msg: err.message }));
      }
    } finally {
      confirmBusyRef.current = false;
      setConfirmBusy(false);
    }
  }, [confirmation, push, applyConfirmation]);

  const stop = useCallback(() => call("/api/stop", { method: "POST" }).catch((e: Error) => {
    setError(e.message);
  }), []);

  const clearHistory = useCallback(async () => {
    try {
      await call("/api/history", { method: "DELETE" });
    } catch (e) {
      setError((e as Error).message);
    }
    refresh();
  }, [refresh]);

  return {
    status, online, wsOpen, tasks, current, confirmation, confirmBusy, confirmError, listening, micLevel, messages,
    error, run, startListening, stopListening, answer, stop, clearHistory, refresh, push,
  };
}
