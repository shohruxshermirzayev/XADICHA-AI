"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const API = process.env.NEXT_PUBLIC_XADICHA_API ?? "http://127.0.0.1:8765";

export type Lang = "uz" | "ru" | "en";
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

export interface Status {
  os: string;
  adapter: string;
  provider: { name: string; ok: boolean; detail: string; vision: boolean };
  config: Record<string, string | number | boolean>;
  stats: { total: number; success: number; failed: number; cancelled: number; success_rate: number | null };
  busy: boolean;
  current_task: string | null;
  pending_confirmation: Confirmation | null;
  permissions: Record<string, boolean | null>;
  tts: Record<Lang, boolean>;
  stt_engine?: string;
}

export interface Confirmation {
  task_id: string;
  description: string;
  risk: Risk;
  reason: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  lang?: string;
  status?: Task["status"];
}

export type Listening = "idle" | "recording" | "transcribing";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {}
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export function describeAction(a: Action): string {
  switch (a.type) {
    case "open_app": return `Ilovani ochish — ${a.app}`;
    case "open_url": return `Sahifani ochish — ${a.url}`;
    case "click": return `Bosish — (${a.x}, ${a.y})`;
    case "double_click": return `Ikki marta bosish — (${a.x}, ${a.y})`;
    case "type_text": return `Matn yozish — "${a.text}"`;
    case "hotkey": return `Tugmalar — ${(a.keys ?? []).join(" + ")}`;
    case "scroll": return "Aylantirish";
    case "create_folder": return `Papka yaratish — ${a.path}`;
    case "create_file": return `Fayl yaratish — ${a.path}`;
    case "delete_path": return `O'chirish — ${a.path}`;
    case "wait": return "Kutish";
    default: return a.type;
  }
}

/** Backend bilan butun aloqa: holat, vazifalar, WebSocket hodisalari, amallar. */
export function useXadicha() {
  const [status, setStatus] = useState<Status | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [current, setCurrent] = useState<Task | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [listening, setListening] = useState<Listening>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([call<Status>("/api/status"), call<Task[]>("/api/tasks?limit=100")]);
      setStatus(s);
      setTasks(t);
      setOnline(true);
      if (s.pending_confirmation) setConfirmation(s.pending_confirmation);
    } catch {
      setOnline(false);
    }
  }, []);

  const push = useCallback((m: Omit<ChatMessage, "id">) => {
    setMessages((prev) => [...prev, { ...m, id: `${Date.now()}-${Math.random()}` }]);
  }, []);

  // WebSocket — qayta ulanish bilan
  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    const connect = () => {
      const ws = new WebSocket(API.replace(/^http/, "ws") + "/api/ws");
      wsRef.current = ws;
      ws.onopen = () => {
        setOnline(true);
        refresh();
      };
      ws.onclose = () => {
        // WebSocket uzilsa ham HTTP ishlashi mumkin — holatni HTTP orqali aniqlaymiz
        refresh();
        if (!closed) retry = setTimeout(connect, 2500);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (ev) => {
        const e = JSON.parse(ev.data);
        switch (e.type) {
          case "task_started":
            setCurrent(e.task);
            break;
          case "step_started":
          case "step_finished":
          case "step_verified":
            setCurrent((t) => {
              if (!t || t.id !== e.task_id) return t;
              const steps = t.steps.filter((s) => s.index !== e.step.index);
              return { ...t, steps: [...steps, e.step].sort((a, b) => a.index - b.index) };
            });
            break;
          case "task_finished":
            setCurrent(e.task);
            push({ role: "assistant", text: e.task.final_message || "—", status: e.task.status, lang: e.task.language });
            refresh();
            break;
          case "confirm_request":
            setConfirmation(e);
            break;
          case "confirm_resolved":
            setConfirmation(null);
            break;
          case "listening":
            setListening(e.state);
            break;
          case "transcript":
            if (e.text) push({ role: "user", text: e.text, lang: e.language });
            break;
          case "error":
            setError(e.message);
            push({ role: "system", text: e.message });
            break;
        }
      };
    };
    connect();
    // Zaxira: WebSocket ochiq bo'lmasa, holatni har 3 soniyada yangilab turamiz
    const poll = setInterval(() => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) refresh();
    }, 3000);
    return () => {
      closed = true;
      clearInterval(poll);
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, [refresh, push]);

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

  /** language — tanlangan til (o'zbekcha nutq boshqa til deb adashib aniqlanmasligi uchun). */
  const startListening = useCallback(async (language?: Lang) => {
    setError(null);
    try {
      await call(`/api/listen/start${language ? `?language=${language}` : ""}`, { method: "POST" });
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  /** Tinglashni to'xtatadi va aniqlangan matnni qaytaradi. */
  const stopListening = useCallback(async () => {
    try {
      return await call<{ text: string; language: Lang; supported: boolean }>("/api/listen/stop", { method: "POST" });
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, []);

  const answer = useCallback(async (approve: boolean) => {
    if (!confirmation) return;
    try {
      await call(`/api/tasks/${confirmation.task_id}/confirm`, { method: "POST", body: JSON.stringify({ approve }) });
    } finally {
      setConfirmation(null);
    }
  }, [confirmation]);

  const stop = useCallback(() => call("/api/stop", { method: "POST" }).catch(() => {}), []);

  const clearHistory = useCallback(async () => {
    await call("/api/history", { method: "DELETE" });
    refresh();
  }, [refresh]);

  return {
    status, online, tasks, current, confirmation, listening, messages, error,
    run, startListening, stopListening, answer, stop, clearHistory, refresh,
  };
}
