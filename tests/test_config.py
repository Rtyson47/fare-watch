import pytest

from farewatch import config


def test_set_base_rejects_bad_codes(sample_config):
    for bad in ["lhr7", "XX", "LHRR", "12A", ""]:
        with pytest.raises(ValueError):
            config.set_base(bad, path=str(sample_config))


def test_set_base_updates_and_templates(sample_config):
    config.set_base("LHR", path=str(sample_config))
    cfg = config.load_config(str(sample_config))
    assert cfg["current_base"] == "LHR"
    # {BASE} in corridor origin resolves to the new base
    assert cfg["corridors"][0]["origin"] == "LHR"
    # {BASE} in inspiration origins list resolves too
    assert cfg["inspiration"]["origins"] == ["LHR"]


def test_set_base_lowercases_input(sample_config):
    config.set_base("cun", path=str(sample_config))
    assert config.load_config(str(sample_config))["current_base"] == "CUN"


def test_validate_flags_missing_destination(sample_config):
    cfg = config.load_config(str(sample_config))
    cfg["corridors"][0].pop("destination")
    problems = config.validate_config(cfg)
    assert any("destination" in p for p in problems)


def test_validate_ok_on_example(sample_config):
    cfg = config.load_config(str(sample_config))
    assert config.validate_config(cfg) == []
