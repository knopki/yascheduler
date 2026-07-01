# FILE: tests/unit/test_config.py
# VERSION: 1.5.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for INI → config parsing across all yascheduler config sub-modules.
#   SCOPE: PostgresDbConfig, LocalSettings, RemoteDefaults, cloud configs, Engine, EngineRepository, warn_unknown_fields, Config top-level.
#   DEPENDS: M-INFRA-DB-CONFIG, M-DOMAIN-SETTINGS, M-CLOUD-CONFIGS, M-DOMAIN-ENGINE, M-ENTRYPOINTS-CONFIG-PARSER, M-ENTRYPOINTS-CONFIG
#   LINKS: M-INFRA-DB-CONFIG, M-DOMAIN-SETTINGS, M-CLOUD-CONFIGS, M-DOMAIN-ENGINE, M-ENTRYPOINTS-CONFIG-PARSER, M-ENTRYPOINTS-CONFIG
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_config_db_full_overrides - parses all DB fields from INI with overrides
#   test_config_db_defaults - applies defaults when section empty
#   test_config_local_custom_data_dir - resolves derived paths under custom data_dir
#   test_config_local_defaults - applies numeric defaults for empty section
#   test_config_remote_with_jump_host - parses jump host fields
#   test_config_remote_without_jump_host - jump host defaults to None
#   test_config_cloud_hetzner_parsing - parses hetzner token/username via parse_cloud_section
#   test_config_cloud_upcloud_parsing - parses upcloud login/password via parse_cloud_section
#   test_azure_image_reference_from_urn - parses colon-separated URN
#   test_azure_image_reference_invalid_urn - raises ValueError for short URN
#   test_config_cloud_azure_rejects_root - parse_cloud_section raises ValueError for root user (parser-side)
#   test_engine_valid_parsing - parses complete valid engine section
#   test_engine_invalid_spawn_template - raises ValueError for unknown placeholder
#   test_engine_missing_check_methods - raises ValueError when no check method
#   test_engine_empty_input_files - raises ValueError for empty input_files
#   test_engine_repository_filter - filter returns matching engines
#   test_engine_repository_filter_platforms - filter_platforms returns platform matches
#   test_engine_repository_immutable - raises TypeError on mutation (frozen dataclass, no __setitem__/__delitem__)
#   test_warn_unknown_fields - emits ConfigWarning for unknown keys
#   test_config_remote_no_warnings_known_keys - no warnings for known INI keys
#   test_config_remote_warns_unknown_keys - warns for truly unknown keys
#   test_config_top_level_full_ini - assembles all sub-configs from full INI
#   test_config_top_level_empty_sections - handles empty sections with defaults
#   test_vastai_cloud_section_round_trips - [cloud.vastai] round-trips into ConfigCloudVastAI via parse_clouds registry
#   test_config_cloud_dtos_are_frozen_dataclasses_without_parser_methods - ConfigCloud* are stdlib frozen dataclasses, no from_config_parser_section/get_valid_config_parser_fields
#   test_config_local_is_frozen_dataclass_without_get_private_keys - LocalSettings is stdlib frozen dataclass, no get_private_keys, retains keys_dir
#   test_config_local_post_init_rejects_zero_limit - __post_init__ raises ValueError for ge(1) violation
#   test_config_local_parser_passes_zero_through_to_post_init - parser does not falsy-coerce a 0 limit
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.5.0 - move-cloud-package-upgrade: add [clouds] {prefix}_package_upgrade parser coverage — hetzner_package_upgrade=false parses to False without a ConfigWarning (auto-registered), absent key defaults to True, package_upgrade is NOT on the CloudConfig domain Protocol, and a leftover [local] cloud_package_upgrade=false now emits a ConfigWarning (LocalSettings no longer carries the field).
#   PREVIOUS_CHANGE: v1.4.0 - Migrate config DTO imports to new homes per config-aggregate-to-entrypoints (P4): ConfigDb→PostgresDbConfig (yascheduler.infra.persistence), ConfigLocal→LocalSettings (yascheduler.domain), ConfigRemote→RemoteDefaults (yascheduler.domain), Config→yascheduler.entrypoints, ConfigWarning/warn_unknown_fields→yascheduler.entrypoints._config_utils; X.from_config_parser_section calls → _parse_*_section free functions; Config.from_config_parser → parse_config; GRACE LINKS updated.
# END_CHANGE_SUMMARY

