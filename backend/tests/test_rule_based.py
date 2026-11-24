import pytest

from xadicha.providers.rule_based import parse_command


@pytest.mark.parametrize("text,lang,app", [
    ("Safari ni och", "uz", "Safari"),
    ("Telegram'ni och", "uz", "Telegram"),
    ("Notes ni ishga tushir", "uz", "Notes"),
    ("Открой Telegram", "ru", "Telegram"),
    ("Open Notes", "en", "Notes"),
    ("open the Calculator app", "en", "Calculator"),
])
def test_open_app_three_languages(text, lang, app):
    intent, actions, _ = parse_command(text, lang)
    assert intent == "open_app"
    assert actions[0].app == app


def test_web_search():
    intent, actions, _ = parse_command("Google da qidir Toshkent ob-havosi", "uz")
    assert intent == "web_search"
    assert "Toshkent" in actions[0].url


def test_open_site():
    intent, actions, _ = parse_command("kun.uz saytini och", "uz")
    assert intent == "open_url"
    assert actions[0].url == "https://kun.uz"


def test_create_folder():
    intent, actions, _ = parse_command('Desktopda "Hisobotlar" papka yarat', "uz")
    assert intent == "create_folder"
    assert actions[0].path.endswith("Hisobotlar")


def test_unknown_reply_in_language():
    intent, actions, reply = parse_command("blablabla", "ru")
    assert intent == "unknown" and not actions
    assert "Извините" in reply


def test_is_simple():
    from xadicha.providers.rule_based import is_simple
    assert is_simple("Safari ni och") and is_simple("Открой Notes") and is_simple("Open Calculator")
    assert not is_simple('Notes ni och va "Salom" deb yoz')
    assert not is_simple("Open Notes and type hello")
    assert not is_simple("Открой Notes и напиши привет")
