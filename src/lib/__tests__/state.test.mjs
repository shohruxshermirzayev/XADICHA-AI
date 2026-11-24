// Yagona holat modeli: hodisalar tartibi, eskirgan HTTP javoblari, qayta ulanish (simulyatsiya — backend'siz).
import assert from "node:assert/strict";
import { test } from "node:test";
import { applyEvent, applyStatus, initialState, isBusy, staleRunningTask } from "../state.ts";

const task = (id, status = "running", steps = []) => ({ id, status, steps, instruction: "x", language: "uz" });
const status = (o = {}) => ({ busy: false, phase: "idle", seq: 0, instance: "A", current_task: null,
  pending_confirmation: null, listening: "idle", ...o });

function run(events, st = initialState) {
  return events.reduce((s, e) => applyEvent(s, e), st);
}

test("header and panel agree: task finished + state idle => not busy, panel success", () => {
  let s = applyStatus(initialState, status({ seq: 1 }));
  s = run([
    { type: "state", seq: 2, busy: true, phase: "running", current_task: "t1" },
    { type: "task_started", seq: 3, task: task("t1") },
    { type: "task_finished", seq: 4, task: task("t1", "success") },
    { type: "state", seq: 5, busy: true, phase: "speaking", current_task: "t1" },
    { type: "state", seq: 6, busy: false, phase: "idle", current_task: null },
  ], s);
  assert.equal(isBusy(s), false);
  assert.equal(s.current.status, "success");
});

test("stale HTTP status (older seq, busy=true) does not overwrite newer idle event", () => {
  let s = run([
    { type: "task_finished", seq: 10, task: task("t1", "success") },
    { type: "state", seq: 11, busy: false, phase: "idle", current_task: null },
  ], applyStatus(initialState, status({ seq: 9 })));
  s = applyStatus(s, status({ seq: 10, busy: true, phase: "speaking", current_task: "t1" }));   // kech kelgan javob
  assert.equal(isBusy(s), false);
  assert.equal(s.seq, 11);
  assert.equal(s.status.phase, "speaking");   // ko'rsatish uchun saqlanadi, lekin holatni boshqarmaydi
});

test("fresh HTTP status (newer seq) is applied", () => {
  const s = applyStatus(applyStatus(initialState, status({ seq: 3 })), status({ seq: 7, busy: true, phase: "running", current_task: "t2" }));
  assert.equal(isBusy(s), true);
  assert.equal(s.currentTaskId, "t2");
});

test("duplicate or out-of-order events are ignored", () => {
  let s = run([{ type: "state", seq: 5, busy: false, phase: "idle", current_task: null }], applyStatus(initialState, status({ seq: 4 })));
  const same = applyEvent(s, { type: "state", seq: 5, busy: true, phase: "running", current_task: "x" });
  assert.equal(same, s);
  const older = applyEvent(s, { type: "task_started", seq: 3, task: task("old") });
  assert.equal(older.current, null);
});

test("backend restart (new instance, seq reset) is accepted over HTTP", () => {
  let s = applyStatus(initialState, status({ seq: 500, busy: true, phase: "running", instance: "A" }));
  s = applyStatus(s, status({ seq: 2, busy: false, phase: "idle", instance: "B" }));
  assert.equal(isBusy(s), false);
  assert.equal(s.seq, 2);
});

test("hello on reconnect resets seq and restores pending confirmation", () => {
  let s = applyStatus(initialState, status({ seq: 50, instance: "A" }));
  const conf = { id: "c1", task_id: "t9", description: "O'CHIRISH", risk: "high", reason: "" };
  s = applyEvent(s, { type: "hello", status: status({ seq: 3, instance: "B", busy: true, phase: "awaiting_confirmation", current_task: "t9", pending_confirmation: conf }) });
  assert.equal(s.seq, 3);
  assert.equal(s.confirmation.id, "c1");
  assert.equal(s.phase, "awaiting_confirmation");
});

test("same confirmation from polling keeps the same object (dialog error text survives)", () => {
  const conf = { id: "c1", task_id: "t", description: "d", risk: "high", reason: "" };
  let s = applyEvent(applyStatus(initialState, status({ seq: 1 })), { type: "confirm_request", seq: 2, ...conf });
  const before = s.confirmation;
  s = applyStatus(s, status({ seq: 3, busy: true, phase: "awaiting_confirmation", pending_confirmation: { ...conf } }));
  assert.equal(s.confirmation, before);
  s = applyEvent(s, { type: "confirm_resolved", seq: 4, id: "c1", task_id: "t" });
  assert.equal(s.confirmation, null);
});

test("panel stuck on running while backend idle is detected for re-sync", () => {
  let s = run([{ type: "task_started", seq: 2, task: task("t1") }], applyStatus(initialState, status({ seq: 1 })));
  s = applyEvent(s, { type: "state", seq: 3, busy: false, phase: "idle", current_task: null });   // task_finished yo'qolgan
  assert.equal(staleRunningTask(s), "t1");
});

test("mic level only while recording", () => {
  let s = applyEvent(applyStatus(initialState, status({ seq: 1 })), { type: "listening", seq: 2, state: "recording" });
  s = applyEvent(s, { type: "mic_level", seq: 3, level: 0.7 });
  assert.equal(s.micLevel, 0.7);
  s = applyEvent(s, { type: "listening", seq: 4, state: "transcribing" });
  assert.equal(s.micLevel, 0);
  s = applyEvent(s, { type: "mic_level", seq: 5, level: 0.9 });
  assert.equal(s.micLevel, 0);
});
