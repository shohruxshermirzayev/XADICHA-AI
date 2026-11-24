"""Yagona holat modeli: hodisa tartib raqami (seq), phase va "band" holatda osilib qolmaslik.

Simulyatsiya: soxta model, dry-run adapter, TTS o'rniga sleep.
"""

from __future__ import annotations

import time

from conftest import ScriptedProvider

from xadicha.adapters.base import DryRunAdapter
from xadicha.service import XadichaService


def make(cfg, storage, provider, tts_seconds=0.0):
    cfg.tts_enabled = True
    svc = XadichaService(cfg, provider=provider, adapter=DryRunAdapter(), storage=storage, confirm_timeout=5)
    svc.speaker.say = lambda text, lang: (time.sleep(tts_seconds), True)[1]
    events: list[dict] = []
    svc.subscribe(events.append)
    return svc, events


def wait_idle(svc, timeout=5.0):
    end = time.time() + timeout
    time.sleep(0.05)
    while svc.busy and time.time() < end:
        time.sleep(0.02)
    assert not svc.busy


def test_final_state_event_says_idle_after_task_and_speech(cfg, storage):
    # Xato: task_finished paytida backend hali TTS gapirayotgani uchun busy=True edi va undan keyin
    # "bo'shadim" degan hodisa kelmasdi — sarlavha "Vazifa bajarilmoqda" holatida osilib qolardi.
    svc, events = make(cfg, storage, ScriptedProvider([{"done": True, "success": True, "final_message": "ok"}]),
                       tts_seconds=0.3)
    svc.start_task("salom")
    wait_idle(svc)
    time.sleep(0.05)
    finished = next(e for e in events if e["type"] == "task_finished")
    after = [e for e in events if e["seq"] > finished["seq"] and e["type"] == "state"]
    assert after, "task_finished'dan keyin holat e'loni yo'q"
    assert after[-1]["busy"] is False and after[-1]["phase"] == "idle"
    assert any(e["phase"] == "speaking" for e in after)


def test_event_seq_is_strictly_increasing_and_status_is_not_older(cfg, storage):
    svc, events = make(cfg, storage, ScriptedProvider([{"action": {"type": "open_app", "app": "Notes"}},
                                                       {"previous_step_ok": True, "done": True, "success": True}]))
    svc.start_task("Notes")
    wait_idle(svc)
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert svc.status()["seq"] >= seqs[-1]


def test_phase_awaiting_confirmation_then_idle(cfg, storage, tmp_path):
    p = ScriptedProvider([{"action": {"type": "delete_path", "path": str(tmp_path / "x")}}])
    svc, events = make(cfg, storage, p)
    svc.start_task("o'chir")
    for _ in range(100):
        if svc.pending:
            break
        time.sleep(0.02)
    assert svc.status()["phase"] == "awaiting_confirmation"
    svc.stop()
    wait_idle(svc)
    assert svc.status()["phase"] == "idle"
    phases = [e["phase"] for e in events if e["type"] == "state"]
    assert "awaiting_confirmation" in phases and phases[-1] == "idle"


def test_failed_task_also_ends_idle(cfg, storage):
    svc, events = make(cfg, storage, ScriptedProvider(fail=True))
    svc.start_task("x")
    wait_idle(svc)
    time.sleep(0.05)
    states = [e for e in events if e["type"] == "state"]
    assert states[-1]["busy"] is False
    assert next(e for e in events if e["type"] == "task_finished")["task"]["status"] == "failed"


def test_stop_interrupts_wait_step_and_no_later_action_runs(cfg, storage):
    # Xato: wait qadami to'xtatishga qaramay 10 s gacha uxlardi
    p = ScriptedProvider([{"action": {"type": "wait", "seconds": 10}},
                          {"action": {"type": "open_app", "app": "Notes"}}])
    svc, events = make(cfg, storage, p)
    svc.start_task("kut")
    while not any(e["type"] == "step_started" for e in events):
        time.sleep(0.01)
    t0 = time.time()
    svc.stop()
    wait_idle(svc, timeout=3)
    assert time.time() - t0 < 2
    assert svc.adapter.executed == []                     # Notes ochilmadi
    task = next(e for e in events if e["type"] == "task_finished")["task"]
    assert task["status"] == "cancelled"


def test_stop_pressed_before_task_thread_starts_is_not_lost(cfg, storage):
    import threading

    gate = threading.Event()
    p = ScriptedProvider([{"action": {"type": "open_app", "app": "Notes"}}])
    svc, _ = make(cfg, storage, p)
    real_run = svc.agent.run

    def delayed_run(*a, **k):
        gate.wait(2)            # ip hali ishga tushmagan payt
        return real_run(*a, **k)

    svc.agent.run = delayed_run
    svc.start_task("Notes")
    svc.stop()                  # foydalanuvchi darhol to'xtatdi
    gate.set()
    wait_idle(svc)
    assert svc.adapter.executed == []
