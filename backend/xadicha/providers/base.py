"""Provayderdan mustaqil LLM interfeysi."""

from __future__ import annotations

import logging
import platform
from abc import ABC, abstractmethod
from typing import Any

from pydantic import ValidationError

from ..models import Decision, Plan
from ..vision.screen import Screenshot
from .prompts import PLAN_PROMPT, SYSTEM_PROMPT, parse_json, user_turn

LANG_NAMES = {"uz": "Uzbek", "ru": "Russian", "en": "English"}


class ProviderError(RuntimeError):
    """Provayder mavjud emas yoki javob bermadi."""


def os_name() -> str:
    return {"Darwin": "macOS", "Windows": "Windows"}.get(platform.system(), platform.system())


class LLMProvider(ABC):
    name = "base"
    supports_vision = True

    def system_prompt(self, language: str, screen: Screenshot | None) -> str:
        w, h = (screen.width, screen.height) if screen else (0, 0)
        return SYSTEM_PROMPT.format(os_name=os_name(), language=LANG_NAMES.get(language, "the user's language"),
                                    width=w, height=h)

    def decide(self, instruction: str, history: list[dict[str, Any]], screen: Screenshot | None,
               language: str, context: str = "") -> Decision:
        system = self.system_prompt(language, screen)
        user = user_turn(instruction, history, screen is not None, context)
        raw = self.complete(system, user, screen)
        try:
            return parse_decision(raw)
        except (ValueError, ValidationError) as e:
            logging.getLogger("xadicha").warning("noto'g'ri model javobi: %r", raw[:500])
            # Bir marta qayta so'raymiz: modelga xatosini aytamiz
            fix = (f"{user}\n\nYour previous reply was invalid ({str(e)[:300]}). "
                   "Reply again with ONE valid JSON object exactly in the required format.")
            raw = self.complete(system, fix, screen)
            try:
                return parse_decision(raw)
            except (ValueError, ValidationError) as e2:
                raise ProviderError(f"Model noto'g'ri formatda javob berdi: {str(e2)[:200]}") from e2

    def plan(self, instruction: str, language: str) -> Plan:
        system = PLAN_PROMPT.format(os_name=os_name(), language=LANG_NAMES.get(language, "the user's language"))
        raw = self.complete(system, f"User instruction: {instruction}\nReturn the JSON object now.", None)
        try:
            data = parse_json(raw)
            data["steps"] = [normalize_decision(st) for st in data.get("steps", []) if isinstance(st, dict)]
            return Plan.model_validate(data)
        except (ValueError, ValidationError) as e:
            raise ProviderError(f"Model noto'g'ri reja qaytardi: {str(e)[:200]}") from e

    @abstractmethod
    def complete(self, system: str, user: str, screen: Screenshot | None) -> str:
        """Matnli javob qaytaradi (JSON kutiladi)."""

    def health(self) -> tuple[bool, str]:
        return True, "ok"

    def warmup(self) -> None:
        """Modelni oldindan xotiraga yuklash (birinchi buyruq kutib qolmasligi uchun)."""


_RISKS = {"low", "medium", "high"}
_ACTION_ALIASES = {"open": "open_app", "launch": "open_app", "open_application": "open_app",
                   "navigate": "open_url", "goto": "open_url", "open_website": "open_url", "browse": "open_url",
                   "type": "type_text", "write": "type_text", "press": "hotkey", "key": "hotkey", "keys": "hotkey",
                   "sleep": "wait", "mkdir": "create_folder", "left_click": "click"}


def normalize_decision(d: dict[str, Any]) -> dict[str, Any]:
    """Kichik model xatolarini tuzatadi: noma'lum xavf darajasi, sinonim harakat nomlari, bo'sh harakat."""
    d = dict(d)
    risk = str(d.get("risk") or "low").lower()
    d["risk"] = risk if risk in _RISKS else "medium"
    a = d.get("action")
    if isinstance(a, dict):
        a = dict(a)
        t = str(a.get("type") or "").lower().strip()
        a["type"] = _ACTION_ALIASES.get(t, t)
        if a["type"] == "hotkey" and isinstance(a.get("keys"), str):
            a["keys"] = [k.strip() for k in a["keys"].replace("+", " ").split()]
        if not a["type"]:
            a = None
        d["action"] = a
    elif a is not None:
        d["action"] = None
    for k in ("intent", "thought", "expected_outcome", "final_message"):
        if d.get(k) is None:
            d[k] = ""
    return d


def parse_decision(raw: str) -> Decision:
    return Decision.model_validate(normalize_decision(parse_json(raw)))
