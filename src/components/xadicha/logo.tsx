"use client";

import { motion, useReducedMotion } from "motion/react";
import { useId } from "react";

/**
 * XADICHA maskoti: quloqchinli robot, porlab turgan tabassumli ko'zlar va mikrofon.
 * listening — quloqchinlar porlaydi; thinking — ko'zlar "o'ylaydi"; aks holda vaqti-vaqti bilan ko'z qisadi.
 */
export function XadichaMark({
  size = 40, aura = true, speaking = false, thinking = false, className,
}: { size?: number; aura?: boolean; tile?: boolean; speaking?: boolean; thinking?: boolean; className?: string }) {
  const id = useId().replace(/:/g, "");
  const reduce = useReducedMotion();
  const u = (n: string) => `url(#${id}${n})`;

  const eyes = reduce
    ? {}
    : thinking
      ? { animate: { opacity: [1, 0.35, 1] }, transition: { duration: 0.9, repeat: Infinity } }
      : { animate: { scaleY: [1, 1, 0.15, 1, 1] }, transition: { duration: 4.5, repeat: Infinity, times: [0, 0.9, 0.93, 0.96, 1] } };
  const cup = speaking && !reduce
    ? { animate: { r: [4, 6, 4], opacity: [0.8, 1, 0.8] }, transition: { duration: 0.8, repeat: Infinity } }
    : {};

  return (
    <svg viewBox="0 0 120 120" width={size} height={size} className={className} role="img" aria-label="XADICHA AI">
      <defs>
        <radialGradient id={`${id}aura`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#4f46e5" stopOpacity="0.55" /><stop offset="0.6" stopColor="#2563eb" stopOpacity="0.18" />
          <stop offset="1" stopColor="#06b6d4" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}shell`} x1="0.2" y1="0" x2="0.8" y2="1">
          <stop offset="0" stopColor="#ffffff" /><stop offset="0.55" stopColor="#e0e7ff" /><stop offset="1" stopColor="#a5b4fc" />
        </linearGradient>
        <linearGradient id={`${id}band`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#7c3aed" /><stop offset="0.5" stopColor="#4f46e5" /><stop offset="1" stopColor="#06b6d4" />
        </linearGradient>
        <linearGradient id={`${id}visor`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#111733" /><stop offset="1" stopColor="#03050d" />
        </linearGradient>
        <linearGradient id={`${id}cup`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3730a3" /><stop offset="1" stopColor="#1e1b4b" />
        </linearGradient>
        <filter id={`${id}glow`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.2" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {aura && <circle cx="60" cy="62" r="56" fill={u("aura")} />}
      <path d="M24 60 C 22 20, 98 20, 96 60" fill="none" stroke={u("band")} strokeWidth="7" strokeLinecap="round" filter={u("glow")} />
      <ellipse cx="60" cy="64" rx="34" ry="31" fill={u("shell")} />
      <path d="M38 44 C 46 36, 70 34, 82 42" fill="none" stroke="#fff" strokeOpacity="0.9" strokeWidth="2.5" strokeLinecap="round" />
      <rect x="35" y="49" width="50" height="30" rx="15" fill={u("visor")} />
      <rect x="38" y="51" width="22" height="5" rx="2.5" fill="#fff" fillOpacity="0.08" />
      <motion.g fill="none" stroke="#22d3ee" strokeWidth="4.2" strokeLinecap="round" filter={u("glow")}
        style={{ transformOrigin: "60px 64px", transformBox: "view-box" }} {...eyes}>
        <path d="M45 67 q6 -8 12 0" /><path d="M63 67 q6 -8 12 0" />
      </motion.g>
      <rect x="15" y="50" width="15" height="28" rx="7.5" fill={u("cup")} stroke={u("band")} strokeWidth="2" />
      <rect x="90" y="50" width="15" height="28" rx="7.5" fill={u("cup")} stroke={u("band")} strokeWidth="2" />
      <motion.circle cx="22.5" cy="64" r="4" fill="#38bdf8" filter={u("glow")} {...cup} />
      <motion.circle cx="97.5" cy="64" r="4" fill="#38bdf8" filter={u("glow")} {...cup} />
      <path d="M20 77 C 22 90, 34 94, 44 91" fill="none" stroke={u("band")} strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="46" cy="90.5" r="3" fill="#22d3ee" filter={u("glow")} />
    </svg>
  );
}

/** "X" harfi — oq qalin chiziq va binafsha-moviy aylanma lenta (namunadagidek). */
function SwooshX({ h }: { h: number }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 40 40" height={h} width={h} aria-hidden className="shrink-0">
      <defs>
        <linearGradient id={`${id}s`} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#a855f7" /><stop offset="0.5" stopColor="#6366f1" /><stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <path d="M6 6 H14 L34 34 H26 Z" fill="#F8FAFC" />
      <path d="M2 37 C 10 34, 22 22, 30 8 C 32 5, 35 3.5, 39 3 C 33 8, 26 22, 16 31 C 11 35.5, 6 37.5, 2 37 Z" fill={`url(#${id}s)`} />
    </svg>
  );
}

export function XadichaWordmark({ size = 46, tagline = true }: { size?: number; tagline?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <XadichaMark size={size} />
      <div className="leading-none">
        <p className="flex items-center text-[17px] font-extrabold tracking-wide">
          <SwooshX h={17} />
          <span className="-ml-0.5">ADICHA</span>
          <span className="ml-1.5 bg-gradient-to-r from-cyan-400 via-blue-500 to-violet-500 bg-clip-text text-transparent">AI</span>
        </p>
        {tagline && <p className="mt-1.5 text-[9.5px] tracking-[0.16em] text-muted-foreground uppercase">Aqlli yordamchi</p>}
      </div>
    </div>
  );
}
