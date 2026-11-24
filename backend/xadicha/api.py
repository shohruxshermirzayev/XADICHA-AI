"""FastAPI server: interfeys (Next.js) shu orqali agent bilan gaplashadi.

Ishga tushirish:  uvicorn xadicha.api:app --port 8765
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import re
import secrets
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field

from .config import load_config
from .models import Mode
from .service import XadichaService
from .understand import understand


# Faqat shu kompyuterdagi sahifalar. CORS — xavfsizlik chegarasi emas, shuning uchun qo'shimcha:
# Host tekshiruvi (DNS rebinding), Origin tekshiruvi (CSRF, WebSocket) va sessiya kaliti (maxsus sarlavha).
LOCAL_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
DEFAULT_HOSTS = ("127.0.0.1", "localhost", "[::1]")
TOKEN_HEADER = "x-xadicha-token"


def _host_ok(host_header: str | None, allowed: tuple[str, ...]) -> bool:
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        name = host.split("]")[0] + "]"
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name in allowed


def _origin_ok(origin: str | None) -> bool:
    return origin is None or bool(LOCAL_ORIGIN.match(origin))   # Origin yo'q — brauzer emas (CLI, curl)


class TaskIn(BaseModel):
    instruction: str = Field(max_length=2000)
    language: Literal["uz", "ru", "en"] = "uz"
    mode: Mode = Mode.multimodal


class ConfirmIn(BaseModel):
    approve: bool
    confirmation_id: str | None = None   # qaysi tasdiqqa javob — eski dialogdan kelgan kech javobni ajratish uchun


class UnderstandIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: Literal["uz", "ru", "en"] = "uz"


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: Literal["uz", "ru", "en"] = "uz"


def create_app(service: XadichaService | None = None, allowed_hosts: tuple[str, ...] = DEFAULT_HOSTS,
               token: str | None = None) -> FastAPI:
    app = FastAPI(title="XADICHA AI", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    session_token = token or secrets.token_urlsafe(32)   # har ishga tushishda yangi; diskka yozilmaydi
    app.state.session_token = session_token

    async def guard(request: Request, call_next):
        if not _host_ok(request.headers.get("host"), allowed_hosts):
            return JSONResponse({"detail": "Ruxsat etilmagan Host."}, status_code=400)
        if not _origin_ok(request.headers.get("origin")):
            return JSONResponse({"detail": "Ruxsat etilmagan Origin."}, status_code=403)
        path = request.url.path
        if request.method != "OPTIONS" and path.startswith("/api/") and path != "/api/session":
            given = request.headers.get(TOKEN_HEADER, "")
            if not hmac.compare_digest(given.encode(), session_token.encode()):
                return JSONResponse({"detail": "Sessiya kaliti noto'g'ri yoki yo'q."}, status_code=401)
        return await call_next(request)

    # Tartib muhim: CORS tashqi qatlam — 401/403 javoblari ham brauzerda o'qiladigan bo'lsin
    app.add_middleware(BaseHTTPMiddleware, dispatch=guard)
    app.add_middleware(CORSMiddleware, allow_origin_regex=LOCAL_ORIGIN.pattern,
                       allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                       allow_headers=["content-type", TOKEN_HEADER])
    svc = service or XadichaService(load_config())
    app.state.service = svc
    if service is None:
        svc.warmup()

    @app.get("/api/session")
    def session() -> JSONResponse:
        """Sessiya kalitini faqat localhost sahifasiga beradi (Host+Origin tekshiruvidan o'tgan so'rov).
        Boshqa sayt CORS sababli javobni o'qiy olmaydi."""
        return JSONResponse({"token": session_token}, headers={"Cache-Control": "no-store"})

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
    def list_tasks(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
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
    def listen_start(language: str | None = None, auto: bool = False, mode: Mode = Mode.multimodal) -> dict[str, Any]:
        """auto=true — gapirib bo'linganini o'zi sezadi va aniq buyruqni darhol bajaradi."""
        if svc.busy:
            raise HTTPException(409, "Vazifa bajarilmoqda — tugashini kuting yoki to'xtating.")
        state = svc.start_listening(language if language in ("uz", "ru", "en") else None, auto=auto, mode=mode)
        return {"ok": True, "state": state}

    @app.post("/api/listen/stop")
    def listen_stop() -> dict[str, Any]:
        try:
            r = svc.stop_listening()
        except RuntimeError as e:
            raise HTTPException(409 if "boshlanmagan" in str(e) else 503, str(e)) from e
        if r is None:
            raise HTTPException(500, "Nutq aniqlanmadi.")
        analysis = understand(r.text, r.language, r.asr_confidence, llm_available=svc.provider.name != "rules")
        return {"text": r.text, "language": r.language, "probability": r.probability, "supported": r.supported,
                "asr_confidence": r.asr_confidence, "analysis": analysis.public() if r.text else None,
                "handled": svc.listen_handled}

    @app.post("/api/understand")
    def understand_text(body: UnderstandIn) -> dict[str, Any]:
        """Buyruqni BAJARMASDAN tahlil qiladi: niyat, ishonch, aniqlashtirish kerakmi."""
        return understand(body.text, body.language, None, llm_available=svc.provider.name != "rules").public()

    @app.post("/api/speak")
    def speak(body: SpeakIn) -> dict[str, Any]:
        return {"spoken": svc.speaker.say(body.text, body.language)}

    @app.delete("/api/history")
    def clear_history() -> dict[str, Any]:
        return {"deleted": svc.storage.clear_history()}

    @app.websocket("/api/ws")
    async def ws(socket: WebSocket) -> None:
        # WebSocket'ga CORS qo'llanmaydi — Origin, Host va kalitni qo'lda tekshiramiz
        given = socket.query_params.get("token", "")
        if (not _host_ok(socket.headers.get("host"), allowed_hosts) or not _origin_ok(socket.headers.get("origin"))
                or not hmac.compare_digest(given.encode(), session_token.encode())):
            await socket.close(code=4401)
            return
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
