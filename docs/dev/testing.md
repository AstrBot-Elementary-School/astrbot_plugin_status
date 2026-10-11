# 测试与回归检查

## 基础命令

优先在插件目录使用一键脚本运行全部测试与检查：

```bash
./tests/run_tests.sh
```

Windows PowerShell：

```powershell
.\tests\run_tests.ps1
```

| 场景 | 工作目录 | 命令 |
| --- | --- | --- |
| Python lint | 插件目录 | `uv run ruff check main.py core tests` |
| Python 格式检查 | 插件目录 | `uv run ruff format --check main.py core tests` |
| 语法检查 | 插件目录 | `python3 -m compileall main.py core tests` |
| pytest | 插件目录 | `pytest tests/ -v` |

> [!TIP]
> 这些是测试与检查命令，不是插件的独立运行命令。实际集成验证入口见 [`setup.md`](./setup.md#本地集成验证)。

## 分层验证矩阵

| 改动类型 | 最小检查 | 建议额外回归 | 关注点 |
| --- | --- | --- | --- |
| Python 业务逻辑 | `ruff check`、语法检查、相关测试 | 命令路径和 tool handler 路径 | 不要只跑被改函数附近的测试。 |
| 渲染模板 / 资源 | `ruff check`、语法检查 | `/status` 或 `/状态` 手工生成图片 | 关注 T2I、字体内联、默认图片缺失。 |
| 配置 schema | `ruff check`、相关配置测试 | README 与配置文档同步核对 | 旧配置是否还能被容忍。 |
| LLM 分析 | `ruff check`、相关测试 | 视觉模型缺失、转述模型缺失、prompt 替换 | provider fallback 要可观测。 |
| 当月流量统计 | `ruff check`、相关流量测试 | 插件启停、提醒目标配置 | 首次采样、跨月重置、计数器回退、提醒去重。 |

## 高风险改动清单

| 改动 | 风险 | 建议 |
| --- | --- | --- |
| 用户图片路径逻辑 | 路径穿越或读取任意文件 | 补路径安全测试。 |
| `StatusPayload` 字段 | 模板渲染失败 | 同步模板和回归测试。 |
| HTML/CSS 变量名 | 图片或角色资源不显示 | 手工验证 T2I 输出。 |
| 网络速度采样 | 首次速度、差值或单位异常 | 覆盖首次采样和连续采样。 |
| 插件状态文件 | 统计丢失、重复提醒或负累计 | 覆盖损坏状态、月份变化和计数器回退。 |
| provider fallback | 分析误用模型或静默失败 | 覆盖配置优先级和缺失提示。 |

## T2I 回归

`tests/test_status_rendering.py` 会在 `localhost:8999` 可访问时调用本地 T2I 服务，检查输出图底部不再出现大块白色留白。若普通沙箱网络访问不到 Docker 服务，该测试会跳过；需要真实验证时用宿主机网络环境运行对应测试。

本地 T2I 服务约定：

| 项目 | 值 |
| --- | --- |
| 服务基址 | `http://localhost:8999/text2img` |
| 测试接口 | `http://localhost:8999/text2img/generate` |
| 生成图读取 | `http://localhost:8999/text2img/{image_id}` |

## AstrBot 集成回归

`tests/test_config_integration.py` 在独立子进程中使用真实 AstrBot 的 `AstrBotConfig`、`validate_config()` 和 `save_config()`，依次验证历史 `"true"`、`"false"` 与原生 `false` 的读取 → 核心归一化 → 框架校验和保存 → 重新加载。该测试直接调用 `normalize_legacy_bool_configs()`，**不实例化 `StatusPlugin`，也不启动浏览器 WebUI**。

`tests/test_architecture_boundaries.py` 使用 AST 静态检查 `StatusPlugin.__init__` 在 `ConfigManager` 构造和 `load()` 前执行迁移调用，且二者接收同一个 `config`；同时检查 `_LEGACY_BOOL_KEYS` 定义包含 `auto_use_current_name`。静态检查不等同于插件实际启动测试。

未安装 AstrBot 时集成测试会跳过；已安装但相关子模块导入失败则报告测试失败。在 AstrBot 4.27.3 环境中，应确认三种配置情形实际验证通过而非跳过；更旧版本的框架校验函数导入路径可能不同，需单独适配测试。

## Playwright 辅助检查

Playwright 不属于插件运行时依赖，但模板、截图和图片裁剪问题适合用浏览器自动化复现。修改 `templates/main.html` 或 `templates/res/css/style.css` 时，建议结合 Playwright 生成截图或检查元素布局，再配合 T2I 回归确认 AstrBot 渲染输出。

若当前环境没有 Playwright 或浏览器依赖，至少运行一键脚本并记录 T2I 测试是否跳过；涉及视觉 issue 时应在具备 Playwright 或真实 T2I 服务的环境补做验证。
