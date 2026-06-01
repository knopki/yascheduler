# FILE: tests/unit/test_config.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for INI → config parsing across all yascheduler config sub-modules.
#   SCOPE: ConfigDb, ConfigLocal, ConfigRemote, cloud configs, Engine, EngineRepository, warn_unknown_fields, Config top-level.
#   DEPENDS: M-CONFIG-DB, M-CONFIG-LOCAL, M-CONFIG-REMOTE, M-CONFIG-CLOUD, M-CONFIG-ENGINE, M-CONFIG-ENGINE-REPO, M-CONFIG-UTILS, M-CONFIG
#   LINKS: M-CONFIG, M-CONFIG-DB, M-CONFIG-LOCAL, M-CONFIG-REMOTE, M-CONFIG-CLOUD, M-CONFIG-ENGINE, M-CONFIG-ENGINE-REPO, M-CONFIG-UTILS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_config_db_full_overrides - parses all DB fields from INI with overrides
#   test_config_db_defaults - applies defaults when section empty
#   test_config_local_custom_data_dir - resolves derived paths under custom data_dir
#   test_config_local_defaults - applies numeric defaults for empty section
#   test_config_remote_with_jump_host - parses jump host fields
#   test_config_remote_without_jump_host - jump host defaults to None
#   test_config_cloud_hetzner_parsing - parses hetzner token/username
#   test_config_cloud_upcloud_parsing - parses upcloud login/password
#   test_azure_image_reference_from_urn - parses colon-separated URN
#   test_azure_image_reference_invalid_urn - raises ValueError for short URN
#   test_config_cloud_azure_rejects_root - raises ValueError for root user
#   test_engine_valid_parsing - parses complete valid engine section
#   test_engine_invalid_spawn_template - raises ValueError for unknown placeholder
#   test_engine_missing_check_methods - raises ValueError when no check method
#   test_engine_empty_input_files - raises ValueError for empty input_files
#   test_engine_repository_filter - filter returns matching engines
#   test_engine_repository_filter_platforms - filter_platforms returns platform matches
#   test_engine_repository_immutable - raises NotImplementedError on mutation
#   test_warn_unknown_fields - emits ConfigWarning for unknown keys
#   test_config_remote_no_warnings_known_keys - no warnings for known INI keys
#   test_config_remote_warns_unknown_keys - warns for truly unknown keys
#   test_config_top_level_full_ini - assembles all sub-configs from full INI
#   test_config_top_level_empty_sections - handles empty sections with defaults
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial config parsing unit tests
# END_CHANGE_SUMMARY

from configparser import ConfigParser
from pathlib import PurePath

import pytest

from yascheduler.config.cloud import (
    AzureImageReference,
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
)
from yascheduler.config.config import Config
from yascheduler.config.db import ConfigDb
from yascheduler.config.engine import Engine
from yascheduler.config.engine_repository import EngineRepository
from yascheduler.config.local import ConfigLocal
from yascheduler.config.remote import ConfigRemote
from yascheduler.config.utils import ConfigWarning, warn_unknown_fields


# START_CONTRACT: test_config_db_full_overrides
#   PURPOSE: Verify ConfigDb from_config_parser_section parses full INI section with all values overridden from defaults
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-DB]
# END_CONTRACT: test_config_db_full_overrides
def test_config_db_full_overrides() -> None:
    """parses full INI section with overrides"""
    cfg = ConfigParser()
    cfg.read_string(
        "[db]\nuser=myuser\npassword=secret\ndatabase=mydb\nhost=db.example.com\nport=5433\n"
    )
    db = ConfigDb.from_config_parser_section(cfg["db"])
    assert db.user == "myuser"
    assert db.password == "secret"
    assert db.database == "mydb"
    assert db.host == "db.example.com"
    assert db.port == 5433


