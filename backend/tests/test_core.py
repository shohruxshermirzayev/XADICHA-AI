import json

import pytest
from pydantic import ValidationError
from PIL import Image

from xadicha.adapters.base import DryRunAdapter, OSAdapter
from xadicha.models import Action, Decision, Mode, TaskRecord, TaskStatus
from xadicha.providers.prompts import parse_json
from xadicha.storage import Storage
from xadicha.vision.screen import encode


def test_parse_json_variants():
    assert parse_json('{"done": true}') == {"done": True}
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Mana javob: {"a": {"b": 2}} tamom') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json("javob yo'q")


def test_decision_validation():
    d = Decision.model_validate({"action": {"type": "open_app", "app": "Safari"}, "risk": "medium"})
    assert d.action.app == "Safari" and not d.done
    with pytest.raises(ValidationError):
        Decision.model_validate({"action": {"type": "format_disk"}})


def test_screen_encode_scales_to_logical_and_limits_size():
    img = Image.new("RGB", (2880, 1800), "white")   # Retina piksellari
    s = encode(img, 1440, 900)                        # mantiqiy nuqtalar
    assert max(s.width, s.height) <= 1280
    assert abs(s.width * s.scale - 1440) < 2


def test_storage_roundtrip_and_stats(tmp_path):
    st = Storage(tmp_path / "db.sqlite")
    a = TaskRecord(instruction="a", mode=Mode.multimodal, status=TaskStatus.success)
    b = TaskRecord(instruction="b", mode=Mode.llm_plan, status=TaskStatus.failed)
    st.save_task(a)
    st.save_task(b)
    assert st.get_task(a.id).instruction == "a"
    assert st.stats()["success_rate"] == 50.0
    st.set_pref("lang", "uz")
    assert st.get_pref("lang") == "uz"


class _FsAdapter(OSAdapter):
    name = "fs"

    def _to_trash(self, path):
        path.unlink()

    def frontmost_app(self):
        return ""

    def screen_size(self):
        return (0, 0)

    def _paste_modifier(self):
        return "command"


def test_file_actions_verify_programmatically(tmp_path):
    ad = _FsAdapter()
    r = ad.execute(Action(type="create_folder", path=str(tmp_path / "Hisobot")))
    assert r.ok and r.verified is True
    f = tmp_path / "Hisobot" / "a.txt"
    r = ad.execute(Action(type="create_file", path=str(f), content="salom"))
    assert r.ok and r.verified and f.read_text() == "salom"
    r = ad.execute(Action(type="create_file", path=str(f), content="x"))
    assert not r.ok, "mavjud faylni ustidan yozmasligi kerak"
    r = ad.execute(Action(type="delete_path", path=str(f)))
    assert r.ok and r.verified and not f.exists()


def test_unsupported_action_reported():
    class Bare(_FsAdapter):
        pass

    r = Bare().execute(Action(type="open_url", url="https://x.uz"))
    assert not r.ok and "Qo'llab-quvvatlanmaydigan" in r.detail


def test_dry_run_records():
    d = DryRunAdapter()
    d.execute(Action(type="open_app", app="Notes"))
    assert d.frontmost_app() == "Notes" and json.dumps(d.executed[0].model_dump())