from configparser import ConfigParser
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path, PurePath
from typing import cast

import pytest

from yascheduler.domain import (
    CloudConfig,
    Engine,
    EngineRepository,
    LocalSettings,
    RemoteDefaults,
)
from yascheduler.entrypoints._config_utils import ConfigWarning, warn_unknown_fields
from yascheduler.entrypoints.config_parser import (
    _parse_db_section,
    _parse_local_section,
    _parse_remote_section,
    parse_cloud_section,
    parse_clouds,
    parse_config,
    parse_engine_section,
)
from yascheduler.infra.cloud import (
    AzureImageReference,
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
)
from yascheduler.infra.persistence import PostgresDbConfig


# START_CONTRACT: test_config_db_full_overrides
#   PURPOSE: Verify PostgresDbConfig from_config_parser_section parses full INI section with all values overridden from defaults
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-INFRA-DB-CONFIG]
# END_CONTRACT: test_config_db_full_overrides
def test_config_db_full_overrides() -> None:
    """parses full INI section with overrides"""
    cfg = ConfigParser()
    cfg.read_string(
        "[db]\nuser=myuser\npassword=secret\ndatabase=mydb\nhost=db.example.com\nport=5433\n"
    )
    db = _parse_db_section(cfg["db"])
    assert db.user == "myuser"
    assert db.password == "secret"
    assert db.database == "mydb"
    assert db.host == "db.example.com"
    assert db.port == 5433


# START_CONTRACT: test_config_db_defaults
#   PURPOSE: Verify PostgresDbConfig from_config_parser_section applies all defaults when section is empty
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-INFRA-DB-CONFIG]
# END_CONTRACT: test_config_db_defaults
def test_config_db_defaults() -> None:
    """applies defaults when section has no keys"""
    cfg = ConfigParser()
    cfg.read_string("[db]\n")
    db = _parse_db_section(cfg["db"])
    assert db.user == "yascheduler"
    assert db.password == "password"
    assert db.database == "database"
    assert db.host == "localhost"
    assert db.port == 5432


# START_CONTRACT: test_config_local_custom_data_dir
#   PURPOSE: Verify LocalSettings resolves derived paths under custom data_dir
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-SETTINGS]
# END_CONTRACT: test_config_local_custom_data_dir
def test_config_local_custom_data_dir() -> None:
    """derived paths resolve under custom data_dir"""
    cfg = ConfigParser()
    cfg.read_string("[local]\ndata_dir=/opt/data\n")
    local = _parse_local_section(cfg["local"])
    assert str(local.data_dir).endswith("data") or "/opt/data" in str(local.data_dir)


# START_CONTRACT: test_config_local_defaults
#   PURPOSE: Verify LocalSettings applies all numeric defaults when section is empty
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-SETTINGS]
# END_CONTRACT: test_config_local_defaults
def test_config_local_defaults() -> None:
    """applies numeric defaults for empty section"""
    cfg = ConfigParser()
    cfg.read_string("[local]\n")
    local = _parse_local_section(cfg["local"])
    assert local.webhook_reqs_limit == 5
    assert local.conn_machine_limit == 10
    assert local.allocate_limit == 20
    assert local.consume_limit == 20
    assert local.deallocate_limit == 5
    assert local.webhook_url is None


# START_CONTRACT: test_config_remote_with_jump_host
#   PURPOSE: Verify RemoteDefaults parses jump host fields from INI section
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-SETTINGS]
# END_CONTRACT: test_config_remote_with_jump_host
def test_config_remote_with_jump_host() -> None:
    """parses jump host fields"""
    cfg = ConfigParser()
    cfg.read_string(
        "[remote]\nuser=admin\njump_user=jumper\njump_host=bastion.example.com\n"
    )
    remote = _parse_remote_section(cfg["remote"])
    assert remote.username == "admin"
    assert remote.jump_username == "jumper"
    assert remote.jump_host == "bastion.example.com"


