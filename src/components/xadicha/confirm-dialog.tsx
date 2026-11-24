"use client";

import { AnimatePresence, motion } from "motion/react";
import { ShieldAlert } from "lucide-react";
import { useEffect, useRef } from "react";
import type { Confirmation } from "@/lib/xadicha";
import { Button, RiskBadge } from "./ui";

export function ConfirmDialog({ confirmation, onAnswer }: {
  confirmation: Confirmation | null; onAnswer: (approve: boolean) => void;
}) {
  const noRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!confirmation) return;
    noRef.current?.focus(); // xavfsiz tanlov standart fokusda
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onAnswer(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirmation, onAnswer]);

  return (
    <AnimatePresence>
      {confirmation && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        >
          <motion.div
            role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-desc"
            className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl"
            initial={{ y: 16, scale: 0.98 }} animate={{ y: 0, scale: 1 }} exit={{ y: 8, opacity: 0 }}
          >
            <div className="flex items-start gap-4">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-warning/10 text-warning">
                <ShieldAlert className="size-5" />
              </div>
              <div className="min-w-0 space-y-2">
                <div className="flex items-center gap-2">
                  <h2 id="confirm-title" className="font-semibold">Tasdiq kerak</h2>
                  <RiskBadge risk={confirmation.risk} />
                </div>
                <p id="confirm-desc" className="break-words text-sm text-foreground">{confirmation.description}</p>
                {confirmation.reason && (
                  <p className="text-xs text-muted-foreground">Kutilgan natija: {confirmation.reason}</p>
                )}
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button ref={noRef} variant="outline" onClick={() => onAnswer(false)}>Yo&apos;q, bajarma</Button>
              <Button variant={confirmation.risk === "high" ? "danger" : "default"} onClick={() => onAnswer(true)}>
                Ha, bajar
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
