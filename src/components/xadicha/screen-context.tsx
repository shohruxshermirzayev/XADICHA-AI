"use client";

import { AnimatePresence, motion } from "motion/react";
import { AppWindow, Camera, Eraser, Eye, Loader2, Monitor, ScanText, Timer, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { LOCALE, type Lang, type MsgKey } from "@/lib/i18n";
import { fmtMs } from "@/lib/presence";
import type { T } from "@/lib/use-lang";
import { cn } from "@/lib/utils";
import type { Capability, ScreenSnapshot, Status, useXadicha } from "@/lib/xadicha";
import { CurrentTaskPanel } from "./conversation";
import { GlassPanel, PanelTitle } from "./glass";
import { Button } from "./ui";

type X = ReturnType<typeof useXadicha>;

const CAP_STYLE: Record<Capability["state"], string> = {
  available: "bg-success/10 text-success ring-success/25",
  not_tested: "bg-warning/10 text-warning ring-warning/25",
  unavailable: "bg-destructive/10 text-destructive ring-destructive/25",
  not_implemented: "bg-white/[0.04] text-muted-foreground ring-white/10",
};

export function capOf(status: Status | null, key: string): Capability | null {
  const c = status?.capabilities?.[key];
  return c && typeof c === "object" ? c : null;
}

export function CapChip({ cap, label, t }: { cap: Capability | null; label?: string; t: T }) {
  const state = cap?.state ?? "not_implemented";
  return (
    <span title={cap?.detail} className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1", CAP_STYLE[state])}>
      {label && <>{label}<span className="opacity-70">·</span></>}<span className={label ? "opacity-80" : undefined}>{t(`cap.${state}`)}</span>
    </span>
  );
}

/** Asosiy ekrandagi ixcham ko'rinish: oxirgi olingan ekran holati (bo'lsa). */
export function ScreenSummary({ snap, t }: { snap: ScreenSnapshot | null; t: T }) {
  if (!snap) return <p className="text-xs leading-relaxed text-muted-foreground">{t("screen.none")}</p>;
  if (snap.error && !snap.app) return <p className="text-xs text-warning">{snap.error}</p>;
  return (
    <div className="flex items-center gap-3">
      {snap.preview && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={snap.preview} alt="" className="h-12 w-20 shrink-0 rounded-lg object-cover ring-1 ring-white/10" />
      )}
      <div className="min-w-0 text-xs">
        <p className="truncate font-medium text-foreground">{snap.app ?? "—"}</p>
        <p className="truncate text-muted-foreground">{snap.window ?? ""}</p>
        <p className="text-faint">{snap.ocr.lines.length} OCR · {snap.ax.elements.length} UI</p>
      </div>
    </div>
  );
}