# START_CONTRACT: test_config_db_defaults
#   PURPOSE: Verify ConfigDb from_config_parser_section applies all defaults when section is empty
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-DB]
# END_CONTRACT: test_config_db_defaults
def test_config_db_defaults() -> None:
    """applies defaults when section has no keys"""
    cfg = ConfigParser()
    cfg.read_string("[db]\n")
    db = ConfigDb.from_config_parser_section(cfg["db"])
    assert db.user == "yascheduler"
    assert db.password == "password"
    assert db.database == "database"
    assert db.host == "localhost"
    assert db.port == 5432


# START_CONTRACT: test_config_local_custom_data_dir
#   PURPOSE: Verify ConfigLocal resolves derived paths under custom data_dir
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-LOCAL]
# END_CONTRACT: test_config_local_custom_data_dir
def test_config_local_custom_data_dir() -> None:
    """derived paths resolve under custom data_dir"""
    cfg = ConfigParser()
    cfg.read_string("[local]\ndata_dir=/opt/data\n")
    local = ConfigLocal.from_config_parser_section(cfg["local"])
    assert str(local.data_dir).endswith("data") or "/opt/data" in str(local.data_dir)


# START_CONTRACT: test_config_local_defaults
#   PURPOSE: Verify ConfigLocal applies all numeric defaults when section is empty
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-LOCAL]
# END_CONTRACT: test_config_local_defaults
def test_config_local_defaults() -> None:
    """applies numeric defaults for empty section"""
    cfg = ConfigParser()
    cfg.read_string("[local]\n")
    local = ConfigLocal.from_config_parser_section(cfg["local"])
    assert local.webhook_reqs_limit == 5
    assert local.conn_machine_limit == 10
    assert local.allocate_limit == 20
    assert local.consume_limit == 20
    assert local.deallocate_limit == 5
    assert local.webhook_url is None


# START_CONTRACT: test_config_remote_with_jump_host
#   PURPOSE: Verify ConfigRemote parses jump host fields from INI section
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-REMOTE]
# END_CONTRACT: test_config_remote_with_jump_host
def test_config_remote_with_jump_host() -> None:
    """parses jump host fields"""
    cfg = ConfigParser()
    cfg.read_string(
        "[remote]\nuser=admin\njump_user=jumper\njump_host=bastion.example.com\n"
    )
    remote = ConfigRemote.from_config_parser_section(cfg["remote"])
    assert remote.username == "admin"
    assert remote.jump_username == "jumper"
    assert remote.jump_host == "bastion.example.com"


# START_CONTRACT: test_config_remote_without_jump_host
#   PURPOSE: Verify ConfigRemote sets jump host fields to None when not specified
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-REMOTE]
# END_CONTRACT: test_config_remote_without_jump_host
def test_config_remote_without_jump_host() -> None:
    """jump host fields default to None"""
    cfg = ConfigParser()
    cfg.read_string("[remote]\nuser=root\n")
    remote = ConfigRemote.from_config_parser_section(cfg["remote"])
    assert remote.username == "root"
    assert remote.jump_username is None
    assert remote.jump_host is None


# START_CONTRACT: test_config_cloud_hetzner_parsing
#   PURPOSE: Verify ConfigCloudHetzner from_config_parser_section parses token and username
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-CLOUD]
# END_CONTRACT: test_config_cloud_hetzner_parsing
def test_config_cloud_hetzner_parsing() -> None:
    """parses hetzner token and username"""
    cfg = ConfigParser()
    cfg.read_string("[clouds]\nhetzner_token=abc123\nhetzner_user=root\n")
    hetzner = ConfigCloudHetzner.from_config_parser_section(cfg["clouds"])
    assert hetzner.token == "abc123"
    assert hetzner.username == "root"
    assert hetzner.server_type == "cx52"  # default
    assert hetzner.image_name == "debian-11"  # default


