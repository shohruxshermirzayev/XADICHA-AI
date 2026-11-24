"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

/** Interfeys afzalliklari (faqat ko'rinish): navigatsiya kengligi va shaffoflik. Brauzerda saqlanadi. */
export interface UiPrefs {
  nav: "compact" | "expanded";
  theme: "glass" | "solid";
}

const KEY = "xadicha.ui";
const DEFAULT: UiPrefs = { nav: "expanded", theme: "glass" };
const listeners = new Set<() => void>();
let memory: UiPrefs | null = null;
let cachedRaw: string | null | undefined;
let cached: UiPrefs = DEFAULT;

function parse(raw: string | null): UiPrefs {
  try {
    const v = raw ? JSON.parse(raw) : {};
    return {
      nav: v.nav === "compact" ? "compact" : "expanded",
      theme: v.theme === "solid" ? "solid" : "glass",
    };
  } catch {
    return DEFAULT;
  }
}

function read(): UiPrefs {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    return memory ?? DEFAULT;
  }
  if (raw !== cachedRaw) {   // useSyncExternalStore barqaror obyekt kutadi
    cachedRaw = raw;
    cached = raw ? parse(raw) : memory ?? DEFAULT;
  }
  return cached;
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  const onStorage = (e: StorageEvent) => { if (e.key === KEY) fn(); };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", onStorage);
  };
}

export function useUiPrefs() {
  const prefs = useSyncExternalStore(subscribe, read, () => DEFAULT);
  const setPrefs = useCallback((patch: Partial<UiPrefs>) => {
    const next = { ...read(), ...patch };
    memory = next;
    cachedRaw = undefined;
    try {
      window.localStorage.setItem(KEY, JSON.stringify(next));
    } catch {}
    cached = next;
    listeners.forEach((fn) => fn());
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("solid-ui", prefs.theme === "solid");
  }, [prefs.theme]);
  return { prefs, setPrefs };
}