/** Ekran tahlili: foydalanuvchi so'raganda olinadigan haqiqiy ekran holati + XADICHA'ning tasviri. */
export function ScreenView({ x, l, snap, setSnap }: {
  x: X; l: { lang: Lang; t: T }; snap: ScreenSnapshot | null; setSnap: (s: ScreenSnapshot | null) => void;
}) {
  const { lang, t } = l;
  const [busy, setBusy] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const offline = x.online === false;
  const prompt = t("screen.prompt");
  const vision = capOf(x.status, "vision_model");
  const noVision = !!x.status && (vision ? vision.state === "unavailable" : !x.status.provider.vision);

  const capture = async () => {
    setBusy(true);
    setErr(null);
    try {
      setSnap(await x.screenSnapshot(true));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const delayed = () => {
    let s = 3;
    setCountdown(s);
    timer.current = setInterval(() => {
      s -= 1;
      if (s <= 0) {
        if (timer.current) clearInterval(timer.current);
        setCountdown(null);
        capture();
      } else setCountdown(s);
    }, 1000);
  };
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  const fmtTime = (ts: number) => new Date(ts * 1000).toLocaleTimeString(LOCALE[lang], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const caps: [string, MsgKey][] = [["screenshot", "cap.screenshot"], ["ocr", "cap.ocr"], ["accessibility_tree", "cap.accessibility_tree"], ["vision_model", "cap.vision_model"]];

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <GlassPanel className="min-w-0 p-5 sm:p-6">
        <PanelTitle icon={<Monitor className="size-4" aria-hidden />}>{t("screen.title")}</PanelTitle>
        <div className="flex flex-wrap gap-1.5">
          {caps.map(([k, label]) => <CapChip key={k} cap={capOf(x.status, k)} label={t(label)} t={t} />)}
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <Button onClick={capture} disabled={busy || countdown != null || offline}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Camera className="size-4" />}
            {busy ? t("screen.capturing") : t("screen.snapshot")}
          </Button>
          <Button variant="outline" onClick={delayed} disabled={busy || countdown != null || offline}>
            <Timer className="size-4" />{t("screen.snapshotDelay")}
          </Button>
          {snap && <Button variant="ghost" onClick={() => setSnap(null)}><Eraser className="size-4" />{t("screen.clear")}</Button>}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{t("screen.privacy")}</p>
        <AnimatePresence>
          {countdown != null && (
            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} role="status"
              className="mt-3 text-sm text-secondary">{t("screen.countdown", { s: countdown })}</motion.p>
          )}
        </AnimatePresence>
        {err && <p role="alert" className="mt-3 rounded-xl border border-destructive/25 bg-destructive/10 px-3 py-2 text-xs text-destructive">{err}</p>}

        {!snap ? (
          <div className="glass-subtle mt-6 flex flex-col items-center justify-center gap-3 rounded-[20px] px-6 py-14 text-center">
            <Eye className="size-7 text-muted-foreground" strokeWidth={1.5} aria-hidden />
            <p className="max-w-sm text-sm text-muted-foreground">{t("screen.none")}</p>
          </div>
        ) : (
          <div className="mt-6 space-y-5">
            {snap.error && (
              <p role="alert" className="flex items-start gap-2 rounded-xl border border-warning/25 bg-warning/10 px-3 py-2 text-xs text-warning">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span>{snap.available ? t("screen.unavailable") + ": " : ""}{snap.error}</span>
              </p>
            )}
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <figure className="min-w-0">
                {snap.preview ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={snap.preview} alt={t("screen.preview")} className="w-full rounded-[18px] ring-1 ring-white/10" />
                ) : (
                  <div className="glass-subtle flex aspect-video items-center justify-center rounded-[18px] text-xs text-muted-foreground">—</div>
                )}
              </figure>
              <dl className="space-y-3 text-sm">
                <Field icon={<AppWindow className="size-3.5" />} label={t("screen.app")} value={snap.app} />
                <Field icon={<Monitor className="size-3.5" />} label={t("screen.window")} value={snap.window} />
                <Field label={t("screen.captured")} value={fmtTime(snap.captured_at)} />
                <Field label={t("screen.status")} value={[
                  snap.timings.capture_ms != null && `capture ${fmtMs(snap.timings.capture_ms)}`,
                  snap.timings.ocr_ms != null && `OCR ${fmtMs(snap.timings.ocr_ms)}`,
                  snap.timings.ax_ms != null && `AX ${fmtMs(snap.timings.ax_ms)}`,
                ].filter(Boolean).join(" · ") || "—"} />
              </dl>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <ListBox title={t("screen.ocr")} icon={<ScanText className="size-3.5" aria-hidden />} state={snap.ocr.state} t={t}
                items={snap.ocr.lines.map((o) => ({ main: o.text, side: `${Math.round(o.confidence * 100)}%` }))} />
              <ListBox title={t("screen.elements")} icon={<AppWindow className="size-3.5" aria-hidden />} state={snap.ax.state} t={t}
                items={snap.ax.elements.map((e) => ({ main: e.name || "—", side: e.role.replace(/^AX/, ""), dim: !e.enabled }))} />
            </div>
          </div>
        )}
      </GlassPanel>

      <div className="flex min-w-0 flex-col gap-4">
        <GlassPanel className="p-5">
          <PanelTitle>{t("screen.button")}</PanelTitle>
          <p className="text-sm leading-relaxed text-muted-foreground">{t("screen.desc")}</p>
          <p className="mt-2 text-xs text-faint">{t("screen.limits")}</p>
          {noVision && (
            <p role="alert" className="mt-3 rounded-xl border border-warning/25 bg-warning/10 px-3 py-2 text-xs text-warning">{t("screen.noVision")}</p>
          )}
          <Button className="mt-4 w-full" disabled={x.busy || offline} onClick={() => x.run(prompt, lang, "C")}>
            <Eye className="size-4" />{t("screen.button")}
          </Button>
          {x.current?.instruction === prompt && x.current.status !== "running" && (
            <div className="glass-subtle mt-4 rounded-[18px] p-4">
              <p className="mb-1 text-[11px] text-muted-foreground">{t("screen.lastAnswer")}</p>
              <p className="text-sm leading-relaxed" lang={x.current.language}>{x.current.final_message}</p>
            </div>
          )}
        </GlassPanel>
        <CurrentTaskPanel task={x.current} lang={lang} t={t} activeStep={x.activeStep}
          awaiting={x.phase === "awaiting_confirmation" && x.confirmation?.task_id === x.current?.id} />
      </div>
    </div>
  );
}

function Field({ label, value, icon }: { label: string; value: string | null | undefined; icon?: React.ReactNode }) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground">{icon}{label}</dt>
      <dd className="mt-0.5 break-words text-foreground">{value || "—"}</dd>
    </div>
  );
}

function ListBox({ title, icon, items, state, t }: {
  title: string; icon: React.ReactNode; items: { main: string; side?: string; dim?: boolean }[]; state: Capability["state"]; t: T;
}) {
  return (
    <div className="glass-subtle min-w-0 rounded-[18px] p-3.5">
      <p className="mb-2 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">{icon}{title}</span>
        <span>{items.length ? items.length : t(`cap.${state}`)}</span>
      </p>
      {!items.length ? <p className="py-3 text-center text-xs text-faint">{t("screen.noItems")}</p> : (
        <ul className="scroll-soft max-h-64 space-y-1 overflow-y-auto pr-1">
          {items.map((it, i) => (
            <li key={i} className={cn("flex items-baseline justify-between gap-3 text-xs", it.dim && "opacity-50")}>
              <span className="min-w-0 truncate text-foreground/90" title={it.main}>{it.main}</span>
              {it.side && <span className="shrink-0 font-mono text-[10px] text-faint">{it.side}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