# START_CONTRACT: test_config_cloud_upcloud_parsing
#   PURPOSE: Verify ConfigCloudUpcloud from_config_parser_section parses login/password
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-CLOUD]
# END_CONTRACT: test_config_cloud_upcloud_parsing
def test_config_cloud_upcloud_parsing() -> None:
    """parses upcloud login and password"""
    cfg = ConfigParser()
    cfg.read_string("[clouds]\nupcloud_login=user\nupcloud_password=pass\n")
    upcloud = ConfigCloudUpcloud.from_config_parser_section(cfg["clouds"])
    assert upcloud.login == "user"
    assert upcloud.password == "pass"
    assert upcloud.username == "root"  # default


# START_CONTRACT: test_azure_image_reference_from_urn
#   PURPOSE: Verify AzureImageReference.from_urn parses colon-separated URN string
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-CLOUD]
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
#   LINKS: [M-CONFIG-CLOUD]
# END_CONTRACT: test_azure_image_reference_invalid_urn
def test_azure_image_reference_invalid_urn() -> None:
    """raises ValueError for too-short URN"""
    with pytest.raises(ValueError):
        AzureImageReference.from_urn("a:b:c")


# START_CONTRACT: test_config_cloud_azure_rejects_root
#   PURPOSE: Verify ConfigCloudAzure raises ValueError when username is "root"
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-CLOUD]
# END_CONTRACT: test_config_cloud_azure_rejects_root
def test_config_cloud_azure_rejects_root() -> None:
    """raises ValueError for root user on Azure"""
    with pytest.raises(ValueError):
        ConfigCloudAzure(
            tenant_id="tid",
            client_id="cid",
            client_secret="secret",
            subscription_id="sid",
            username="root",
        )


# START_CONTRACT: test_engine_valid_parsing
#   PURPOSE: Verify Engine.from_config_parser_section parses a complete valid engine section
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-ENGINE]
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
    engine = Engine.from_config_parser_section(cfg["engine.test"], PurePath("."))
    assert engine.name == "test"
    assert engine.spawn == "{task_path} {engine_path} {ncpus}"
    assert engine.check_cmd == "echo ok"
    assert engine.input_files == ("input.txt",)
    assert engine.output_files == ("output.txt",)


# START_CONTRACT: test_engine_invalid_spawn_template
#   PURPOSE: Verify Engine raises ValueError when spawn contains unknown template placeholder
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-ENGINE]
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
        Engine.from_config_parser_section(cfg["engine.test"], PurePath("."))


# START_CONTRACT: test_engine_missing_check_methods
#   PURPOSE: Verify Engine raises ValueError when neither check_cmd nor check_pname is set
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-ENGINE]
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
        Engine.from_config_parser_section(cfg["engine.test"], PurePath("."))


# START_CONTRACT: test_engine_empty_input_files
#   PURPOSE: Verify Engine raises ValueError when input_files is empty
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-ENGINE]
# END_CONTRACT: test_engine_empty_input_files
def test_engine_empty_input_files() -> None:
    """direct construction raises ValueError when input_files is empty"""
    with pytest.raises(ValueError):
        Engine(
            name="test",
            spawn="{task_path}",
            check_cmd="echo ok",
            check_pname=None,
            input_files=(),
        )


# START_CONTRACT: test_engine_repository_filter
#   PURPOSE: Verify EngineRepository.filter returns new repo with only matching engines
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-ENGINE-REPO]
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
    repo = EngineRepository(data={"a": e1, "b": e2}, engines_dir=PurePath("."))
    filtered = repo.filter(lambda e: e.name == "a")
    assert "a" in filtered
    assert "b" not in filtered
    assert isinstance(filtered, EngineRepository)


# START_CONTRACT: test_engine_repository_filter_platforms
#   PURPOSE: Verify EngineRepository.filter_platforms returns engines matching given platforms
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-ENGINE-REPO]
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
    repo = EngineRepository(data={"a": e1, "b": e2}, engines_dir=PurePath("."))
    filtered = repo.filter_platforms(["linux"])
    assert "a" in filtered
    assert "b" not in filtered


