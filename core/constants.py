from __future__ import annotations

DEFAULT_BOT_NAME = "AstrBot"
DEFAULT_DASHBOARD_NAME = "AstrBot"
MAX_RENDERED_BOT_NAME_LENGTH = 15
MAX_RENDERED_DETAIL_NAME_LENGTH = 36
DEFAULT_TIMEOUT = 30
LLM_TIMEOUT = 60
MAX_FILE_SIZE = 5 * 1024 * 1024
TRAFFIC_SAMPLE_INTERVAL_SECONDS = 300
PLUGIN_STATE_FILE = "status_state.json"

DEFAULT_VISION_PROMPT = "把图片中各种指标用文字描述出来"
DEFAULT_COMMENT_PROMPT = (
    "根据以下系统状态描述，用简洁友好的语气总结当前服务器状况，重点关注异常项。\n\n"
    "系统状态描述：{description}"
)

RENDER_OPTIONS = {"full_page": True, "type": "png", "scale": "device"}

STATUS_TOOL_NAME = "astrbot_get_system_status"
STATUS_TOOL_DESCRIPTION = (
    "Get the current system status image including CPU, RAM, SWAP, DISK, "
    "network usage and uptime. Call this when user asks about system status, "
    "server status, or machine status."
)
