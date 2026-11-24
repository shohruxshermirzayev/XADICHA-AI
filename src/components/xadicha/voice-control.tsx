"use client";

import { motion, useReducedMotion } from "motion/react";
import type { OrbState, RowState } from "@/lib/presence";
import type { T } from "@/lib/use-lang";
import type { Listening } from "@/lib/xadicha";
import { cn } from "@/lib/utils";
import { AIOrb } from "./ai-orb";

/**
 * Ovoz tugmasi — orbning o'zi. Bosing va gapiring: gapirib bo'linganini backend o'zi sezadi.
 * Mikrofon faqat backend'da ochiladi; daraja `mic_level` hodisasidan keladi (brauzer alohida yozmaydi).
 * Yozuv davom etayotganda tugma o'chirilmaydi — aks holda to'xtatib bo'lmay qolardi.
 */
export function VoiceControl({ orb, listening, level, segments, disabled, onToggle, size = 56, t }: {
  orb: OrbState; listening: Listening; level: number; segments?: RowState[]; disabled?: boolean;
  onToggle: () => void; size?: number; t: T;
}) {
  const reduce = useReducedMotion();
  const recording = listening === "recording";
  const transcribing = listening === "transcribing";
  const label = recording ? t("voice.stopListening") : transcribing ? t("voice.transcribing") : t("voice.talk");
  return (
    <motion.button
      type="button"
      onClick={onToggle}
      disabled={disabled || transcribing}
      aria-label={label}
      aria-pressed={recording}
      title={label}
      whileHover={reduce || disabled ? undefined : { scale: 1.04 }}
      whileTap={reduce ? undefined : { scale: 0.95 }}
      className={cn("relative shrink-0 rounded-full focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-secondary",
        "disabled:cursor-not-allowed disabled:opacity-60")}
      style={{ width: size, height: size }}
    >
      <AIOrb state={orb} level={level} segments={segments} size={size} />
      {recording && (
        <span className="absolute -bottom-1.5 left-1/2 -translate-x-1/2 rounded-full bg-secondary px-1.5 py-px text-[9px] font-semibold tracking-wider text-secondary-foreground">
          REC
        </span>
      )}
    </motion.button>
  );
}
