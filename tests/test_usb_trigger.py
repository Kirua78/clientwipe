from clientwipe.usb_trigger import is_allowed, load_allowlist


def test_load_allowlist_ignores_blank_and_comment_lines(tmp_path):
    allowlist = tmp_path / "allowed.txt"
    allowlist.write_text("# comment\n\nAB12CD34\n", encoding="utf-8")

    assert load_allowlist(allowlist) == {"AB12CD34"}


def test_load_allowlist_missing_file_returns_empty_set(tmp_path):
    assert load_allowlist(tmp_path / "does-not-exist.txt") == set()


def test_is_allowed_true_for_known_serial(tmp_path):
    allowlist = tmp_path / "allowed.txt"
    allowlist.write_text("AB12CD34\n", encoding="utf-8")

    assert is_allowed("AB12CD34", allowlist) is True


def test_is_allowed_false_for_unknown_or_missing_serial(tmp_path):
    allowlist = tmp_path / "allowed.txt"
    allowlist.write_text("AB12CD34\n", encoding="utf-8")

    assert is_allowed("UNKNOWN", allowlist) is False
    assert is_allowed(None, allowlist) is False
    assert is_allowed("", allowlist) is False
