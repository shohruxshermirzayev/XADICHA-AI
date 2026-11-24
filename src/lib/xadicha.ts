"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { parseEvent, reconnectDelay } from "./events";
import { translate, type Lang, type MsgKey } from "./i18n";
import { applyEvent, applyStatus, initialState, isBusy, staleRunningTask, type UiState } from "./state";

export type { Lang } from "./i18n";

export const API = process.env.NEXT_PUBLIC_XADICHA_API ?? "http://127.0.0.1:8765";

import type { Action, ChatMessage, Mode, Status, Task, Transcript } from "./types";

export type * from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

/**
 * Mahalliy sessiya kaliti: backend ishga tushganda yaratadi, faqat localhost sahifasi /api/session orqali oladi.
 * Har bir so'rov X-Xadicha-Token sarlavhasi bilan yuboriladi — boshqa saytdan CSRF so'rovi uni bila olmaydi,
 * maxsus sarlavha esa CORS preflight'ni majburiy qiladi.
 */
let token: string | null = null;
let tokenPromise: Promise<string> | null = null;

async function getToken(): Promise<string> {
  if (token) return token;
  tokenPromise ??= fetch(`${API}/api/session`, { credentials: "omit" })
    .then(async (r) => {
      if (!r.ok) throw new ApiError(`session ${r.status}`, r.status);
      const t = String((await r.json()).token ?? "");
      token = t;
      return t;
    })
    .finally(() => { tokenPromise = null; });
  return tokenPromise;
}

export function wsUrl(t: string): string {
  return API.replace(/^http/, "ws") + `/api/ws?token=${encodeURIComponent(t)}`;
}

