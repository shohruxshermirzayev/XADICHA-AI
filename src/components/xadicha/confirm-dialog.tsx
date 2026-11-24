"use client";

import { AnimatePresence, motion } from "motion/react";
import { Loader2, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { secondsLeft } from "@/lib/events";
import type { Confirmation } from "@/lib/xadicha";
import type { T } from "@/lib/use-lang";
import { Button, RiskBadge } from "./ui";

/** Qolgan soniyalar — har soniyada yangilanadi (holat faqat timer callback'ida o'zgaradi). */
function useSecondsLeft(expiresAt: number | undefined) {
  // Render paytida Date.now() chaqirilmaydi (Next prerender buni taqiqlaydi) — vaqt faqat timer'da olinadi
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (expiresAt == null) return;
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 500);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [expiresAt]);
  return now == null ? null : secondsLeft(expiresAt, now);
}

export function ConfirmDialog({ confirmation, busy, error, onAnswer, t }: {
  confirmation: Confirmation | null;
  busy: boolean;
  error: string | null;
  onAnswer: (approve: boolean) => void;
  t: T;
}) {
  const noRef = useRef<HTMLButtonElement>(null);
  const left = useSecondsLeft(confirmation?.expires_at);
  const expired = left === 0;

  useEffect(() => {
    if (!confirmation) return;
    noRef.current?.focus(); // xavfsiz tanlov standart fokusda
  }, [confirmation]);

  useEffect(() => {
    if (!confirmation) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onAnswer(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirmation, onAnswer, busy]);

  return (
    <AnimatePresence>
      {confirmation && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        >
          <motion.div
            role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-desc"
            aria-busy={busy}
            className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl"
            initial={{ y: 16, scale: 0.98 }} animate={{ y: 0, scale: 1 }} exit={{ y: 8, opacity: 0 }}
          >
            <div className="flex items-start gap-4">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-warning/10 text-warning">
                <ShieldAlert className="size-5" />
              </div>
              <div className="min-w-0 space-y-2">
                <div className="flex items-center gap-2">
                  <h2 id="confirm-title" className="font-semibold">{t("confirm.title")}</h2>
                  <RiskBadge risk={confirmation.risk} t={t} />
                </div>
                <p id="confirm-desc" className="break-words text-sm text-foreground">{confirmation.description}</p>
                {confirmation.reason && (
                  <p className="text-xs text-muted-foreground">{t("confirm.expected")} {confirmation.reason}</p>
                )}
                {left != null && (
                  <p className="text-xs tabular-nums text-muted-foreground" aria-live="polite">
                    {expired ? t("confirm.expiredNow") : t("confirm.expiresIn", { s: left })}
                  </p>
                )}
              </div>
            </div>
            {error && (
              <p role="alert" className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {error}
              </p>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <Button ref={noRef} variant="outline" disabled={busy} onClick={() => onAnswer(false)}>{t("confirm.no")}</Button>
              <Button variant={confirmation.risk === "high" ? "danger" : "default"} disabled={busy || expired}
                onClick={() => onAnswer(true)}>
                {busy && <Loader2 className="size-4 animate-spin" />}
                {busy ? t("confirm.sending") : t("confirm.yes")}
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
