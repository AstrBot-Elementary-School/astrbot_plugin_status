from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACKAGE_NAME = "status_core_for_tests"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT / "core")]
sys.modules[PACKAGE_NAME] = package

CONSTANTS_SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.constants",
    ROOT / "core" / "constants.py",
)
assert CONSTANTS_SPEC is not None
assert CONSTANTS_SPEC.loader is not None
status_constants = importlib.util.module_from_spec(CONSTANTS_SPEC)
sys.modules[CONSTANTS_SPEC.name] = status_constants
CONSTANTS_SPEC.loader.exec_module(status_constants)

CONFIG_SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.config_manager",
    ROOT / "core" / "config_manager.py",
)
assert CONFIG_SPEC is not None
assert CONFIG_SPEC.loader is not None
status_config_manager = importlib.util.module_from_spec(CONFIG_SPEC)
sys.modules[CONFIG_SPEC.name] = status_config_manager
CONFIG_SPEC.loader.exec_module(status_config_manager)

ConfigManager = status_config_manager.ConfigManager
DEFAULT_BOT_NAME = status_config_manager.DEFAULT_BOT_NAME
DEFAULT_COMMENT_PROMPT = status_config_manager.DEFAULT_COMMENT_PROMPT
DEFAULT_VISION_PROMPT = status_config_manager.DEFAULT_VISION_PROMPT
migrate_legacy_bool_config = status_config_manager.migrate_legacy_bool_config
normalize_legacy_bool_configs = status_config_manager.normalize_legacy_bool_configs
parse_bool_token = status_config_manager.parse_bool_token


def test_config_manager_loads_defaults() -> None:
    manager = ConfigManager({})
    manager.load()

    assert manager.auto_use_current_name is True
    assert manager.bot_name == DEFAULT_BOT_NAME
    assert manager.banner_paths == []
    assert manager.traffic_monitor.enabled is True
    assert manager.traffic_monitor.alert_enabled is False
    assert manager.traffic_monitor.alert_threshold_gb == 100.0
    assert manager.traffic_monitor.alert_target_umo == ""
    assert manager.llm_analysis.enabled is False
    assert manager.llm_analysis.vision_provider_id == ""
    assert manager.llm_analysis.comment_provider_id == ""
    assert manager.llm_analysis.vision_prompt == DEFAULT_VISION_PROMPT
    assert manager.llm_analysis.comment_prompt == DEFAULT_COMMENT_PROMPT


def test_config_manager_normalizes_valid_values() -> None:
    manager = ConfigManager(
        {
            "auto_use_current_name": "false",
            "bot_name": "  酒狐  ",
            "banner_image": [
                "/tmp/banner-a.png",
                "",
                123,
                "/tmp/banner-b.jpg",
            ],
            "traffic_monitor": {
                "enabled": "false",
                "alert_enabled": "true",
                "alert_threshold_gb": "42.5",
                "alert_target_umo": "  aiocqhttp:group:123456  ",
            },
            "enable_llm_analysis": "true",
            "vision_provider_id": "  vlm-provider  ",
            "comment_provider_id": "  text-provider  ",
            "vision_prompt": "  描述状态图  ",
            "comment_prompt": "  总结：{description}  ",
        }
    )
    manager.load()

    assert manager.auto_use_current_name is False
    assert manager.bot_name == "酒狐"
    assert manager.banner_paths == ["/tmp/banner-a.png", "/tmp/banner-b.jpg"]
    assert manager.traffic_monitor.enabled is False
    assert manager.traffic_monitor.alert_enabled is True
    assert manager.traffic_monitor.alert_threshold_gb == 42.5
    assert manager.traffic_monitor.alert_target_umo == "aiocqhttp:group:123456"
    assert manager.llm_analysis.enabled is True
    assert manager.llm_analysis.vision_provider_id == "vlm-provider"
    assert manager.llm_analysis.comment_provider_id == "text-provider"
    assert manager.llm_analysis.vision_prompt == "描述状态图"
    assert manager.llm_analysis.comment_prompt == "总结：{description}"


