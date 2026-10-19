import json
from pathlib import Path

from clientwipe.certificate import generate_certificate
from clientwipe.config import Config, SanitizeTarget
from clientwipe.sanitize import sanitize
from clientwipe.verify import verify


def test_generate_certificate_reports_pass_and_writes_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / ".bash_history").write_text("ssh root@10.0.0.1", encoding="utf-8")

    config = Config(targets=[SanitizeTarget(name="history", patterns=[".bash_history"])], passes=1)
    sanitize_report = sanitize(root, config)
    verify_report = verify(root, config)

    out_dir = tmp_path / "certificates"
    result = generate_certificate(sanitize_report, verify_report, out_dir, operator="test-operator")

    assert result["overall_passed"] is True
    json_path = Path(result["json_path"])
    assert json_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["operator"] == "test-operator"
    assert payload["overall_passed"] is True
    assert payload["sha256"] == result["sha256"]

    assert Path(result["html_path"]).exists()
    assert "SANITISATION VALIDEE" in Path(result["html_path"]).read_text(encoding="utf-8")


def test_generate_certificate_reports_failure_when_residual_file_remains(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / ".bash_history").write_text("ssh root@10.0.0.1", encoding="utf-8")

    config = Config(targets=[SanitizeTarget(name="history", patterns=[".bash_history"])], passes=1)
    sanitize_report = sanitize(root, config)
    # Simulate a residual file surviving the wipe.
    (root / ".bash_history").write_text("leftover", encoding="utf-8")
    verify_report = verify(root, config)

    result = generate_certificate(sanitize_report, verify_report, tmp_path / "certificates")

    assert result["overall_passed"] is False
    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "ECHEC" in html
