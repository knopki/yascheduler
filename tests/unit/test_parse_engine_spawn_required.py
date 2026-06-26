# FILE: tests/unit/test_parse_engine_spawn_required.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Assert parse_engine_section raises ValueError (not AttributeError) when spawn is missing (D2).
#   SCOPE: Missing-spawn ValueError hoist; spawn-present happy path.
#   DEPENDS: M-ENTRYPOINTS-CONFIG-PARSER, M-DOMAIN-ENGINE
#   LINKS: M-ENTRYPOINTS-CONFIG-PARSER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_parse_engine_section_raises_value_error_on_missing_spawn  - missing spawn → ValueError naming the engine
#   test_parse_engine_section_does_not_raise_when_spawn_present    - spawn present → Engine.spawn == the value
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Assert missing-spawn raises ValueError (not AttributeError) from the hoisted check in parse_engine_section (resolve-type-bridge-debt / D2).
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

from configparser import ConfigParser
from pathlib import PurePath

import pytest

from yascheduler.entrypoints.config_parser import parse_engine_section


def test_parse_engine_section_raises_value_error_on_missing_spawn() -> None:
    """missing spawn key → ValueError naming the engine, not AttributeError from _check_spawn."""
    cfg = ConfigParser()
    cfg.read_string(
        "[engine.fleur]\n"
        "check_cmd=echo ok\n"
        "input_files=input.txt\n"
        "output_files=output.txt\n"
    )
    with pytest.raises(ValueError, match="fleur.*has no spawn command"):
        parse_engine_section(cfg["engine.fleur"], PurePath("."))


def test_parse_engine_section_does_not_raise_when_spawn_present() -> None:
    """spawn present → no exception, Engine.spawn carries the value."""
    cfg = ConfigParser()
    cfg.read_string(
        "[engine.fleur]\n"
        "spawn=echo hi\n"
        "check_cmd=echo ok\n"
        "input_files=input.txt\n"
        "output_files=output.txt\n"
    )
    engine = parse_engine_section(cfg["engine.fleur"], PurePath("."))
    assert engine.spawn == "echo hi"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
