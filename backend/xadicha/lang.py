"""Matn tilini aniqlash: o'zbek (lotin / kirill), rus, ingliz.

Signal manbalari (birgalikda): yozuv (lotin / kirill), o'zbekka xos harflar (ў қ ғ ҳ, o' g'), har tilga xos
tez-tez uchraydigan so'zlar, ASR til ehtimolligi va foydalanuvchi tanlagan til (faqat "prior" — aniq boshqa
tildagi matnni noto'g'ri belgilash uchun bahona emas).

Qoida asosida; aniqligi faqat muallif tuzgan matn korpusida o'lchangan (benchmark/speech_manifest.csv).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CYR = re.compile(r"[Ѐ-ӿ]")
_LAT = re.compile(r"[A-Za-z]")
_UZ_CYR_LETTERS = re.compile(r"[ўқғҳЎҚҒҲ]")
_UZ_LAT_LETTERS = re.compile(r"\b\w*(?:o['ʻ’‘`]|g['ʻ’‘`])\w*", re.I)

_UZ_LAT_WORDS = {
    "ni", "och", "ochib", "ochgin", "ber", "qil", "qiling", "yarat", "yaratib", "qidir", "qidirib", "top", "topib",
    "va", "uchun", "bilan", "menga", "nima", "qayer", "qayerda", "shu", "bu", "uni", "buni", "yana", "qayta",
    "ekran", "ekranda", "papka", "papkani", "fayl", "faylni", "ovoz", "ovozni", "kerak", "ayt", "aytib", "ko'rsat",
    "ishga", "tushir", "haqida", "dan", "da", "ga", "ning", "yoq", "o'chir", "kir", "yoz", "deb", "iltimos",
    "hozir", "qanday", "nechta", "bormi", "yo'q", "ha", "salom", "rahmat", "brauzer", "brauzerni", "turgan",
    "turganini", "birinchisini", "oching", "qo'y", "pasaytir", "ko'tar", "oshir", "yorug'lik",
}
_EN_WORDS = {
    "open", "the", "search", "for", "what", "is", "on", "my", "screen", "please", "create", "folder", "close",
    "show", "find", "turn", "volume", "set", "to", "and", "file", "weather", "a", "an", "it", "again", "go", "type",
    "launch", "start", "about", "in", "of", "how", "where", "which", "who", "this", "that", "me", "describe", "up",
    "down", "mute", "unmute", "brightness", "first", "result", "look", "information", "tell", "can", "you",
    "louder", "quieter", "brighter", "dimmer", "again", "reopen", "right", "now",
}
_UZ_CYR_WORDS = {
    "ни", "оч", "очиб", "бер", "қил", "ярат", "қидир", "топ", "ва", "учун", "билан", "менга", "нима", "шу", "бу",
    "уни", "яна", "экран", "экранда", "папка", "файл", "овоз", "керак", "айт", "ишга", "туширинг", "ҳақида", "дан",
    "да", "га", "нинг", "ёқ", "ўчир", "кир", "ёз", "деб", "илтимос", "ҳозир", "уни", "шуни", "қидир", "топ",
}
_RU_WORDS = {
    "открой", "открыть", "найди", "поищи", "что", "на", "экране", "и", "в", "с", "сделай", "громче", "тише",
    "выключи", "включи", "звук", "папку", "файл", "создай", "запусти", "пожалуйста", "покажи", "это", "его",
    "снова", "ещё", "еще", "про", "о", "об", "какое", "сейчас", "мне", "напиши", "перейди", "сайт", "яркость",
    "темнее", "ярче", "удали", "раз", "первый", "покажи", "громкость", "музыку", "информацию",
}


def _words(text: str) -> list[str]:
    t = re.sub(r"[ʻ’‘`´]", "'", text.lower())
    return re.findall(r"[\w']+", t)


@dataclass
class LangGuess:
    lang: str
    confidence: float      # 0..1 — qoida signali kuchi (kalibrlanmagan ehtimollik emas)
    signals: list[str]


def detect_text_language(text: str, selected: str = "uz") -> LangGuess:
    words = _words(text)
    if not words:
        return LangGuess(selected, 0.0, ["empty"])
    cyr_words = [w for w in words if _CYR.search(w)]
    if cyr_words:   # kirill so'z bor — til kirill so'zlardan aniqlanadi (lotin — odatda ilova nomi: "Открой Safari")
        uz = sum(w in _UZ_CYR_WORDS for w in words) + 2 * len(_UZ_CYR_LETTERS.findall(text))
        ru = sum(w in _RU_WORDS for w in words)
        # "Телеграмни", "Сафарини" — o'zbekcha qo'shimcha
        uz += sum(1 for w in words if len(w) > 4 and w.endswith(("ни", "га", "да", "дан")) and w not in _RU_WORDS)
        if uz > ru:
            return LangGuess("uz", min(1.0, 0.5 + 0.15 * (uz - ru)), ["cyrillic", "uz_markers"])
        if ru > uz:
            return LangGuess("ru", min(1.0, 0.5 + 0.15 * (ru - uz)), ["cyrillic", "ru_markers"])
        return LangGuess("uz" if selected == "uz" else "ru", 0.4, ["cyrillic", "tie_selected_prior"])
    uz = sum(w in _UZ_LAT_WORDS for w in words) + len(_UZ_LAT_LETTERS.findall(text))
    uz += sum(1 for w in words if len(w) > 4 and re.search(r"(ni|ga|da|dan|ning)$", w) and w not in _EN_WORDS)
    en = sum(w in _EN_WORDS for w in words)
    if uz > en:
        return LangGuess("uz", min(1.0, 0.5 + 0.15 * (uz - en)), ["latin", "uz_markers"])
    if en > uz:
        return LangGuess("en", min(1.0, 0.5 + 0.15 * (en - uz)), ["latin", "en_markers"])
    # Faqat ilova nomi kabi neytral so'zlar: tanlangan til saqlanadi (lotinda ruscha bo'lmaydi)
    return LangGuess(selected if selected in ("uz", "en") else "uz", 0.3, ["latin", "tie_selected_prior"])


def refine_asr_language(text: str, asr_lang: str, asr_prob: float | None, selected: str | None) -> str:
    """Whisper aniqlagan tilni matn signallari bilan tekshiradi. Kuchli qarama-qarshi signal bo'lsa — tuzatadi."""
    if not text:
        return asr_lang
    g = detect_text_language(text, selected or asr_lang or "uz")
    if g.lang == asr_lang:
        return asr_lang
    strong = g.confidence >= 0.65
    weak_asr = asr_prob is None or asr_prob < 0.8
    if strong and (weak_asr or (asr_lang == "ru" and g.lang == "uz" and _UZ_CYR_LETTERS.search(text))):
        return g.lang
    return asr_lang


