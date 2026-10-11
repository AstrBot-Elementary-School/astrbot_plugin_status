# 架构说明

## 模块关系

```text
main.py
  -> core.ConfigManager
  -> core.TrafficUsageRecorder
       -> core.JsonStateStore
  -> core.HtmlRender
       -> core.BotIdentityResolver
       -> core.SystemDataSource
       -> core.TrafficUsageRecorder
       -> core.utils
       -> core.models.StatusPayload
       -> AstrBot html_render()
  -> core.StatusService
       -> AstrBot LLM provider
  -> core.logger
```

## `main.py`

`main.py` 保留插件入口职责：

- 初始化路径、`ConfigManager`、`HtmlRender` 和 `StatusService`
- 构造 `ConfigManager` 前通过 `_normalize_legacy_config()` 归一化历史字符串布尔配置（仅修改内存，不主动保存）
- 初始化 `TrafficUsageRecorder`，并在插件启停时启动或取消后台采样任务
- 注册和注销 `astrbot_get_system_status`
- 将 `/status`、`/状态` 事件转发给 `StatusService`

不要把复杂采集、图片资源选择、CSS 内联或 payload 组装重新塞回 `main.py`。

## `core/status_service.py`

`StatusService` 负责路由和 LLM 分支：

- 处理 `/status`、`/状态` 的流程分支
- 处理 `astrbot_get_system_status` tool 的发送和返回
- 根据配置解析 provider，并区分配置缺失、模型超时和异常
- 调用 `HtmlRender` 获取状态图 URL 和文本摘要，但不直接拼接渲染数据

## `core/html_render.py`

`HtmlRender` 负责状态图渲染和数据拼接：

- 管理模板、CSS、默认 Banner 和角色图片资源路径
- 调用 `BotIdentityResolver` 解析状态卡片展示的机器人名称
- 调用 `SystemDataSource` 采集状态指标
- 调用 `TrafficUsageRecorder` 更新和读取当月流量统计
- 构建 `StatusPayload` 和 LLM tool 文本摘要
- 调用 AstrBot `html_render()` 生成图片 URL

## `core/data_source.py`

`SystemDataSource` 负责读取运行环境状态：

- CPU 百分比、频率、核心数和名称
- 内存、交换分区、磁盘
- 系统负载
- 网络瞬时上传/下载速度
- AstrBot 版本和已加载插件数
- 当前进程运行时间

macOS 的 CPU 详情名称优先从 `system_profiler SPHardwareDataType` 的 `Chip` 字段读取，只显示芯片或处理器名称；CPU 使用率指标通过 `psutil` 区分物理核和线程数，渲染文本使用英文单位，例如 `10 Cores / 20 Threads`。

网络速度是基于两次采样之间的差值计算的，因此首次调用通常返回 `0.0`。

## `core/traffic_usage.py`

`TrafficUsageRecorder` 负责插件运行期间观察到的当月流量累计：

- 使用 `psutil.net_io_counters()` 读取整机上传/下载累计字节数
- 使用独立采样基线，不复用 `SystemDataSource.get_net_speed_kbs()` 的瞬时网速基线
- 将当前自然月累计、上次采样基线和本月提醒状态写入插件数据目录的 `status_state.json` 中的 `traffic_monitor` 命名空间
- 月份变化、系统重启或计数器回退时重新建立基线，不补记无法观察到的流量
- 当配置开启提醒且上传+下载合计达到阈值时，每个自然月最多向配置的 UMO 发送一次提醒

## `core/state_store.py`

`JsonStateStore` 负责插件级轻量状态持久化：

- 使用单个 `status_state.json` 承载多个功能命名空间，避免未来功能继续增加散落 JSON 文件
- 写入时先写临时文件再替换，降低半写入破坏状态的概率
- 只保存运行态轻量状态，不保存完整历史指标

`HtmlRender.build_render_data()` 负责把模板、CSS、图片资源和系统数据组装为：

- HTML 模板文本
- `StatusPayload`

它不负责发送消息；对外业务代码通过 `HtmlRender.render_status_image()` 和 `HtmlRender.build_status_text()` 使用渲染能力，不直接拼接状态图数据。