# START_CONTRACT: test_config_remote_without_jump_host
#   PURPOSE: Verify RemoteDefaults sets jump host fields to None when not specified
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-SETTINGS]
# END_CONTRACT: test_config_remote_without_jump_host
def test_config_remote_without_jump_host() -> None:
    """jump host fields default to None"""
    cfg = ConfigParser()
    cfg.read_string("[remote]\nuser=root\n")
    remote = _parse_remote_section(cfg["remote"])
    assert remote.username == "root"
    assert remote.jump_username is None
    assert remote.jump_host is None


# START_CONTRACT: test_config_cloud_hetzner_parsing
#   PURPOSE: Verify parse_cloud_section parses hetzner token and username
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: test_config_cloud_hetzner_parsing
def test_config_cloud_hetzner_parsing() -> None:
    """parses hetzner token and username via parse_cloud_section"""
    cfg = ConfigParser()
    cfg.read_string("[clouds]\nhetzner_token=abc123\nhetzner_user=root\n")
    hetzner = cast("ConfigCloudHetzner", parse_cloud_section(cfg["clouds"], "hetzner"))
    assert hetzner.token == "abc123"
    assert hetzner.username == "root"
    assert hetzner.server_type == "cx52"  # default
    assert hetzner.image_name == "debian-13"  # default


# START_CONTRACT: test_config_cloud_upcloud_parsing
#   PURPOSE: Verify parse_cloud_section parses upcloud login and password
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: test_config_cloud_upcloud_parsing
def test_config_cloud_upcloud_parsing() -> None:
    """parses upcloud login and password via parse_cloud_section"""
    cfg = ConfigParser()
    cfg.read_string("[clouds]\nupcloud_login=user\nupcloud_password=pass\n")
    upcloud = cast("ConfigCloudUpcloud", parse_cloud_section(cfg["clouds"], "upcloud"))
    assert upcloud.login == "user"
    assert upcloud.password == "pass"
    assert upcloud.username == "root"  # default


# START_CONTRACT: test_azure_image_reference_from_urn
#   PURPOSE: Verify AzureImageReference.from_urn parses colon-separated URN string
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CLOUD-CONFIGS]
# END_CONTRACT: test_azure_image_reference_from_urn
def test_azure_image_reference_from_urn() -> None:
    """parses URN into publisher, offer, sku, version"""
    ref = AzureImageReference.from_urn("Publisher:Offer:SKU:1.0")
    assert ref.publisher == "Publisher"
    assert ref.offer == "Offer"
    assert ref.sku == "SKU"
    assert ref.version == "1.0"


# START_CONTRACT: test_azure_image_reference_invalid_urn
#   PURPOSE: Verify AzureImageReference.from_urn raises ValueError on short URN
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CLOUD-CONFIGS]
# END_CONTRACT: test_azure_image_reference_invalid_urn
def test_azure_image_reference_invalid_urn() -> None:
    """raises ValueError for too-short URN"""
    with pytest.raises(ValueError):
        AzureImageReference.from_urn("a:b:c")


# START_CONTRACT: test_config_cloud_azure_rejects_root
#   PURPOSE: Verify parse_cloud_section raises ValueError when az_user is "root" (parser-side _check_az_user, not DTO __post_init__)
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: test_config_cloud_azure_rejects_root
def test_config_cloud_azure_rejects_root() -> None:
    """parse_cloud_section raises ValueError for root user on Azure (parser-side)"""
    cfg = ConfigParser()
    cfg.read_string("[clouds]\naz_tenant_id=tid\naz_user=root\n")
    with pytest.raises(ValueError, match="Root user is forbidden on Azure"):
        parse_cloud_section(cfg["clouds"], "az")


# START_CONTRACT: test_config_cloud_hetzner_package_upgrade_false
#   PURPOSE: Verify [clouds] hetzner_package_upgrade=false parses to ConfigCloudHetzner.package_upgrade is False AND does not warn
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: test_config_cloud_hetzner_package_upgrade_false
@pytest.mark.filterwarnings(
    "error::yascheduler.entrypoints._config_utils.ConfigWarning"
)
def test_config_cloud_hetzner_package_upgrade_false() -> None:
    """[clouds] hetzner_package_upgrade=false → ConfigCloudHetzner.package_upgrade is False (no ConfigWarning)"""
    cfg = ConfigParser()
    cfg.read_string("[clouds]\nhetzner_token=t\nhetzner_package_upgrade=false\n")
    clouds = parse_clouds(cfg, RemoteDefaults())
    hetzner = next(c for c in clouds if isinstance(c, ConfigCloudHetzner))
    assert hetzner.package_upgrade is False


