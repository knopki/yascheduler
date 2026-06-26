# FILE: yascheduler/entrypoints/cli/submit.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: yasubmit CLI command — parse AiiDA script, submit task via DI.
#   SCOPE: submit command + argparse + script metadata/input file helpers + metadata assembly.
#   DEPENDS: M-DI, M-ENTRYPOINTS-CONFIG, M-DOMAIN-ENGINE, M-SHARED, M-ENTRYPOINTS-CLI-ARGS
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT, M-DI, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   submit - Sync entry point: asyncio.run(_submit_async(argv))
#   _submit_async - Parse AiiDA script, build metadata, submit task via DI; exit 0/1/2
#   _parse_submit_args - argparse → Namespace (--config/--log-level + positional script)
#   _parse_script_metadata - Parse key=value pairs from script text
#   _read_input_files - Read engine input files from disk
#   _build_metadata - Assemble task metadata dict with webhook branch
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Runtime import Engine from yascheduler.domain (split from Config which stays from yascheduler.config) (engine-to-domain-frozen).
#   PREVIOUS_CHANGE: v1.1.1 - post-review fix: added StreamHandler→stderr guard (`if not log.handlers:`) so --log-level DEBUG produces visible output (was relying on logging.lastResort at WARNING only).
# END_CHANGE_SUMMARY

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import os
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


# START_CONTRACT: _parse_submit_args
#   PURPOSE: Parse yasubmit argparse — one positional script path (type=existing_path) plus shared --config and --log-level flags.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv }
#   OUTPUTS: { argparse.Namespace - parsed args with .script as Path, .config as Path, .log_level as str }
#   SIDE_EFFECTS: argparse may call sys.exit on --help/error (exit 0/2).
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT, M-ENTRYPOINTS-CLI-ARGS
# END_CONTRACT: _parse_submit_args
def _parse_submit_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yasubmit",
        description="Submit task to yascheduler via AiiDA script",
    )
    parser.add_argument("script", type=existing_path)
    add_config_arg(parser)
    add_log_level_arg(parser, default="WARNING")
    # START_BLOCK_PARSE_ARGS
    args = parser.parse_args(argv)
    # END_BLOCK_PARSE_ARGS
    return args


# START_CONTRACT: _parse_script_metadata
#   PURPOSE: Parse key=value pairs from AiiDA script file content; malformed lines ignored.
#   INPUTS: { script_text: str - raw script text }
#   OUTPUTS: { dict[str, str] - key → value mapping }
#   SIDE_EFFECTS: None
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT
# END_CONTRACT: _parse_script_metadata
def _parse_script_metadata(script_text: str) -> dict[str, str]:
    script_params: dict[str, str] = {}
    for line in script_text.splitlines():
        try:
            k, v = line.split("=")
            script_params[k.strip()] = v.strip()
        except ValueError:
            pass
    return script_params


# START_CONTRACT: _read_input_files
#   PURPOSE: Read input files declared by engine config, return filename → content; base64 fallback for binary.
#   INPUTS: { engine: Engine - declares .input_files, local_folder: str - folder containing the files }
#   OUTPUTS: { dict[str, str] - filename → text content or base64-encoded bytes }
#   SIDE_EFFECTS: Reads files from disk.
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT
# END_CONTRACT: _read_input_files
def _read_input_files(engine: Engine, local_folder: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for input_file in engine.input_files:
        path = Path(local_folder, input_file)
        try:
            metadata[input_file] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            with open(path, "rb") as f:
                metadata[input_file] = base64.b64encode(f.read()).decode("ascii")
    return metadata


# START_CONTRACT: _build_metadata
#   PURPOSE: Assemble the task metadata dict — local_folder, engine input files, webhook branch when PARENT and webhook_url set.
#   INPUTS: { script_params: dict[str, str] - parsed script, config: Config - engines + local.webhook_url, local_folder: str }
#   OUTPUTS: { dict[str, Any] - metadata with local_folder, input files, and optional webhook_url/webhook_custom_params }
#   SIDE_EFFECTS: Reads input files from disk via _read_input_files.
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT
#   NOTE: Promotion to application/submit_script.py awaits a second consumer; today only yasubmit parses AiiDA scripts.
# END_CONTRACT: _build_metadata
def _build_metadata(
    script_params: dict[str, str],
    config: Config,
    local_folder: str,
) -> dict[str, Any]:
    # START_BLOCK_BUILD_METADATA
    metadata: dict[str, Any] = {"local_folder": local_folder}
    engine = config.engines.get(script_params.get("ENGINE", ""))
    if engine is not None:
        metadata.update(_read_input_files(engine, local_folder))
    if "PARENT" in script_params and config.local.webhook_url:
        metadata["webhook_url"] = config.local.webhook_url
        metadata["webhook_custom_params"] = {"parent": script_params["PARENT"]}
    # END_BLOCK_BUILD_METADATA
    return metadata


# START_CONTRACT: _submit_async
#   PURPOSE: Parse AiiDA script file and submit a task via CLIDeps; exit 0 on success, 1 on runtime error, 2 on argparse error.
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv (console_script default) }
#   OUTPUTS: { None - prints str(task_id) to stdout on success, Error: ... to stderr on failure, calls sys.exit(1) on failure }
#   SIDE_EFFECTS: Reads script + input files from disk, creates DB task via deps.submit, may call sys.exit.
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT, M-DI
# END_CONTRACT: _submit_async
async def _submit_async(argv: list[str] | None) -> None:
    # START_BLOCK_PARSE_ARGS
    args = _parse_submit_args(argv)
    script_file: Path = args.script
    # END_BLOCK_PARSE_ARGS

    # START_BLOCK_HANDLE_FAILURE
    try:
        logging.captureWarnings(True)
        log = logging.getLogger()
        log.setLevel(logging.getLevelName(args.log_level))
        if not log.handlers:
            log.addHandler(logging.StreamHandler(sys.stderr))

        # START_BLOCK_CONFIGURE
        config = parse_config(args.config)
        deps = make_cli_deps(config)
        # END_BLOCK_CONFIGURE

        script_params = _parse_script_metadata(script_file.read_text())  # noqa: ASYNC240
        label = script_params.get("LABEL", "AiiDA job")

        # START_BLOCK_VALIDATE_CONTENT
        engine_name = script_params.get("ENGINE")
        if not engine_name:
            raise ValueError("Script has not defined an engine")
        engine = config.engines.get(engine_name)
        if not engine:
            raise ValueError(f"Engine {engine_name} is not supported")
        # END_BLOCK_VALIDATE_CONTENT

        metadata = _build_metadata(script_params, config, os.getcwd())

        # START_BLOCK_SUBMIT
        task_id = await deps.submit(label, dict(metadata), engine.name)
        print(str(task_id))
        # END_BLOCK_SUBMIT
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    # END_BLOCK_HANDLE_FAILURE


# START_CONTRACT: submit
#   PURPOSE: Sync entry point — run _submit_async via asyncio.run (no @to_sync; CLI entry points have no async caller).
#   INPUTS: { argv: list[str] | None - optional argv, None reads sys.argv (console_script default) }
#   OUTPUTS: { None - delegates to asyncio.run }
#   SIDE_EFFECTS: Starts a fresh event loop via asyncio.run.
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT
# END_CONTRACT: submit
def submit(argv: list[str] | None = None) -> None:
    asyncio.run(_submit_async(argv))


if __name__ == "__main__":
    submit()
