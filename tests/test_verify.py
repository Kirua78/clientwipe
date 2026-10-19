from clientwipe.config import Config, SanitizeTarget
from clientwipe.verify import verify


def test_verify_passes_when_targets_absent(tmp_path):
    config = Config(targets=[SanitizeTarget(name="ssh", patterns=[".ssh/id_*"])], passes=1)

    report = verify(tmp_path, config)

    assert report.passed
    assert report.targets[0].residual_files == []


def test_verify_fails_when_residual_file_remains(tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("still here", encoding="utf-8")

    config = Config(targets=[SanitizeTarget(name="ssh", patterns=[".ssh/id_*"])], passes=1)
    report = verify(tmp_path, config)

    assert not report.passed
    assert str(tmp_path / ".ssh" / "id_rsa") in report.targets[0].residual_files
