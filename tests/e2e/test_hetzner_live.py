# FILE: tests/e2e/test_hetzner_live.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Real-Hetzner cloud-provider E2E test — autoscale -> allocate -> download -> idle-deallocate happy path against a live Hetzner Cloud account.
#   SCOPE: opt-in env-gated test (YASCHEDULER_TEST_HETZNER=1 + token); drives make_daemon + _submit_async; asserts VM creation, both jobs DONE with matching outputs, idle deallocation, strong deletion via find_srv; guaranteed observed-IP cleanup with loud-fail-on-leak in finally.
#   DEPENDS: M-DI, M-ENTRYPOINTS-CLI-SUBMIT, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ALLOCATE, M-APPLICATION-DEALLOCATE, M-CLOUD-PROVIDER-HETZNER, M-PERSISTENCE-UOW
#   LINKS: M-DI, M-ENTRYPOINTS-CLI-SUBMIT, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ALLOCATE, M-APPLICATION-DEALLOCATE, M-CLOUD-PROVIDER-HETZNER, M-PERSISTENCE-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _cloud_env_or_skip - read opt-in env gate (YASCHEDULER_TEST_HETZNER + token) + provider knobs; pytest.skip when unset
#   hetzner_config     - session-scoped Config fixture: temp INI with [db]/[local]/[remote]/[engine.test_shell]/[clouds](max_nodes=1, hetzner_package_upgrade=false)
#   _ini_path_from_env - read YASCHEDULER_CONF_PATH published by hetzner_config
#   _assert_vm_deleted - poll find_srv(client, ip) until None; pytest.fail naming the leaked IP otherwise
#   _cleanup_observed  - best-effort hetzner_delete_node per observed IP, then strong _assert_vm_deleted per IP
#   _submit_two_jobs   - submit 2 tasks via _submit_async in per-job temp CWDs with distinct payloads
#   _poll_for_hetzner_node - poll uow.nodes.list_all() until a cloud=="hetzner" node appears; record its IP
#   _wait_both_done    - poll until both tasks DONE, capturing RUNNING node.ip snapshots
#   _assert_outputs    - assert each task DONE, error None, local_folder set, 1.input.out matches payload, resolved node.ip is an observed hetzner IP, created_at/updated_at present
#   _assert_cloud_logs - assert CLOUD_DONE (provider=hetzner) and CLOUD_DELETE (cloud=hetzner) log records captured
#   _poll_node_gone    - poll uow.nodes.list_all() until no cloud=="hetzner" row remains
#   test_hetzner_live  - full live e2e scenario
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - task-schema-and-entity-cleanup: t.allocated_ip -> node.ip via uow.nodes.get_by_id(t.allocated_node_id); assert created_at/updated_at on DONE tasks.
#   PREVIOUS_CHANGE: v1.0.0 - add-hetzner-live-e2e: new opt-in env-gated real-Hetzner e2e exercising the cold-start autoscale -> allocate -> download -> idle-deallocate happy path through the real entrypoints (make_daemon, _submit_async) and asserting via uow_factory. Hetzner hcloud SDK is imported lazily inside helpers so module collection succeeds without the optional extra; the env gate (YASCHEDULER_TEST_HETZNER=1 + YASCHEDULER_CLOUDS_HETZNER_TOKEN) skips by default. Cleanup is observed-IP based with a loud-fail-on-leak finally; a strong find_srv deletion assertion complements DB-row removal. Refined via a live run: _poll_for_hetzner_node requires n.enabled (the tmp node inserted by _select_and_insert_tmp has cloud=hetzner/enabled=False with a placeholder IP); CLOUD_DELETE is asserted after _poll_node_gone (it is emitted by the idle-deallocate loop, not at completion); timeouts sized to the observed ~83s cold-start.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from yascheduler.domain.model import TaskId
from yascheduler.domain.model import TaskStatus as DomainTaskStatus
from yascheduler.entrypoints.cli.submit import _submit_async
from yascheduler.entrypoints.config_parser import parse_config
from yascheduler.entrypoints.di import make_daemon

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.entrypoints import Config
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork

log = logging.getLogger("e2e.test_hetzner_live")

