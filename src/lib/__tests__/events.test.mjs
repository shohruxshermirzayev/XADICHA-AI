import assert from "node:assert/strict";
import { test } from "node:test";
import { parseEvent, reconnectDelay, secondsLeft, upsertStep } from "../events.ts";

test("malformed WebSocket payloads are rejected, not thrown", () => {
  for (const raw of ["{not json", "", "null", "42", "[1,2]", '"text"', '{"no":"type"}', '{"type":5}',
    '{"type":"unknown_event"}', undefined, null, new ArrayBuffer(4)]) {
    assert.equal(parseEvent(raw), null, String(raw));
  }
});

test("events with missing required fields are rejected", () => {
  assert.equal(parseEvent('{"type":"task_started"}'), null);
  assert.equal(parseEvent('{"type":"task_started","task":{"id":"a"}}'), null);   // steps yo'q
  assert.equal(parseEvent('{"type":"step_finished","task_id":"a","step":{}}'), null);
  assert.equal(parseEvent('{"type":"listening","state":"dancing"}'), null);
  assert.equal(parseEvent('{"type":"mic_level","level":"loud"}'), null);
  assert.equal(parseEvent('{"type":"confirm_request","task_id":"a"}'), null);
  assert.equal(parseEvent('{"type":"error"}'), null);
});

test("valid events pass through", () => {
  assert.equal(parseEvent('{"type":"pong"}').type, "pong");
  assert.equal(parseEvent('{"type":"listening","state":"recording"}').state, "recording");
  assert.equal(parseEvent('{"type":"mic_level","level":0.4}').level, 0.4);
  const e = parseEvent('{"type":"task_started","task":{"id":"t1","steps":[]}}');
  assert.equal(e.task.id, "t1");
});

test("upsertStep replaces by index, keeps order, ignores other tasks", () => {
  const task = { id: "t", status: "running", steps: [{ index: 2, s: "b" }] };
  const a = upsertStep(task, "t", { index: 1, s: "a" });
  assert.deepEqual(a.steps.map((s) => s.index), [1, 2]);
  const b = upsertStep(a, "t", { index: 2, s: "B" });
  assert.equal(b.steps[1].s, "B");
  assert.equal(b.steps.length, 2);
  assert.equal(upsertStep(task, "other", { index: 9 }), task);
  assert.equal(upsertStep(null, "t", { index: 1 }), null);
});

test("reconnect delay backs off exponentially and is capped", () => {
  const mid = () => 0.5;   // siljishsiz
  assert.equal(reconnectDelay(0, mid), 1000);
  assert.equal(reconnectDelay(1, mid), 2000);
  assert.equal(reconnectDelay(3, mid), 8000);
  assert.equal(reconnectDelay(50, mid), 30000);
  assert.ok(reconnectDelay(0, () => 0) >= 800 && reconnectDelay(0, () => 1) <= 1200);
});

test("confirmation countdown", () => {
  assert.equal(secondsLeft(undefined, 0), null);
  assert.equal(secondsLeft(100, 90_000), 10);
  assert.equal(secondsLeft(100, 100_500), 0);
});

test("voice events: clarify and voice_result are validated", () => {
  assert.equal(parseEvent('{"type":"clarify","text":"Staffar in och","analysis":{"needs_clarification":true}}').type, "clarify");
  assert.equal(parseEvent('{"type":"clarify","text":"x"}'), null);
  assert.equal(parseEvent('{"type":"voice_result","status":"empty"}').status, "empty");
  assert.equal(parseEvent('{"type":"voice_result","status":"hacked"}'), null);
});
