"use client";

import { Loader2, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { secondsLeft } from "@/lib/events";
import type { Confirmation } from "@/lib/xadicha";
import type { T } from "@/lib/use-lang";
import { GlassModal } from "./glass";
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

  return (
    <GlassModal open={!!confirmation} onClose={() => onAnswer(false)} closeDisabled={busy} role="alertdialog"
      labelledBy="confirm-title" describedBy="confirm-desc" busy={busy}>
      {confirmation && (
        <>
          <div className="flex items-start gap-4">
            <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-warning/12 text-warning ring-1 ring-warning/25">
              <ShieldAlert className="size-5" />
            </div>
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <h2 id="confirm-title" className="text-base font-semibold">{t("confirm.title")}</h2>
                <RiskBadge risk={confirmation.risk} t={t} />
              </div>
              <p id="confirm-desc" className="break-words text-[15px] text-foreground">{confirmation.description}</p>
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
            <p role="alert" className="mt-4 rounded-xl border border-destructive/25 bg-destructive/10 px-3 py-2 text-xs text-destructive">
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
        </>
      )}
    </GlassModal>
  );
}
