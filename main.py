from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.register import llm_tools

from .core import (
    ConfigManager,
    HtmlRender,
    StatusService,
    TrafficUsageRecorder,
    normalize_legacy_bool_configs,
)
from .core.constants import STATUS_TOOL_DESCRIPTION, STATUS_TOOL_NAME
from .core.logger import logger
from .core.traffic_usage import cancel_task

_LEGACY_BOOL_KEYS = ("auto_use_current_name",)


class StatusPlugin(Star):
    """系统状态卡插件入口，负责框架生命周期和命令注册。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.base_dir = Path(__file__).parent
        self._normalize_legacy_config(config)
        self.config_manager = ConfigManager(config)
        self.config_manager.load()
        self.plugin_data_dir = StarTools.get_data_dir(self.name)
        self.traffic_recorder = TrafficUsageRecorder(
            data_dir=self.plugin_data_dir,
            config=self.config_manager.traffic_monitor,
            send_alert=self._send_traffic_alert,
        )
        self._traffic_task: asyncio.Task[object] | None = None
        self.html_renderer = HtmlRender(
            context=context,
            config_manager=self.config_manager,
            base_dir=self.base_dir,
            plugin_data_dir=self.plugin_data_dir,
            html_render=self.html_render,
            traffic_recorder=self.traffic_recorder,
        )
        self.status_service = StatusService(
            context=context,
            config_manager=self.config_manager,
            html_renderer=self.html_renderer,
        )

    @staticmethod
    def _normalize_legacy_config(config: AstrBotConfig) -> None:
        """把历史字符串布尔配置就地归一化为原生 bool，不写盘。

        兼容 Issue #23：旧配置中的 "true"/"false" 字符串会触发 WebUI 布尔
        校验失败。这里只改内存对象；用户在 WebUI 正常保存时由 AstrBot 持久化。
        """
        invalid = normalize_legacy_bool_configs(config, _LEGACY_BOOL_KEYS)
        for key in invalid:
            logger.warning(
                f"配置项 {key} 的值既不是布尔值也无法识别为布尔字符串，"
                "已保留原值，请在 WebUI 中重新设置为开启或关闭。"
            )

    async def initialize(self) -> None:
        """Register LLM tool for Agent to fetch status image."""
        llm_tools.add_func(
            name=STATUS_TOOL_NAME,
            func_args=[],
            desc=STATUS_TOOL_DESCRIPTION,
            handler=self.status_service.get_status_tool_handler,
        )
        tool = llm_tools.get_func(STATUS_TOOL_NAME)
        if tool:
            tool.handler_module_path = __name__
        if self.config_manager.traffic_monitor.enabled:
            self._traffic_task = asyncio.create_task(
                self.traffic_recorder.run_forever()
            )

    async def terminate(self) -> None:
        """Unregister LLM tool on plugin disable."""
        llm_tools.remove_func(STATUS_TOOL_NAME)
        await cancel_task(self._traffic_task)
        self._traffic_task = None
        await self.traffic_recorder.close()

    @filter.command("status", alias={"状态"})
    async def show_status(self, event: AstrMessageEvent):
        """返回状态图片"""
        async for result in self.status_service.show_status(event):
            yield result

    async def _send_traffic_alert(self, umo: str, text: str) -> None:
        """向配置的 UMO 发送当月流量提醒。"""
        await self.context.send_message(umo, MessageChain().message(text))
