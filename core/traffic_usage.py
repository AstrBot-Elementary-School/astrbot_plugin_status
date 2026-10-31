from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from .config_manager import TrafficMonitorConfig
from .constants import PLUGIN_STATE_FILE, TRAFFIC_SAMPLE_INTERVAL_SECONDS
from .logger import logger
from .state_store import JsonStateStore

BYTES_PER_KB = 1024
BYTES_PER_MB = BYTES_PER_KB**2
BYTES_PER_GB = BYTES_PER_KB**3
BYTES_PER_TB = BYTES_PER_KB**4
TRAFFIC_STATE_NAMESPACE = "traffic_monitor"
MONTH_ABBREVIATIONS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

AlertSender = Callable[[str, str], Awaitable[None]]
CounterReader = Callable[[], Any]
NowProvider = Callable[[], dt.datetime]


@dataclass(slots=True, frozen=True)
class MonthlyTrafficUsage:
    """当前自然月累计的网络流量。"""

    month: str
    upload_bytes: int
    download_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.upload_bytes + self.download_bytes

    @property
    def card_text(self) -> str:
        return (
            f"{format_month_abbreviation(self.month)}  ↑ "
            f"{format_bytes(self.upload_bytes)} | "
            f"↓ {format_bytes(self.download_bytes)}"
        )

    @property
    def summary_text(self) -> str:
        return (
            f"合计 {format_bytes(self.total_bytes)}，"
            f"上传 {format_bytes(self.upload_bytes)}，"
            f"下载 {format_bytes(self.download_bytes)}"
        )


class TrafficUsageRecorder:
    """记录插件运行期间观察到的当月整机网络流量。"""

    def __init__(
        self,
        *,
        data_dir: Path,
        config: TrafficMonitorConfig,
        send_alert: AlertSender | None = None,
        counter_reader: CounterReader | None = None,
        now_provider: NowProvider | None = None,
        sample_interval_seconds: int = TRAFFIC_SAMPLE_INTERVAL_SECONDS,
    ) -> None:
        self.data_dir = data_dir
        self.state_store = JsonStateStore(self.data_dir, PLUGIN_STATE_FILE)
        self.config = config
        self.send_alert = send_alert
        self.counter_reader = counter_reader or psutil.net_io_counters
        self.now_provider = now_provider or dt.datetime.now
        self.sample_interval_seconds = sample_interval_seconds
        self._lock = asyncio.Lock()

    async def run_forever(self) -> None:
        """后台定时采样；插件卸载时由调用方取消该任务。"""
        while True:
            try:
                await self.sample()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("当月流量后台采样失败")
            await asyncio.sleep(self.sample_interval_seconds)

    async def sample(self) -> MonthlyTrafficUsage:
        """采样一次网络计数器并更新当前自然月累计。"""
        async with self._lock:
            now = self.now_provider()
            month = month_key(now)
            sent, recv = self._read_counter_bytes()
            timestamp = now.timestamp()
            state = await self._load_state()

            if state.get("month") != month:
                state = self._new_state(month, sent, recv, timestamp)
                await self._save_state(state)
                return self._usage_from_state(state)

            last_sample = state.get("last_sample")
            if not isinstance(last_sample, dict):
                state["last_sample"] = self._sample_dict(sent, recv, timestamp)
                await self._save_state(state)
                return self._usage_from_state(state)

            last_sent = self._to_non_negative_int(last_sample.get("bytes_sent"))
            last_recv = self._to_non_negative_int(last_sample.get("bytes_recv"))
            upload_delta = sent - last_sent
            download_delta = recv - last_recv

            if upload_delta < 0 or download_delta < 0:
                logger.warning("网络计数器回退，跳过本次当月流量累计并重建基线")
            else:
                state["upload_bytes"] = (
                    self._to_non_negative_int(state.get("upload_bytes")) + upload_delta
                )
                state["download_bytes"] = (
                    self._to_non_negative_int(state.get("download_bytes"))
                    + download_delta
                )

            state["last_sample"] = self._sample_dict(sent, recv, timestamp)
            usage = self._usage_from_state(state)
            alert_sent = await self._maybe_send_alert(state, usage)
            if alert_sent:
                state["alerted_month"] = usage.month
            await self._save_state(state)
            return self._usage_from_state(state)

    async def get_current_usage(self) -> MonthlyTrafficUsage:
        """读取当前状态文件；没有状态时返回当前月份的 0 流量。"""
        async with self._lock:
            now = self.now_provider()
            month = month_key(now)
            state = await self._load_state()
            if state.get("month") != month:
                return MonthlyTrafficUsage(
                    month=month, upload_bytes=0, download_bytes=0
                )
            return self._usage_from_state(state)

    async def close(self) -> None:
        """预留异步清理入口，便于生命周期代码保持一致。"""
        return None

    def _read_counter_bytes(self) -> tuple[int, int]:
        counters = self.counter_reader()
        return (
            self._to_non_negative_int(getattr(counters, "bytes_sent", 0)),
            self._to_non_negative_int(getattr(counters, "bytes_recv", 0)),
        )

    async def _maybe_send_alert(
        self,
        state: dict[str, Any],
        usage: MonthlyTrafficUsage,
    ) -> bool:
        if not self.config.alert_enabled:
            return False
        if state.get("alerted_month") == usage.month:
            return False

        threshold_bytes = int(self.config.alert_threshold_gb * BYTES_PER_GB)
        if threshold_bytes <= 0 or usage.total_bytes < threshold_bytes:
            return False

        if not self.config.alert_target_umo:
            logger.warning("当月流量已超过提醒阈值，但未配置提醒目标 UMO")
            return False
        if self.send_alert is None:
            logger.warning("当月流量已超过提醒阈值，但提醒发送器未初始化")
            return False

        text = build_alert_text(
            usage,
            threshold_gb=self.config.alert_threshold_gb,
        )
        try:
            await self.send_alert(self.config.alert_target_umo, text)
        except Exception as exc:
            logger.warning(f"发送当月流量提醒失败: {exc}")
            return False

        logger.info(f"已发送 {usage.month} 当月流量提醒")
        return True

    async def _load_state(self) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(self._load_state_sync)
        except Exception as exc:
            logger.warning(f"读取当月流量状态失败，重新建立基线: {exc}")
            return {}

    def _load_state_sync(self) -> dict[str, Any]:
        return self.state_store.load_namespace(TRAFFIC_STATE_NAMESPACE)

    async def _save_state(self, state: dict[str, Any]) -> None:
        await asyncio.to_thread(self._save_state_sync, state)

    def _save_state_sync(self, state: dict[str, Any]) -> None:
        self.state_store.save_namespace(
            TRAFFIC_STATE_NAMESPACE,
            state,
            reset_on_corrupt=True,
        )

    def _new_state(
        self,
        month: str,
        sent: int,
        recv: int,
        timestamp: float,
    ) -> dict[str, Any]:
        return {
            "month": month,
            "upload_bytes": 0,
            "download_bytes": 0,
            "alerted_month": "",
            "last_sample": self._sample_dict(sent, recv, timestamp),
        }

    @staticmethod
    def _sample_dict(sent: int, recv: int, timestamp: float) -> dict[str, Any]:
        return {
            "timestamp": timestamp,
            "bytes_sent": sent,
            "bytes_recv": recv,
        }

    @classmethod
    def _usage_from_state(cls, state: dict[str, Any]) -> MonthlyTrafficUsage:
        return MonthlyTrafficUsage(
            month=str(state.get("month") or ""),
            upload_bytes=cls._to_non_negative_int(state.get("upload_bytes")),
            download_bytes=cls._to_non_negative_int(state.get("download_bytes")),
        )

    @staticmethod
    def _to_non_negative_int(value: Any) -> int:
        if isinstance(value, bool):
            return 0
        try:
            result = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, result)


