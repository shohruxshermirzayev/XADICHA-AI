"""Ko'p tilli va aralash tilli buyruqlar — marshrutlash regressiyasi (modelsiz, deterministik).

Bu testlar real ovoz yoki real model sifatini o'lchamaydi; faqat buyruq to'g'ri yo'lga tushishini tekshiradi.
"""

from __future__ import annotations

import pytest

from xadicha.lang import detect_text_language
from xadicha.router import needs_web, route, strip_wake

# (matn, kutilgan yo'l, kutilgan intent yoki None, kutilgan til)
EXAMPLES = [
    ("Xadicha, Google Chrome'ni och.", "fast", "open_app", "uz"),
    ("Kecha yuklab olgan PDF faylimni top.", "tool", "find_file", "uz"),
    ("Рабочий столдаги Excel файлни оч.", "autonomous", None, "uz"),       # fayl — ilova sifatida ochilmaydi
    ("Open VS Code and find my latest Python project.", "autonomous", None, "en"),
    ("Xadicha, ovozni 50 foizga tushir.", "fast", "system", "uz"),
    ("Internetdan Gemini Live API haqida eng yangi ma'lumotlarni top.", "tool", "web_search", "uz"),
    ("Mana shu ekranda nima xato borligini tushuntir.", "autonomous", None, "uz"),   # ekran — agent ko'radi
    ("Open the last downloaded presentation and summarize it in Uzbek.", "autonomous", None, "en"),
]


@pytest.mark.parametrize("text,path,intent,lang", EXAMPLES)
def test_examples_route_and_language(text, path, intent, lang):
    r = route(text, "uz")
    assert r.path == path, (text, r.path)
    if intent:
        assert r.intent == intent
    assert detect_text_language(text).lang == lang


def test_wake_word_is_not_part_of_command():
    assert strip_wake("Xadicha, Safari ni och") == "Safari ni och"
    assert strip_wake("Хадича, сделай тише") == "сделай тише"
    assert strip_wake("Hey Khadija open Notes") == "open Notes"
    assert strip_wake("Xadicha") == "Xadicha"                  # yolg'iz ism — o'zgarmaydi
    r = route("Xadicha, Google Chrome'ni och.", "uz")
    assert r.actions[0].app == "Google Chrome"


@pytest.mark.parametrize("text,control,amount", [
    ("Xadicha, ovozni 50 foizga tushir.", "volume_down", 50),   # "-ga" — qadam (bir ma'noli emas)
    ("ovozni 30 gacha pasaytir", "volume_set", 30),
    ("уменьши громкость до 30", "volume_set", 30),
    ("turn the volume down to 20", "volume_set", 20),
    ("ovozni 40 ga qo'y", "volume_set", 40),
])
def test_volume_amount_semantics(text, control, amount):
    a = route(text, "uz").actions[0]
    assert (a.control, a.amount) == (control, amount)


def test_file_word_never_opened_as_app():
    r = route("Excel файлни оч", "uz")
    assert not (r.path == "fast" and r.intent == "open_app")


def test_search_example_needs_web():
    assert needs_web("Internetdan Gemini Live API haqida eng yangi ma'lumotlarni top.")
