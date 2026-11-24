// Orb holati va vazifa vaqt chizig'i faqat haqiqiy backend holatidan kelib chiqadi (simulyatsiya — backend'siz).
import assert from "node:assert/strict";
import { test } from "node:test";
import { fmtMs, orbState, outcomeFlash, timeline } from "../presence.ts";
import { applyEvent, initialState } from "../state.ts";

const base = { online: true, listening: "idle", phase: "idle", busy: false, current: null };
const step = (index, status = "executed", duration_ms = 0) => ({ index, status, duration_ms, action: { type: "open_app" }, risk: "low", detail: "", verified: null, expected_outcome: "" });
const task = (status = "running", steps = [], extra = {}) => ({ id: "t", status, steps, instruction: "x", language: "uz", started_at: 100, finished_at: null, ...extra });

test("idle when nothing runs — never 'thinking' without a request", () => {
  assert.equal(orbState(base), "idle");
  assert.equal(orbState({ ...base, current: task("success") }), "idle");
});

test("each real state maps to a distinct orb state", () => {
  assert.equal(orbState({ ...base, online: false, busy: true }), "offline");
  assert.equal(orbState({ ...base, listening: "recording" }), "listening");
  assert.equal(orbState({ ...base, listening: "transcribing" }), "processing");
  assert.equal(orbState({ ...base, busy: true, phase: "awaiting_confirmation" }), "awaiting");
  assert.equal(orbState({ ...base, busy: true, phase: "speaking" }), "speaking");
  assert.equal(orbState({ ...base, busy: true, phase: "running", current: task("running") }), "thinking");
  assert.equal(orbState({ ...base, busy: true, phase: "running", current: task("running", [step(1)]) }), "executing");
  assert.equal(orbState({ ...base, flash: "interrupted" }), "interrupted");
  assert.equal(orbState({ ...base, flash: "error" }), "error");
});

test("outcome flash only for failed/cancelled", () => {
  assert.equal(outcomeFlash(task("failed")), "error");
  assert.equal(outcomeFlash(task("cancelled")), "interrupted");
  assert.equal(outcomeFlash(task("success")), null);
  assert.equal(outcomeFlash(null), null);
});

test("timeline: planning active before first step, final pending, no fabricated durations", () => {
  const rows = timeline(task("running"));
  assert.deepEqual(rows.map((r) => [r.kind, r.state]), [["received", "done"], ["planning", "active"], ["final", "pending"]]);
  assert.equal(rows.at(-1).ms, undefined);
});

test("timeline: active step, verifying, verified, failed, denied, awaiting", () => {
  const t = task("running", [step(1, "verified", 420), step(2, "executed"), step(3, "executed")]);
  const rows = timeline(t, { activeStep: 3, awaiting: true });
  const s = rows.filter((r) => r.step).map((r) => [r.step.index, r.kind, r.state, r.ms]);
  assert.deepEqual(s, [[1, "step", "done", 420], [2, "verifying", "active", undefined], [3, "step", "active", undefined]]);
  assert.equal(rows.find((r) => r.kind === "awaiting").state, "warn");
  const done = timeline(task("failed", [step(1, "failed", 30), step(2, "denied")], { finished_at: 101.25 }));
  assert.deepEqual(done.filter((r) => r.step).map((r) => r.state), ["failed", "warn"]);
  assert.equal(done.at(-1).state, "failed");
  assert.equal(done.at(-1).ms, 1250);
});

test("finished task: executed steps are done (not stuck verifying)", () => {
  const rows = timeline(task("success", [step(1, "executed", 12)], { finished_at: 100.5 }));
  assert.deepEqual(rows.map((r) => r.state), ["done", "done", "done", "done"]);
});

test("state tracks the active step from step_started to step_finished", () => {
  let s = applyEvent(initialState, { type: "task_started", seq: 1, task: task("running") });
  s = applyEvent(s, { type: "step_started", seq: 2, task_id: "t", step: step(1) });
  assert.equal(s.activeStep, 1);
  s = applyEvent(s, { type: "step_finished", seq: 3, task_id: "t", step: step(1, "executed", 50) });
  assert.equal(s.activeStep, null);
});

test("fmtMs", () => {
  assert.equal(fmtMs(850), "850 ms");
  assert.equal(fmtMs(1430), "1.4 s");
  assert.equal(fmtMs(null), "—");
});
