from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "_conf_schema.json"


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))


def _iter_schema_fields(
    schema: dict[str, Any],
    prefix: str = "",
):
    """递归遍历顶层字段与 object.items 内的嵌套字段。"""
    for key, meta in schema.items():
        if not isinstance(meta, dict):
            continue
        path = f"{prefix}{key}"
        yield path, meta
        if meta.get("type") == "object" and isinstance(meta.get("items"), dict):
            yield from _iter_schema_fields(meta["items"], prefix=f"{path}.")


def test_schema_json_is_valid() -> None:
    schema = _load_schema()
    assert isinstance(schema, dict)
    assert schema, "schema 不应为空"


def test_bool_fields_use_native_bool_defaults() -> None:
    """所有 bool 字段的默认值必须是真正的 JSON 布尔值，而非字符串。

    回归 Issue #23：auto_use_current_name 的 default 曾写成字符串 "true"，
    导致 AstrBot WebUI 保存配置时布尔类型校验失败。
    """
    offenders: list[str] = []
    checked: list[str] = []

    for path, meta in _iter_schema_fields(_load_schema()):
        if meta.get("type") != "bool":
            continue
        checked.append(path)
        default = meta.get("default")
        if not isinstance(default, bool):
            offenders.append(f"{path}: {default!r} ({type(default).__name__})")

    assert checked, "未在 schema 中找到任何 bool 字段，测试可能失效"
    assert not offenders, "以下 bool 字段的默认值不是原生布尔值：" + "; ".join(
        offenders
    )


def test_known_bool_fields_are_covered() -> None:
    """确保关键字段仍声明为 bool，避免字段被误删或类型被改错。

    仅断言字段存在不足以捕获回归：若 `type` 从 `bool` 被改成 `string`，
    `test_bool_fields_use_native_bool_defaults` 会因跳过非 bool 字段而漏过。
    """
    types = {
        path: meta.get("type") for path, meta in _iter_schema_fields(_load_schema())
    }

    for path in (
        "auto_use_current_name",
        "enable_llm_analysis",
        "traffic_monitor.enabled",
        "traffic_monitor.alert_enabled",
    ):
        assert types.get(path) == "bool", (
            f"{path} 的 type 应为 bool，实际为 {types.get(path)!r}"
        )