# Timeouts sized to observed real-Hetzner cold-start: VM create + boot +
# cloud-init + setup_node takes ~80-90s with package_upgrade=false; the two
# test_shell jobs (3s each) finish seconds after the node is enabled; idle
# deallocate fires ~idle_tolerance(5)s later. Margins are ~1.4x the observed
# values — tight enough to fail fast on a real regression, generous enough to
# absorb Hetzner variance.
_AUTOSCALE_TIMEOUT_S = 120.0
_COMPLETION_TIMEOUT_S = 60.0
_DEALLOC_TIMEOUT_S = 60.0
_VM_DELETE_TIMEOUT_S = 30.0
_POLL_INTERVAL_S = 1.0

_CLOUD_DONE_MARKER = "[AllocateTask][allocate_task][CLOUD_DONE]"
_CLOUD_DELETE_MARKER = "[deallocate_node][CLOUD_DELETE]"


# START_CONTRACT: _cloud_env_or_skip
#   PURPOSE: Read the opt-in env gate (YASCHEDULER_TEST_HETZNER == "1" + non-empty token) and provider knobs; pytest.skip naming the missing var when the gate is not satisfied. Imports NOTHING optional (no hcloud) so module collection + skip work without the SDK installed.
#   INPUTS: { None }
#   OUTPUTS: { tuple[str, str, str, str] - (token, server_type, location, image_name) }
#   SIDE_EFFECTS: pytest.skip(...) when the gate is unset; reads process environment.
#   LINKS: M-CLOUD-PROVIDER-HETZNER
# END_CONTRACT: _cloud_env_or_skip
def _cloud_env_or_skip() -> tuple[str, str, str, str]:
    if os.environ.get("YASCHEDULER_TEST_HETZNER") != "1":
        pytest.skip(
            "YASCHEDULER_TEST_HETZNER != 1; set YASCHEDULER_TEST_HETZNER=1 to enable"
        )
    token = os.environ.get("YASCHEDULER_CLOUDS_HETZNER_TOKEN", "")
    if not token:
        pytest.skip(
            "YASCHEDULER_CLOUDS_HETZNER_TOKEN unset/empty; set it to a real Hetzner API token"
        )
    server_type = os.environ.get("YASCHEDULER_CLOUDS_HETZNER_SERVER_TYPE", "cx23")
    location = os.environ.get("YASCHEDULER_CLOUDS_HETZNER_LOCATION", "hel1")
    image = os.environ.get("YASCHEDULER_CLOUDS_HETZNER_IMAGE_NAME", "debian-13")
    return token, server_type, location, image