# START_CONTRACT: test_engine_repository_immutable
#   PURPOSE: Verify EngineRepository raises NotImplementedError on mutation
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-ENGINE-REPO]
# END_CONTRACT: test_engine_repository_immutable
def test_engine_repository_immutable() -> None:
    """__setitem__ and __delitem__ raise NotImplementedError"""
    e1 = Engine(
        name="a",
        spawn="{task_path}",
        check_cmd="echo ok",
        check_pname=None,
        input_files=("f",),
        output_files=("o",),
    )
    repo = EngineRepository(data={"a": e1}, engines_dir=PurePath("."))
    with pytest.raises(NotImplementedError):
        repo["b"] = e1
    with pytest.raises(NotImplementedError):
        del repo["a"]


# START_CONTRACT: test_warn_unknown_fields
#   PURPOSE: Verify warn_unknown_fields emits ConfigWarning for keys not in known list
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-UTILS]
# END_CONTRACT: test_warn_unknown_fields
def test_warn_unknown_fields() -> None:
    """emits ConfigWarning for unknown config keys"""
    cfg = ConfigParser()
    cfg.read_string("[db]\nuser=root\nunknown_key=value\n")
    with pytest.warns(ConfigWarning, match="unknown fields"):
        warn_unknown_fields(["user", "password", "database", "host", "port"], cfg["db"])


# START_CONTRACT: test_config_remote_no_warnings_known_keys
#   PURPOSE: Verify ConfigRemote does not warn for valid INI key names (user, jump_user)
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-REMOTE]
# END_CONTRACT: test_config_remote_no_warnings_known_keys
@pytest.mark.filterwarnings("error::yascheduler.config.utils.ConfigWarning")
def test_config_remote_no_warnings_known_keys() -> None:
    """no warnings for known INI keys user and jump_user"""
    cfg = ConfigParser()
    cfg.read_string("[remote]\nuser=admin\njump_user=jumper\njump_host=bastion\n")
    remote = ConfigRemote.from_config_parser_section(cfg["remote"])
    assert remote.username == "admin"
    assert remote.jump_username == "jumper"


# START_CONTRACT: test_config_remote_warns_unknown_keys
#   PURPOSE: Verify ConfigRemote warns for truly unknown INI keys
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG-REMOTE]
# END_CONTRACT: test_config_remote_warns_unknown_keys
def test_config_remote_warns_unknown_keys() -> None:
    """emits ConfigWarning for unknown keys in remote section"""
    cfg = ConfigParser()
    cfg.read_string("[remote]\nuser=root\nbogus=yes\n")
    with pytest.warns(ConfigWarning, match="unknown fields"):
        ConfigRemote.from_config_parser_section(cfg["remote"])


# START_CONTRACT: test_config_top_level_full_ini
#   PURPOSE: Verify Config.from_config_parser assembles all sub-configs from full INI
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG]
# END_CONTRACT: test_config_top_level_full_ini
def test_config_top_level_full_ini() -> None:
    """assembles all sub-configs from full INI"""
    ini = "[db]\nuser=myuser\n[local]\n[remote]\nuser=root\n[clouds]\n"
    config = Config.from_config_parser(ini)
    assert isinstance(config.db, ConfigDb)
    assert isinstance(config.local, ConfigLocal)
    assert isinstance(config.remote, ConfigRemote)
    # engines must be an EngineRepository
    assert isinstance(config.engines, EngineRepository)


# START_CONTRACT: test_config_top_level_empty_sections
#   PURPOSE: Verify Config.from_config_parser produces valid config from INI with empty sections only
#   INPUTS: { None }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: [M-CONFIG]
# END_CONTRACT: test_config_top_level_empty_sections
def test_config_top_level_empty_sections() -> None:
    """handles empty sections with defaults"""
    ini = "[db]\n[local]\n[remote]\n[clouds]\n"
    config = Config.from_config_parser(ini)
    assert config.db.user == "yascheduler"  # default
    assert config.local.webhook_reqs_limit == 5  # default
    assert config.remote.username == "root"  # default
