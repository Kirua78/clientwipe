import pytest

from clientwipe.config import Config


def test_load_parses_full_reset_section(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "targets:\n"
        "  - name: ssh\n"
        "    patterns: ['.ssh/id_*']\n"
        "full_reset:\n"
        "  device: /dev/sda3\n"
        "  boot_entry: Clonezilla Recovery\n",
        encoding="utf-8",
    )

    config = Config.load(config_path)

    assert config.full_reset is not None
    assert config.full_reset.device == "/dev/sda3"
    assert config.full_reset.boot_entry == "Clonezilla Recovery"


def test_load_allows_full_reset_only_config_without_targets(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "full_reset:\n"
        "  device: /dev/sda3\n"
        "  boot_entry: Clonezilla Recovery\n",
        encoding="utf-8",
    )

    config = Config.load(config_path)

    assert config.targets == []
    assert config.full_reset is not None


def test_load_raises_when_neither_targets_nor_full_reset_defined(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("passes: 3\n", encoding="utf-8")

    with pytest.raises(ValueError):
        Config.load(config_path)