# START_CONTRACT: hetzner_config
#   PURPOSE: Session-scoped Config fixture with a temp INI ([db]/[local]/[remote]/[engine.test_shell]/[clouds] max_nodes=1, hetzner_package_upgrade=false) wired to the shared PostgreSQL container; fresh keys_dir so the daemon generates its own SSH key.
#   INPUTS: {
#     tmp_path_factory: Any - pytest session temp factory,
#     _db_config: PostgresDbConfig - shared container DB config,
#     _init_schema: None - schema applied once
#   }
#   OUTPUTS: { Config - parsed config with one ConfigCloudHetzner(max_nodes=1) }
#   SIDE_EFFECTS: Creates temp dirs (data/engines/test_shell/run.sh, empty keys_dir), writes the INI, sets YASCHEDULER_CONF_PATH; calls _cloud_env_or_skip (skips when the gate is unset).
#   LINKS: M-ENTRYPOINTS-CONFIG, M-CLOUD-CONFIGS, M-CLOUD-PROVIDER-HETZNER
# END_CONTRACT: hetzner_config
@pytest.fixture(scope="session")
def hetzner_config(
    tmp_path_factory: Any,  # noqa: ANN401
    _db_config: Any,  # noqa: ANN401
    _init_schema: None,
) -> Config:
    token, server_type, location, image = _cloud_env_or_skip()

    tmp = tmp_path_factory.mktemp("hetzner_config")
    data_dir = tmp / "data"
    ini_path = tmp / "yascheduler.conf"
    db_cfg = _db_config
    # START_BLOCK_WRITE_INI
    # hetzner_package_upgrade=false skips the slow cloud-init apt-get upgrade so the
    # default ConfigCloudHetzner.connect_grace (60s, NOT INI-parsed) is ample.
    # connect_grace is deliberately NOT set here (it is not an INI-parsed key).
    ini_content = (
        f"[db]\n"
        f"host = {db_cfg.host}\n"
        f"port = {db_cfg.port}\n"
        f"user = {db_cfg.user}\n"
        f"password = {db_cfg.password}\n"
        f"database = {db_cfg.database}\n"
        f"\n"
        f"[local]\n"
        f"data_dir = {data_dir}\n"
        f"\n"
        f"[remote]\n"
        f"user = root\n"
        f"\n"
        f"[engine.test_shell]\n"
        f"spawn = {{engine_path}}/run.sh\n"
        f"check_pname = sleep\n"
        f"input_files = 1.input\n"
        f"output_files = 1.input.out\n"
        f"deploy_local_files = run.sh\n"
        f"sleep_interval = 1\n"
        f"platforms = linux\n"
        f"\n"
        f"[clouds]\n"
        f"hetzner_token = {token}\n"
        f"hetzner_max_nodes = 1\n"
        f"hetzner_server_type = {server_type}\n"
        f"hetzner_location = {location}\n"
        f"hetzner_image_name = {image}\n"
        f"hetzner_idle_tolerance = 5\n"
        f"hetzner_package_upgrade = false\n"
    )
    ini_path.write_text(ini_content)
    # END_BLOCK_WRITE_INI

    # START_BLOCK_ENGINE_SCRIPT
    engines_dir = tmp / "data" / "engines" / "test_shell"
    engines_dir.mkdir(parents=True)
    run_sh = engines_dir / "run.sh"
    run_sh.write_text("#!/bin/sh\nsleep 3\ncat 1.input > 1.input.out\n")
    run_sh.chmod(run_sh.stat().st_mode | stat.S_IEXEC)
    # END_BLOCK_ENGINE_SCRIPT

    # START_BLOCK_KEYS_DIR
    # Fresh empty keys_dir: the daemon generates its own key via get_or_create_ssh_key,
    # registered into the Hetzner project by get_ssh_key_id. NOT the static-node ssh_pool key.
    keys_dir = tmp / "data" / "keys"
    keys_dir.mkdir(parents=True)
    # END_BLOCK_KEYS_DIR

    # START_BLOCK_ENV_CONFIG
    os.environ["YASCHEDULER_CONF_PATH"] = str(ini_path)
    config = parse_config(str(ini_path))
    # END_BLOCK_ENV_CONFIG

    return config


# START_CONTRACT: _ini_path_from_env
#   PURPOSE: Read the INI path the session-scoped hetzner_config fixture published via YASCHEDULER_CONF_PATH.
#   INPUTS: { None }
#   OUTPUTS: { str - absolute INI path set by hetzner_config }
#   SIDE_EFFECTS: None
#   RAISES: RuntimeError - if the env var is unset (fixture ordering bug)
#   LINKS: hetzner_config fixture (this module)
# END_CONTRACT: _ini_path_from_env
def _ini_path_from_env() -> str:
    path = os.environ.get("YASCHEDULER_CONF_PATH")
    if not path:
        raise RuntimeError(
            "YASCHEDULER_CONF_PATH unset; hetzner_config fixture must run first"
        )
    return path


# START_CONTRACT: _assert_vm_deleted
#   PURPOSE: Poll find_srv(client, ip) until it returns None (VM gone) or the timeout elapses; pytest.fail loudly naming the leaked IP if the VM survived. Lazy-imports find_srv (and hcloud via the client passed in) so module collection is SDK-free.
#   INPUTS: {
#     client: Any - hcloud.Client instance (created by the caller with a real token),
#     ip: str - VM public IP to verify deletion of
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: pytest.fail(...) if the VM is not deleted within _VM_DELETE_TIMEOUT_S; makes a Hetzner API list call per poll.
#   LINKS: M-CLOUD-PROVIDER-HETZNER
# END_CONTRACT: _assert_vm_deleted
async def _assert_vm_deleted(client: Any, ip: str) -> None:  # noqa: ANN401
    from yascheduler.infra.cloud.providers.hetzner import find_srv

    deadline = asyncio.get_running_loop().time() + _VM_DELETE_TIMEOUT_S
    while asyncio.get_running_loop().time() < deadline:
        srv = await asyncio.to_thread(find_srv, client, ip)
        if srv is None:
            return
        await asyncio.sleep(_POLL_INTERVAL_S)
    log.error(
        "[hetzner_live][CLEANUP] VM %s was NOT deleted — manual cleanup required", ip
    )
    pytest.fail(f"Hetzner VM {ip} was NOT deleted — manual cleanup required")


