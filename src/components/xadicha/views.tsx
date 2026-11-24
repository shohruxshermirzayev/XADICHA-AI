"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, Monitor, Octagon, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { describeAction, type ChatMessage, type Lang, type Mode, type Status, type Task, type useXadicha } from "@/lib/xadicha";
import { Button, Card, CardTitle, Dot, RiskBadge, StepIcon, TaskStatus, formatTime, latency } from "./ui";
import { VoiceOrb } from "./voice-orb";

type X = ReturnType<typeof useXadicha>;

const LANGS: { id: Lang; label: string }[] = [
  { id: "uz", label: "O'zbek" },
  { id: "ru", label: "Русский" },
  { id: "en", label: "English" },
];

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "C", label: "Multimodal", hint: "Ekran + tekshiruv + tiklanish (taklif etilgan usul)" },
  { id: "B", label: "LLM reja", hint: "Ekransiz, bir martalik reja" },
  { id: "A", label: "Faqat ovoz", hint: "Qoida asosida, bitta harakat" },
];

/* ---------------- Ovozli yordamchi (asosiy ekran) ---------------- */

export function AssistantView({ x }: { x: X }) {
  const [lang, setLang] = useState<Lang>("uz");
  const [mode, setMode] = useState<Mode>("C");
  const [text, setText] = useState("");
  const busy = !!x.status?.busy || x.current?.status === "running";
  const offline = x.online === false;

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || busy || offline) return;
    setText("");
    // Kirill yozuvi — ruscha buyruq; javob ham ruscha bo'ladi
    x.run(t, /[\u0400-\u04FF]/.test(t) ? "ru" : lang, mode);
  };

  const toggleVoice = async () => {
    if (x.listening === "recording") {
      const r = await x.stopListening();
      if (r?.text && r.supported) x.run(r.text, r.language, mode, true);
    } else {
      x.startListening(lang);
    }
  };

  // Space — gapirishni boshlash/to'xtatish (matn maydonida yozayotganda emas)
  const toggleRef = useRef(toggleVoice);
  useEffect(() => {
    toggleRef.current = toggleVoice;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.code !== "Space" || e.repeat || el.closest("input, textarea, select, button, [contenteditable]")) return;
      e.preventDefault();
      if (!offline && !busy) toggleRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [offline, busy]);

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card className="flex min-h-[560px] flex-col p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
          <div role="radiogroup" aria-label="Til" className="flex gap-1 rounded-lg bg-muted p-1">
            {LANGS.map((l) => (
              <button key={l.id} role="radio" aria-checked={lang === l.id} onClick={() => setLang(l.id)}
                className={cn("rounded-md px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring",
                  lang === l.id ? "bg-card text-foreground shadow" : "text-muted-foreground hover:text-foreground")}>
                {l.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Rejim
            <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} title={MODES.find((m) => m.id === mode)?.hint}
              className="rounded-md border border-border bg-muted px-2 py-1 text-xs text-foreground focus-visible:outline-2 focus-visible:outline-ring">
              {MODES.map((m) => <option key={m.id} value={m.id}>{m.id} — {m.label}</option>)}
            </select>
          </label>
        </div>

        <Conversation messages={x.messages} lang={lang} onExample={(t) => !busy && !offline && x.run(t, lang, mode)} />

        <div className="flex flex-col items-center gap-2 px-5 pb-2">
          <VoiceOrb state={x.listening} busy={busy} disabled={offline || busy} onToggle={toggleVoice} />
          <p className="h-5 text-xs text-muted-foreground" aria-live="polite">
            {offline ? "Backend ishlamayapti" : x.listening === "recording" ? "Tinglayapman… tugatganda yana bosing"
              : x.listening === "transcribing" ? "Matnga aylantirilmoqda…" : busy ? "Vazifa bajarilmoqda…" : "Belgini bosing yoki Space — va gapiring"}
          </p>
        </div>

        <form onSubmit={submit} className="flex gap-2 border-t border-border p-3">
          <label htmlFor="cmd" className="sr-only">Buyruq</label>
          <input id="cmd" value={text} onChange={(e) => setText(e.target.value)} disabled={offline}
            placeholder={lang === "ru" ? "Например: Открой Notes" : lang === "en" ? "e.g. Open Calculator" : "Masalan: Safari ni och"}
            className="h-10 flex-1 rounded-lg border border-input bg-muted/60 px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring" />
          {busy ? (
            <Button type="button" variant="danger" onClick={x.stop} className="h-10"><Octagon className="size-4" />To&apos;xtatish</Button>
          ) : (
            <Button type="submit" disabled={!text.trim() || offline} className="h-10" aria-label="Yuborish"><ArrowUp className="size-4" /></Button>
          )}
        </form>
      </Card>

      <LiveTask task={x.current} />
    </div>
  );
}

const EXAMPLES: Record<Lang, string[]> = {
  uz: ["Safari ni och", "YouTube'da o'zbek musiqasini qidir", "Desktopda \"Hisobot\" papka yarat", "Ekranda nima bor?"],
  ru: ["Открой Notes", "Найди погоду в Ташкенте", "Открой kun.uz"],
  en: ["Open Calculator", "Search Google for Tashkent weather", "What is on my screen?"],
};

function Conversation({ messages, lang, onExample }: {
  messages: ChatMessage[]; lang: Lang; onExample: (text: string) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  if (!messages.length) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
        <p className="text-lg font-medium">Assalomu alaykum, men XADICHA.</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Ovoz bilan yoki yozib buyruq bering — ilovalarni ochaman, ekranni ko&apos;rib harakat qilaman va natijani tekshiraman.
        </p>
        <div className="mt-4 flex max-w-lg flex-wrap justify-center gap-2">
          {EXAMPLES[lang].map((t) => (
            <button key={t} onClick={() => onExample(t)}
              className="rounded-full border border-border bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
              {t}
            </button>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4" aria-live="polite">
      <AnimatePresence initial={false}>
        {messages.map((m) => (
          <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
            className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cn("max-w-[80%] rounded-2xl px-4 py-2.5 text-sm",
              m.role === "user" && "rounded-br-md bg-primary text-primary-foreground",
              m.role === "assistant" && "rounded-bl-md bg-muted",
              m.role === "system" && "border border-destructive/30 bg-destructive/10 text-destructive")}>
              {m.text}
              {m.role === "assistant" && m.status && m.status !== "success" && (
                <div className="mt-1"><TaskStatus status={m.status} /></div>
              )}
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
      <div ref={end} />
    </div>
  );
}

/* ---------------- Joriy vazifa (Task Manager) ---------------- */

export function LiveTask({ task }: { task: Task | null }) {
  return (
    <Card className="h-fit">
      <CardTitle hint={task ? <TaskStatus status={task.status} /> : null}>Joriy vazifa</CardTitle>
      {!task ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Hali vazifa yo&apos;q. Buyruq bering — rejasi va har bir qadam shu yerda ko&apos;rinadi.</p>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="text-sm font-medium">{task.instruction}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Rejim {task.mode} · {task.language.toUpperCase()} {task.intent && `· ${task.intent}`}
              {task.planner === "rules" && " · tezkor yo'l (modelsiz)"}
            </p>
          </div>
          <ol className="relative space-y-3 border-l border-border pl-5">
            {task.steps.length === 0 && task.status === "running" && (
              <li className="text-xs text-muted-foreground">Ekran tahlil qilinmoqda va reja tuzilmoqda…</li>
            )}
            {task.steps.map((s) => (
              <motion.li key={s.index} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} className="relative">
                <span className="absolute top-0.5 -left-[27px] rounded-full bg-card"><StepIcon step={s} /></span>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm break-words">{describeAction(s.action)}</p>
                  <RiskBadge risk={s.risk} />
                </div>
                {s.expected_outcome && <p className="mt-0.5 text-xs text-muted-foreground">Kutilgan: {s.expected_outcome}</p>}
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {s.status === "verified" ? "Tekshiruv: tasdiqlandi" : s.status === "executed" ? "Tekshirilmoqda…"
                    : s.status === "denied" ? `Bajarilmadi: ${s.detail}` : `Xato: ${s.detail}`} · {s.duration_ms} ms
                </p>
              </motion.li>
            ))}
          </ol>
          {task.status !== "running" && (
            <div className="space-y-3 border-t border-border pt-3">
              <dl className="grid grid-cols-3 gap-2 text-center">
                <Metric label="Kechikish" value={latency(task)} />
                <Metric label="Model chaqiruvi" value={String(task.llm_calls)} />
                <Metric label="Tiklanish" value={String(task.recoveries)} />
              </dl>
              {task.timings && <TimingBar t={task.timings} />}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/** Kechikish qayerga ketganini ko'rsatadi: ekran surati, model, bajarish. */
function TimingBar({ t }: { t: { screen_ms: number; llm_ms: number; exec_ms: number } }) {
  const total = t.screen_ms + t.llm_ms + t.exec_ms;
  if (!total) return null;
  const parts = [
    { k: "Model", v: t.llm_ms, c: "bg-primary" },
    { k: "Ekran", v: t.screen_ms, c: "bg-secondary" },
    { k: "Bajarish", v: t.exec_ms, c: "bg-success" },
  ];
  const fmt = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
  return (
    <div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-muted" role="img"
        aria-label={parts.map((p) => `${p.k} ${fmt(p.v)}`).join(", ")}>
        {parts.map((p) => p.v > 0 && <div key={p.k} className={p.c} style={{ width: `${(p.v / total) * 100}%` }} />)}
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-muted-foreground">
        {parts.map((p) => (
          <span key={p.k} className="inline-flex items-center gap-1"><span className={cn("size-1.5 rounded-full", p.c)} />{p.k} {fmt(p.v)}</span>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}

/* ---------------- Dashboard ---------------- */

export function DashboardView({ x }: { x: X }) {
  const s = x.status;
  const recent = x.tasks.slice(0, 6);
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Yordamchi" value={x.online ? (s?.busy ? "Band" : "Tayyor") : "O'chiq"} ok={x.online} />
        <StatCard label="AI model" value={s ? `${s.provider.name}` : "—"} sub={s?.provider.detail !== "ok" ? s?.provider.detail : String(s?.config.model ?? "")} ok={s?.provider.ok} />
        <StatCard label="Operatsion tizim" value={s?.os ?? "—"} sub={s ? `adapter: ${s.adapter}` : undefined} ok={!!s} />
        <StatCard label="Muvaffaqiyat (TSR)" value={s?.stats.success_rate != null ? `${s.stats.success_rate}%` : "—"}
          sub={s ? `${s.stats.success} / ${s.stats.success + s.stats.failed} vazifa` : undefined} ok={s ? (s.stats.success_rate ?? 0) >= 50 : null} />
      </div>
      <Card>
        <CardTitle hint={`${x.tasks.length} ta`}>So&apos;nggi vazifalar</CardTitle>
        <TaskTable tasks={recent} />
      </Card>
    </div>
  );
}

function StatCard({ label, value, sub, ok }: { label: string; value: string; sub?: string; ok?: boolean | null }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-xs text-muted-foreground">{label}<Dot ok={ok} /></div>
      <p className="mt-2 truncate text-xl font-semibold tracking-tight">{value}</p>
      {sub && <p className="mt-0.5 truncate text-xs text-muted-foreground">{sub}</p>}
    </Card>
  );
}

/* ---------------- Tarix ---------------- */

export function TaskTable({ tasks, onSelect }: { tasks: Task[]; onSelect?: (t: Task) => void }) {
  if (!tasks.length) return <p className="py-8 text-center text-sm text-muted-foreground">Tarix bo&apos;sh.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="pb-2 font-medium">Buyruq</th><th className="pb-2 font-medium">Rejim</th>
            <th className="pb-2 font-medium">Holat</th><th className="pb-2 font-medium">Qadam</th>
            <th className="pb-2 font-medium">Vaqt</th><th className="pb-2 text-right font-medium">Sana</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {tasks.map((t) => (
            <tr key={t.id} onClick={() => onSelect?.(t)} className={cn(onSelect && "cursor-pointer hover:bg-accent/40")}>
              <td className="max-w-[320px] truncate py-2.5 pr-3">{t.instruction}</td>
              <td className="py-2.5 font-mono text-xs">{t.mode}</td>
              <td className="py-2.5"><TaskStatus status={t.status} /></td>
              <td className="py-2.5 tabular-nums">{t.steps.length}</td>
              <td className="py-2.5 tabular-nums">{latency(t)}</td>
              <td className="py-2.5 text-right text-xs text-muted-foreground">{formatTime(t.started_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HistoryView({ x }: { x: X }) {
  const [selected, setSelected] = useState<Task | null>(null);
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card>
        <CardTitle hint={
          <Button variant="ghost" className="h-7 px-2 text-xs" onClick={() => { if (confirm("Butun tarix o'chirilsinmi?")) x.clearHistory(); }}>
            <Trash2 className="size-3.5" />Tozalash
          </Button>}>Vazifalar tarixi</CardTitle>
        <TaskTable tasks={x.tasks} onSelect={setSelected} />
      </Card>
      <LiveTask task={selected} />
    </div>
  );
}

/* ---------------- Tadqiqot va baholash ---------------- */

export function ResearchView({ x }: { x: X }) {
  const rows = useMemo(() => (["A", "B", "C"] as Mode[]).map((m) => {
    const ts = x.tasks.filter((t) => t.mode === m && t.status !== "running");
    const done = ts.filter((t) => t.status === "success" || t.status === "failed");
    const ok = ts.filter((t) => t.status === "success").length;
    const lat = ts.filter((t) => t.finished_at).map((t) => (t.finished_at! - t.started_at) * 1000);
    const rec = ts.reduce((a, t) => a + t.recoveries, 0);
    const failedSteps = ts.reduce((a, t) => a + t.steps.filter((s) => s.status === "failed").length, 0);
    return {
      m, n: ts.length,
      tsr: done.length ? (ok / done.length) * 100 : null,
      lat: lat.length ? lat.reduce((a, b) => a + b, 0) / lat.length : null,
      recovery: failedSteps ? (Math.min(rec, failedSteps) / failedSteps) * 100 : null,
    };
  }), [x.tasks]);

  return (
    <div className="space-y-5">
      <Card>
        <CardTitle hint="Faqat haqiqatda bajarilgan vazifalar asosida">Rejimlar bo&apos;yicha natijalar</CardTitle>
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th className="pb-2 font-medium">Rejim</th><th className="pb-2 font-medium">Vazifalar</th>
              <th className="pb-2 font-medium">TSR</th><th className="pb-2 font-medium">O&apos;rtacha kechikish</th>
              <th className="pb-2 font-medium">Tiklanish (taxminiy)</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((r) => (
              <tr key={r.m}>
                <td className="py-2.5">{r.m} — {MODES.find((x) => x.id === r.m)?.label}</td>
                <td className="py-2.5 tabular-nums">{r.n}</td>
                <td className="py-2.5 tabular-nums">{r.tsr == null ? "—" : `${r.tsr.toFixed(1)}%`}</td>
                <td className="py-2.5 tabular-nums">{r.lat == null ? "—" : `${(r.lat / 1000).toFixed(2)} s`}</td>
                <td className="py-2.5 tabular-nums">{r.recovery == null ? "—" : `${r.recovery.toFixed(0)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-4 text-xs text-muted-foreground">
          TSR = muvaffaqiyatli vazifalar / yakunlangan vazifalar × 100%. Bu jonli statistika; dissertatsiya uchun rasmiy
          natijalar benchmark skripti orqali (30+ vazifa, 3 til) olinadi.
        </p>
      </Card>
    </div>
  );
}

/* ---------------- Sozlamalar ---------------- */

export function SettingsView({ status }: { status: Status | null }) {
  if (!status) return <Card><p className="text-sm text-muted-foreground">Backend bilan aloqa yo&apos;q.</p></Card>;
  const c = status.config;
  const rows: [string, React.ReactNode][] = [
    ["AI provayder", `${status.provider.name} — ${c.model}`],
    ["Model holati", <span key="h" className="inline-flex items-center gap-2"><Dot ok={status.provider.ok} />{status.provider.detail}</span>],
    ["Ekranni ko'rish", status.provider.vision ? "Bor" : "Yo'q"],
    ["Nutqni aniqlash", `${c.whisper_model} · ${status.stt_engine === "mlx" ? "MLX (Apple GPU)" : status.stt_engine ?? "—"}`],
    ["Tezkor yo'l", c.fast_path ? "yoqilgan (oddiy buyruqlar modelsiz)" : "o'chirilgan"],
    ["Ovoz", `${c.tts_engine} · ${c.tts_enabled ? "yoqilgan" : "o'chirilgan"}`],
    ["Ovoz mavjudligi", (["uz", "ru", "en"] as Lang[]).map((l) => `${l}: ${status.tts[l] ? "✓" : "—"}`).join("  ")],
    ["Tasdiq so'raladi", `${c.confirm_risk} xavfdan boshlab`],
    ["Qadamlar chegarasi", String(c.max_steps)],
    ["Fayl amallari papkasi", String(c.workspace)],
    ["Accessibility ruxsati", status.permissions.accessibility == null ? "noma'lum" : status.permissions.accessibility ? "berilgan" : "berilmagan"],
  ];
  return (
    <Card className="max-w-3xl">
      <CardTitle hint="O'zgartirish: backend/.env">Sozlamalar</CardTitle>
      <dl className="divide-y divide-border">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[200px_1fr] gap-4 py-2.5 text-sm">
            <dt className="text-muted-foreground">{k}</dt><dd className="break-words">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/* ---------------- Ekran tahlili ---------------- */

export function ScreenView({ x }: { x: X }) {
  const [lang, setLang] = useState<Lang>("uz");
  const prompts: Record<Lang, string> = {
    uz: "Ekranda nima borligini qisqacha tushuntir va men keyin nima qila olishimni ayt. Hech narsani bosma.",
    ru: "Кратко опиши, что на экране, и что я могу сделать дальше. Ничего не нажимай.",
    en: "Briefly describe what is on the screen and what I can do next. Do not click anything.",
  };
  const busy = !!x.status?.busy;
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card>
        <CardTitle>Ekran tahlili</CardTitle>
        <p className="text-sm text-muted-foreground">
          XADICHA joriy ekranni ko&apos;radi va unda nima borligini tushuntiradi. Bu rejimda hech qanday harakat bajarilmaydi —
          ko&apos;zi ojiz foydalanuvchilar uchun foydali.
        </p>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <select value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label="Til"
            className="h-9 rounded-lg border border-border bg-muted px-2 text-sm">
            {LANGS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
          <Button disabled={busy || x.online === false} onClick={() => x.run(prompts[lang], lang, "C")}>
            <Monitor className="size-4" />Ekranni tasvirlab ber
          </Button>
        </div>
        {x.current?.instruction === prompts[lang] && x.current.status !== "running" && (
          <p className="mt-5 rounded-xl bg-muted p-4 text-sm leading-relaxed">{x.current.final_message}</p>
        )}
      </Card>
      <LiveTask task={x.current} />
    </div>
  );
}
