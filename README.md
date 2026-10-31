# 🌟 系统状态

<div align="center">

<img src="https://count.getloli.com/@astrbot_plugin_status?name=astrbot_plugin_status&theme=rule34&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter">

**一个用于展示系统状态的简易可爱插件，支持生成可视化的状态卡片。**

[![License: AGPL](https://img.shields.io/badge/License-AGPL-blue.svg)](https://opensource.org/licenses/agpl-3-0)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue)
![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.10.4-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
[![Last Commit](https://img.shields.io/github/last-commit/FlanChanXwO/astrbot_plugin_status)](https://github.com/FlanChanXwO/astrbot_plugin_status/commits/master)

</div>

本插件完全开源免费，欢迎 Issue 和 PR。

---

## 📸 预览

<div align="center">
  <table>
    <tr>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_status/master/assets/preview_1.png" width="400" alt="状态卡片预览1"/>
        <br/>
        <sub>状态卡片</sub>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_status/master/assets/preview_2.png" width="400" alt="状态卡片预览2"/>
        <br/>
        <sub>LLM 智能分析效果</sub>
      </td>
      <td align="center">
        <img src="https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_status/master/assets/preview_3.png" width="400" alt="状态卡片预览3"/>
        <br/>
        <sub>自定义背景图效果</sub>
      </td>
    </tr>
  </table>
</div>

---

## ✨ 功能特性

- 🖼️ **精美状态卡片** - 可视化展示 CPU、内存、磁盘、网络等系统状态
- 📝 **长名称适配** - CPU 和系统名称超过 36 个字符时在状态卡中间省略，文本摘要保留完整名称
- 🎨 **自定义背景** - 支持上传自定义背景图片，打造个性化状态卡片
- 📡 **当月流量统计** - 记录插件运行期间观察到的本月上传/下载流量，可配置阈值提醒
- 🤖 **LLM 智能分析** - 可选开启 AI 分析，自动解读系统状态
- ⚡ **性能优化** - 静态资源缓存、轻量采样，降低系统开销
- 🌐 **多平台支持** - 适配 AstrBot 支持的所有消息平台

---

## 📦 安装

### 方式一：通过 AstrBot 插件市场安装（推荐）

在 AstrBot 管理面板中搜索 `astrbot_plugin_status` 并安装。

### 方式二：手动安装

1. 克隆本仓库到 AstrBot 的插件目录：
   ```bash
   cd AstrBot/data/plugins
   git clone https://github.com/FlanChanXwO/astrbot_plugin_status.git
   ```

2. 重启 AstrBot 或重载插件

---

## 🛠️ 配置项

在 AstrBot 管理面板中配置以下选项：

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `auto_use_current_name` | 布尔值 | 自动获取机器人自身名称或标识；取不到时回退到平台实例 ID，再取不到时使用 `bot_name` | `true` |
| `bot_name` | 字符串 | 显示在状态卡片上的机器人名称 | `AstrBot` |
| `banner_image` | 文件列表 | 自定义状态背景图（支持 png/jpg/jpeg），可上传多张随机展示 | `[]` |
| `traffic_monitor` | 对象 | 流量统计设置，包含当月统计开关、提醒开关、提醒阈值和提醒目标 UMO | 见 `_conf_schema.json` |
| `enable_llm_analysis` | 布尔值 | 是否在返回状态图后调用 LLM 进行智能分析 | `false` |
| `vision_provider_id` | 字符串 | 识图模型 provider，留空时优先使用 AstrBot 全局图片描述模型 | `""` |
| `comment_provider_id` | 字符串 | 文本转述 provider，留空时使用当前会话模型 | `""` |
| `vision_prompt` | 字符串 | 发送给视觉模型的提示词 | `把图片中各种指标用文字描述出来` |
| `comment_prompt` | 字符串 | 发送给文本模型的提示词，使用 `{description}` 表示识图结果 | 见 `_conf_schema.json` |

### 配置示例

```json
{
  "auto_use_current_name": false,
  "bot_name": "我的Bot",
  "banner_image": ["/path/to/banner1.png", "/path/to/banner2.jpg"],
  "traffic_monitor": {
    "enabled": true,
    "alert_enabled": false,
    "alert_threshold_gb": 100.0,
    "alert_target_umo": ""
  },
  "enable_llm_analysis": true,
  "vision_provider_id": "",
  "comment_provider_id": "",
  "vision_prompt": "请描述这张系统状态图片中的关键指标",
  "comment_prompt": "请根据以下状态描述判断是否异常：{description}"
}
```

### 自动获取名称支持范围

启用 `auto_use_current_name` 后，状态卡片会优先显示机器人自身名称或账号标识，不同平台适配器暴露的信息不同，无法取得机器人显示名时会回退到 `event.get_platform_id()`；若平台实例 ID 也不可用，则使用手动配置的 `bot_name`。状态卡片上的名称过长时会在中间使用 `...` 省略，文本摘要仍保留完整名称。

| 平台 | 优先读取 | 回退规则 |
|------|----------|----------|
| kook | `client.bot_nickname`，其次 `client.bot_username` | 取不到名称时使用 `event.get_platform_id()`，再取不到时使用 `bot_name` |
| mattermost | `bot_username` | 取不到名称时使用 `event.get_platform_id()`，再取不到时使用 `bot_name` |
| misskey | `_bot_username` | 取不到名称时使用 `event.get_platform_id()`，再取不到时使用 `bot_name` |
| discord | `client.user.display_name`，其次 `client.user.name` / `client.user.global_name` | 取不到名称时使用 `event.get_platform_id()`，再取不到时使用 `bot_name` |
| telegram | `client.username`，其次 `application.bot.username` | 取不到名称时使用 `event.get_platform_id()`，再取不到时使用 `bot_name` |
| aiocqhttp | OneBot `get_login_info.nickname` | 调用失败或昵称为空时使用 `event.get_platform_id()`，再取不到时使用 `bot_name` |

---

## 📝 使用方法

> [!IMPORTANT]
> **关于 T2I 渲染服务**
>
> 本插件依赖 AstrBot 的 T2I（HTML 转图片）功能生成状态卡片。由于公共 T2I 服务的节点在国外，第三方公共 T2I 服务通常有请求大小限制或 SSL 连接问题，**强烈建议自建 T2I 服务**以获得最佳体验。
>
> - 自部署文档：[AstrBot T2I 服务部署指南](https://docs.astrbot.app/others/self-host-t2i.html)

### 基础命令

发送以下任一指令即可获取系统状态卡片：

```
/状态
/status
```

### 使用 LLM 分析功能

1. 在配置中开启 `enable_llm_analysis`
2. 确保已配置 LLM 提供商
3. 发送 `/状态` 后，Bot 会先发送状态图片，然后自动返回 AI 分析结果

### 当月流量统计

默认开启后，插件会在后台每 300 秒采样一次系统网络计数器，并在状态卡片详情框中显示本月上传和下载累计；卡片中月份使用英文缩写，例如 `Jul`。统计从插件启用后的首次采样开始；如果 AstrBot 未运行、系统重启或网络计数器重置，中间流量无法补记。

如需提醒，在 `traffic_monitor` 中开启 `alert_enabled`，设置 `alert_threshold_gb`，并填写提醒目标 `alert_target_umo`（格式如 `aiocqhttp:group:123456`）。阈值支持小数 GiB，例如 `0.02`；当本月上传和下载合计达到阈值时，每个自然月最多提醒一次。

流量状态保存在 AstrBot 插件数据目录的 `status_state.json` 中。


### 自定义背景图

1. 在配置中找到 `banner_image` 项
2. 点击上传按钮选择背景图片（推荐尺寸：1200x600 或更高）
3. 保存配置后发送 `/状态` 查看效果

---

## 📄 开源协议

本项目基于 [AGPL](LICENSE) 协议开源。

---
