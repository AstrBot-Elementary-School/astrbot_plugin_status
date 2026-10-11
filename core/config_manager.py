from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .constants import (
    DEFAULT_BOT_NAME,
    DEFAULT_COMMENT_PROMPT,
    DEFAULT_VISION_PROMPT,
)

_BOOL_TRUE_TOKENS = frozenset({"true", "1", "yes", "on"})
_BOOL_FALSE_TOKENS = frozenset({"false", "0", "no", "off"})


def parse_bool_token(value: Any) -> bool | None:
    """解析布尔值或布尔字符串；无法识别时返回 None。

    运行时读取与历史配置归一化共用同一套映射，避免两处规则漂移。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE_TOKENS:
            return True
        if normalized in _BOOL_FALSE_TOKENS:
            return False
    return None


_MISSING = object()


def migrate_legacy_bool_config(config: Any, key: str) -> bool | None:
    """原地把历史字符串布尔配置归一化为原生 bool，不写盘。

    返回值区分三种情况：

    - ``True``: 成功把历史字符串归一化为原生 bool
    - ``False``: 无需迁移（字段缺失，或已经是原生布尔值）
    - ``None``: 值不合法（无法识别的字符串，或其他非法类型），
      保留原值不覆盖，交由调用方诊断
    """
    value = config.get(key, _MISSING)
    if value is _MISSING:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        parsed = parse_bool_token(value)
        if parsed is None:
            return None
        config[key] = parsed
        return True
    return None


def normalize_legacy_bool_configs(
    config: Any,
    keys: Iterable[str],
) -> list[str]:
    """批量归一化历史字符串布尔配置，返回不合法的键列表。

    只改内存对象，不写盘。无法识别的字符串或其他非法类型保留原值，
    交由调用方诊断。
    """
    invalid: list[str] = []
    for key in keys:
        if migrate_legacy_bool_config(config, key) is None:
            invalid.append(key)
    return invalid


@dataclass(slots=True, frozen=True)
class LLMAnalysisConfig:
    """LLM 分析相关配置，供命令处理流程直接读取。"""

    enabled: bool
    vision_provider_id: str
    comment_provider_id: str
    vision_prompt: str
    comment_prompt: str


@dataclass(slots=True, frozen=True)
class TrafficMonitorConfig:
    """当月流量统计与提醒配置。"""

    enabled: bool
    alert_enabled: bool
    alert_threshold_gb: float
    alert_target_umo: str


class ConfigManager:
    """集中解析 status 插件配置，避免业务逻辑散落直接读取 AstrBotConfig。"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.auto_use_current_name = True
        self.bot_name = DEFAULT_BOT_NAME
        self.banner_paths: list[str] = []
        self.traffic_monitor = TrafficMonitorConfig(
            enabled=True,
            alert_enabled=False,
            alert_threshold_gb=100.0,
            alert_target_umo="",
        )
        self.llm_analysis = LLMAnalysisConfig(
            enabled=False,
            vision_provider_id="",
            comment_provider_id="",
            vision_prompt=DEFAULT_VISION_PROMPT,
            comment_prompt=DEFAULT_COMMENT_PROMPT,
        )

    def load(self) -> None:
        """加载并校验全部配置字段。"""
        self.auto_use_current_name = self._get_bool("auto_use_current_name", True)
        self.bot_name = self._get_non_empty_string("bot_name", DEFAULT_BOT_NAME)
        self.banner_paths = self._get_string_list("banner_image")
        traffic_config = self._get_object("traffic_monitor")
        self.traffic_monitor = TrafficMonitorConfig(
            enabled=self._get_bool_from(traffic_config, "enabled", True),
            alert_enabled=self._get_bool_from(
                traffic_config,
                "alert_enabled",
                False,
            ),
            alert_threshold_gb=self._get_positive_float_from(
                traffic_config,
                "alert_threshold_gb",
                100.0,
            ),
            alert_target_umo=self._get_string_from(
                traffic_config,
                "alert_target_umo",
            ).strip(),
        )
        self.llm_analysis = LLMAnalysisConfig(
            enabled=self._get_bool("enable_llm_analysis", False),
            vision_provider_id=self._get_string("vision_provider_id").strip(),
            comment_provider_id=self._get_string("comment_provider_id").strip(),
            vision_prompt=self._get_non_empty_string(
                "vision_prompt",
                DEFAULT_VISION_PROMPT,
            ),
            comment_prompt=self._get_non_empty_string(
                "comment_prompt",
                DEFAULT_COMMENT_PROMPT,
            ),
        )

    def _get_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        return self._normalize_bool(value, default)

    @classmethod
    def _normalize_bool(cls, value: Any, default: bool) -> bool:
        parsed = parse_bool_token(value)
        return default if parsed is None else parsed

    def _get_object(self, key: str) -> dict[str, Any]:
        value = self.config.get(key, {})
        return value if isinstance(value, dict) else {}

    def _get_bool_from(
        self,
        source: dict[str, Any],
        key: str,
        default: bool,
    ) -> bool:
        return self._normalize_bool(source.get(key, default), default)

    def _get_string_from(
        self,
        source: dict[str, Any],
        key: str,
        default: str = "",
    ) -> str:
        value = source.get(key, default)
        return value if isinstance(value, str) else default

    def _get_positive_float_from(
        self,
        source: dict[str, Any],
        key: str,
        default: float,
    ) -> float:
        value = source.get(key, default)
        if isinstance(value, bool):
            return default
        if isinstance(value, int | float):
            result = float(value)
            return result if result > 0 else default
        if isinstance(value, str):
            try:
                result = float(value.strip())
            except ValueError:
                return default
            return result if result > 0 else default
        return default

    def _get_string(self, key: str, default: str = "") -> str:
        value = self.config.get(key, default)
        return value if isinstance(value, str) else default

    def _get_non_empty_string(self, key: str, default: str) -> str:
        value = self._get_string(key, default).strip()
        return value or default

    def _get_string_list(self, key: str) -> list[str]:
        value = self.config.get(key, [])
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item.strip()]
