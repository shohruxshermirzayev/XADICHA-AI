"""Ollama — bepul, lokal model provayderi (masalan, qwen3.5)."""

from __future__ import annotations

import requests

from ..vision.screen import Screenshot
from .base import LLMProvider, ProviderError


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, url: str, model: str, timeout: float = 180):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, user: str, screen: Screenshot | None) -> str:
        msg: dict = {"role": "user", "content": user}
        if screen is not None:
            msg["images"] = [screen.png_base64]
        payload = {"model": self.model, "stream": False, "format": "json", "think": False,
                   "messages": [{"role": "system", "content": system}, msg],
                   "keep_alive": "30m",   # model xotirada qoladi — har safar qayta yuklanmaydi
                   "options": {"temperature": 0.1, "num_predict": 400}}
        try:
            r = requests.post(f"{self.url}/api/chat", json=payload, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            raise ProviderError(f"Ollama bilan aloqa yo'q ({self.url}). Ollama ishga tushirilganmi?") from e
        return r.json().get("message", {}).get("content", "")

    def warmup(self) -> None:
        try:
            requests.post(f"{self.url}/api/generate", json={"model": self.model, "keep_alive": "30m"},
                          timeout=self.timeout)
        except requests.RequestException:
            pass

    def health(self) -> tuple[bool, str]:
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=3)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
        except requests.RequestException:
            return False, "Ollama ishlamayapti"
        if not any(n.startswith(self.model.split(":")[0]) for n in names):
            return False, f"Model yuklanmagan: ollama pull {self.model}"
        return True, "ok"
