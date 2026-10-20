from pathlib import Path

from clientwipe.cli import main


def test_full_pipeline_demo_to_certificate(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "sanitize_targets.yaml"
    config_path.write_text(
        "passes: 1\ntargets:\n  - name: ssh\n    patterns: ['.ssh/id_*']\n",
        encoding="utf-8",
    )

    assert main(["demo", "--path", "demo/sandbox"]) == 0
    assert (tmp_path / "demo" / "sandbox" / ".ssh" / "id_rsa").exists()

    exit_code = main(["run", "--root", "demo/sandbox", "--config", str(config_path), "--yes"])
    assert exit_code == 0
    assert not (tmp_path / "demo" / "sandbox" / ".ssh" / "id_rsa").exists()

    out = capsys.readouterr().out
    assert "Verification: OK" in out

    verify_exit_code = main(["verify", "--root", "demo/sandbox", "--config", str(config_path)])
    assert verify_exit_code == 0


def test_run_refuses_non_sandbox_root_without_yes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    real_root = tmp_path / "real-workstation"
    real_root.mkdir()

    config_path = tmp_path / "sanitize_targets.yaml"
    config_path.write_text(
        "passes: 1\ntargets:\n  - name: ssh\n    patterns: ['.ssh/id_*']\n",
        encoding="utf-8",
    )

    exit_code = main(["run", "--root", str(real_root), "--config", str(config_path)])

    assert exit_code == 2
    assert "ATTENTION" in capsys.readouterr().err


def test_trigger_without_tty_fails_safe_instead_of_crashing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    allowlist_path = tmp_path / "allowed.txt"
    allowlist_path.write_text("AB12CD34\n", encoding="utf-8")

    config_path = tmp_path / "sanitize_targets.yaml"
    config_path.write_text(
        "passes: 1\ntargets:\n  - name: ssh\n    patterns: ['.ssh/id_*']\n",
        encoding="utf-8",
    )

    def raise_eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    # No desktop session to fall back to in this test environment either.
    monkeypatch.setattr("clientwipe.gui_confirm.ask_confirmation_gui", lambda message, timeout=30: None)

    exit_code = main([
        "trigger",
        "--serial", "AB12CD34",
        "--allowlist", str(allowlist_path),
        "--config", str(config_path),
        "--root", str(tmp_path),
    ])

    assert exit_code == 1
    assert "terminal interactif" in capsys.readouterr().err
