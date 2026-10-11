from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _parse_module(name: str) -> ast.Module:
    return ast.parse((ROOT / name).read_text(encoding="utf-8-sig"))


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"未找到类 {name}")


def _find_method(
    cls: ast.ClassDef, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in cls.body:
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name
        ):
            return node
    raise AssertionError(f"未找到方法 {name}")


def _attr_chain(node: ast.AST) -> list[str]:
    """把 `self.config_manager.load` 解析成 ['self', 'config_manager', 'load']。"""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def _expr_call(stmt: ast.stmt) -> ast.Call | None:
    """返回语句中作为顶层调用出现的调用节点（含赋值右值）。

    覆盖 `self._normalize_legacy_config(config)` 这类表达式调用，以及
    `self.config_manager = ConfigManager(config)` 这类赋值右值调用。
    """
    value: ast.AST | None = None
    if isinstance(stmt, ast.Expr):
        value = stmt.value
    elif isinstance(stmt, ast.Assign):
        value = stmt.value
    if isinstance(value, ast.Call):
        return value
    return None


def test_status_service_delegates_rendering_to_html_render() -> None:
    source = (ROOT / "core/status_service.py").read_text(encoding="utf-8-sig")

    assert "from .data_source import SystemDataSource" not in source
    assert "build_render_data" not in source
    assert "render_status_image" in source
    assert "build_status_text" in source
    assert "self.html_renderer.render_status_image" in source
    assert "self.html_renderer.build_status_text" in source


def test_html_render_owns_status_data_and_rendering() -> None:
    source = (ROOT / "core/html_render.py").read_text(encoding="utf-8-sig")
    init_source = (ROOT / "core/__init__.py").read_text(encoding="utf-8-sig")

    assert "class HtmlRender" in source
    assert "from .data_source import SystemDataSource" in source
    assert "async def render_status_image" in source
    assert "async def build_status_text" in source
    assert "async def build_render_data" in source
    assert "build_render_data" not in init_source


def test_traffic_usage_owns_monthly_persistence() -> None:
    traffic_source = (ROOT / "core/traffic_usage.py").read_text(encoding="utf-8-sig")
    main_source = (ROOT / "main.py").read_text(encoding="utf-8-sig")

    assert "class TrafficUsageRecorder" in traffic_source
    assert "psutil.net_io_counters" in traffic_source
    assert "JsonStateStore" in traffic_source
    assert "TRAFFIC_STATE_NAMESPACE" in traffic_source
    assert "status_state.json" not in main_source
    assert "monthly_traffic.json" not in main_source
    assert "net_io_counters" not in main_source


def test_core_modules_use_prefixed_logger() -> None:
    logger_source = (ROOT / "core/logger.py").read_text(encoding="utf-8-sig")

    assert 'PREFIX = "[astrbot_plugin_status] "' in logger_source

    for path in (ROOT / "core").glob("*.py"):
        source = path.read_text(encoding="utf-8-sig")
        if path.name == "logger.py":
            assert "from astrbot.api import logger as _astrbot_logger" in source
            continue
        assert "from astrbot.api import logger" not in source
        assert "[Status]" not in source


def test_status_plugin_init_normalizes_legacy_config_before_load() -> None:
    """插件构造函数必须在 ConfigManager 读取配置前归一化历史布尔配置。

    Issue #23：旧配置中的字符串布尔值若不归一化会导致 WebUI 保存失败。
    本测试用 AST 校验调用关系，防止构造函数意外移除或后移归一化调用；
    仅检查源码文本无法区分调用顺序，也容易被注释/格式变化误导。
    """
    init = _find_method(
        _find_class(_parse_module("main.py"), "StatusPlugin"), "__init__"
    )

    # 收集构造函数体内顶层表达式调用，记录其顺序与实参
    calls: list[tuple[int, list[str], ast.Call]] = []
    for index, stmt in enumerate(init.body):
        call = _expr_call(stmt)
        if call is not None:
            calls.append((index, _attr_chain(call.func), call))

    def find(chain_suffix: list[str]) -> tuple[int, ast.Call] | None:
        for index, chain, call in calls:
            if chain[-len(chain_suffix) :] == chain_suffix:
                return index, call
        return None

    normalize_call = find(["self", "_normalize_legacy_config"])
    config_manager_call = find(["ConfigManager"])
    load_call = find(["self", "config_manager", "load"])

    assert normalize_call is not None, "__init__ 必须调用 self._normalize_legacy_config"
    assert config_manager_call is not None, "__init__ 必须构造 ConfigManager"
    assert load_call is not None, "__init__ 必须调用 self.config_manager.load()"

    normalize_index, normalize_node = normalize_call
    config_index, config_node = config_manager_call
    load_index, _ = load_call

    # 1) 归一化必须在 ConfigManager 构造之前
    assert normalize_index < config_index, (
        "_normalize_legacy_config 必须在 ConfigManager 构造之前调用"
    )
    # 2) 归一化必须在配置读取（load）之前
    assert normalize_index < load_index, (
        "_normalize_legacy_config 必须在 self.config_manager.load() 之前调用"
    )

    # 3) 归一化与 ConfigManager 必须收到同一个 config 参数
    def single_arg(call: ast.Call) -> ast.AST | None:
        if len(call.args) != 1 or call.keywords:
            return None
        return call.args[0]

    normalize_arg = single_arg(normalize_node)
    config_arg = single_arg(config_node)
    assert normalize_arg is not None, "_normalize_legacy_config 应只接收一个位置参数"
    assert config_arg is not None, "ConfigManager 应只接收一个位置参数"
    assert ast.unparse(normalize_arg) == ast.unparse(config_arg) == "config", (
        "归一化与 ConfigManager 必须接收同一个 config 参数"
    )


def test_normalize_legacy_config_covers_auto_use_current_name() -> None:
    """_normalize_legacy_config 必须把 auto_use_current_name 纳入迁移范围。"""
    method = _find_method(
        _find_class(_parse_module("main.py"), "StatusPlugin"),
        "_normalize_legacy_config",
    )

    call_names = {
        node.func.id
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "normalize_legacy_bool_configs" in call_names, (
        "_normalize_legacy_config 必须调用 normalize_legacy_bool_configs"
    )

    module = _parse_module("main.py")
    keys: list[str] = []
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_LEGACY_BOOL_KEYS"
            for t in node.targets
        ):
            keys = [
                elt.value
                for elt in getattr(node.value, "elts", [])
                if isinstance(elt, ast.Constant)
            ]
    assert "auto_use_current_name" in keys, (
        "_LEGACY_BOOL_KEYS 必须包含 auto_use_current_name"
    )
