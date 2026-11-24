"""FastAPI server: interfeys (Next.js) shu orqali agent bilan gaplashadi.

Ishga tushirish:  uvicorn xadicha.api:app --port 8765
"""

from __future__ import annotations

import asyncio
import contextlib
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
        if not svc.answer_confirmation(task_id, body.approve):
            raise HTTPException(404, "Kutilayotgan tasdiq yo'q.")
        return {"ok": True}

    @app.post("/api/stop")
    def stop() -> dict[str, Any]:
        svc.stop()
        return {"ok": True}

    @app.post("/api/listen/start")
    def listen_start(language: str | None = None) -> dict[str, Any]:
        svc.start_listening(language if language in ("uz", "ru", "en") else None)
        return {"ok": True}

    @app.post("/api/listen/stop")
    def listen_stop() -> dict[str, Any]:
        r = svc.stop_listening()
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
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        unsub = svc.subscribe(lambda e: loop.call_soon_threadsafe(queue.put_nowait, e))
        try:
            await socket.send_json({"type": "hello", "status": svc.status()})
            while True:
                event = await queue.get()
                await socket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
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
