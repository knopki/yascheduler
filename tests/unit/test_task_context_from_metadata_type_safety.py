# FILE: tests/unit/test_task_context_from_metadata_type_safety.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Assert TaskContext.from_metadata raises TypeError on non-str values under str|None keys (D5).
#   SCOPE: 4 str|None field TypeErrors; None acceptance; engine str() coercion; webhook_custom_params dict guard + fallback.
#   DEPENDS: M-DOMAIN-MODEL
#   LINKS: M-DOMAIN-MODEL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_from_metadata_raises_type_error_on_non_str_remote_folder  - int remote_folder → TypeError
#   test_from_metadata_raises_type_error_on_non_str_local_folder   - list local_folder → TypeError
#   test_from_metadata_raises_type_error_on_non_str_webhook_url    - dict webhook_url → TypeError
#   test_from_metadata_raises_type_error_on_non_str_error          - float error → TypeError
#   test_from_metadata_accepts_none_for_str_or_none_fields         - None remote_folder/error → no exception
#   test_from_metadata_coerces_engine_to_str                       - int engine → "42"
#   test_from_metadata_accepts_dict_for_webhook_custom_params      - dict wcp → preserved
#   test_from_metadata_falls_back_to_empty_dict_for_non_dict_webhook_custom_params - str wcp → {} (no TypeError)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Assert _get_opt_str boundary raises TypeError on non-str/non-None for the 4 str|None fields; engine str() coercion and webhook_custom_params dict-guard fallback preserved (resolve-type-bridge-debt / D5).
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from __future__ import annotations

import pytest

from yascheduler.domain.model import TaskContext


def test_from_metadata_raises_type_error_on_non_str_remote_folder() -> None:
    with pytest.raises(TypeError, match="remote_folder.*int"):
        TaskContext.from_metadata({"engine": "fleur", "remote_folder": 123})


def test_from_metadata_raises_type_error_on_non_str_local_folder() -> None:
    with pytest.raises(TypeError, match="local_folder"):
        TaskContext.from_metadata({"engine": "fleur", "local_folder": ["a", "b"]})


def test_from_metadata_raises_type_error_on_non_str_webhook_url() -> None:
    with pytest.raises(TypeError, match="webhook_url"):
        TaskContext.from_metadata({"engine": "fleur", "webhook_url": {"k": "v"}})


def test_from_metadata_raises_type_error_on_non_str_error() -> None:
    with pytest.raises(TypeError, match="error"):
        TaskContext.from_metadata({"engine": "fleur", "error": 4.5})


def test_from_metadata_accepts_none_for_str_or_none_fields() -> None:
    ctx = TaskContext.from_metadata(
        {"engine": "fleur", "remote_folder": None, "error": None}
    )
    assert ctx.remote_folder is None
    assert ctx.error is None
    assert ctx.engine == "fleur"


def test_from_metadata_coerces_engine_to_str() -> None:
    ctx = TaskContext.from_metadata({"engine": 42})
    assert ctx.engine == "42"


def test_from_metadata_accepts_dict_for_webhook_custom_params() -> None:
    ctx = TaskContext.from_metadata(
        {"engine": "fleur", "webhook_custom_params": {"k": "v"}}
    )
    assert ctx.webhook_custom_params == {"k": "v"}


def test_from_metadata_falls_back_to_empty_dict_for_non_dict_webhook_custom_params() -> (
    None
):
    ctx = TaskContext.from_metadata(
        {"engine": "fleur", "webhook_custom_params": "not-a-dict"}
    )
    assert ctx.webhook_custom_params == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
