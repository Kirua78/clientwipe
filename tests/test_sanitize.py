from clientwipe.config import Config, SanitizeTarget
from clientwipe.sanitize import resolve_target_files, sanitize, secure_delete_file


def test_secure_delete_file_removes_file_and_returns_size(tmp_path):
    f = tmp_path / "secret.txt"
    data = b"super-secret-data"
    f.write_bytes(data)

    size = secure_delete_file(f, passes=2, use_shred=False)

    assert size == len(data)
    assert not f.exists()


def test_resolve_target_files_matches_glob_pattern(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.burp").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")

    target = SanitizeTarget(name="burp", patterns=["**/*.burp"])
    files = resolve_target_files(tmp_path, target)

    assert files == [tmp_path / "sub" / "a.burp"]


def test_sanitize_wipes_matching_files_only(tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("private-key", encoding="utf-8")
    (tmp_path / "keep.txt").write_text("not targeted", encoding="utf-8")

    config = Config(targets=[SanitizeTarget(name="ssh", patterns=[".ssh/id_*"])], passes=1)
    report = sanitize(tmp_path, config)

    assert report.total_files_wiped == 1
    assert report.targets[0].errors == []
    assert not (tmp_path / ".ssh" / "id_rsa").exists()
    assert (tmp_path / "keep.txt").exists()


def test_sanitize_records_errors_without_raising(tmp_path, monkeypatch):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("private-key", encoding="utf-8")

    def boom(path, passes=3, use_shred=None):
        raise OSError("permission denied (simulated)")

    monkeypatch.setattr("clientwipe.sanitize.secure_delete_file", boom)

    config = Config(targets=[SanitizeTarget(name="ssh", patterns=[".ssh/id_*"])], passes=1)
    report = sanitize(tmp_path, config)

    assert report.total_files_wiped == 0
    assert len(report.targets[0].errors) == 1
