"use client";

import { Cpu, Globe, KeyRound, Lock, Mic, Palette, ShieldCheck, Volume2 } from "lucide-react";
import { LANG_LABEL, LANGS, type Lang } from "@/lib/i18n";
import type { T } from "@/lib/use-lang";
import type { UiPrefs } from "@/lib/use-ui-prefs";
import { cn } from "@/lib/utils";
import type { Status } from "@/lib/xadicha";
import { GlassPanel, PanelTitle, Segmented } from "./glass";
import { CapChip, capOf } from "./screen-context";
import { Dot } from "./ui";

interface L { lang: Lang; setLang: (l: Lang) => void; t: T }

export function LangSwitch({ lang, setLang, t, layoutId = "lang-seg" }: L & { layoutId?: string }) {
  return (
    <Segmented value={lang} onChange={setLang} label={t("lang.label")} layoutId={layoutId}
      options={LANGS.map((id) => ({ id, label: LANG_LABEL[id], lang: id }))} />
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 py-2.5 text-sm sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-4">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="min-w-0 break-words">{v}</dd>
    </div>
  );
}

function Section({ icon, title, hint, children, className }: {
  icon: React.ReactNode; title: string; hint?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <GlassPanel className={cn("min-w-0 p-5", className)}>
      <PanelTitle icon={icon} hint={hint}>{title}</PanelTitle>
      <dl className="divide-y divide-white/[0.06]">{children}</dl>
    </GlassPanel>
  );
}

const CAP_ORDER = ["os_adapter", "screenshot", "vision_model", "ocr", "accessibility_tree", "microphone", "stt", "tts", "windows_ui_automation"] as const;

