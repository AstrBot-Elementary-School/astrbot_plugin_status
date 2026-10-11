# 配置说明

配置真源是根目录 `_conf_schema.json`。修改配置字段时必须同步更新 README、本文档和相关测试。

## 字段

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `auto_use_current_name` | `bool` | `true` | 自动获取机器人自身名称或标识；取不到时回退到平台实例 ID，再取不到时使用 `bot_name`。 |
| `bot_name` | `string` | `AstrBot` | 显示在状态卡片上的机器人名称。 |
| `banner_image` | `file` | `[]` | 自定义状态背景图，可上传多张随机展示。 |
| `traffic_monitor` | `object` | 见 schema | 当月流量统计和提醒设置。 |
| `enable_llm_analysis` | `bool` | `false` | `/状态` 返回图片后是否调用 LLM 分析。 |
| `vision_provider_id` | `string` | 空字符串 | 识图模型 provider。留空时优先使用 AstrBot 全局图片描述模型，再回退到当前会话模型。 |
| `comment_provider_id` | `string` | 空字符串 | 文本转述 provider。留空时使用当前会话模型。 |
| `vision_prompt` | `string` | `把图片中各种指标用文字描述出来` | 发送给视觉模型的提示词。 |
| `comment_prompt` | `string` | 见 schema | 发送给文本模型的提示词，使用 `{description}` 表示识图结果占位符。 |

## `traffic_monitor`

| 子字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `true` | 开启当月流量统计；关闭后不启动后台采样，也不在状态卡片展示流量行。 |
| `alert_enabled` | `bool` | `false` | 开启当月流量阈值提醒。 |
| `alert_threshold_gb` | `float` | `100.0` | 提醒阈值，单位固定为 GB，支持小数，按上传和下载合计计算。 |
| `alert_target_umo` | `string` | 空字符串 | 提醒目标 UMO，例如 `aiocqhttp:group:123456`；留空时不主动发送提醒。 |

## 配置维护规则

- README 中的配置表必须和 `_conf_schema.json` 保持一致。
- 运行时代码通过 `core.config_manager.ConfigManager` 读取配置，业务流程不要直接散落调用 `config.get(...)`。
- 删除、重命名或改变字段类型时，必须说明兼容影响。
- Provider 字段使用 AstrBot 的 `select_provider` 特殊选择器。
- `banner_image` 是用户文件路径入口，读取时必须保留路径范围检查。
- `traffic_monitor` 的统计基于系统网络计数器差值，首次启用只建立基线；系统重启或计数器重置期间的流量无法补记。
- 流量统计状态保存在 AstrBot 插件数据目录 `status_state.json` 的 `traffic_monitor` 命名空间中，仅保存当前自然月累计、上次采样基线和本月提醒状态。
- `auto_use_current_name` 表示状态卡片优先显示机器人自身身份，不表示命令发送者名称；平台无法提供机器人名称时按 `event.get_platform_id()`、`bot_name` 顺序回退。OneBot v11 平台标识使用 AstrBot 的真实名称 `aiocqhttp`，并通过 `get_login_info.nickname` 尝试获取机器人昵称。
- 状态卡片渲染 payload 会限制机器人名称展示长度，超长时在中间用 `...` 省略；`HtmlRender.build_status_text()` 的文本摘要保留完整名称。
- `comment_prompt` 修改时必须保留 `{description}` 语义，或同步修改代码中的替换逻辑。

## 历史配置兼容

- 旧版本曾把 `auto_use_current_name` 的默认值写成字符串 `"true"`，导致 AstrBot WebUI 保存配置时布尔类型校验失败（Issue #23）。
- 插件加载时会调用 `core.config_manager.normalize_legacy_bool_configs()`，把该字段的历史字符串布尔值在内存中归一化为原生布尔值，**不主动写盘**；用户在 WebUI 正常保存时由 AstrBot 完成持久化。
- 归一化复用与运行时读取相同的映射（`parse_bool_token()`）：`true`/`1`/`yes`/`on` 视为 `True`，`false`/`0`/`no`/`off` 视为 `False`，忽略大小写和首尾空格。
- `migrate_legacy_bool_config()` 的返回值区分三种情况：`True` 表示已归一化历史字符串；`False` 表示无需迁移（字段缺失或已是原生布尔值）；`None` 表示值不合法（无法识别的字符串，或非 `bool` 非 `str` 的其他类型）。
- 非法值一律**保留原值不覆盖**并记录 warning，需在 WebUI 中重新设置为开启或关闭；原生布尔值不会被改动。
- 归一化只在插件启用（初始化）时执行；插件处于禁用状态时旧配置不会被自动归一化。
- `tests/test_config_integration.py` 使用真实 `AstrBotConfig` 验证历史 `"true"`、`"false"` 和原生 `false` 的读取 → 核心归一化 → `validate_config()` 校验 → `save_config()` 保存 → 重新加载。它不实例化 `StatusPlugin`，也不执行浏览器 WebUI 操作；插件构造函数的迁移调用顺序由 `tests/test_architecture_boundaries.py` 中的 AST 测试单独检查。
