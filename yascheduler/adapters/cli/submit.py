# FILE: yascheduler/adapters/cli/submit.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: yasubmit CLI command — parse AiiDA script, submit task via DI.
#   SCOPE: submit command + script metadata and input file helpers.
#   DEPENDS: M-DI, M-CONFIG, M-VARIABLES
#   LINKS: M-CLI-COMMANDS, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   submit - Submit task via AiiDA script
#   _parse_script_metadata - Parse key=value pairs from script text
#   _read_input_files - Read engine input files from disk
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from adapters/cli/commands.py per-command split.
# END_CHANGE_SUMMARY

import argparse
import base64
import logging
import os
from pathlib import Path
from typing import Any

from yascheduler.client import to_sync
from yascheduler.config import Config, Engine
from yascheduler.di import make_cli_deps
from yascheduler.variables import CONFIG_FILE


def _parse_script_metadata(script_text: str) -> dict[str, str]:
    """Parse key=value pairs from script file content."""
    script_params = {}
    for line in script_text.splitlines():
        try:
            k, v = line.split("=")
            script_params[k.strip()] = v.strip()
        except ValueError:
            pass
    return script_params


def _read_input_files(engine: Engine, local_folder: str) -> dict[str, str]:
    """Read input files specified by engine config, return dict of filename -> content."""
    metadata: dict[str, str] = {}
    for input_file in engine.input_files:
        path = Path(local_folder, input_file)
        try:
            metadata[input_file] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            with open(path, "rb") as f:
                metadata[input_file] = base64.b64encode(f.read()).decode("ascii")
    return metadata


# START_CONTRACT: submit
#   PURPOSE: Parse AiiDA script file and submit a task via CLIDeps
#   INPUTS: { None - reads CLI args via argparse }
#   OUTPUTS: { None - prints task ID to stdout }
#   SIDE_EFFECTS: Reads script file and input files from disk, creates DB task
#   LINKS: M-CLI-COMMANDS, M-DI
# END_CONTRACT: submit
@to_sync
async def submit() -> None:
    parser = argparse.ArgumentParser(
        description="Submit task to yascheduler via AiiDA script"
    )
    parser.add_argument("script")

    args = parser.parse_args()
    script_file = Path(args.script)
    if not script_file.exists():  # noqa: ASYNC240
        raise ValueError("Script parameter is not a file name")

    logging.captureWarnings(True)
    log = logging.getLogger()
    log.setLevel(logging.WARN)

    config = Config.from_config_parser(CONFIG_FILE)
    deps = make_cli_deps(config)

    script_params = _parse_script_metadata(script_file.read_text())  # noqa: ASYNC240

    label = script_params.get("LABEL", "AiiDA job")
    metadata: dict[str, Any] = {"local_folder": os.getcwd()}

    engine_name = script_params.get("ENGINE")
    if not engine_name:
        raise ValueError("Script has not defined an engine")

    engine = config.engines.get(engine_name)
    if not engine:
        raise ValueError(f"Engine {engine_name} is not supported")

    metadata.update(_read_input_files(engine, metadata["local_folder"]))

    if "PARENT" in script_params and config.local.webhook_url:
        metadata["webhook_url"] = config.local.webhook_url
        metadata["webhook_custom_params"] = {"parent": script_params["PARENT"]}

    task_id = await deps.submit(label, dict(metadata), engine.name)
    print(str(task_id))
