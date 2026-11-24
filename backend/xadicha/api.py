"""FastAPI server: interfeys (Next.js) shu orqali agent bilan gaplashadi.

Ishga tushirish:  uvicorn xadicha.api:app --port 8765
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import load_config
from .models import Mode
from .service import XadichaService


class TaskIn(BaseModel):
    instruction: str
    language: str = "uz"
    mode: Mode = Mode.multimodal


class ConfirmIn(BaseModel):
    approve: bool
    confirmation_id: str | None = None   # qaysi tasdiqqa javob — eski dialogdan kelgan kech javobni ajratish uchun


class SpeakIn(BaseModel):
    text: str
    language: str = "uz"


def create_app(service: XadichaService | None = None) -> FastAPI:
    app = FastAPI(title="XADICHA AI", version="0.1.0")
    # Faqat shu kompyuterdagi interfeysdan so'rovlarga ruxsat (istalgan port)
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
                       allow_methods=["*"], allow_headers=["*"])
    svc = service or XadichaService(load_config())
    app.state.service = svc
    if service is None:
        svc.warmup()

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return svc.status()

    @app.post("/api/tasks", status_code=202)
    def create_task(body: TaskIn) -> dict[str, Any]:
        if not body.instruction.strip():
            raise HTTPException(400, "Buyruq bo'sh.")
        try:
            svc.start_task(body.instruction.strip(), body.language, body.mode)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
        return {"accepted": True}

    @app.get("/api/tasks")
    def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
        return [t.model_dump(mode="json") for t in svc.storage.list_tasks(limit)]

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        t = svc.storage.get_task(task_id)
        if not t:
            raise HTTPException(404, "Vazifa topilmadi.")
        return t.model_dump(mode="json")

    @app.post("/api/tasks/{task_id}/confirm")
    def confirm(task_id: str, body: ConfirmIn) -> dict[str, Any]:
        result = svc.answer_confirmation(task_id, body.approve, body.confirmation_id)
        if result == "none":
            raise HTTPException(404, "Kutilayotgan tasdiq yo'q (muddati tugagan yoki allaqachon yopilgan).")
        if result == "already":
            raise HTTPException(409, "Bu tasdiqqa allaqachon javob berilgan.")
        return {"ok": True}

    @app.post("/api/stop")
    def stop() -> dict[str, Any]:
        svc.stop()
        return {"ok": True}

    @app.post("/api/listen/start")
    def listen_start(language: str | None = None) -> dict[str, Any]:
        if svc.busy:
            raise HTTPException(409, "Vazifa bajarilmoqda — tugashini kuting yoki to'xtating.")
        state = svc.start_listening(language if language in ("uz", "ru", "en") else None)
        return {"ok": True, "state": state}

    @app.post("/api/listen/stop")
    def listen_stop() -> dict[str, Any]:
        try:
            r = svc.stop_listening()
        except RuntimeError as e:
            raise HTTPException(409 if "boshlanmagan" in str(e) else 503, str(e)) from e
        if r is None:
            raise HTTPException(500, "Nutq aniqlanmadi.")
        return {"text": r.text, "language": r.language, "probability": r.probability, "supported": r.supported}

    @app.post("/api/speak")
    def speak(body: SpeakIn) -> dict[str, Any]:
        return {"spoken": svc.speaker.say(body.text, body.language)}

    @app.delete("/api/history")
    def clear_history() -> dict[str, Any]:
        return {"deleted": svc.storage.clear_history()}

    @app.websocket("/api/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

        def deliver(e: dict[str, Any]) -> None:
            def put() -> None:
                if queue.full() and e.get("type") == "mic_level":
                    return   # sekin mijoz: vizualizatsiya hodisalarini tashlab yuboramiz, muhimlarini emas
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(e)
            with contextlib.suppress(RuntimeError):   # loop yopilgan bo'lsa
                loop.call_soon_threadsafe(put)

        unsub = svc.subscribe(deliver)

        async def reader() -> None:
            # Mijoz xabarlarini o'qiymiz: uzilishni darhol sezish uchun. Noto'g'ri xabarlar e'tiborsiz qoldiriladi.
            while True:
                raw = await socket.receive_text()
                with contextlib.suppress(ValueError, TypeError):
                    msg = json.loads(raw)
                    if isinstance(msg, dict) and msg.get("type") == "ping":
                        await socket.send_json({"type": "pong"})

        async def writer() -> None:
            await socket.send_json({"type": "hello", "status": svc.status()})
            while True:
                event = await queue.get()
                await socket.send_json(event)

        tasks = [asyncio.create_task(reader()), asyncio.create_task(writer())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError, Exception):
                    await t
            unsub()
            with contextlib.suppress(Exception):
                await socket.close()

    return app


_app: FastAPI | None = None


def __getattr__(name: str):  # `uvicorn xadicha.api:app` — server faqat kerak bo'lganda yaratiladi
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
