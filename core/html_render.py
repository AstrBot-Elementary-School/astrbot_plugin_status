from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context

from .bot_identity_resolver import BotIdentityResolver
from .config_manager import ConfigManager
from .constants import (
    DEFAULT_DASHBOARD_NAME,
    MAX_RENDERED_BOT_NAME_LENGTH,
    MAX_RENDERED_DETAIL_NAME_LENGTH,
    RENDER_OPTIONS,
)
from .data_source import SystemDataSource
from .models import StatusPayload
from .logger import logger
from .traffic_usage import MonthlyTrafficUsage, TrafficUsageRecorder
from .utils import get_random_file_data_uri, inline_fonts_in_css, truncate_middle

HtmlRenderCallable = Callable[..., Awaitable[str]]


class HtmlRender:
    """负责状态图 HTML 数据拼接、图片渲染和文本摘要构建。"""

    def __init__(
        self,
        *,
        context: Context,
        config_manager: ConfigManager,
        base_dir: Path,
        plugin_data_dir: Path,
        html_render: HtmlRenderCallable,
        data_source: SystemDataSource | None = None,
        bot_identity_resolver: BotIdentityResolver | None = None,
        traffic_recorder: TrafficUsageRecorder | None = None,
    ) -> None:
        self.context = context
        self.config_manager = config_manager
        self.base_dir = base_dir
        self.plugin_data_dir = plugin_data_dir
        self.html_render = html_render
        self.template_path = self.base_dir / "templates" / "main.html"
        self.css_path = self.base_dir / "templates" / "res" / "css" / "style.css"
        self.character_dir = self.base_dir / "templates" / "res" / "image" / "character"
        self.default_banner_dir = (
            self.base_dir / "templates" / "res" / "image" / "banner"
        )
        self.render_options = dict(RENDER_OPTIONS)
        self.data_source = data_source or SystemDataSource(context, self.base_dir)
        self.bot_identity_resolver = bot_identity_resolver or BotIdentityResolver(
            context,
            config_manager,
        )
        self.traffic_recorder = traffic_recorder

    async def render_status_image(self, event: AstrMessageEvent) -> str:
        """构建状态卡数据，并调用 AstrBot html_render 生成图片 URL。"""
        html_content, payload = await self.build_render_data(event)
        return await self.html_render(
            html_content,
            asdict(payload),
            return_url=True,
            options=self.render_options,
        )

    async def build_status_text(self, event: AstrMessageEvent) -> str:
        """构建给 LLM tool 返回的纯文本状态摘要。"""
        metrics = self.data_source.get_metrics()
        cpu_name = await self.data_source.get_cpu_name()
        os_name = self.data_source.get_os_name()
        project_version = self.data_source.get_project_version(event)
        plugin_count = await self.data_source.get_plugin_counts()
        upload_kbs, download_kbs = self.data_source.get_net_speed_kbs()
        uptime = self.data_source.get_uptime_text()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bot_name = await self.bot_identity_resolver.resolve(event)
        monthly_traffic = await self._sample_monthly_traffic()
        monthly_traffic_line = (
            f"\n本月流量: {monthly_traffic.summary_text}"
            if monthly_traffic is not None
            else ""
        )

        metrics_map = {m.label: m.value for m in metrics}
        return f"""\
系统状态信息
================
机器人名称: {bot_name}
当前时间: {current_time}
框架版本: {project_version}
运行时间: {uptime}

系统信息
--------
操作系统: {os_name}
CPU: {cpu_name}

资源使用
--------
CPU: {metrics_map.get("CPU", "N/A")}
内存: {metrics_map.get("RAM", "N/A")}
交换: {metrics_map.get("SWAP", "N/A")}
磁盘: {metrics_map.get("DISK", "N/A")}
负载: {metrics_map.get("LOAD", "N/A")}

网络与插件
----------
网络速度: ↑{upload_kbs:.1f} KB/s ↓{download_kbs:.1f} KB/s
已加载插件: {plugin_count} 个{monthly_traffic_line}"""

    async def build_render_data(
        self, event: AstrMessageEvent
    ) -> tuple[str, StatusPayload]:
        """构建 HTML 模板和渲染 payload。"""
        html = self.template_path.read_text(encoding="utf-8-sig")
        banner_uri = get_random_file_data_uri(
            paths=self.config_manager.banner_paths,
            base_dir=self.base_dir,
            plugin_data_dir=self.plugin_data_dir,
            is_user_path=True,
            log_prefix="尝试使用自定义 Banner",
        )

        if not banner_uri:
            banner_uri = get_random_file_data_uri(
                directory=self.default_banner_dir,
                base_dir=self.base_dir,
                plugin_data_dir=self.plugin_data_dir,
                log_prefix="使用默认 Banner",
            )

        character_uri = get_random_file_data_uri(
            directory=self.character_dir,
            base_dir=self.base_dir,
            plugin_data_dir=self.plugin_data_dir,
        )

        css = self.css_path.read_text(encoding="utf-8-sig")
        css = css.replace("${topBannerImage}", banner_uri or "")
        css = css.replace("${characterImage}", character_uri or "")
        css = inline_fonts_in_css(css, self.base_dir)

        upload_kbs, download_kbs = self.data_source.get_net_speed_kbs()
        plugin_count_str = str(await self.data_source.get_plugin_counts())
        bot_name = await self.bot_identity_resolver.resolve(event)
        monthly_traffic = await self._sample_monthly_traffic()

        payload = StatusPayload(
            css_style=f"<style>{css}</style>",
            bot_name=truncate_middle(bot_name, MAX_RENDERED_BOT_NAME_LENGTH),
            metrics=self.data_source.get_metrics(),
            cpu_name=truncate_middle(
                await self.data_source.get_cpu_name(),
                MAX_RENDERED_DETAIL_NAME_LENGTH,
            ),
            os_name=truncate_middle(
                self.data_source.get_os_name(),
                MAX_RENDERED_DETAIL_NAME_LENGTH,
            ),
            project_version=self.data_source.get_project_version(event),
            plugin_count=plugin_count_str,
            upload_speed=f"{upload_kbs:.1f}",
            download_speed=f"{download_kbs:.1f}",
            monthly_traffic=monthly_traffic.card_text
            if monthly_traffic is not None
            else "",
            dashboard_name=DEFAULT_DASHBOARD_NAME,
            uptime=self.data_source.get_uptime_text(),
        )
        return html, payload

    async def _sample_monthly_traffic(self) -> MonthlyTrafficUsage | None:
        traffic_config = getattr(self.config_manager, "traffic_monitor", None)
        if not getattr(traffic_config, "enabled", False):
            return None
        if self.traffic_recorder is None:
            return None
        try:
            return await self.traffic_recorder.sample()
        except Exception:
            logger.exception("当月流量统计采样失败")
            return None