def month_key(value: dt.datetime) -> str:
    return value.strftime("%Y-%m")


def format_month_abbreviation(month: str) -> str:
    try:
        month_number = int(month.split("-", maxsplit=1)[1])
    except (IndexError, ValueError):
        return "Month"
    if not 1 <= month_number <= 12:
        return "Month"
    return MONTH_ABBREVIATIONS[month_number - 1]


def format_bytes(value: int) -> str:
    size = max(0, int(value))
    if size >= BYTES_PER_TB:
        return f"{size / BYTES_PER_TB:.1f} TiB"
    if size >= BYTES_PER_GB:
        return f"{size / BYTES_PER_GB:.1f} GiB"
    if size >= BYTES_PER_MB:
        return f"{size / BYTES_PER_MB:.1f} MiB"
    if size >= BYTES_PER_KB:
        return f"{size / BYTES_PER_KB:.1f} KiB"
    return f"{size} B"


def build_alert_text(
    usage: MonthlyTrafficUsage,
    *,
    threshold_gb: float,
) -> str:
    return (
        "本月流量提醒\n"
        f"月份: {usage.month}\n"
        f"阈值: {format_gb_value(threshold_gb)} GiB\n"
        f"当前合计: {format_bytes(usage.total_bytes)}\n"
        f"上传: {format_bytes(usage.upload_bytes)}\n"
        f"下载: {format_bytes(usage.download_bytes)}"
    )


def format_gb_value(value: float) -> str:
    text = f"{max(0.0, float(value)):.6f}".rstrip("0").rstrip(".")
    return text or "0"


async def cancel_task(task: asyncio.Task[object] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