# START_CONTRACT: test_config_cloud_package_upgrade_defaults_true
#   PURPOSE: Verify an absent {prefix}_package_upgrade key leaves ConfigCloudHetzner.package_upgrade at the True default
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: test_config_cloud_package_upgrade_defaults_true
def test_config_cloud_package_upgrade_defaults_true() -> None:
    """absent hetzner_package_upgrade → ConfigCloudHetzner.package_upgrade is True (default)"""
    cfg = ConfigParser()
    cfg.read_string("[clouds]\nhetzner_token=t\n")
    clouds = parse_clouds(cfg, RemoteDefaults())
    hetzner = next(c for c in clouds if isinstance(c, ConfigCloudHetzner))
    assert hetzner.package_upgrade is True


# START_CONTRACT: test_package_upgrade_not_on_cloud_config_protocol
#   PURPOSE: Verify package_upgrade is declared on the concrete DTOs only, NOT on the domain CloudConfig Protocol
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-CONFIGS, M-DOMAIN-PORTS
# END_CONTRACT: test_package_upgrade_not_on_cloud_config_protocol
def test_package_upgrade_not_on_cloud_config_protocol() -> None:
    """package_upgrade is NOT on the CloudConfig Protocol (infra-only consumer, like token/vm_size)"""
    assert not hasattr(CloudConfig, "package_upgrade")
    assert "package_upgrade" not in CloudConfig.__annotations__


# START_CONTRACT: test_local_cloud_package_upgrade_now_warns_unknown
#   PURPOSE: Verify a leftover [local] cloud_package_upgrade key now surfaces as a ConfigWarning (the field was relocated to ConfigCloud*)
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-SETTINGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: test_local_cloud_package_upgrade_now_warns_unknown
def test_local_cloud_package_upgrade_now_warns_unknown() -> None:
    """a leftover [local] cloud_package_upgrade=false emits a ConfigWarning (clean break, no deprecation shim)"""
    cfg = ConfigParser()
    cfg.read_string("[local]\ncloud_package_upgrade=false\n")
    with pytest.warns(ConfigWarning, match="unknown fields"):
        local = _parse_local_section(cfg["local"])
    assert not hasattr(local, "cloud_package_upgrade")


# START_CONTRACT: test_engine_valid_parsing
#   PURPOSE: Verify parse_engine_section parses a complete valid engine section
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-ENGINE]
# END_CONTRACT: test_engine_valid_parsing
def test_engine_valid_parsing() -> None:
    """parses a valid engine section"""
    cfg = ConfigParser()
    cfg.read_string(
        "[engine.test]\n"
        "spawn={task_path} {engine_path} {ncpus}\n"
        "check_cmd=echo ok\n"
        "input_files=input.txt\n"
        "output_files=output.txt\n"
    )
    engine = parse_engine_section(cfg["engine.test"], PurePath("."))
    assert engine.name == "test"
    assert engine.spawn == "{task_path} {engine_path} {ncpus}"
    assert engine.check_cmd == "echo ok"
    assert engine.input_files == ("input.txt",)
    assert engine.output_files == ("output.txt",)


# START_CONTRACT: test_engine_invalid_spawn_template
#   PURPOSE: Verify parse_engine_section raises ValueError when spawn contains unknown template placeholder
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-ENGINE]
# END_CONTRACT: test_engine_invalid_spawn_template
def test_engine_invalid_spawn_template() -> None:
    """raises ValueError for unknown template placeholder in spawn"""
    with pytest.raises(ValueError, match="unknown"):
        cfg = ConfigParser()
        cfg.read_string(
            "[engine.test]\n"
            "spawn={unknown} {engine_path}\n"
            "check_cmd=echo ok\n"
            "input_files=input.txt\n"
            "output_files=out.txt\n"
        )
        parse_engine_section(cfg["engine.test"], PurePath("."))


