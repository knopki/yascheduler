"""yasubmit CLI command — parse AiiDA script and submit task via DI."""
# region MODULE_CONTRACT
# PURPOSE: yasubmit CLI command — parse an AiiDA submission script, read input files, and submit a task via the DI layer.
# SCOPE: submit command — parse AiiDA script and submit task via DI.
# KEYWORDS: submit, cli, aiida, script, task
# endregion MODULE_CONTRACT

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yascheduler.entrypoints import Config, make_cli_deps
from yascheduler.entrypoints.config_parser import parse_config

from .args import (
    add_config_arg,
    add_log_level_arg,
    existing_path,
)

if TYPE_CHECKING:
    from yascheduler.domain import Engine


class EngineNotDefinedError(ValueError):
    """Script has not defined an engine."""

    def __init__(self) -> None:
        super().__init__("Script has not defined an engine")


class EngineNotSupportedError(ValueError):
    """Engine is not supported."""

    def __init__(self, engine_name: str) -> None:
        super().__init__(f"Engine {engine_name} is not supported")


def _parse_submit_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yasubmit",
        description="Submit task to yascheduler via AiiDA script",
    )
    parser.add_argument("script", type=existing_path)
    add_config_arg(parser)
    add_log_level_arg(parser, default="WARNING")
    # region BLOCK_parse_args
    return parser.parse_args(argv)
    # endregion BLOCK_parse_args


def _parse_script_metadata(script_text: str) -> dict[str, str]:
    script_params: dict[str, str] = {}
    for line in script_text.splitlines():
        try:
            k, v = line.split("=")
            script_params[k.strip()] = v.strip()
        except ValueError:  # noqa: PERF203
            pass
    return script_params


def _read_input_files(engine: Engine, local_folder: str | Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for input_file in engine.input_files:
        path = Path(local_folder, input_file)
        try:
            metadata[input_file] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            with path.open("rb") as f:
                metadata[input_file] = base64.b64encode(f.read()).decode("ascii")
    return metadata


def _build_metadata(
    script_params: dict[str, str],
    config: Config,
    local_folder: str | Path,
) -> dict[str, Any]:
    # region BLOCK_build_metadata
    metadata: dict[str, Any] = {"local_folder": str(local_folder)}
    engine = config.engines.get(script_params.get("ENGINE", ""))
    if engine is not None:
        metadata.update(_read_input_files(engine, local_folder))
    if "PARENT" in script_params and config.local.webhook_url:
        metadata["webhook_url"] = config.local.webhook_url
        metadata["webhook_custom_params"] = {"parent": script_params["PARENT"]}
    # endregion BLOCK_build_metadata
    return metadata


# region FUNC__submit_async
# PURPOSE: Parse AiiDA script file and submit a task via CLIDeps; exit 0 on success, 1 on runtime error, 2 on argparse error.
async def _submit_async(argv: list[str] | None) -> None:
    args = _parse_submit_args(argv)
    script_file: Path = args.script

    # region BLOCK_handle_failure
    try:
        logging.captureWarnings(True)
        log = logging.getLogger()
        log.setLevel(logging.getLevelName(args.log_level))
        if not log.handlers:
            log.addHandler(logging.StreamHandler(sys.stderr))

        # region BLOCK_configure
        config = parse_config(args.config)
        deps = make_cli_deps(config)
        # endregion BLOCK_configure

        script_params = _parse_script_metadata(script_file.read_text())  # noqa: ASYNC240
        label = script_params.get("LABEL", "AiiDA job")

        # region BLOCK_validate_content
        engine_name = script_params.get("ENGINE")
        if not engine_name:
            raise EngineNotDefinedError  # noqa: TRY301
        engine = config.engines.get(engine_name)
        if not engine:
            raise EngineNotSupportedError(engine_name)  # noqa: TRY301
        # endregion BLOCK_validate_content

        metadata = _build_metadata(script_params, config, Path.cwd())

        # region BLOCK_submit
        task_id = await deps.submit(label, dict(metadata), engine.name)
        sys.stdout.write(f"{task_id!s}\n")
        # endregion BLOCK_submit
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    # endregion BLOCK_handle_failure


# endregion FUNC__submit_async


# region FUNC_submit
# PURPOSE: Sync entry point — run _submit_async via asyncio.run (no @to_sync; CLI entry points have no async caller).
def submit(argv: list[str] | None = None) -> None:
    """Sync entry point — runs _submit_async via asyncio.run."""
    asyncio.run(_submit_async(argv))


# endregion FUNC_submit

if __name__ == "__main__":
    submit()
