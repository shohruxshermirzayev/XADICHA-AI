"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { OrbState, RowState } from "@/lib/presence";
import { cn } from "@/lib/utils";

/**
 * XADICHA orbi — shisha shar. Har bir holat faqat backend'dan kelgan haqiqiy holatni ko'rsatadi:
 *  idle — tinch nur; listening — mikrofon darajasiga (mic_level) bog'liq moviy to'lqinlar;
 *  processing — nutq matnga aylantirilmoqda; thinking — sekin binafsha oqim; executing — qadamlar halqasi
 *  (har bir segment — haqiqiy qadam); speaking — javob aytilmoqda (TTS ovoz darajasi backend'dan kelmaydi,
 *  shuning uchun to'lqin "reaktiv" deb ko'rsatilmaydi); awaiting — tasdiq kutilmoqda; interrupted / error / offline.
 */
const TONE: Record<OrbState, { a: string; b: string; halo: number }> = {
  idle: { a: "#7775ff", b: "#37d9f5", halo: 0.32 },
  listening: { a: "#37d9f5", b: "#4285ff", halo: 0.55 },
  processing: { a: "#37d9f5", b: "#7775ff", halo: 0.45 },
  thinking: { a: "#7775ff", b: "#a78bfa", halo: 0.5 },
  searching: { a: "#37d9f5", b: "#34d399", halo: 0.5 },
  connecting: { a: "#37d9f5", b: "#7775ff", halo: 0.35 },
  recovering: { a: "#fbbf24", b: "#7775ff", halo: 0.4 },
  executing: { a: "#4285ff", b: "#37d9f5", halo: 0.5 },
  speaking: { a: "#8b7bff", b: "#37d9f5", halo: 0.55 },
  awaiting: { a: "#fbbf24", b: "#f59e0b", halo: 0.42 },
  interrupted: { a: "#f5b452", b: "#94a3b8", halo: 0.28 },
  error: { a: "#fb7185", b: "#f43f5e", halo: 0.4 },
  offline: { a: "#64748b", b: "#334155", halo: 0.18 },
};

const SEG_COLOR: Record<RowState, string> = {
  done: "#37d9f5", active: "#8f8dff", failed: "#fb7185", warn: "#fbbf24", pending: "rgb(255 255 255 / 0.12)",
};

function ProgressRing({ segments, size }: { segments: RowState[]; size: number }) {
  const r = size / 2 - 3;
  const c = 2 * Math.PI * r;
  const n = Math.max(1, segments.length);
  const gap = n > 1 ? Math.min(10, c / n / 4) : 0;
  const len = c / n - gap;
  return (
    <svg aria-hidden width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(255 255 255 / 0.06)" strokeWidth={2} />
      {segments.map((s, i) => (
        <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={SEG_COLOR[s]} strokeWidth={2.5}
          strokeLinecap="round" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-i * (len + gap)}
          className={cn(s === "active" && "animate-pulse")} style={{ transition: "stroke 300ms ease" }} />
      ))}
    </svg>
  );
}