# START_CONTRACT: _cleanup_observed
#   PURPOSE: Best-effort delete every observed VM IP via hetzner_delete_node (per-IP failures swallowed+logged so all IPs are attempted), then strong _assert_vm_deleted per IP which fails loudly if any VM survived. Builds a fresh minimal ConfigCloudHetzner so its get_client is a DISTINCT hcloud.Client from the daemon's (only cfg.token is read).
#   INPUTS: {
#     token: str - Hetzner API token,
#     observed_ips: list[str] - VM IPs observed during the test,
#     log: logging.Logger - logger
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Deletes cloud VMs via the real Hetzner API; pytest.fail on survivor.
#   LINKS: M-CLOUD-PROVIDER-HETZNER, _assert_vm_deleted
# END_CONTRACT: _cleanup_observed
async def _cleanup_observed(
    token: str, observed_ips: list[str], log: logging.Logger
) -> None:
    if not observed_ips:
        return
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import (
        get_client,
        hetzner_delete_node,
    )

    cfg: ConfigCloudHetzner = ConfigCloudHetzner(token=token, max_nodes=1)
    client = get_client(cfg)

    # START_BLOCK_BEST_EFFORT_DELETE
    for ip in observed_ips:
        try:
            await hetzner_delete_node(log, cfg, ip)
        except Exception as err:  # noqa: BLE001
            log.error(
                "[hetzner_live][CLEANUP] hetzner_delete_node raised for ip=%s err=%s "
                "— proceeding to deletion verification",
                ip,
                err,
            )
    # END_BLOCK_BEST_EFFORT_DELETE

    # START_BLOCK_VERIFY_DELETED
    # Strong per-IP deletion assertion: a survivor fails the test loudly.
    for ip in observed_ips:
        await _assert_vm_deleted(client, ip)
    # END_BLOCK_VERIFY_DELETED


