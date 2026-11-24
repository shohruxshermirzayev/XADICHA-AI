"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import type { Listening } from "@/lib/xadicha";
import { cn } from "@/lib/utils";
import { XadichaMark } from "./logo";

/** Brauzer mikrofonidan haqiqiy ovoz balandligi (0..1) — faqat vizualizatsiya uchun; yozuvni backend qiladi. */
function useMicLevel(active: boolean) {
  const [level, setLevel] = useState(0);
  useEffect(() => {
    if (!active) return;
    let raf = 0;
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    let cancelled = false;
    navigator.mediaDevices?.getUserMedia({ audio: true }).then((s) => {
      if (cancelled) return s.getTracks().forEach((t) => t.stop());
      stream = s;
      ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(s).connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      const tick = () => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += v * v;
        setLevel((prev) => prev * 0.6 + Math.min(1, Math.sqrt(sum / buf.length) * 6) * 0.4);
        raf = requestAnimationFrame(tick);
      };
      tick();
    }).catch(() => {});
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close().catch(() => {});
    };
  }, [active]);
  return active ? level : 0;
}

/** Asosiy ovoz tugmasi — XADICHA belgisi. Bosing — gapiring — yana bosing (yoki Space). */
export function VoiceOrb({ state, busy, disabled, onToggle }: {
  state: Listening; busy: boolean; disabled?: boolean; onToggle: () => void;
}) {
  const reduce = useReducedMotion();
  const recording = state === "recording";
  const transcribing = state === "transcribing";
  const thinking = transcribing || busy;
  const level = useMicLevel(recording);
  const btn = useRef<HTMLButtonElement>(null);
  const label = recording ? "Tinglashni to'xtatish" : transcribing ? "Matnga aylantirilmoqda" : "XADICHA bilan gapirish";

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
