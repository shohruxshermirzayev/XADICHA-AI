"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import { isLang, translate, type Lang, type MsgKey } from "./i18n";

const KEY = "xadicha.lang";
const listeners = new Set<() => void>();
let memory: Lang | null = null;   // localStorage ishlamasa ham til almashishi kerak

function read(): Lang {
  try {
    const v = window.localStorage.getItem(KEY);
    if (isLang(v)) return v;
  } catch {
    // xususiy rejim yoki saqlash taqiqlangan — xotiradagi qiymat ishlatiladi
  }
  return memory ?? "uz";
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  const onStorage = (e: StorageEvent) => { if (e.key === KEY) fn(); };   // boshqa oynada o'zgartirilsa
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", onStorage);
  };
}

/** Tanlangan til: brauzerda saqlanadi, sahifa yangilansa ham qoladi. Server render — har doim "uz". */
export function useLang() {
  const lang = useSyncExternalStore(subscribe, read, () => "uz" as Lang);

  const setLang = useCallback((l: Lang) => {
    memory = l;
    try {
      window.localStorage.setItem(KEY, l);
    } catch {}
    listeners.forEach((fn) => fn());
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const t = useCallback((key: MsgKey, vars?: Record<string, string | number>) => translate(lang, key, vars), [lang]);
  return { lang, setLang, t };
}

export type T = ReturnType<typeof useLang>["t"];