# START_CONTRACT: _submit_two_jobs
#   PURPOSE: Submit TWO tasks via _submit_async in per-job temp CWDs holding distinct 1.input payloads; capture each task_id from stdout.
#   INPUTS: {
#     ini_path: str - INI path passed as --config,
#     monkeypatch: pytest.MonkeyPatch - per-call chdir isolation,
#     tmp_path: Path - base temp dir for per-job CWDs,
#     capfd: pytest.CaptureFixture - captures _submit_async's print(str(task_id))
#   }
#   OUTPUTS: { list[int] - two positive task_ids in submission order }
#   SIDE_EFFECTS: Creates per-job temp CWDs with 1.input; chdir's into each during _submit_async; writes per-job script files.
#   LINKS: M-ENTRYPOINTS-CLI-SUBMIT
# END_CONTRACT: _submit_two_jobs
async def _submit_two_jobs(
    ini_path: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> list[int]:
    task_ids: list[int] = []
    for n in range(1, 3):
        job_dir = tmp_path / f"job_{n}"
        job_dir.mkdir(parents=True)
        (job_dir / "1.input").write_text(f"hello cloud {n}")

        script = tmp_path / f"submit_{n}.script"
        script.write_text(f"ENGINE=test_shell\nLABEL=cloud_job_{n}\n")

        monkeypatch.chdir(job_dir)
        capfd.readouterr()
        await _submit_async([str(script), "--config", ini_path])
        out = capfd.readouterr().out.strip()
        monkeypatch.undo()

        assert out, f"job {n}: _submit_async printed nothing to stdout"
        task_id = int(out)
        assert task_id > 0, f"job {n}: task_id={task_id} not positive"
        task_ids.append(task_id)
    return task_ids


# START_CONTRACT: _poll_for_hetzner_node
#   PURPOSE: Poll uow.nodes.list_all() until a cloud=="hetzner" node appears; record its IP into observed_ips; pytest.fail on timeout.
#   INPUTS: { uow_factory, observed_ips: list[str] - appended in place, timeout_s: float }
#   OUTPUTS: { str - the provisioned hetzner node IP }
#   SIDE_EFFECTS: None — read-only UoW polls.
#   LINKS: M-PERSISTENCE-UOW
# END_CONTRACT: _poll_for_hetzner_node
async def _poll_for_hetzner_node(
    uow_factory: Callable[[], PostgresUnitOfWork],
    observed_ips: list[str],
    timeout_s: float,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        async with uow_factory() as uow:
            nodes = await uow.nodes.list_all()
        # Require enabled: _select_and_insert_tmp inserts a tmp node with
        # cloud="hetzner"/enabled=False (placeholder IP); the real provisioned
        # node is committed enabled=True in _persist_node_with_cleanup (which
        # atomically removes the tmp row in the same commit).
        hetzner_nodes = [n for n in nodes if n.cloud == "hetzner" and n.enabled]
        if hetzner_nodes:
            ip = hetzner_nodes[0].ip
            if ip not in observed_ips:
                observed_ips.append(ip)
            return ip
        await asyncio.sleep(_POLL_INTERVAL_S)
    pytest.fail(f"no enabled cloud==hetzner node appeared within {timeout_s}s")


# START_CONTRACT: _wait_both_done
#   PURPOSE: Poll until both tasks reach DONE; capture each task's RUNNING node.ip snapshot into observed_ips en route; pytest.fail on timeout.
#   INPUTS: { uow_factory, task_ids: list[int], observed_ips: list[str] - appended in place, timeout_s: float }
#   OUTPUTS: { dict[int, str] - task_id -> node.ip for every task observed RUNNING }
#   SIDE_EFFECTS: None — read-only UoW polls.
#   LINKS: M-PERSISTENCE-UOW
# END_CONTRACT: _wait_both_done
async def _wait_both_done(
    uow_factory: Callable[[], PostgresUnitOfWork],
    task_ids: list[int],
    observed_ips: list[str],
    timeout_s: float,
) -> dict[int, str]:
    deadline = asyncio.get_running_loop().time() + timeout_s
    statuses: list[Any] = []
    seen_running: dict[int, str] = {}
    while asyncio.get_running_loop().time() < deadline:
        async with uow_factory() as uow:
            statuses = []
            for tid in task_ids:
                t = await uow.tasks.get(TaskId(tid))
                statuses.append(t.status if t else None)
                if t and t.status == DomainTaskStatus.RUNNING and t.allocated_node_id:
                    node = await uow.nodes.get_by_id(t.allocated_node_id)
                    seen_running[tid] = node.ip if node else ""
                    if node and node.ip not in observed_ips:
                        observed_ips.append(node.ip)
        if all(s == DomainTaskStatus.DONE for s in statuses):
            return seen_running
        await asyncio.sleep(_POLL_INTERVAL_S)
    pytest.fail(
        f"tasks not all DONE within {timeout_s}s; "
        f"task_ids={task_ids} last statuses={statuses}"
    )


# START_CONTRACT: _assert_outputs
#   PURPOSE: For each task assert status==DONE, context.error is None, local_folder set, <local_folder>/1.input.out matches its payload; assert each task's resolved node.ip is an observed hetzner node IP; assert created_at/updated_at on DONE tasks. Does NOT require both tasks on the same IP (idle-deallocate race may provision a 2nd VM).
#   INPUTS: { uow_factory, task_ids: list[int], observed_ips: list[str], payloads: list[str] - per-job expected 1.input content }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None — read-only UoW + filesystem reads.
#   LINKS: M-PERSISTENCE-UOW
# END_CONTRACT: _assert_outputs
async def _assert_outputs(
    uow_factory: Callable[[], PostgresUnitOfWork],
    task_ids: list[int],
    observed_ips: list[str],
    payloads: list[str],
) -> None:
    async with uow_factory() as uow:
        tasks = [await uow.tasks.get(TaskId(tid)) for tid in task_ids]
        node_ids = [t.allocated_node_id for t in tasks if t and t.allocated_node_id]
        nodes_by_id = await uow.nodes.get_by_ids(node_ids) if node_ids else {}
    for idx, (tid, task) in enumerate(zip(task_ids, tasks)):
        assert task is not None, f"task {tid} vanished from DB"
        assert task.status == DomainTaskStatus.DONE, (
            f"task {tid} status={task.status}, expected DONE"
        )
        assert task.context.error is None, f"task {tid} error={task.context.error!r}"
        local_folder = task.context.local_folder
        assert local_folder, f"task {tid} missing local_folder"
        out_file = Path(str(local_folder)) / "1.input.out"
        assert out_file.exists(), f"task {tid} output missing: {out_file}"
        actual = out_file.read_text()
        expected = payloads[idx]
        assert actual == expected, (
            f"task {tid} output={actual!r}, expected {expected!r}"
        )
        task_ip = (
            nodes_by_id[task.allocated_node_id].ip
            if task.allocated_node_id and task.allocated_node_id in nodes_by_id
            else ""
        )
        assert task_ip in observed_ips, (
            f"task {tid} node.ip={task_ip} "
            f"not among observed hetzner IPs={observed_ips}"
        )
        assert isinstance(task.created_at, datetime), (
            f"task {tid} created_at={task.created_at!r} is not datetime"
        )
        assert isinstance(task.updated_at, datetime), (
            f"task {tid} updated_at={task.updated_at!r} is not datetime"
        )


# START_CONTRACT: _assert_cloud_done_log
#   PURPOSE: Assert captured log_records contain a CLOUD_DONE record with ip=<node_ip> provider=hetzner. Emitted by _persist_node_with_cleanup at provision time, so it is present once both tasks have reached DONE. Does NOT assert on CREATED or [CloudProvisionerImpl] (those are on the Orchestrator logger, invisible to log_records).
#   INPUTS: { records: list[LogRecord], node_ips: list[str] - provisioned hetzner IPs to match against ip= }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None — pure assertion over captured records.
#   LINKS: M-APPLICATION-ALLOCATE
# END_CONTRACT: _assert_cloud_done_log
def _assert_cloud_done_log(
    records: list[logging.LogRecord], node_ips: list[str]
) -> None:
    cloud_done_msgs = [
        r.getMessage() for r in records if _CLOUD_DONE_MARKER in r.getMessage()
    ]
    done_match = any(
        "provider=hetzner" in msg
        and any(re.search(rf"ip={re.escape(ip)}\b", msg) for ip in node_ips)
        for msg in cloud_done_msgs
    )
    assert done_match, (
        f"no [CLOUD_DONE] record with provider=hetzner and ip in {node_ips}; "
        f"captured CLOUD_DONE msgs={cloud_done_msgs}"
    )


# START_CONTRACT: _assert_cloud_delete_log
#   PURPOSE: Assert captured log_records contain a CLOUD_DELETE record with cloud=hetzner. Emitted by deallocate_node during idle-deallocation, so it is only present AFTER the node row has been removed — must be called after _poll_node_gone, not at completion time.
#   INPUTS: { records: list[LogRecord] }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None — pure assertion over captured records.
#   LINKS: M-APPLICATION-DEALLOCATE
# END_CONTRACT: _assert_cloud_delete_log
def _assert_cloud_delete_log(records: list[logging.LogRecord]) -> None:
    cloud_delete_msgs = [
        r.getMessage() for r in records if _CLOUD_DELETE_MARKER in r.getMessage()
    ]
    delete_match = any("cloud=hetzner" in msg for msg in cloud_delete_msgs)
    assert delete_match, (
        f"no [CLOUD_DELETE] record with cloud=hetzner; "
        f"captured CLOUD_DELETE msgs={cloud_delete_msgs}"
    )


# START_CONTRACT: _poll_node_gone
#   PURPOSE: Poll uow.nodes.list_all() until no cloud=="hetzner" row remains (idle-deallocate fired); pytest.fail on timeout.
#   INPUTS: { uow_factory, timeout_s: float }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None — read-only UoW polls.
#   LINKS: M-PERSISTENCE-UOW
# END_CONTRACT: _poll_node_gone
async def _poll_node_gone(
    uow_factory: Callable[[], PostgresUnitOfWork],
    timeout_s: float,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        async with uow_factory() as uow:
            nodes = await uow.nodes.list_all()
        if not any(n.cloud == "hetzner" for n in nodes):
            return
        await asyncio.sleep(_POLL_INTERVAL_S)
    pytest.fail(f"cloud==hetzner node row not removed within {timeout_s}s")


# START_CONTRACT: test_hetzner_live
#   PURPOSE: Real-Hetzner e2e — daemon autoscales one VM, two jobs run to DONE with matching outputs, idle-deallocate removes the node, the VM is deleted and verified gone via find_srv; guaranteed observed-IP cleanup with loud-fail-on-leak in finally.
#   INPUTS: {
#     hetzner_config: Config - session config (skips when the env gate is unset),
#     uow_factory: Callable[[], PostgresUnitOfWork],
#     log_records: list[LogRecord],
#     monkeypatch: pytest.MonkeyPatch,
#     tmp_path: Path,
#     capfd: pytest.CaptureFixture
#   }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Starts the daemon (background asyncio.Task), creates and deletes real Hetzner VMs, reads/writes temp job dirs.
#   LINKS: M-DI, M-ENTRYPOINTS-CLI-SUBMIT, M-APPLICATION-ORCHESTRATOR, M-CLOUD-PROVIDER-HETZNER
# END_CONTRACT: test_hetzner_live
async def test_hetzner_live(
    hetzner_config: Config,
    uow_factory: Callable[[], PostgresUnitOfWork],
    log_records: list[logging.LogRecord],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config = hetzner_config
    # Redundant gate check (hetzner_config already skipped if unset) + token for cleanup.
    token, _server_type, _location, _image = _cloud_env_or_skip()
    ini_path = _ini_path_from_env()

    observed_ips: list[str] = []
    payloads = ["hello cloud 1", "hello cloud 2"]

    orchestrator = await make_daemon(config)
    orch_task = asyncio.create_task(orchestrator.start())

    try:
        # START_BLOCK_SUBMIT
        task_ids = await _submit_two_jobs(ini_path, monkeypatch, tmp_path, capfd)
        # Assert both queued before any node exists.
        async with uow_factory() as uow:
            for tid in task_ids:
                t = await uow.tasks.get(TaskId(tid))
                assert t is not None, f"task {tid} missing after submit"
                assert t.status == DomainTaskStatus.TO_DO, (
                    f"task {tid} status={t.status}, expected TO_DO after submit"
                )
        # END_BLOCK_SUBMIT

        # START_BLOCK_AUTOSCALE
        # Poll until exactly one cloud==hetzner node appears (cold-start 0 -> 1).
        # The node IP is recorded into observed_ips by the helper as a side effect.
        await _poll_for_hetzner_node(uow_factory, observed_ips, _AUTOSCALE_TIMEOUT_S)
        # END_BLOCK_AUTOSCALE

        # START_BLOCK_COMPLETION
        await _wait_both_done(
            uow_factory, task_ids, observed_ips, _COMPLETION_TIMEOUT_S
        )
        # END_BLOCK_COMPLETION

        # START_BLOCK_OUTPUTS
        await _assert_outputs(uow_factory, task_ids, observed_ips, payloads)
        # END_BLOCK_OUTPUTS

        # START_BLOCK_LOG_ASSERT_DONE
        # CLOUD_DONE is emitted by _persist_node_with_cleanup at provision time,
        # so it is already present once both tasks reached DONE.
        _assert_cloud_done_log(log_records, observed_ips)
        # END_BLOCK_LOG_ASSERT_DONE

        # START_BLOCK_DELETION
        # DB-row removal (idle deallocate), then strong find_srv deletion assertion.
        await _poll_node_gone(uow_factory, _DEALLOC_TIMEOUT_S)
        # CLOUD_DELETE is emitted by deallocate_node during the idle-deallocate
        # that just removed the row — assert it only now, not at completion time.
        _assert_cloud_delete_log(log_records)
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
        from yascheduler.infra.cloud.providers.hetzner import get_client

        verify_cfg: ConfigCloudHetzner = ConfigCloudHetzner(token=token, max_nodes=1)
        verify_client = get_client(verify_cfg)
        for ip in observed_ips:
            await _assert_vm_deleted(verify_client, ip)
        # END_BLOCK_DELETION

    finally:
        # START_BLOCK_CLEANUP
        # (a) stop daemon + best-effort await of the background task.
        await orchestrator.stop()
        try:
            await asyncio.wait_for(orch_task, timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            orch_task.cancel()
        # (b) observed-IP cleanup with loud-fail-on-leak.
        await _cleanup_observed(token, observed_ips, log)
        # END_BLOCK_CLEANUP