async function call<T>(path: string, init?: RequestInit, retried = false): Promise<T> {
  let r: Response;
  try {
    const t = await getToken();
    r = await fetch(`${API}${path}`, {
      ...init,
      credentials: "omit",
      headers: { "content-type": "application/json", "x-xadicha-token": t, ...(init?.headers ?? {}) },
    });
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError((e as Error).message || "network error", 0);   // backend ishlamayapti / tarmoq
  }
  if (r.status === 401 && !retried) {
    token = null;   // backend qayta ishga tushgan — yangi kalit olib, bir marta qayta urinamiz
    return call<T>(path, init, true);
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
  const [st, setSt] = useState<UiState>(initialState);
  const [online, setOnline] = useState<boolean | null>(null);
  const [wsOpen, setWsOpen] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);

  const stRef = useRef(st);
  const wsRef = useRef<WebSocket | null>(null);
  const announced = useRef(new Set<string>());     // javobi chatga qo'shilgan vazifalar (takrorlanmasin)
  const confirmBusyRef = useRef(false);
  const langRef = useRef(uiLang);

  useEffect(() => {
    langRef.current = uiLang;
  }, [uiLang]);

  /** Holatni o'zgartirish: ref darhol yangilanadi (keyingi hodisa eski holatni ko'rmasligi uchun). */
  const update = useCallback((fn: (s: UiState) => UiState) => {
    const next = fn(stRef.current);
    if (next === stRef.current) return;
    if ((next.confirmation?.id ?? next.confirmation?.task_id) !== (stRef.current.confirmation?.id ?? stRef.current.confirmation?.task_id)) {
      setConfirmError(null);
    }
    stRef.current = next;
    setSt(next);
  }, []);

  const push = useCallback((m: Omit<ChatMessage, "id" | "ts">) => {
    setMessages((prev) => [...prev, { ...m, id: `${Date.now()}-${Math.random()}`, ts: Date.now() }]);
  }, []);

  const announce = useCallback((t: Task) => {
    if (t.status === "running" || announced.current.has(t.id)) return;
    announced.current.add(t.id);
    push({ role: "assistant", text: t.final_message || "—", status: t.status, lang: t.language });
  }, [push]);

  /** Panelda "bajarilmoqda" qolib ketgan vazifani backend'dan qayta oladi. */
  const syncTask = useCallback(async () => {
    const id = staleRunningTask(stRef.current);
    if (!id) return;
    const task = await call<Task>(`/api/tasks/${id}`).catch(() => null);
    if (!task) return;
    update((s) => (s.current && s.current.id === task.id && s.current.status !== "running" && task.status === "running"
      ? s : { ...s, current: task }));
    announce(task);
  }, [announce, update]);

  /** HTTP orqali tiklash: qayta ulanganda, WebSocket yo'q paytda va vazifa tugaganda. */
  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const [s, t] = await Promise.all([call<Status>("/api/status"), call<Task[]>("/api/tasks?limit=100")]);
      update((cur) => applyStatus(cur, s));   // eskirgan javob (seq kichik) band/tasdiq holatini bosmaydi
      setTasks(t);
      setOnline(true);
      await syncTask();
      return true;
    } catch {
      setOnline(false);
      return false;
    }
  }, [update, syncTask]);

  // WebSocket — bitta ulanish, eksponensial qayta ulanish, noto'g'ri xabarlarga chidamli
  useEffect(() => {
    let disposed = false;
    let attempt = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ping: ReturnType<typeof setInterval> | undefined;

    const handle = (raw: unknown) => {
      const e = parseEvent(raw);
      if (!e) return;   // noto'g'ri yoki noma'lum xabar — e'tiborsiz
      const before = stRef.current;
      update((s) => applyEvent(s, e));
      const applied = stRef.current !== before || e.type === "hello";
      switch (e.type) {
        case "hello":
          refresh();   // tarix va joriy vazifani tiklash
          break;
        case "task_finished":
          if (applied) announce(e.task as Task);
          refresh();
          break;
        case "state":
          if (applied && !e.busy) {
            syncTask();
            call<Task[]>("/api/tasks?limit=100").then(setTasks).catch(() => {});
          }
          break;
        case "transcript":
          if (applied && typeof e.text === "string" && e.text) push({ role: "user", text: e.text, lang: e.language as string });
          break;
        case "error":
          if (applied) {
            setError(e.message as string);
            push({ role: "system", text: e.message as string });
          }
          break;
      }
    };

    const connect = async () => {
      if (disposed) return;
      const prev = wsRef.current;
      if (prev && (prev.readyState === WebSocket.OPEN || prev.readyState === WebSocket.CONNECTING)) return;   // takroriy ulanish yo'q
      let ws: WebSocket;
      try {
        const t = await getToken();
        if (disposed || wsRef.current) return;
        ws = new WebSocket(wsUrl(t));
      } catch {
        clearTimeout(retry);
        retry = setTimeout(connect, reconnectDelay(attempt++));
        return;
      }
      wsRef.current = ws;
      let opened = false;
      ws.onopen = () => {
        if (wsRef.current !== ws) return;
        opened = true;
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
      ws.onclose = (ev) => {
        if (wsRef.current !== ws) return;   // eski ulanish — e'tiborsiz
        wsRef.current = null;
        clearInterval(ping);
        setWsOpen(false);
        // Ulanish umuman ochilmagan bo'lsa — kalit eskirgan bo'lishi mumkin (backend qayta ishga tushgan);
        // brauzer rad etish kodini (4401) ko'rsatmaydi, shuning uchun kalitni yangidan olamiz
        if (!opened || ev.code === 4401) token = null;
        if (disposed) return;
        refresh();   // WebSocket uzilsa ham HTTP ishlashi mumkin
        clearTimeout(retry);
        retry = setTimeout(connect, reconnectDelay(attempt++));
      };
    };

    connect();
    // Zaxira: WebSocket yo'q paytda holatni HTTP orqali yangilab turamiz (ochiq bo'lsa — so'rov yo'q)
    const poll = setInterval(async () => {
      if (wsRef.current) return;
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
  }, [refresh, push, announce, update, syncTask]);

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

  /** Buyruq matnini bajarmasdan tahlil qiladi (aniqlashtirish kerakmi). */
  const analyze = useCallback(async (text: string, language: Lang) => {
    try {
      return await call<Transcript["analysis"]>("/api/understand", { method: "POST", body: JSON.stringify({ text, language }) });
    } catch {
      return undefined;
    }
  }, []);

  /** language — tanlangan til (o'zbek nutqi boshqa til deb adashib aniqlanmasligi uchun). */
  const startListening = useCallback(async (language?: Lang) => {
    setError(null);
    try {
      const r = await call<{ ok: boolean; state?: UiState["listening"] }>(
        `/api/listen/start${language ? `?language=${language}` : ""}`, { method: "POST" });
      // WebSocket uzilgan bo'lsa ham tugma holati haqiqiy yozuv bilan mos bo'lsin
      update((s) => ({ ...s, listening: r.state ?? "recording" }));
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      push({ role: "system", text: msg });
      update((s) => ({ ...s, listening: "idle", micLevel: 0 }));
    }
  }, [push, update]);

  /** Tinglashni to'xtatadi va aniqlangan matnni (tahlili bilan) qaytaradi; xato bo'lsa null. */
  const stopListening = useCallback(async () => {
    update((s) => ({ ...s, listening: "transcribing", micLevel: 0 }));
    try {
      return await call<Transcript>("/api/listen/stop", { method: "POST" });
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      // Mikrofon xatosi WebSocket "error" hodisasi orqali ham keladi — chatda ikki marta chiqmasin
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) push({ role: "system", text: msg });
      return null;
    } finally {
      update((s) => ({ ...s, listening: "idle", micLevel: 0 }));
    }
  }, [push, update]);

  /** Tasdiq javobi. Xato bo'lsa dialog ochiq qoladi va xato ko'rsatiladi; takroriy bosish e'tiborsiz. */
  const answer = useCallback(async (approve: boolean) => {
    const c = stRef.current.confirmation;
    if (!c || confirmBusyRef.current) return;
    confirmBusyRef.current = true;
    setConfirmBusy(true);
    setConfirmError(null);
    const close = () => update((s) => (s.confirmation === c ? { ...s, confirmation: null } : s));
    try {
      await call(`/api/tasks/${c.task_id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ approve, confirmation_id: c.id ?? null }),
      });
      close();
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 404 || err.status === 409) {
        // Tasdiq endi mavjud emas (muddati tugagan / allaqachon javob berilgan) — dialogni yopamiz va aytamiz
        close();
        push({ role: "system", text: translate(langRef.current, err.status === 404 ? "confirm.expired" : "confirm.already") });
      } else {
        setConfirmError(translate(langRef.current, "confirm.failed", { msg: err.message }));
      }
    } finally {
      confirmBusyRef.current = false;
      setConfirmBusy(false);
    }
  }, [push, update]);

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
    status: st.status, phase: st.phase, busy: isBusy(st), current: st.current, confirmation: st.confirmation,
    listening: st.listening, micLevel: st.micLevel,
    online, wsOpen, tasks, confirmBusy, confirmError, messages, error,
    run, analyze, startListening, stopListening, answer, stop, clearHistory, refresh, push,
  };
}
