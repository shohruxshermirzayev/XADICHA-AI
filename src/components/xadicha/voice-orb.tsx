"use client";

import { motion, useReducedMotion } from "motion/react";
import { useRef } from "react";
import type { T } from "@/lib/use-lang";
import type { Listening } from "@/lib/xadicha";
import { cn } from "@/lib/utils";
import { XadichaMark } from "./logo";

/**
 * Mikrofon faqat backend'da (Python sounddevice) ochiladi. Avval brauzer ham getUserMedia orqali mikrofonni
 * alohida ochardi — bu ikki marta yozish, qo'shimcha ruxsat oynasi va haqiqiy yozuv bilan mos kelmaydigan
 * animatsiyaga olib kelardi. Endi `level` backend'ning `mic_level` hodisasidan keladi (0..1).
 */
/** Asosiy ovoz tugmasi — XADICHA belgisi. Bosing — gapiring — yana bosing (yoki Space). */
export function VoiceOrb({ state, level: rawLevel, busy, disabled, onToggle, t }: {
  state: Listening; level: number; busy: boolean; disabled?: boolean; onToggle: () => void; t: T;
}) {
  const reduce = useReducedMotion();
  const recording = state === "recording";
  const transcribing = state === "transcribing";
  const thinking = transcribing || busy;
  const level = recording ? Math.min(1, Math.max(0, rawLevel)) : 0;
  const btn = useRef<HTMLButtonElement>(null);
  const label = recording ? t("voice.stopListening") : transcribing ? t("voice.transcribing") : t("voice.talk");

  return (
    <div className="relative flex size-56 items-center justify-center">
      {/* tashqi nur */}
      <motion.div
        aria-hidden
        className={cn("absolute inset-0 rounded-full blur-2xl",
          recording ? "bg-[radial-gradient(circle,rgb(244_63_94/0.35),transparent_65%)]"
            : "bg-[radial-gradient(circle,rgb(99_102_241/0.40),rgb(6_182_212/0.12)_50%,transparent_70%)]")}
        animate={reduce ? undefined : { scale: recording ? 1 + level * 0.35 : [1, 1.06, 1] }}
        transition={recording ? { duration: 0.1 } : { duration: 3.5, repeat: Infinity, ease: "easeInOut" }}
      />
      {/* ovoz balandligi halqasi */}
      {recording && (
        <motion.div aria-hidden className="absolute inset-6 rounded-full border-2 border-rose-400/70"
          animate={{ scale: 1 + level * 0.25, opacity: 0.5 + level * 0.5 }} transition={{ duration: 0.08 }} />
      )}
      {/* o'ylash halqasi */}
      {thinking && !reduce && (
        <motion.div aria-hidden
          className="absolute inset-5 rounded-full bg-[conic-gradient(from_0deg,transparent,rgb(6_182_212/0.9),transparent_40%)] [mask:radial-gradient(circle,transparent_62%,#000_63%)]"
          animate={{ rotate: 360 }} transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }} />
      )}
      <motion.button
        ref={btn}
        type="button"
        onClick={onToggle}
        disabled={disabled || transcribing}
        aria-label={label}
        aria-pressed={recording}
        whileHover={reduce || disabled ? undefined : { scale: 1.03 }}
        whileTap={reduce ? undefined : { scale: 0.96 }}
        className={cn(
          "relative z-10 flex size-36 items-center justify-center rounded-full",
          "bg-[radial-gradient(circle_at_50%_30%,#1f2547,#0b1020_70%)] ring-1 transition-shadow",
          "shadow-[0_20px_60px_-20px_rgb(99_102_241/0.8),inset_0_1px_0_rgb(255_255_255/0.08)]",
          "focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-secondary disabled:opacity-60",
          recording ? "ring-rose-400/60" : "ring-white/10",
        )}
      >
        <XadichaMark size={168} aura={false} speaking={recording} thinking={thinking} className="pointer-events-none -m-4" />
        {recording && (
          <span className="absolute bottom-3 rounded-full bg-rose-500/90 px-2 py-0.5 text-[10px] font-semibold tracking-wider text-white">
            REC
          </span>
        )}
      </motion.button>
    </div>
  );
}
