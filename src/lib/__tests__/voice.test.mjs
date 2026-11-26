// Gemini Live, STT provayderi va yangi orb holatlari — faqat haqiqiy backend hodisalaridan (simulyatsiya — backend'siz).
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseEvent } from "../events.ts";
import { orbState } from "../presence.ts";
import { applyEvent, applyStatus, initialState, liveActive } from "../state.ts";

const ev = (o) => parseEvent(JSON.stringify(o));
const run = (events, st = initialState) => events.reduce((s, e) => applyEvent(s, e), st);
const base = { online: true, listening: "idle", phase: "idle", busy: false, current: null };
const status = (o = {}) => ({ busy: false, phase: "idle", seq: 0, instance: "A", current_task: null,
  pending_confirmation: null, listening: "idle", ...o });

test("live events are validated; unknown states and malformed payloads are dropped", () => {
  assert.ok(ev({ type: "live_state", state: "listening", seq: 1 }));
  assert.equal(ev({ type: "live_state", state: "hacking", seq: 1 }), null);
  assert.equal(ev({ type: "live_transcript", role: "system", text: "x", seq: 1 }), null);
  assert.equal(ev({ type: "live_transcript", role: "user", text: 5, seq: 1 }), null);
  assert.ok(ev({ type: "live_turn", user: "salom", assistant: "salom!", seq: 1 }));
  assert.equal(ev({ type: "live_turn", user: "salom", seq: 1 }), null);
});

test("live session lifecycle drives the state; transcripts are live partials and cleared on turn end", () => {
  let st = run([
    ev({ type: "live_state", state: "connecting", seq: 1 }),
    ev({ type: "live_state", state: "listening", seq: 2 }),
    ev({ type: "live_transcript", role: "user", text: "Safari ni", seq: 3 }),
    ev({ type: "live_transcript", role: "user", text: "Safari ni och", seq: 4 }),
    ev({ type: "live_state", state: "speaking", seq: 5 }),
    ev({ type: "live_transcript", role: "assistant", text: "Ochyapman", seq: 6 }),
  ]);
  assert.ok(liveActive(st));
  assert.deepEqual(st.live, { state: "speaking", user: "Safari ni och", assistant: "Ochyapman" });
  st = run([ev({ type: "live_turn", user: "Safari ni och", assistant: "Ochyapman", seq: 7 })], st);
  assert.equal(st.live.user, "");
  st = run([ev({ type: "live_state", state: "closed", seq: 8 })], st);
  assert.equal(liveActive(st), false);
});

test("barge-in: interrupted clears the assistant partial immediately", () => {
  const st = run([
    ev({ type: "live_state", state: "speaking", seq: 1 }),
    ev({ type: "live_transcript", role: "assistant", text: "Uzun javob...", seq: 2 }),
    ev({ type: "live_state", state: "interrupted", seq: 3 }),
  ]);
  assert.equal(st.live.assistant, "");
  assert.equal(orbState({ ...base, live: st.live.state }), "interrupted");
});

test("mic level is shown during live, never when nothing listens", () => {
  let st = run([ev({ type: "mic_level", level: 0.5, seq: 1 })]);
  assert.equal(st.micLevel, 0);                              // hech kim tinglamayapti — soxta faollik yo'q
  st = run([ev({ type: "live_state", state: "listening", seq: 2 }), ev({ type: "mic_level", level: 0.4, seq: 3 })], st);
  assert.equal(st.micLevel, 0.4);
  st = run([ev({ type: "live_state", state: "error", seq: 4 })], st);
  assert.equal(st.micLevel, 0);
});

test("status says live is not active → UI stops showing a live session", () => {
  const st = run([ev({ type: "live_state", state: "listening", seq: 1 })]);
  const next = applyStatus(st, status({ seq: 5, live: { active: false, state: "closed", available: true, detail: "ok", model: "m" } }));
  assert.equal(liveActive(next), false);
});

test("orb maps real live states; connecting and reconnecting are distinct", () => {
  assert.equal(orbState({ ...base, live: "connecting" }), "connecting");
  assert.equal(orbState({ ...base, live: "reconnecting" }), "recovering");
  assert.equal(orbState({ ...base, live: "listening" }), "listening");
  assert.equal(orbState({ ...base, live: "speaking" }), "speaking");
  assert.equal(orbState({ ...base, live: "idle" }), "idle");
  assert.equal(orbState({ ...base, live: "closed" }), "idle");
});

test("searching only while a real web_search step runs; recovering only when fallback is active", () => {
  const step = (index, type) => ({ index, status: "executed", duration_ms: 0, action: { type }, risk: "low", detail: "" });
  const running = { id: "t", status: "running", steps: [step(1, "web_search")], instruction: "x", language: "uz" };
  assert.equal(orbState({ ...base, busy: true, phase: "running", current: running, activeStep: 1 }), "searching");
  assert.equal(orbState({ ...base, busy: true, phase: "running", current: running, activeStep: null }), "executing");
  const thinking = { ...running, steps: [] };
  assert.equal(orbState({ ...base, busy: true, phase: "running", current: thinking, usingFallback: true }), "recovering");
  assert.equal(orbState({ ...base, busy: false, usingFallback: true }), "idle");   // bo'sh paytda soxta faollik yo'q
});

test("command-mode partial transcript shows only while listening; cleared by final transcript", () => {
  let st = run([ev({ type: "stt_partial", text: "Safari", seq: 1 })]);
  assert.equal(st.partial, "");                                // tinglanmayapti — soxta matn yo'q
  st = run([
    ev({ type: "listening", state: "recording", seq: 2 }),
    ev({ type: "stt_partial", text: "Safari ni", seq: 3 }),
    ev({ type: "stt_partial", text: "Safari ni och", seq: 4 }),
  ], st);
  assert.equal(st.partial, "Safari ni och");
  st = run([ev({ type: "transcript", text: "Safari ni och", seq: 5 })], st);
  assert.equal(st.partial, "");
});

test("voice_latency stores real measured values; missing values stay null (not invented)", () => {
  const st = run([ev({ type: "voice_latency", ttf_partial: 700, ttf_final: 2100, tt_first_action: 2150, e2e: 2600, stt: "gemini-live", seq: 1 })]);
  assert.deepEqual(st.latency, { ttf_partial: 700, ttf_final: 2100, tt_first_action: 2150, tt_response_text: null,
    tt_response_audio: null, e2e: 2600, stt: "gemini-live" });
  assert.equal(ev({ type: "stt_partial", text: 5, seq: 2 }), null);
});

test("streamed response text shows while the task runs and clears on task_finished", () => {
  let st = run([
    ev({ type: "response_partial", task_id: "t1", text: "Samarqand —", seq: 1 }),
    ev({ type: "response_partial", task_id: "t1", text: "Samarqand — qadimiy shahar.", seq: 2 }),
  ]);
  assert.deepEqual(st.streaming, { taskId: "t1", text: "Samarqand — qadimiy shahar." });
  st = run([ev({ type: "task_finished", task_id: "t1", task: { id: "t1", status: "success", steps: [] }, seq: 3 })], st);
  assert.equal(st.streaming, null);
  assert.equal(ev({ type: "response_partial", text: "x", seq: 4 }), null);   // task_id majburiy
});