状态卡 payload 中的机器人名称超过 `MAX_RENDERED_BOT_NAME_LENGTH=15` 字符时使用中间省略；CPU 和 System（操作系统）名称超过 `MAX_RENDERED_DETAIL_NAME_LENGTH=36` 字符时也使用中间省略，保持单行布局。名称截断仅发生在展示层，`SystemDataSource` 提供完整的 CPU 和系统名称，文本状态摘要保留完整名称。

状态图 payload 中的当月流量由 `TrafficUsageRecorder` 格式化为详情框的 `Traffic` 行，月份使用英文缩写，例如 `Jul`；关闭流量统计时该行不渲染。

## `core/utils.py`

工具函数集中处理可复用边界：

- 字体资源内联
- 图片转 Data URI
- 随机选择用户 Banner、默认 Banner 或角色图片
- 本地路径范围检查
- 图片大小限制

路径安全是硬边界：用户路径必须限制在插件目录或插件数据目录内。

## `core/config_manager.py`

`ConfigManager.load()` 负责集中读取并容错解析配置字段，不直接修改原始 `AstrBotConfig`。历史字符串布尔值由插件构造时调用的 `normalize_legacy_bool_configs()` 在内存中归一化；Schema 类型校验和配置保存由 AstrBot 框架负责。入口和核心模块应读取已解析后的属性，不要在业务流程里散落直接调用 `config.get(...)`。

`auto_use_current_name` 的语义是解析机器人自身名称或标识，用于状态卡片中的机器人名称展示。平台适配器无法提供机器人显示名时，名称解析应回退到 `event.get_platform_id()`，仍不可用时回退到手动配置的 `bot_name`；该配置不应解析为命令发送者名称。

## `core/bot_identity_resolver.py`

`BotIdentityResolver` 负责按当前事件和平台实例解析机器人自身显示名。它通过 `Context.get_platform_inst(event.get_platform_id())` 优先定位当前平台实例，并按白名单读取 `kook`、`mattermost`、`misskey`、`discord`、`telegram` 的可用机器人昵称或账号标识；`aiocqhttp` 使用 OneBot `get_login_info.nickname` 动态获取机器人昵称。取不到时回退到 `event.get_platform_id()`，再取不到时回退到 `ConfigManager.bot_name`。

AstrBot 的 OneBot v11 平台标识是 `aiocqhttp`，不是 `aiohttpcq`；文档和代码均应使用 `PlatformMetadata.name` 的真实值。

禁止使用 `event.get_sender_name()` 作为机器人名称来源，因为该方法表示命令发送者。

## `core/logger.py`

`core.logger` 负责集中包装 AstrBot logger，并为插件日志统一添加 `[astrbot_plugin_status]` 前缀。业务模块应使用 `from .logger import logger` 或 `get_logger()`，不要直接从 `astrbot.api` 导入原始 logger，也不要在消息文本中手写局部插件前缀。

## 渲染链路

1. 命令或 tool handler 进入 `StatusService`
2. `StatusService` 调用 `HtmlRender.render_status_image()`
3. `HtmlRender` 使用 `SystemDataSource` 拼接 HTML 与 payload
4. `HtmlRender` 触发一次当月流量采样并把当前累计写入 payload
5. `HtmlRender` 调用 AstrBot `html_render()` 生成图片 URL
6. 命令路径返回图片；LLM tool 路径发送图片并通过 `HtmlRender.build_status_text()` 返回文本状态摘要

## 模板边界

`templates/main.html` 的背景 paw SVG 必须保留在 `.card` 内部，由 `.card { overflow: hidden; }` 负责裁剪。不要把这些绝对定位装饰元素移到 `.card` 外面，否则 AstrBot/T2I 的 full-page 截图会把它们计入页面滚动高度，导致状态卡片底部出现大块留白。

## LLM 分析链路

开启 `enable_llm_analysis` 后，`/status` 会：

1. 先发送状态图片
2. 使用 `vision_provider_id` 或全局图片描述模型识别图片
3. 使用 `comment_provider_id` 或当前会话模型生成文字总结
4. 视觉模型未配置、返回空结果或超时时，向用户返回明确提示

Provider 选择逻辑位于 `StatusService.resolve_provider()`。
