"use client";

import { Check, Loader2, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { MsgKey } from "@/lib/i18n";
import type { T } from "@/lib/use-lang";
import type { RuntimeSettingsValues, SettingsResponse, Status } from "@/lib/types";
import { GlassPanel, PanelTitle, Segmented } from "./glass";
import { Button } from "./ui";

export interface SettingsApi {
  getSettings: () => Promise<SettingsResponse>;
  saveSettings: (patch: Partial<RuntimeSettingsValues>) => Promise<SettingsResponse>;
}

const parseCorrections = (s: string): Record<string, string> => Object.fromEntries(
  s.split("\n").map((l) => l.split(/=>|→/)).filter((p) => p.length === 2 && p[0].trim() && p[1].trim())
    .map(([a, b]) => [a.trim(), b.trim()]),
);
const fmtCorrections = (c: Record<string, string>) => Object.entries(c).map(([a, b]) => `${a} => ${b}`).join("\n");

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 py-3 text-sm sm:grid-cols-[200px_minmax(0,1fr)] sm:gap-4">
      <div className="text-muted-foreground">{label}{hint && <p className="mt-0.5 text-[11px] text-faint">{hint}</p>}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Ish vaqtidagi (maxfiy bo'lmagan) sozlamalar — backend'da saqlanadi va darhol qo'llanadi. */
export function RuntimeSettings({ api, status, t }: { api: SettingsApi; status: Status | null; t: T }) {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<RuntimeSettingsValues | null>(null);
  const [vocab, setVocab] = useState("");
  const [corr, setCorr] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [err, setErr] = useState("");
  const instance = status?.instance;

  useEffect(() => {
    let alive = true;
    api.getSettings().then((r) => {
      if (!alive) return;
      setData(r);
      setDraft(r.values);
      setVocab(r.values.vocabulary.join("\n"));
      setCorr(fmtCorrections(r.values.corrections));
    }).catch(() => {});
    return () => { alive = false; };
  }, [api, instance]);

  const patch = useMemo(() => {
    if (!data || !draft) return {};
    const p: Partial<RuntimeSettingsValues> = {};
    (Object.keys(draft) as (keyof RuntimeSettingsValues)[]).forEach((k) => {
      if (k === "vocabulary" || k === "corrections") return;
      if (draft[k] !== data.values[k]) (p as Record<string, unknown>)[k] = draft[k];
    });
    const v = vocab.split("\n").map((s) => s.trim()).filter(Boolean);
    if (v.join("\n") !== data.values.vocabulary.join("\n")) p.vocabulary = v;
    const c = parseCorrections(corr);
    if (JSON.stringify(c) !== JSON.stringify(data.values.corrections)) p.corrections = c;
    return p;
  }, [data, draft, vocab, corr]);
  const dirty = Object.keys(patch).length > 0;

  if (!data || !draft) return null;
  const set = <K extends keyof RuntimeSettingsValues>(k: K, v: RuntimeSettingsValues[K]) => {
    setDraft({ ...draft, [k]: v });
    setState("idle");
  };
  const onOff = (k: "live_enabled" | "live_barge_in" | "tts_enabled" | "offline_mode" | "auto_language") => (
    <Segmented value={draft[k] ? "on" : "off"} onChange={(v) => set(k, v === "on")} label={k} layoutId={`rt-${k}`}
      options={[{ id: "on", label: t("set.on") }, { id: "off", label: t("set.off") }]} />
  );
  const save = async () => {
    setState("saving");
    setErr("");
    try {
      const r = await api.saveSettings(patch);
      setData(r);
      setDraft(r.values);
      setVocab(r.values.vocabulary.join("\n"));
      setCorr(fmtCorrections(r.values.corrections));
      setState("saved");
    } catch (e) {
      setErr((e as Error).message);
      setState("error");
    }
  };
  const ro = data.readonly;
  const sttNow = status?.stt ? (status.stt.active === "gemini" ? `Gemini · ${status.stt.gemini.model}` : `Whisper · ${status.stt.whisper.model}`) : "—";
  const area = "w-full min-h-[84px] rounded-2xl border border-white/10 bg-white/[0.04] px-3 py-2 font-mono text-xs text-foreground placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35";

  return (
    <GlassPanel className="p-5">
      <PanelTitle icon={<SlidersHorizontal className="size-4" aria-hidden />}
        hint={<Button onClick={save} disabled={!dirty || state === "saving"} className="h-8 px-4 text-xs">
          {state === "saving" ? <Loader2 className="size-3.5 animate-spin" /> : state === "saved" && !dirty ? <Check className="size-3.5" /> : null}
          {state === "saved" && !dirty ? t("set.saved") : t("set.save")}
        </Button>}>{t("set.sec.runtime")}</PanelTitle>
      <p className="-mt-2 mb-2 text-xs text-muted-foreground">{t("set.runtimeHint")}</p>
      {state === "error" && <p role="alert" className="mb-2 rounded-xl border border-destructive/25 bg-destructive/10 px-3 py-2 text-xs text-destructive">{t("set.saveFailed", { msg: err })}</p>}
      <div className="divide-y divide-white/[0.06]">
        <Row label={t("set.searchMode")} hint={t("set.searchHint")}>
          <Segmented value={draft.search_mode} onChange={(v) => set("search_mode", v)} label={t("set.searchMode")} layoutId="rt-search"
            options={(["auto", "always", "never"] as const).map((id) => ({ id, label: t(`set.search.${id}` as MsgKey) }))} />
        </Row>
        <Row label={t("set.stt")} hint={t("set.sttActive", { p: sttNow })}>
          <Segmented value={draft.stt_provider} onChange={(v) => set("stt_provider", v)} label={t("set.stt")} layoutId="rt-stt"
            options={(["auto", "gemini", "whisper"] as const).map((id) => ({ id, label: t(`set.stt.${id}` as MsgKey) }))} />
        </Row>
        <Row label={t("set.live")} hint={status?.live && !status.live.available ? status.live.detail : t("live.hint")}>{onOff("live_enabled")}</Row>
        <Row label={t("set.liveBargeIn")} hint={t("set.liveBargeInHint")}>{onOff("live_barge_in")}</Row>
        <Row label={t("set.uzScript")}>
          <Segmented value={draft.uz_script} onChange={(v) => set("uz_script", v)} label={t("set.uzScript")} layoutId="rt-uzscript"
            options={(["latin", "cyrillic"] as const).map((id) => ({ id, label: t(`set.uzScript.${id}` as MsgKey) }))} />
        </Row>
        <Row label={t("set.tts")}>{onOff("tts_enabled")}</Row>
        <Row label={t("set.rate")}>
          <div className="flex items-center gap-3">
            <input type="range" min={100} max={300} step={5} value={draft.tts_rate} aria-label={t("set.rate")}
              onChange={(e) => set("tts_rate", Number(e.target.value))} className="w-48 accent-[#7775ff]" />
            <span className="text-xs tabular-nums text-muted-foreground">{draft.tts_rate}</span>
          </div>
        </Row>
        <Row label={t("set.autoLang")} hint={t("set.autoLangHint")}>{onOff("auto_language")}</Row>
        <Row label={t("set.offline")}>{onOff("offline_mode")}</Row>
        <Row label={t("set.mic")}>
          <select value={draft.microphone} onChange={(e) => set("microphone", e.target.value)} aria-label={t("set.mic")}
            className="h-9 w-full max-w-sm cursor-pointer rounded-full border border-white/10 bg-white/[0.05] px-3 text-xs text-foreground focus-visible:outline-2 focus-visible:outline-ring">
            <option value="" className="bg-[#10162b]">{t("set.micDefault")}</option>
            {data.options.microphones.map((m) => <option key={m.name} value={m.name} className="bg-[#10162b]">{m.name}{m.default ? " ★" : ""}</option>)}
          </select>
        </Row>
        <Row label={t("set.vocab")} hint={t("set.vocabHint")}>
          <textarea value={vocab} onChange={(e) => { setVocab(e.target.value); setState("idle"); }} className={area}
            aria-label={t("set.vocab")} placeholder={"Shohrux\nXADICHA AI"} spellCheck={false} />
        </Row>
        <Row label={t("set.corrections")} hint={t("set.correctionsHint")}>
          <textarea value={corr} onChange={(e) => { setCorr(e.target.value); setState("idle"); }} className={area}
            aria-label={t("set.corrections")} placeholder={"vs kod => VS Code"} spellCheck={false} />
        </Row>
        <Row label={t("set.envOnly")}>
          <dl className="grid gap-1 text-xs text-muted-foreground">
            <div><dt className="inline text-faint">{t("settings.provider")}: </dt><dd className="inline text-foreground/90">{String(ro.provider)}</dd></div>
            <div><dt className="inline text-faint">{t("set.geminiModels")}: </dt><dd className="inline text-foreground/90">{[ro.gemini_model, ...((ro.gemini_fallback_models as string[]) ?? [])].join(" → ")} → {String(ro.ollama_model)}</dd></div>
            <div><dt className="inline text-faint">{t("set.sttModels")}: </dt><dd className="inline text-foreground/90">{String(ro.gemini_stt_model)} · Whisper {String(ro.whisper_model)}</dd></div>
            <div><dt className="inline text-faint">{t("set.liveModel")}: </dt><dd className="inline text-foreground/90">{String(ro.live_model)}</dd></div>
            <div><dt className="inline text-faint">{t("set.key")}: </dt><dd className="inline text-foreground/90">{ro.has_gemini_key ? t("set.keySet") : t("set.keyMissing")}</dd></div>
          </dl>
        </Row>
      </div>
    </GlassPanel>
  );
}
