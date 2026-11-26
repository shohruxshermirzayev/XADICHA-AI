"use client";

import { AnimatePresence, motion } from "motion/react";
import { AudioLines, Cpu, Mic, Radio, Search, Square } from "lucide-react";
import { liveActive } from "@/lib/state";
import type { T } from "@/lib/use-lang";
import { cn } from "@/lib/utils";
import type { Grounding, LiveState, Status } from "@/lib/types";
import type { VoiceLatency } from "@/lib/state";

/** Provayder nomi — inson o'qiydigan ko'rinish. */
function prettyProvider(name?: string): string {
  if (!name) return "—";
  if (name.startsWith("whisper")) return name.includes("mlx") ? "Whisper (MLX)" : "Whisper";
  return ({ gemini: "Gemini", ollama: "Ollama", claude: "Claude", rules: "Qoidalar", mock: "Qoidalar",
    "gemini-live": "Gemini Live" } as Record<string, string>)[name] ?? name;
}

/** Buyruq rejimi: foydalanuvchi gapirayotgan paytdagi oraliq matn (Gemini Live Transcription, haqiqiy bo'laklar). */
export function CommandPartial({ text, level, active, t }: { text: string; level: number; active: boolean; t: T }) {
  return (
    <AnimatePresence>
      {active && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }}
          className="mx-3 mb-2 flex items-center gap-3 rounded-[18px] border border-secondary/20 bg-secondary/[0.05] px-4 py-2.5 sm:mx-4"
          role="status" aria-live="polite">
          <span aria-hidden className="flex h-5 items-end gap-[3px]">
            {[0.5, 0.8, 1, 0.8, 0.5].map((k, i) => (
              <span key={i} className="w-[3px] rounded-full bg-secondary transition-[height] duration-75"
                style={{ height: `${Math.max(3, Math.min(20, 3 + level * 22 * k))}px` }} />
            ))}
          </span>
          <p className={cn("min-w-0 flex-1 truncate text-sm", text ? "text-foreground" : "text-muted-foreground")}>
            {text || t("stt.listening")}
          </p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Oxirgi ovozli buyruqning HAQIQIY kechikishi (backend o'lchovi; taxmin emas). */
export function LatencyChip({ lat, t }: { lat: VoiceLatency | null; t: T }) {
  if (!lat || lat.ttf_final == null) return null;
  const s = (v: number | null) => (v == null ? "—" : v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1)} s`);
  const tip = [
    `${t("lat.partial")}: ${s(lat.ttf_partial)}`, `${t("lat.final")}: ${s(lat.ttf_final)}`,
    `${t("lat.action")}: ${s(lat.tt_first_action)}`, `${t("lat.text")}: ${s(lat.tt_response_text)}`,
    `${t("lat.audio")}: ${s(lat.tt_response_audio)}`, `STT: ${prettyProvider(lat.stt)}`,
  ].join("\n");
  return (
    <span title={tip} className="hidden items-center gap-1 rounded-full bg-white/[0.04] px-2 py-0.5 text-[11px] text-muted-foreground ring-1 ring-white/10 lg:inline-flex">
      ⏱ {t("lat.label")} {s(lat.tt_first_action ?? lat.ttf_final)}
    </span>
  );
}

/** Hozir HAQIQATAN ishlayotgan AI va STT provayderlari (backend /api/status'dan; taxmin yo'q). */
export function ProviderChips({ status, t }: { status: Status | null; t: T }) {
  if (!status) return null;
  const p = status.provider;
  const fallback = !!p.using_fallback;
  const aiModel = fallback ? p.fallback?.model : (p.primary?.active_model || p.primary?.model || String(status.config.model ?? ""));
  const stt = status.stt;
  const sttName = stt ? (stt.active === "gemini" ? "Gemini" : prettyProvider(`whisper:${stt.whisper.engine}`)) : undefined;
  const title = fallback ? t("prov.usingFallback", { why: p.last_error || "—" }) : `${prettyProvider(p.name)} · ${aiModel ?? ""}`;
  return (
    <div className="flex min-w-0 items-center gap-1.5 text-[11px]">
      <span title={title}
        className={cn("inline-flex min-w-0 items-center gap-1 rounded-full px-2 py-0.5 ring-1",
          fallback ? "bg-warning/10 text-warning ring-warning/25" : "bg-white/[0.04] text-muted-foreground ring-white/10")}>
        <Cpu className="size-3 shrink-0" aria-hidden />
        <span className="truncate">{t("chip.ai")} · {prettyProvider(p.name)}{fallback ? ` (${t("chip.fallback")})` : ""}</span>
      </span>
      {sttName && (
        <span title={stt?.gemini.error || `${t("set.stt")}: ${sttName}`}
          className={cn("hidden items-center gap-1 rounded-full px-2 py-0.5 ring-1 md:inline-flex",
            stt?.mode !== "whisper" && stt?.active === "whisper" && stt?.gemini.configured
              ? "bg-warning/10 text-warning ring-warning/25" : "bg-white/[0.04] text-muted-foreground ring-white/10")}>
          <Mic className="size-3" aria-hidden />{t("chip.stt")} · {sttName}
        </span>
      )}
      {p.offline && (
        <span className="rounded-full bg-white/[0.04] px-2 py-0.5 text-muted-foreground ring-1 ring-white/10">{t("chip.offline")}</span>
      )}
    </div>
  );
}

/** Gemini Live tugmasi — faqat backend "mavjud" desa yoqiladi; aks holda sababi tooltip'da. */
export function LiveButton({ status, state, busy, onStart, onStop, t }: {
  status: Status | null; state: LiveState; busy: boolean; onStart: () => void; onStop: () => void; t: T;
}) {
  const live = status?.live;
  const on = liveActive({ live: { state, user: "", assistant: "" } });
  if (!live) return null;
  const disabled = !on && (!live.available || busy);
  const label = on ? t("live.stop") : live.available ? t("live.start") : t("live.unavailable", { why: live.detail });
  return (
    <button type="button" onClick={on ? onStop : onStart} disabled={disabled} aria-pressed={on} aria-label={label} title={label}
      className={cn("inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors",
        "focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-40",
        on ? "bg-secondary/15 text-secondary ring-1 ring-secondary/40" : "border border-white/10 bg-white/[0.05] text-muted-foreground hover:text-foreground")}>
      {on ? <Square className="size-3 fill-current" aria-hidden /> : <Radio className="size-3.5" aria-hidden />}
      <span className="hidden sm:inline">{t("live.button")}</span>
      {on && <span className="size-1.5 animate-pulse rounded-full bg-secondary" aria-hidden />}
    </button>
  );
}

/** Jonli transkripsiya (Live): foydalanuvchi va XADICHA matni — backend'dan kelgan haqiqiy bo'laklar. */
export function LiveTranscript({ state, user, assistant, t }: { state: LiveState; user: string; assistant: string; t: T }) {
  const on = liveActive({ live: { state, user, assistant } });
  return (
    <AnimatePresence>
      {on && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }}
          className="mx-3 mb-2 rounded-[18px] border border-secondary/20 bg-secondary/[0.05] px-4 py-2.5 sm:mx-4" role="status" aria-live="polite">
          <p className="flex items-center gap-2 text-[11px] font-medium tracking-wide text-secondary">
            <AudioLines className="size-3.5" aria-hidden />Gemini Live · {t(`live.state.${state}`)}
          </p>
          {user && <p className="mt-1 text-sm text-foreground/90"><span className="text-muted-foreground">{t("live.you")}: </span>{user}</p>}
          {assistant && <p className="mt-0.5 text-sm text-foreground">XADICHA: {assistant}</p>}
          {!user && !assistant && <p className="mt-1 text-xs text-muted-foreground">{t("live.hint")}</p>}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/**
 * Google Search Suggestions — Google talabi bo'yicha grounded javob bilan birga ko'rsatiladi.
 * HTML backend'dan o'zgarishsiz keladi va IZOLYATSIYALANGAN iframe'da ochiladi (skript yo'q, sahifaga kira olmaydi);
 * havolalar yangi oynada ochiladi.
 */
export function SearchSuggestions({ html, t }: { html: string; t: T }) {
  if (!html) return null;
  const doc = `<!doctype html><html><head><meta charset="utf-8"><base target="_blank"><style>html,body{margin:0;background:transparent;overflow-x:auto}</style></head><body>${html}</body></html>`;
  return (
    <iframe title={t("card.suggestions")} srcDoc={doc} sandbox="allow-popups allow-popups-to-escape-sandbox"
      referrerPolicy="no-referrer" className="mt-2 h-[58px] w-full rounded-xl border-0" loading="lazy" />
  );
}

/** Grounding tafsilotlari: model bajargan qidiruv so'rovlari va (bo'lsa) "qidiruv bajarilmadi" izohi. */
export function GroundingMeta({ g, t }: { g: Grounding; t: T }) {
  return (
    <div className="mt-2.5 space-y-1.5">
      {g.queries.length > 0 && (
        <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <Search className="size-3" aria-hidden /><span>{t("card.queries")}:</span>
          {g.queries.slice(0, 4).map((q) => (
            <span key={q} className="rounded-full bg-white/[0.05] px-2 py-0.5 text-foreground/80">{q}</span>
          ))}
        </p>
      )}
      {!g.grounded && <p className="text-[11px] text-faint">{t("card.notGrounded")}</p>}
    </div>
  );
}

export { prettyProvider };