def test_config_manager_falls_back_for_invalid_types() -> None:
    manager = ConfigManager(
        {
            "auto_use_current_name": object(),
            "bot_name": 123,
            "banner_image": "/tmp/banner.png",
            "traffic_monitor": {
                "enabled": object(),
                "alert_enabled": object(),
                "alert_threshold_gb": -1,
                "alert_target_umo": [],
            },
            "enable_llm_analysis": object(),
            "vision_provider_id": [],
            "comment_provider_id": {},
            "vision_prompt": "",
            "comment_prompt": "",
        }
    )
    manager.load()

    assert manager.auto_use_current_name is True
    assert manager.bot_name == DEFAULT_BOT_NAME
    assert manager.banner_paths == []
    assert manager.traffic_monitor.enabled is True
    assert manager.traffic_monitor.alert_enabled is False
    assert manager.traffic_monitor.alert_threshold_gb == 100.0
    assert manager.traffic_monitor.alert_target_umo == ""
    assert manager.llm_analysis.enabled is False
    assert manager.llm_analysis.vision_provider_id == ""
    assert manager.llm_analysis.comment_provider_id == ""
    assert manager.llm_analysis.vision_prompt == DEFAULT_VISION_PROMPT
    assert manager.llm_analysis.comment_prompt == DEFAULT_COMMENT_PROMPT


def test_parse_bool_token_shared_mapping() -> None:
    assert parse_bool_token(True) is True
    assert parse_bool_token(False) is False
    for token in ("true", "TRUE", " true ", "1", "yes", "on"):
        assert parse_bool_token(token) is True, token
    for token in ("false", "FALSE", " false ", "0", "no", "off"):
        assert parse_bool_token(token) is False, token
    for invalid in ("", "maybe", 1, 0, None, [], object()):
        assert parse_bool_token(invalid) is None, invalid


def test_migrate_legacy_bool_config_handles_strings() -> None:
    config = {"auto_use_current_name": "false"}
    assert migrate_legacy_bool_config(config, "auto_use_current_name") is True
    assert config["auto_use_current_name"] is False

    config = {"auto_use_current_name": " TRUE "}
    assert migrate_legacy_bool_config(config, "auto_use_current_name") is True
    assert config["auto_use_current_name"] is True


def test_migrate_legacy_bool_config_preserves_native_and_missing() -> None:
    native_false = {"auto_use_current_name": False}
    assert migrate_legacy_bool_config(native_false, "auto_use_current_name") is False
    assert native_false["auto_use_current_name"] is False

    native_true = {"auto_use_current_name": True}
    assert migrate_legacy_bool_config(native_true, "auto_use_current_name") is False
    assert native_true["auto_use_current_name"] is True

    missing: dict[str, object] = {}
    assert migrate_legacy_bool_config(missing, "auto_use_current_name") is False
    assert "auto_use_current_name" not in missing


def test_migrate_legacy_bool_config_rejects_invalid_string() -> None:
    config = {"auto_use_current_name": "maybe"}
    assert migrate_legacy_bool_config(config, "auto_use_current_name") is None
    assert config["auto_use_current_name"] == "maybe"


def test_migrate_legacy_bool_config_rejects_invalid_types() -> None:
    """非 bool 非 str 的值属于类型不合法，返回 None 且不覆盖原值。"""
    for invalid in (None, 0, 1, 2, [], {}, [True], {"on": True}, 1.0):
        config = {"auto_use_current_name": invalid}
        assert migrate_legacy_bool_config(config, "auto_use_current_name") is None, (
            invalid
        )
        assert config["auto_use_current_name"] == invalid, invalid


def test_migrate_legacy_bool_config_is_idempotent() -> None:
    config = {"auto_use_current_name": "true"}
    assert migrate_legacy_bool_config(config, "auto_use_current_name") is True
    assert config["auto_use_current_name"] is True
    assert migrate_legacy_bool_config(config, "auto_use_current_name") is False
    assert config["auto_use_current_name"] is True


def test_normalize_legacy_bool_configs_reports_unrecognized() -> None:
    config = {
        "auto_use_current_name": "false",
        "enable_llm_analysis": "maybe",
    }
    unrecognized = normalize_legacy_bool_configs(
        config,
        ("auto_use_current_name", "enable_llm_analysis"),
    )

    assert unrecognized == ["enable_llm_analysis"]
    assert config["auto_use_current_name"] is False
    assert config["enable_llm_analysis"] == "maybe"


def test_normalize_legacy_bool_configs_all_recognized() -> None:
    config = {"auto_use_current_name": "true"}
    assert normalize_legacy_bool_configs(config, ("auto_use_current_name",)) == []
    assert config["auto_use_current_name"] is True