export function AIOrb({ state, level = 0, segments = [], size = 160, className }: {
  state: OrbState; level?: number; segments?: RowState[]; size?: number; className?: string;
}) {
  const reduce = useReducedMotion();
  const tone = TONE[state];
  const lv = state === "listening" ? Math.min(1, Math.max(0, level)) : 0;
  const animated = !reduce;
  const flowing = state === "thinking" || state === "processing" || state === "executing" || state === "speaking"
    || state === "searching" || state === "recovering";
  const ringPad = Math.round(size * 0.14);

  return (
    <div className={cn("relative shrink-0", className)} style={{ width: size, height: size }} data-orb-state={state}>
      {/* Nur — holat rangiga mos; listening paytida mikrofon darajasiga qarab kattalashadi */}
      <AnimatePresence initial={false}>
        <motion.div key={state} aria-hidden className="absolute -inset-[38%] rounded-full blur-2xl"
          style={{ background: `radial-gradient(circle, ${tone.a}, ${tone.b}55 38%, transparent 66%)` }}
          initial={{ opacity: 0 }} animate={{ opacity: tone.halo + lv * 0.35, scale: 1 + lv * 0.18 }}
          exit={{ opacity: 0 }} transition={{ duration: lv ? 0.12 : 0.7, ease: "easeOut" }} />
      </AnimatePresence>

      {/* Tinglash: moviy to'lqinlar (har biri real mic_level bilan) */}
      {state === "listening" && animated && [0, 0.8, 1.6].map((d) => (
        <span key={d} aria-hidden className="animate-orb-ripple absolute inset-0 rounded-full border border-secondary/60"
          style={{ animationDelay: `${d}s` }} />
      ))}
      {state === "listening" && (
        <motion.span aria-hidden className="absolute inset-0 rounded-full border-2 border-secondary/80"
          animate={{ scale: 1 + lv * 0.22, opacity: 0.35 + lv * 0.65 }} transition={{ duration: 0.08 }} />
      )}
      {/* Tasdiq kutilmoqda / gapirmoqda: yumshoq halqa nafasi */}
      {(state === "awaiting" || state === "speaking") && animated && (
        <span aria-hidden className="animate-orb-ripple absolute inset-0 rounded-full border"
          style={{ borderColor: `${tone.a}99`, animationDuration: state === "speaking" ? "1.8s" : "3s" }} />
      )}

      {/* Bajarish: har bir segment — haqiqiy qadam (bajarilgan / joriy / xato / rad etilgan) */}
      {state === "executing" && segments.length > 0 && <ProgressRing segments={segments} size={size} />}

      {/* Shisha shar */}
      <motion.div
        className="absolute overflow-hidden rounded-full"
        style={{
          inset: state === "executing" ? ringPad / 2 + 4 : 0,
          background:
            `radial-gradient(circle at 50% 116%, ${tone.a}e6 0%, ${tone.b}40 36%, transparent 60%),` +
            `radial-gradient(circle at 70% 30%, ${tone.b}26 0%, transparent 45%),` +
            "radial-gradient(circle at 42% 38%, #1b2246 0%, #0b1022 58%, #05070e 100%)",
          boxShadow: `inset 0 -${size * 0.08}px ${size * 0.2}px ${tone.a}40, inset 0 1px 1px rgb(255 255 255 / 0.35), ` +
            `inset 0 0 0 1px rgb(255 255 255 / 0.12), 0 ${size * 0.12}px ${size * 0.35}px -${size * 0.12}px ${tone.a}88`,
        }}
        animate={{ scale: state === "interrupted" ? 0.94 : 1 }}
        transition={{ type: "spring", stiffness: 220, damping: 20 }}
      >
        {/* Ichki oqim: o'ylash/bajarish/gapirish paytida aylanadi */}
        <div aria-hidden
          className={cn("absolute -inset-1/4 rounded-full blur-xl transition-opacity duration-700",
            animated && (state === "processing" || state === "searching" || state === "connecting" ? "animate-orb-spin-fast" : state === "idle" || flowing ? "animate-orb-spin" : ""))}
          style={{
            background: `conic-gradient(from 0deg, transparent 0deg, ${tone.a} 70deg, transparent 150deg, ${tone.b} 230deg, transparent 300deg)`,
            opacity: flowing ? 0.55 : state === "idle" ? 0.22 : state === "listening" ? 0.3 : 0.15,
            animationDuration: state === "thinking" ? "11s" : state === "speaking" ? "5s" : undefined,
          }} />
        {/* Mikrofon darajasi ustunlari (listening) — real qiymat */}
        {state === "listening" && (
          <div aria-hidden className="absolute inset-0 flex items-center justify-center gap-[6%]">
            {[0.55, 0.85, 1, 0.85, 0.55].map((k, i) => (
              <motion.span key={i} className="w-[5%] rounded-full bg-white/85"
                animate={{ height: `${10 + lv * 46 * k}%` }} transition={{ duration: 0.09 }} />
            ))}
          </div>
        )}
        {/* Gapirish — reaktiv emas (TTS darajasi yo'q): sokin to'lqin */}
        {state === "speaking" && animated && (
          <div aria-hidden className="absolute inset-0 flex items-center justify-center gap-[6%]">
            {[0, 0.15, 0.3, 0.15, 0].map((d, i) => (
              <span key={i} className="animate-orb-breathe w-[5%] rounded-full bg-white/70"
                style={{ height: `${[18, 28, 36, 28, 18][i]}%`, animationDelay: `${d}s`, animationDuration: "1.6s" }} />
            ))}
          </div>
        )}
        {/* Shisha: yuqori yarim oy aks, kichik yaltirash, pastki sinish nuri, ichki qirra */}
        <div aria-hidden className="absolute top-[5%] left-[15%] h-[34%] w-[62%] -rotate-[14deg] rounded-[50%] bg-gradient-to-b from-white/40 via-white/10 to-transparent blur-[1.5px]" />
        <div aria-hidden className="absolute top-[14%] left-[26%] size-[7%] rounded-full bg-white/80 blur-[1px]" />
        <div aria-hidden className="absolute right-[18%] bottom-[5%] left-[18%] h-[16%] rounded-full blur-md"
          style={{ background: `radial-gradient(closest-side, ${tone.b}aa, transparent)` }} />
        <div aria-hidden className="absolute inset-0 rounded-full shadow-[inset_0_0_0_1px_rgb(255_255_255/0.14),inset_0_2px_10px_rgb(255_255_255/0.08)]" />
      </motion.div>
    </div>
  );
}