# START_CONTRACT: test_engine_missing_check_methods
#   PURPOSE: Verify parse_engine_section raises ValueError when neither check_cmd nor check_pname is set
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-ENGINE]
# END_CONTRACT: test_engine_missing_check_methods
def test_engine_missing_check_methods() -> None:
    """raises ValueError when no check method is set"""
    with pytest.raises(ValueError):
        cfg = ConfigParser()
        cfg.read_string(
            "[engine.test]\n"
            "spawn={task_path}\n"
            "input_files=input.txt\n"
            "output_files=out.txt\n"
        )
        parse_engine_section(cfg["engine.test"], PurePath("."))


# START_CONTRACT: test_engine_empty_input_files
#   PURPOSE: Verify Engine raises ValueError when input_files is empty
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-ENGINE]
# END_CONTRACT: test_engine_empty_input_files
def test_engine_empty_input_files() -> None:
    """parse_engine_section raises ValueError when input_files is empty"""
    cfg = ConfigParser()
    cfg.read_string(
        "[engine.test]\nspawn={task_path}\ncheck_cmd=echo ok\noutput_files=output.txt\n"
    )
    with pytest.raises(ValueError):
        parse_engine_section(cfg["engine.test"], PurePath("."))


# START_CONTRACT: test_engine_repository_filter
#   PURPOSE: Verify EngineRepository.filter returns new repo with only matching engines
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-ENGINE]
# END_CONTRACT: test_engine_repository_filter
def test_engine_repository_filter() -> None:
    """filter returns new repo with matching engines only"""
    e1 = Engine(
        name="a",
        spawn="{task_path}",
        check_cmd="echo ok",
        check_pname=None,
        input_files=("f",),
        output_files=("o",),
    )
    e2 = Engine(
        name="b",
        spawn="{task_path}",
        check_cmd="echo ok",
        check_pname=None,
        input_files=("f",),
        output_files=("o",),
    )
    repo = EngineRepository(data={"a": e1, "b": e2})
    filtered = repo.filter(lambda e: e.name == "a")
    assert "a" in filtered
    assert "b" not in filtered
    assert isinstance(filtered, EngineRepository)


# START_CONTRACT: test_engine_repository_filter_platforms
#   PURPOSE: Verify EngineRepository.filter_platforms returns engines matching given platforms
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-ENGINE]
# END_CONTRACT: test_engine_repository_filter_platforms
def test_engine_repository_filter_platforms() -> None:
    """filter_platforms returns engines for matching platforms"""
    e1 = Engine(
        name="a",
        spawn="{task_path}",
        check_cmd="echo ok",
        check_pname=None,
        input_files=("f",),
        output_files=("o",),
        platforms=("linux",),
    )
    e2 = Engine(
        name="b",
        spawn="{task_path}",
        check_cmd="echo ok",
        check_pname=None,
        input_files=("f",),
        output_files=("o",),
        platforms=("windows",),
    )
    repo = EngineRepository(data={"a": e1, "b": e2})
    filtered = repo.filter_platforms(["linux"])
    assert "a" in filtered
    assert "b" not in filtered


# START_CONTRACT: test_engine_repository_immutable
#   PURPOSE: Verify EngineRepository raises TypeError on mutation (no UserDict)
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-ENGINE]
# END_CONTRACT: test_engine_repository_immutable
def test_engine_repository_immutable() -> None:
    """__setitem__ and __delitem__ raise TypeError"""
    e1 = Engine(
        name="a",
        spawn="{task_path}",
        check_cmd="echo ok",
        check_pname=None,
        input_files=("f",),
        output_files=("o",),
    )
    repo = EngineRepository(data={"a": e1})
    with pytest.raises(TypeError):
        repo["b"] = e1  # type: ignore[index]  # intentional mutation of frozen dataclass
    with pytest.raises(TypeError):
        del repo["a"]  # type: ignore[attr-defined]  # intentional mutation of frozen dataclass


# START_CONTRACT: test_warn_unknown_fields
#   PURPOSE: Verify warn_unknown_fields emits ConfigWarning for keys not in known list
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-ENTRYPOINTS-CONFIG-PARSER]
# END_CONTRACT: test_warn_unknown_fields
def test_warn_unknown_fields() -> None:
    """emits ConfigWarning for unknown config keys"""
    cfg = ConfigParser()
    cfg.read_string("[db]\nuser=root\nunknown_key=value\n")
    with pytest.warns(ConfigWarning, match="unknown fields"):
        warn_unknown_fields(["user", "password", "database", "host", "port"], cfg["db"])


