# Changelog

## [2.1.1] - 2026-10-11

### Fixed

- 修复 `auto_use_current_name` 配置默认值类型错误（`"true"` 写成字符串），避免插件配置保存时发生布尔类型校验失败；并在插件加载时对历史字符串布尔配置做内存归一化，用户下次在 WebUI 正常保存时完成持久化（Issue #23）。

### Changed

- 状态卡 CPU 和 System（操作系统）名称超过 36 个字符时使用中间省略，保持单行展示；文本状态摘要保留完整名称。

## [2.1.0] - 2026-07-07

### Added

- 新增当月流量统计：插件运行时定期采样系统网络计数器，在状态卡片中展示本月上传/下载累计。
- 新增 `traffic_monitor` 配置项，支持开启/关闭当月流量统计、配置流量提醒开关、提醒阈值和提醒目标 UMO。
- 新增当月流量阈值提醒：上传和下载合计达到阈值后，每个自然月最多向配置目标发送一次提醒。

### Changed

- 状态图详情区域新增 `Traffic` 行，展示当前自然月累计流量，月份使用英文缩写。
- LLM tool 返回的文本状态摘要新增本月流量汇总，便于模型分析系统网络使用情况。

## [2.0.0] - 2026-05-27

### Changed

- 重构插件架构：`main.py` 仅保留 AstrBot 插件入口、生命周期和命令注册职责，主要业务逻辑迁移到 `core/` 包。
- 新增 `StatusService` 作为状态命令和 LLM tool 的业务路由层，负责消息发送、LLM 分析分支和 provider 选择。
- 新增 `HtmlRender` 作为状态图渲染层，统一负责模板读取、CSS/字体/图片资源处理、状态数据拼接、`StatusPayload` 构建和文本摘要生成。
- 将配置读取集中到 `ConfigManager`，入口和业务模块不再散落直接读取原始配置。
- 将常量集中到 `core/constants.py`，避免命令名、工具描述、渲染选项和限制值分散维护。
- 状态图渲染链路现在按 `main.py -> StatusService -> HtmlRender -> SystemDataSource` 分层，便于测试和后续维护。

### Added

- 新增 `core/logger.py`，统一包装 AstrBot logger，并为插件日志添加 `[astrbot_plugin_status]` 前缀。
- 新增 `BotIdentityResolver`，集中解析机器人自身显示名，并支持 `kook`、`mattermost`、`misskey`、`discord`、`telegram`、`aiocqhttp` 的平台差异；其中 `aiocqhttp` 通过 OneBot `get_login_info.nickname` 获取机器人昵称。
- 新增 `auto_use_current_name` 配置支持：启用后优先获取机器人自身名称或标识，无法获取名称时回退到平台实例 ID，最后回退到手动配置的 `bot_name`。
- 新增架构边界测试，防止渲染数据拼接重新回到 `StatusService` 或 `main.py`。
- 新增 T2I 回归测试，用于验证状态图底部不再出现大块白色留白。
- 新增项目文档目录，记录架构、配置、开发、测试和维护约束。
- 新增 `AGENTS.md` 和 `CLAUDE.md`，为协作 agent 提供精简项目规则入口。

### Fixed

- 修复背景 paw 装饰在 T2I full-page 截图中被计入页面滚动高度后导致底部异常留白的问题。
- 修复部分 paw 装饰因布局位置调整不当导致从状态图中消失的问题。
- 修复 `auto_use_current_name` 误把命令发送者名称当作机器人名称的问题。
- 修复 macOS 下 Apple Silicon 芯片名称不准确；CPU 详情行仅显示芯片名称，CPU 指标行区分物理核和线程数且单位文本统一使用英文。

### Removed

- 移除根目录下分散的业务模块文件，相关代码统一迁移到 `core/` 包。

## [1.0.4] - 2026-05-24

### Fixed
- 修复LLM超时无用户提示的问题

### Changed

- LLM分析拆分为两步：视觉模型识图→文本模型转述，避免非vision模型传图片导致400错误

### Added
- 新增 vision_provider_id / comment_provider_id 配置项，支持单独指定识图和转述模型
- 新增 vision_prompt / comment_prompt 配置项，支持自定义提示词
- 添加 _resolve_provider 方法，模型解析优先级：配置 > 框架全局视觉模型 > 当前会话模型
- 补充调用模型时的日志输出

## [1.0.3] - 2026-04-10

### Fixed

- 修复运行时间显示为系统启动时间而非 AstrBot 进程运行时间的问题，改用 `psutil.Process(os.getpid()).create_time()` (data_source.py:34)
- 修复llm调用不会自行发送状态图片的问题

### Changed

- **LLM调用返回结果优化**：现在LLM结果兼容非多模态模型，且不再需要依赖于tool工具的调用图片缓存
- **T2I 渲染性能优化**：通过将 Google Fonts 内联为 base64 Data URI 消除外部网络依赖，移除渲染时的 CDN 请求
- **图片优化**：将所有横幅和角色图片转换为 WebP 格式以减小文件体积
- **字体优化**：
  - `baotu.ttf`：压缩一半的字体大小，以确保常用的字体都可以使用
  - 其他字体 (`DingTalk-JinBuTi.ttf`, `Ma-Shan-Zheng-Regular.ttf`, `Noto-Sans-SC-*.ttf`, `Spicy-Rice-Regular.ttf`, `ADLaM-Display-Regular.ttf`)：通过子集化优化减小体积

### Added

- 在 `get_image_data_uri()` 函数中添加 WebP MIME 类型支持 (utils.py:113-114)

## [1.0.2] - 2026-03-11

### Removed

- 移除了不必要的模块导入

## [1.0.1] - 2026-03-08

### Changed

- 在所有模块中使用 `astrbot.api` 导入日志记录器
- 优化获取系统信息时的性能
- 使用 StarTools 改进数据存储位置的获取

### Added

- 为图片提供默认的 base64 透明占位符

## [1.0.0] - 2026-03-08

### Added

- astrbot_plugin_status 初始版本发布
- 系统状态卡片渲染，包含 CPU、RAM、SWAP、DISK 和 LOAD 指标
- HTML 转图片 (T2I) 渲染支持
- LLM 工具集成，供 Agent 获取状态图片
- 可通过配置自定义机器人名称和横幅图片
- 网络速度监控（上传/下载）
- 插件数量显示
- 跨平台支持（Windows、Linux）
