from pathlib import Path

import pytest

from app.config.settings import Settings
from app.notifications.telegram_commands import CommandHandlers, TelegramCommandPoller
from app.services.self_update import self_update


def fake_run(heads, pull=(0, "ok"), changed="app/main.py", pip=(0, "")):
    heads = list(heads)
    calls = []

    def run(cmd, cwd, timeout=300):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, heads.pop(0)
        if cmd[:2] == ["git", "pull"]:
            return pull
        if cmd[:2] == ["git", "diff"]:
            return 0, changed
        if cmd[:2] == ["git", "log"]:
            return 0, "• Cambio de prueba"
        if "pip" in cmd:
            return pip
        raise AssertionError(cmd)
    run.calls = calls
    return run


def test_already_up_to_date():
    r = self_update(Path("."), fake_run(["abc", "abc"]))
    assert not r.restart and "Ya estaba" in r.text


def test_updates_and_restarts():
    run = fake_run(["abc", "def"])
    r = self_update(Path("."), run)
    assert r.restart and "abc → def" in r.text and "Cambio de prueba" in r.text
    assert not any("pip" in c for c in run.calls)


def test_installs_requirements_when_changed():
    run = fake_run(["abc", "def"], changed="requirements.txt\napp/x.py")
    assert self_update(Path("."), run).restart and any("pip" in c for c in run.calls)
    failed = self_update(Path("."), fake_run(["abc", "def"], changed="requirements.txt", pip=(1, "boom")))
    assert not failed.restart and "falló la instalación" in failed.text


def test_pull_failure_changes_nothing():
    r = self_update(Path("."), fake_run(["abc"], pull=(1, "fatal: Not possible to fast-forward")))
    assert not r.restart and "no cambié nada" in r.text


class FakeSession:
    def __init__(self, updates):
        self.updates, self.sent = updates, []

    def get(self, url, params=None, timeout=None):
        data, self.updates = self.updates, []
        return type("R", (), {"json": lambda _self: {"ok": True, "result": data}})()

    def post(self, url, json=None, **kw):
        self.sent.append(json["text"])


def _poller(tmp_path, updates, result):
    settings = Settings(_env_file=None, telegram_bot_token="T", telegram_chat_id="42",
                        manual_quotes_file=str(tmp_path / "m.csv"))
    handlers = CommandHandlers(known_houses=dict, after_price=str, top=str, update=lambda: result)
    return TelegramCommandPoller(settings, handlers, session=FakeSession(updates), offset_file=tmp_path / "o.txt")


def _msg(chat, text, uid=7):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


def test_actualizar_restarts_after_saving_offset(tmp_path):
    poller = _poller(tmp_path, [_msg(42, "/actualizar")], ("✅ Actualizado", True))
    with pytest.raises(SystemExit):
        poller.poll_once()
    assert poller.session.sent == ["⏳ Actualizando…", "✅ Actualizado"]
    assert (tmp_path / "o.txt").read_text() == "8"  # no se repite al volver


def test_actualizar_ignored_from_other_chat(tmp_path):
    poller = _poller(tmp_path, [_msg(99, "/actualizar")], ("x", True))
    assert poller.poll_once() == 0 and poller.session.sent == []


def test_actualizar_without_changes_keeps_running(tmp_path):
    poller = _poller(tmp_path, [_msg(42, "/actualizar")], ("✅ Ya estaba", False))
    assert poller.poll_once() == 1