_L2C_MULTI = [("sh", "ш"), ("ch", "ч"), ("o'", "ў"), ("g'", "ғ"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ye", "е"),
              ("ts", "ц"), ("ng", "нг")]
_L2C = {"a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "ҳ", "i": "и", "j": "ж", "k": "к", "l": "л",
        "m": "м", "n": "н", "o": "о", "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "x": "х",
        "y": "й", "z": "з", "'": "ъ"}


def latin_to_cyrillic_uz(text: str, keep: list[str] | None = None) -> str:
    """O'zbek lotin → kirill. `keep` dagi atamalar (ilova/brend nomlari: Safari, VS Code) o'zgarmaydi; so'z boshidagi
    "e" → "э"; o'/g' (turli apostroflar) → ў/ғ. Faqat ko'rsatish/yozuv afzalligi uchun — ma'noni o'zgartirmaydi."""
    import re as _re

    t = _re.sub(r"[ʻʼ’‘`´]", "'", text)
    keep_l = sorted({k.lower() for k in (keep or []) if k}, key=len, reverse=True)
    # Ko'p so'zli nomlar ("VS Code", "Google Chrome") — o'girishdan oldin to'liq himoyalanadi
    saved: list[str] = []
    for k in [k for k in keep_l if " " in k]:
        def _hold(m, saved=saved):
            saved.append(m.group(0))
            return f"\u0000{len(saved) - 1}\u0000"
        t = _re.sub(rf"(?<!\w){_re.escape(k)}(?!\w)", _hold, t, flags=_re.I)
    out: list[str] = []
    for word in _re.split(r"(\s+)", t):
        low = word.lower()
        stem = low.rstrip(".,!?;:")
        if not word.strip() or "\u0000" in word or any(stem == k or stem.startswith(k + "'") or (len(k) >= 4 and stem.startswith(k))
                                   for k in keep_l):
            out.append(word)   # brend/ilova nomi yoki bo'sh joy — lotinda qoladi
            continue
        res, i = "", 0
        while i < len(word):
            ch = word[i]
            pair = word[i:i + 2].lower()
            hit = next((c for lat, c in _L2C_MULTI if pair == lat), None)
            if hit and not (pair == "ye" and i > 0):
                res += hit.upper() if ch.isupper() else hit
                i += 2
                continue
            lo = ch.lower()
            if lo == "e" and (i == 0 or not word[i - 1].isalpha()):
                c = "э"
            else:
                c = _L2C.get(lo, ch)
            res += c.upper() if ch.isupper() and c != ch else c
            i += 1
        out.append(res)
    joined = "".join(out)
    return _re.sub("\u0000(\\d+)\u0000", lambda m: saved[int(m.group(1))], joined)