# START_CONTRACT: test_config_remote_no_warnings_known_keys
#   PURPOSE: Verify RemoteDefaults does not warn for valid INI key names (user, jump_user)
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-SETTINGS]
# END_CONTRACT: test_config_remote_no_warnings_known_keys
@pytest.mark.filterwarnings(
    "error::yascheduler.entrypoints._config_utils.ConfigWarning"
)
def test_config_remote_no_warnings_known_keys() -> None:
    """no warnings for known INI keys user and jump_user"""
    cfg = ConfigParser()
    cfg.read_string("[remote]\nuser=admin\njump_user=jumper\njump_host=bastion\n")
    remote = _parse_remote_section(cfg["remote"])
    assert remote.username == "admin"
    assert remote.jump_username == "jumper"


# START_CONTRACT: test_config_remote_warns_unknown_keys
#   PURPOSE: Verify RemoteDefaults warns for truly unknown INI keys
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-SETTINGS]
# END_CONTRACT: test_config_remote_warns_unknown_keys
def test_config_remote_warns_unknown_keys() -> None:
    """emits ConfigWarning for unknown keys in remote section"""
    cfg = ConfigParser()
    cfg.read_string("[remote]\nuser=root\nbogus=yes\n")
    with pytest.warns(ConfigWarning, match="unknown fields"):
        _parse_remote_section(cfg["remote"])


# START_CONTRACT: test_config_top_level_full_ini
#   PURPOSE: Verify parse_config assembles all sub-configs from full INI
#   INPUTS: { tmp_path: Path - temporary directory for INI file }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Writes a temp INI file under tmp_path
#   LINKS: [M-ENTRYPOINTS-CONFIG]
# END_CONTRACT: test_config_top_level_full_ini
def test_config_top_level_full_ini(tmp_path: Path) -> None:
    """assembles all sub-configs from full INI"""
    ini = "[db]\nuser=myuser\n[local]\n[remote]\nuser=root\n[clouds]\n"
    cfg_file = tmp_path / "full.ini"
    cfg_file.write_text(ini)
    config = parse_config(str(cfg_file))
    assert isinstance(config.db, PostgresDbConfig)
    assert isinstance(config.local, LocalSettings)
    assert isinstance(config.remote, RemoteDefaults)
    # engines must be an EngineRepository
    assert isinstance(config.engines, EngineRepository)


# START_CONTRACT: test_config_top_level_empty_sections
#   PURPOSE: Verify parse_config produces valid config from INI with empty sections only
#   INPUTS: { tmp_path: Path - temporary directory for INI file }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Writes a temp INI file under tmp_path
#   LINKS: [M-ENTRYPOINTS-CONFIG]
# END_CONTRACT: test_config_top_level_empty_sections
def test_config_top_level_empty_sections(tmp_path: Path) -> None:
    """handles empty sections with defaults"""
    ini = "[db]\n[local]\n[remote]\n[clouds]\n"
    cfg_file = tmp_path / "empty.ini"
    cfg_file.write_text(ini)
    config = parse_config(str(cfg_file))
    assert config.db.user == "yascheduler"  # default
    assert config.local.webhook_reqs_limit == 5  # default
    assert config.remote.username == "root"  # default


# START_CONTRACT: test_vastai_cloud_section_round_trips
#   PURPOSE: Verify parse_config produces a ConfigCloudVastAI entry for a [cloud.vastai] section
#   INPUTS: { None - uses tmp_path fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Writes a temp INI file under tmp_path
#   LINKS: [M-ENTRYPOINTS-CONFIG], [M-CLOUD-CONFIGS]
# END_CONTRACT: test_vastai_cloud_section_round_trips
def test_vastai_cloud_section_round_trips(tmp_path: Path) -> None:
    """parse_config recognises [cloud.vastai] and produces a ConfigCloudVastAI entry.

    parse_config delegates to ConfigParser.read, which expects a file
    path (not INI contents), so the INI is written to a temp file and the path is
    passed. This exercises the real production parsing path.
    """
    ini = "[db]\n[local]\n[remote]\nuser=root\n[clouds]\nvastai_api_key=secretkey\n"
    cfg_file = tmp_path / "vastai.ini"
    cfg_file.write_text(ini)
    config = parse_config(str(cfg_file))
    vastai_entries = [c for c in config.clouds if isinstance(c, ConfigCloudVastAI)]
    assert len(vastai_entries) == 1
    assert vastai_entries[0].prefix == "vastai"
    assert vastai_entries[0].api_key == "secretkey"


