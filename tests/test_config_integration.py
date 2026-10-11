"""Issue #23 集成回归：真实 AstrBotConfig -> 配置归一化 -> WebUI 保存 -> 重新加载。

覆盖范围：**配置核心的迁移与持久化链路**。直接调用 `normalize_legacy_bool_configs()`
（即 `StatusPlugin._normalize_legacy_config` 内部使用的函数），验证真实
`AstrBotConfig` 的加载、归一化、校验、保存与重载行为。它**不**实例化
`StatusPlugin`，因此不覆盖构造函数是否调用归一化——该调用关系由
`tests/test_architecture_boundaries.py` 的 AST 测试保证。

本测试在**独立子进程**中运行：其它测试模块会在导入阶段注入假 `astrbot` /
`psutil` 桩，污染 `sys.modules`；子进程隔离可拿到干净的真实 AstrBot，且不会
反过来影响桩测试。

仅在未安装 AstrBot 时跳过；已安装但导入失败会暴露为测试失败（子进程返回非 0），
不会被 skip 掩盖。本机 AstrBot 4.27.3 下三个用例必须实际执行通过。
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# 子进程脚本：用真实 AstrBot 跑完整链路，结果以 JSON 打到 stdout 最后一行。
_PROBE = textwrap.dedent(
    """
    import json
    import sys
    import tempfile
    from pathlib import Path

    root = Path(sys.argv[1])
    sys.path.insert(0, str(root))

    import astrbot  # 未安装时抛出 ImportError，由外层判定为 skip
    from astrbot.core.config.astrbot_config import AstrBotConfig
    from astrbot.dashboard.services.config_service import validate_config

    from tests.support import create_core_package, load_core_module

    PACKAGE = "status_core_integration_subprocess"
    create_core_package(PACKAGE)
    load_core_module(PACKAGE, "constants")
    cm = load_core_module(PACKAGE, "config_manager")
    normalize = cm.normalize_legacy_bool_configs
    ConfigManager = cm.ConfigManager

    KEY = "auto_use_current_name"
    schema = json.loads((root / "_conf_schema.json").read_text(encoding="utf-8-sig"))

    def disk_value(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))[KEY]

    cases = [("true", True), ("false", False), (False, False)]
    report = []
    with tempfile.TemporaryDirectory() as d:
        for legacy, expected in cases:
            path = Path(d) / f"cfg_{legacy}.json"
            path.write_text(
                json.dumps({KEY: legacy, "bot_name": "旧名字"}, ensure_ascii=False),
                encoding="utf-8",
            )
            cfg = AstrBotConfig(config_path=str(path), schema=schema)
            assert cfg[KEY] == legacy, (legacy, "加载旧值失败")
            invalid = normalize(cfg, (KEY,))
            assert invalid == [], (legacy, invalid)
            assert cfg[KEY] is expected, (legacy, "归一化后内存值错误")
            assert disk_value(path) == legacy, (legacy, "归一化阶段不应写盘")
            mgr = ConfigManager(cfg)
            mgr.load()
            assert mgr.auto_use_current_name is expected, (legacy, "读取时序错误")
            post = dict(cfg)
            post["bot_name"] = "新名字"
            errors, post = validate_config(
                post, getattr(cfg, "schema", {}), is_core=False
            )
            assert errors == [], (legacy, "校验失败", errors)
            cfg.save_config(post)
            assert disk_value(path) is expected, (legacy, "保存后磁盘值错误")
            reloaded = AstrBotConfig(config_path=str(path), schema=schema)
            assert reloaded[KEY] is expected, (legacy, "重新加载值错误")
            assert isinstance(reloaded[KEY], bool), (legacy, "重新加载类型错误")
            r_mgr = ConfigManager(reloaded)
            r_mgr.load()
            assert r_mgr.auto_use_current_name is expected, (legacy, "重载时序错误")
            report.append({"legacy": repr(legacy), "expected": expected})

        # 对照：不归一化时历史字符串会触发 WebUI 校验失败（复现 Issue #23）
        ctrl = Path(d) / "ctrl.json"
        ctrl.write_text(json.dumps({KEY: "false"}, ensure_ascii=False), encoding="utf-8")
        cfg = AstrBotConfig(config_path=str(ctrl), schema=schema)
        errors, _ = validate_config(
            dict(cfg), getattr(cfg, "schema", {}), is_core=False
        )
        assert errors, "未归一化时应触发校验失败"
        assert KEY in errors[0], errors

    print("__RESULT__" + json.dumps(report, ensure_ascii=False))
    """
)


def test_legacy_bool_full_chain_in_subprocess() -> None:
    """在干净子进程中验证历史 'true'/'false'/原生 false 的配置迁移与持久化链路。

    注意：本测试直接调用归一化函数，不实例化 StatusPlugin；构造函数是否调用
    归一化由 test_architecture_boundaries.py 的 AST 测试覆盖。
    """
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )

    if proc.returncode != 0 and "No module named 'astrbot'" in proc.stderr:
        pytest.skip("未安装 AstrBot，跳过集成回归")

    assert proc.returncode == 0, (
        f"集成子进程失败:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

    result_line = next(
        (line for line in proc.stdout.splitlines() if line.startswith("__RESULT__")),
        None,
    )
    assert result_line is not None, f"未找到结果输出:\n{proc.stdout}"

    report = json.loads(result_line.removeprefix("__RESULT__"))
    assert len(report) == 3, report
    assert [item["legacy"] for item in report] == ["'true'", "'false'", "False"]
    assert [item["expected"] for item in report] == [True, False, False]
