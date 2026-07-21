# region MODULE_CONTRACT
# PURPOSE: Assert parse_engine_section raises ValueError (not AttributeError) when spawn is missing (D2).
# SCOPE: Missing-spawn ValueError hoist; spawn-present happy path.
# KEYWORDS: parse_engine_section, spawn, ValueError, AttributeError
# endregion MODULE_CONTRACT

from __future__ import annotations

from configparser import ConfigParser
from pathlib import PurePath

import pytest

from yascheduler.entrypoints.config_parser import parse_engine_section


def test_parse_engine_section_raises_value_error_on_missing_spawn() -> None:
    """Missing spawn key → ValueError naming the engine, not AttributeError from _check_spawn."""
    cfg = ConfigParser()
    cfg.read_string(
        "[engine.fleur]\n"
        "check_cmd=echo ok\n"
        "input_files=input.txt\n"
        "output_files=output.txt\n",
    )
    with pytest.raises(ValueError, match=r"fleur.*has no spawn command"):
        parse_engine_section(cfg["engine.fleur"], PurePath())


def test_parse_engine_section_does_not_raise_when_spawn_present() -> None:
    """Spawn present → no exception, Engine.spawn carries the value."""
    cfg = ConfigParser()
    cfg.read_string(
        "[engine.fleur]\n"
        "spawn=echo hi\n"
        "check_cmd=echo ok\n"
        "input_files=input.txt\n"
        "output_files=output.txt\n",
    )
    engine = parse_engine_section(cfg["engine.fleur"], PurePath())
    assert engine.spawn == "echo hi"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