/** Sozlamalar — barcha qiymatlar backend holatidan (/api/status); o'zgartirish backend/.env orqali. */
export function SettingsView({ status, l, prefs, setPrefs }: {
  status: Status | null; l: L; prefs: UiPrefs; setPrefs: (p: Partial<UiPrefs>) => void;
}) {
  const { t } = l;
  const ic = "size-4";
  const appearance = (
    <div className="grid gap-4 lg:grid-cols-2">
      <Section icon={<Globe className={ic} aria-hidden />} title={t("settings.sec.language")}>
        <Row k={t("settings.uiLang")} v={<LangSwitch {...l} layoutId="lang-settings" />} />
      </Section>
      <Section icon={<Palette className={ic} aria-hidden />} title={t("settings.sec.theme")}>
        <Row k={t("theme.surface")} v={
          <div className="space-y-2">
            <Segmented value={prefs.theme} onChange={(v) => setPrefs({ theme: v })} label={t("settings.sec.theme")} layoutId="theme-seg"
              options={[{ id: "glass", label: t("theme.glass") }, { id: "solid", label: t("theme.solid") }]} />
            <p className="text-xs text-muted-foreground">{t("theme.hint")}</p>
          </div>} />
        <Row k={t("theme.nav")} v={
          <Segmented value={prefs.nav} onChange={(v) => setPrefs({ nav: v })} label={t("theme.nav")} layoutId="nav-seg"
            options={[{ id: "expanded", label: t("theme.navExpanded") }, { id: "compact", label: t("theme.navCompact") }]} />} />
      </Section>
    </div>
  );
  if (!status) {
    return (
      <div className="max-w-6xl space-y-4">
        {appearance}
        <GlassPanel className="p-5"><p className="text-sm text-muted-foreground">{t("settings.noBackend")}</p></GlassPanel>
      </div>
    );
  }
  const c = status.config;
  const confirmRisk = (["low", "medium", "high"] as const).includes(c.confirm_risk as "low")
    ? t(`risk.${c.confirm_risk as "low" | "medium" | "high"}`) : String(c.confirm_risk);
  const provider = status.provider.name;
  const privacyModel = provider === "ollama" ? t("privacy.modelLocal")
    : provider === "rules" || provider === "mock" ? t("privacy.modelRules")
      : t("privacy.modelCloud", { p: provider === "claude" ? "Anthropic Claude" : provider });

  return (
    <div className="max-w-6xl space-y-4">
      <p className="px-1 text-xs text-muted-foreground">{t("settings.hint")}</p>
      {appearance}
      <div className="grid gap-4 lg:grid-cols-2">
        <Section icon={<Cpu className={ic} aria-hidden />} title={t("settings.sec.ai")}>
          <Row k={t("settings.provider")} v={`${provider} — ${c.model}`} />
          <Row k={t("settings.modelHealth")} v={<span className="inline-flex items-center gap-2"><Dot ok={status.provider.ok} />{status.provider.detail}</span>} />
          <Row k={t("settings.vision")} v={status.provider.vision ? t("common.yes") : t("common.no")} />
          <Row k={t("settings.fastPath")} v={c.fast_path ? t("settings.fastPathOn") : t("common.off")} />
        </Section>
        <Section icon={<Mic className={ic} aria-hidden />} title={t("settings.sec.speech")}>
          <Row k={t("settings.model")} v={String(c.whisper_model)} />
          <Row k={t("settings.engine")} v={status.stt_engine === "mlx" ? "MLX (Apple GPU)" : status.stt_engine ?? "—"} />
          <Row k={t("cap.microphone")} v={<CapChip cap={capOf(status, "microphone")} t={t} />} />
          <Row k={t("cap.stt")} v={<CapChip cap={capOf(status, "stt")} t={t} />} />
        </Section>
        <Section icon={<Volume2 className={ic} aria-hidden />} title={t("settings.sec.voice")}>
          <Row k={t("settings.tts")} v={`${c.tts_engine} · ${c.tts_enabled ? t("common.on") : t("common.off")}`} />
          <Row k={t("settings.ttsAvail")} v={
            <span className="flex flex-wrap gap-1.5">
              {LANGS.map((lg) => (
                <span key={lg} className={cn("rounded-full px-2 py-0.5 text-[11px] ring-1",
                  status.tts[lg] ? "bg-success/10 text-success ring-success/25" : "bg-white/[0.04] text-muted-foreground ring-white/10")}>
                  {lg.toUpperCase()} {status.tts[lg] ? "✓" : "—"}
                </span>
              ))}
            </span>} />
          {capOf(status, "tts")?.detail && <Row k={t("cap.tts")} v={<span className="text-xs text-muted-foreground">{capOf(status, "tts")!.detail}</span>} />}
        </Section>
        <Section icon={<ShieldCheck className={ic} aria-hidden />} title={t("settings.sec.safety")}>
          <Row k={t("settings.confirm")} v={t("settings.confirmFrom", { risk: confirmRisk })} />
          <Row k={t("settings.maxSteps")} v={String(c.max_steps)} />
          <Row k={t("settings.workspace")} v={<code className="font-mono text-xs">{String(c.workspace)}</code>} />
        </Section>
        <Section icon={<Lock className={ic} aria-hidden />} title={t("settings.sec.privacy")}>
          {[privacyModel, t("privacy.asr"), t("privacy.screens"), t("privacy.memory"),
            c.tts_engine === "edge" ? t("privacy.ttsEdge") : t("privacy.ttsLocal")].map((line) => (
            <div key={line} className="flex items-start gap-2.5 py-2.5 text-sm">
              <span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-secondary/70" />
              <dd className="text-foreground/90">{line}</dd>
            </div>
          ))}
        </Section>
        <GlassPanel className="min-w-0 p-5">
          <PanelTitle icon={<KeyRound className={ic} aria-hidden />}>{t("settings.capabilities")}</PanelTitle>
          <p className="-mt-2 mb-3 text-xs text-muted-foreground">{t("settings.capHint")}</p>
          <ul className="divide-y divide-white/[0.06]">
            <li className="flex items-center justify-between gap-3 py-2.5 text-sm">
              <span>{t("settings.accessibility")}</span>
              <span className="text-xs text-muted-foreground">{status.permissions.accessibility == null ? t("common.unknown")
                : status.permissions.accessibility ? t("common.granted") : t("common.notGranted")}</span>
            </li>
            {CAP_ORDER.map((key) => {
              const cap = capOf(status, key);
              if (!cap) return null;
              return (
                <li key={key} className="flex items-start justify-between gap-3 py-2.5 text-sm">
                  <div className="min-w-0">
                    <p>{t(`cap.${key}`)}</p>
                    {cap.detail && <p className="mt-0.5 break-words text-xs text-muted-foreground">{cap.detail}</p>}
                  </div>
                  <CapChip cap={cap} t={t} />
                </li>
              );
            })}
          </ul>
        </GlassPanel>
      </div>
    </div>
  );
}