# START_CONTRACT: test_config_local_is_frozen_dataclass_without_get_private_keys
#   PURPOSE: Verify LocalSettings is a stdlib @dataclass(frozen=True), has no get_private_keys, retains keys_dir
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-SETTINGS], [M-SSH-KEYS]
# END_CONTRACT: test_config_local_is_frozen_dataclass_without_get_private_keys
def test_config_local_is_frozen_dataclass_without_get_private_keys() -> None:
    """LocalSettings is a stdlib frozen dataclass with keys_dir and no get_private_keys method"""
    assert is_dataclass(LocalSettings)
    # frozen: assigning to a field must raise FrozenInstanceError
    instance = LocalSettings()
    with pytest.raises(FrozenInstanceError):
        instance.data_dir = PurePath("/x")  # type: ignore[misc,assignment]
    # get_private_keys is gone (extracted to M-SSH-KEYS as list_private_keys)
    assert not hasattr(instance, "get_private_keys")
    # keys_dir field retained
    assert hasattr(instance, "keys_dir")


# START_CONTRACT: test_config_cloud_dtos_are_frozen_dataclasses_without_parser_methods
#   PURPOSE: Verify ConfigCloud* DTOs are stdlib @dataclass(frozen=True) with no from_config_parser_section / get_valid_config_parser_fields methods
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CLOUD-CONFIGS]
# END_CONTRACT: test_config_cloud_dtos_are_frozen_dataclasses_without_parser_methods
def test_config_cloud_dtos_are_frozen_dataclasses_without_parser_methods() -> None:
    """ConfigCloud* DTOs are stdlib frozen dataclasses with no parser methods (relocated to infra.cloud)"""
    for dto_cls in (
        ConfigCloudAzure,
        ConfigCloudHetzner,
        ConfigCloudUpcloud,
        ConfigCloudVastAI,
        AzureImageReference,
    ):
        assert is_dataclass(dto_cls), f"{dto_cls.__name__} is not a dataclass"
        instance = dto_cls()
        # frozen: assigning to a declared field must raise FrozenInstanceError
        first_field = next(iter(dto_cls.__dataclass_fields__))
        with pytest.raises(FrozenInstanceError):
            setattr(instance, first_field, getattr(instance, first_field))
        # parser methods removed (moved to entrypoints.config_parser free functions);
        # only ConfigCloud* DTOs ever had them, but assert on all for consistency.
        assert not hasattr(dto_cls, "from_config_parser_section")
        assert not hasattr(dto_cls, "get_valid_config_parser_fields")


# START_CONTRACT: test_config_local_post_init_rejects_zero_limit
#   PURPOSE: Verify LocalSettings.__post_init__ raises ValueError when a ge(1) field is 0
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-SETTINGS]
# END_CONTRACT: test_config_local_post_init_rejects_zero_limit
def test_config_local_post_init_rejects_zero_limit() -> None:
    """__post_init__ raises ValueError for allocate_limit=0 (preserving attrs ge(1))"""
    with pytest.raises(ValueError):
        LocalSettings(allocate_limit=0)


# START_CONTRACT: test_config_local_parser_passes_zero_through_to_post_init
#   PURPOSE: Verify the INI parser path does not silently coerce a 0 limit to the default
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-SETTINGS]
# END_CONTRACT: test_config_local_parser_passes_zero_through_to_post_init
def test_config_local_parser_passes_zero_through_to_post_init() -> None:
    """vastai parser fix companion: a 0 in INI reaches __post_init__ (no falsy 'or' coercion)"""
    cfg = ConfigParser()
    cfg.read_string("[local]\nallocate_limit=0\n")
    with pytest.raises(ValueError):
        _parse_local_section(cfg["local"])
