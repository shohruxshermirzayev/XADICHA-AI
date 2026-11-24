"use client";

import { Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import type { Lang } from "@/lib/i18n";
import type { T } from "@/lib/use-lang";
import { cn } from "@/lib/utils";
import type { Mode, Task, useXadicha } from "@/lib/xadicha";
import { CurrentTaskPanel } from "./conversation";
import { GlassPanel, PanelTitle } from "./glass";
import { Button, TaskStatus, formatTime, latency } from "./ui";

type X = ReturnType<typeof useXadicha>;
interface L { lang: Lang; setLang: (l: Lang) => void; t: T }

/* ---------------- Boshqaruv paneli ---------------- */

function breakdown(tasks: Task[], key: (t: Task) => string) {
  const m = new Map<string, { n: number; ok: number; done: number }>();
  for (const t of tasks) {
    if (t.status === "running") continue;
    const k = key(t) || "—";
    const r = m.get(k) ?? { n: 0, ok: 0, done: 0 };
    r.n++;
    if (t.status === "success") r.ok++;
    if (t.status === "success" || t.status === "failed") r.done++;
    m.set(k, r);
  }
  return [...m.entries()].sort((a, b) => b[1].n - a[1].n);
}

function Breakdown({ title, rows, t, label }: { title: string; rows: ReturnType<typeof breakdown>; t: T; label?: (k: string) => string }) {
  const max = Math.max(1, ...rows.map(([, r]) => r.n));
  return (
    <GlassPanel className="p-5">
      <PanelTitle>{title}</PanelTitle>
      {!rows.length ? <p className="text-sm text-muted-foreground">{t("dash.noData")}</p> : (
        <ul className="space-y-3">
          {rows.map(([k, r]) => (
            <li key={k} className="text-sm">
              <div className="flex justify-between gap-2"><span>{label ? label(k) : k}</span>
                <span className="text-xs tabular-nums text-muted-foreground">{r.n} · TSR {r.done ? `${Math.round((r.ok / r.done) * 100)}%` : "—"}</span></div>
              <div className="mt-1.5 h-1.5 rounded-full bg-white/[0.05]">
                <div className="h-full rounded-full bg-gradient-to-r from-primary to-secondary" style={{ width: `${(r.n / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}

function StatCard({ label, value, sub, ok }: { label: string; value: string; sub?: string; ok?: boolean | null }) {
  return (
    <GlassPanel className="p-5">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        {label}
        <span className={cn("size-2 rounded-full", ok ? "bg-success shadow-[0_0_10px_rgb(52_211_153/0.7)]" : ok === false ? "bg-destructive" : "bg-white/20")} />
      </div>
      <p className="mt-3 truncate text-2xl font-semibold tracking-tight">{value}</p>
      {sub && <p className="mt-0.5 truncate text-xs text-muted-foreground">{sub}</p>}
    </GlassPanel>
  );
}

export function DashboardView({ x, l }: { x: X; l: L }) {
  const { t, lang } = l;
  const s = x.status;
  const recent = x.tasks.slice(0, 6);
  const byLang = useMemo(() => breakdown(x.tasks, (k) => k.language.toUpperCase()), [x.tasks]);
  const byMode = useMemo(() => breakdown(x.tasks, (k) => k.mode), [x.tasks]);
  return (
    <div className="space-y-4">
      <p className="px-1 text-xs text-muted-foreground">{t("dash.live")}</p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label={t("dash.assistant")} value={x.online ? t(`phase.${x.phase}`) : t("dash.offline")} ok={x.online} />
        <StatCard label={t("dash.model")} value={s ? `${s.provider.name}` : "—"} sub={s?.provider.detail !== "ok" ? s?.provider.detail : String(s?.config.model ?? "")} ok={s?.provider.ok} />
        <StatCard label={t("dash.platform")} value={s?.os ?? "—"} sub={s ? `${t("dash.adapter")}: ${s.adapter}` : undefined} ok={!!s} />
        <StatCard label={t("dash.tsr")} value={s?.stats.success_rate != null ? `${s.stats.success_rate}%` : "—"}
          sub={s ? t("dash.tasksOf", { a: s.stats.success, b: s.stats.success + s.stats.failed }) : undefined} ok={s ? (s.stats.success_rate ?? 0) >= 50 : null} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Breakdown title={t("dash.byLang")} rows={byLang} t={t} />
        <Breakdown title={t("dash.byMode")} rows={byMode} t={t} label={(k) => (["A", "B", "C"].includes(k) ? `${k} — ${t(`mode.${k as Mode}`)}` : k)} />
      </div>
      <GlassPanel className="p-5">
        <PanelTitle hint={t("dash.count", { n: x.tasks.length })}>{t("dash.recent")}</PanelTitle>
        <TaskTable tasks={recent} lang={lang} t={t} />
      </GlassPanel>
    </div>
  );
}

/* ---------------- Tarix ---------------- */

export function TaskTable({ tasks, onSelect, selected, lang, t }: {
  tasks: Task[]; onSelect?: (task: Task) => void; selected?: string; lang: Lang; t: T;
}) {
  if (!tasks.length) return <p className="py-10 text-center text-sm text-muted-foreground">{t("table.empty")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="pb-2.5 font-medium">{t("table.command")}</th><th scope="col" className="pb-2.5 font-medium">{t("table.mode")}</th>
            <th scope="col" className="pb-2.5 font-medium">{t("table.status")}</th><th scope="col" className="pb-2.5 font-medium">{t("table.steps")}</th>
            <th scope="col" className="pb-2.5 font-medium">{t("table.time")}</th><th scope="col" className="pb-2.5 text-right font-medium">{t("table.date")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.05]">
          {tasks.map((task) => (
            <tr key={task.id} className={cn("transition-colors", onSelect && "hover:bg-white/[0.03]", selected === task.id && "bg-white/[0.05]")}>
              <td className="max-w-[340px] truncate py-3 pr-3" lang={task.language}>
                {onSelect ? (
                  <button type="button" onClick={() => onSelect(task)} className="max-w-full truncate text-left hover:text-secondary focus-visible:outline-2 focus-visible:outline-ring">{task.instruction}</button>
                ) : task.instruction}
              </td>
              <td className="py-3 font-mono text-xs text-muted-foreground">{task.mode}</td>
              <td className="py-3"><TaskStatus status={task.status} t={t} /></td>
              <td className="py-3 tabular-nums">{task.steps.length}</td>
              <td className="py-3 tabular-nums">{latency(task)}</td>
              <td className="py-3 text-right text-xs text-muted-foreground">{formatTime(task.started_at, lang)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HistoryView({ x, l }: { x: X; l: L }) {
  const { t, lang } = l;
  const [selected, setSelected] = useState<Task | null>(null);
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <GlassPanel className="min-w-0 p-5">
        <PanelTitle hint={
          <Button variant="ghost" className="h-8 px-3 text-xs" onClick={() => { if (confirm(t("history.clearConfirm"))) x.clearHistory(); }}>
            <Trash2 className="size-3.5" />{t("history.clear")}
          </Button>}>{t("history.title")}</PanelTitle>
        <TaskTable tasks={x.tasks} onSelect={setSelected} selected={selected?.id} lang={lang} t={t} />
      </GlassPanel>
      <CurrentTaskPanel task={selected} lang={lang} t={t} title={t("table.command")} />
    </div>
  );
}

/* ---------------- Tadqiqot va baholash ---------------- */

export function ResearchView({ x, l }: { x: X; l: L }) {
  const { t } = l;
  const rows = useMemo(() => (["A", "B", "C"] as Mode[]).map((m) => {
    const ts = x.tasks.filter((k) => k.mode === m && k.status !== "running");
    const done = ts.filter((k) => k.status === "success" || k.status === "failed");
    const ok = ts.filter((k) => k.status === "success").length;
    const lat = ts.filter((k) => k.finished_at).map((k) => (k.finished_at! - k.started_at) * 1000);
    const rec = ts.reduce((a, k) => a + k.recoveries, 0);
    const failedSteps = ts.reduce((a, k) => a + k.steps.filter((s) => s.status === "failed").length, 0);
    return {
      m, n: ts.length,
      tsr: done.length ? (ok / done.length) * 100 : null,
      lat: lat.length ? lat.reduce((a, b) => a + b, 0) / lat.length : null,
      recovery: failedSteps ? (Math.min(rec, failedSteps) / failedSteps) * 100 : null,
    };
  }), [x.tasks]);

  return (
    <div className="space-y-4">
      <GlassPanel className="p-5 sm:p-6">
        <PanelTitle hint={t("research.hint")}>{t("research.title")}</PanelTitle>
        <div className="grid gap-3 md:grid-cols-3">
          {rows.map((r) => (
            <div key={r.m} className="glass-subtle rounded-[20px] p-4">
              <p className="text-xs text-muted-foreground">{r.m} — {t(`mode.${r.m}`)}</p>
              <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">{r.tsr == null ? "—" : `${r.tsr.toFixed(1)}%`}</p>
              <p className="text-[11px] text-faint">TSR</p>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
                <div><dt className="text-faint">{t("research.tasks")}</dt><dd className="mt-0.5 tabular-nums">{r.n}</dd></div>
                <div><dt className="text-faint">{t("research.latency")}</dt><dd className="mt-0.5 tabular-nums">{r.lat == null ? "—" : `${(r.lat / 1000).toFixed(2)} s`}</dd></div>
                <div><dt className="text-faint">{t("research.recovery")}</dt><dd className="mt-0.5 tabular-nums">{r.recovery == null ? "—" : `${r.recovery.toFixed(0)}%`}</dd></div>
              </dl>
            </div>
          ))}
        </div>
        <p className="mt-5 text-xs leading-relaxed text-muted-foreground">{t("research.note")}</p>
      </GlassPanel>
    </div>
  );
}
