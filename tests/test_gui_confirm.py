from clientwipe import gui_confirm


def test_find_graphical_session_returns_none_without_loginctl(monkeypatch):
    monkeypatch.setattr(gui_confirm.shutil, "which", lambda name: None)

    assert gui_confirm.find_graphical_session() is None


def test_find_graphical_session_parses_active_session(monkeypatch):
    monkeypatch.setattr(gui_confirm.shutil, "which", lambda name: "/usr/bin/loginctl")

    def fake_run(cmd):
        if cmd[:2] == ["loginctl", "list-sessions"]:
            return "2 1000 bycybadmin seat0 tty2\n"
        if cmd[:2] == ["loginctl", "show-session"]:
            return "Name=bycybadmin\nDisplay=:0\nState=active\n"
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gui_confirm, "_run", fake_run)

    session = gui_confirm.find_graphical_session()

    assert session is not None
    assert session.user == "bycybadmin"
    assert session.display == ":0"


def test_find_graphical_session_skips_inactive_sessions(monkeypatch):
    monkeypatch.setattr(gui_confirm.shutil, "which", lambda name: "/usr/bin/loginctl")

    def fake_run(cmd):
        if cmd[:2] == ["loginctl", "list-sessions"]:
            return "2 1000 bycybadmin seat0 tty2\n"
        if cmd[:2] == ["loginctl", "show-session"]:
            return "Name=bycybadmin\nDisplay=:0\nState=closing\n"
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(gui_confirm, "_run", fake_run)

    assert gui_confirm.find_graphical_session() is None


def test_ask_confirmation_gui_returns_none_without_zenity(monkeypatch):
    monkeypatch.setattr(gui_confirm.shutil, "which", lambda name: None)

    assert gui_confirm.ask_confirmation_gui("test") is None


def test_ask_confirmation_gui_returns_none_without_session(monkeypatch):
    monkeypatch.setattr(gui_confirm.shutil, "which", lambda name: "/usr/bin/zenity")
    monkeypatch.setattr(gui_confirm, "find_graphical_session", lambda: None)

    assert gui_confirm.ask_confirmation_gui("test") is None


def test_ask_confirmation_gui_true_when_authorized(monkeypatch):
    monkeypatch.setattr(gui_confirm.shutil, "which", lambda name: "/usr/bin/zenity")
    monkeypatch.setattr(
        gui_confirm, "find_graphical_session",
        lambda: gui_confirm.GraphicalSession(user="bycybadmin", display=":0"),
    )
    monkeypatch.setattr(gui_confirm, "_find_xauthority", lambda user: None)

    class FakeCompleted:
        returncode = 0

    calls = {}

    def fake_run(cmd, check=False):
        calls["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(gui_confirm.subprocess, "run", fake_run)

    result = gui_confirm.ask_confirmation_gui("Lancer la sanitisation ?")

    assert result is True
    assert "zenity" in calls["cmd"]
    assert "--ok-label=Autoriser" in calls["cmd"]
    assert "--cancel-label=Refuser" in calls["cmd"]


def test_ask_confirmation_gui_false_when_refused(monkeypatch):
    monkeypatch.setattr(gui_confirm.shutil, "which", lambda name: "/usr/bin/zenity")
    monkeypatch.setattr(
        gui_confirm, "find_graphical_session",
        lambda: gui_confirm.GraphicalSession(user="bycybadmin", display=":0"),
    )
    monkeypatch.setattr(gui_confirm, "_find_xauthority", lambda user: None)

    class FakeCompleted:
        returncode = 1

    monkeypatch.setattr(gui_confirm.subprocess, "run", lambda cmd, check=False: FakeCompleted())

    assert gui_confirm.ask_confirmation_gui("Lancer la sanitisation ?") is False
