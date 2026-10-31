from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support import (
    create_core_package,
    install_astrbot_stubs,
    install_psutil_stub,
    load_core_module,
)

PACKAGE_NAME = "status_core_traffic_tests"

install_astrbot_stubs()
install_psutil_stub()
create_core_package(PACKAGE_NAME)

load_core_module(PACKAGE_NAME, "constants")
load_core_module(PACKAGE_NAME, "logger")
load_core_module(PACKAGE_NAME, "state_store")
config_module = load_core_module(PACKAGE_NAME, "config_manager")
traffic_module = load_core_module(PACKAGE_NAME, "traffic_usage")

TrafficMonitorConfig = config_module.TrafficMonitorConfig
TrafficUsageRecorder = traffic_module.TrafficUsageRecorder
MonthlyTrafficUsage = traffic_module.MonthlyTrafficUsage
PLUGIN_STATE_FILE = traffic_module.PLUGIN_STATE_FILE
TRAFFIC_STATE_NAMESPACE = traffic_module.TRAFFIC_STATE_NAMESPACE
build_alert_text = traffic_module.build_alert_text

pytestmark = pytest.mark.asyncio


class CounterSequence:
    def __init__(self, values: list[tuple[int, int]]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> SimpleNamespace:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return SimpleNamespace(bytes_sent=value[0], bytes_recv=value[1])


class TimeSequence:
    def __init__(self, values: list[dt.datetime]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> dt.datetime:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


def _config(
    *,
    alert_enabled: bool = False,
    alert_threshold_gb: float = 100.0,
    alert_target_umo: str = "",
) -> TrafficMonitorConfig:
    return TrafficMonitorConfig(
        enabled=True,
        alert_enabled=alert_enabled,
        alert_threshold_gb=alert_threshold_gb,
        alert_target_umo=alert_target_umo,
    )


def _recorder(
    tmp_path: Path,
    *,
    counters: list[tuple[int, int]],
    times: list[dt.datetime] | None = None,
    config: TrafficMonitorConfig | None = None,
    send_alert: object | None = None,
) -> TrafficUsageRecorder:
    return TrafficUsageRecorder(
        data_dir=tmp_path,
        config=config or _config(),
        counter_reader=CounterSequence(counters),
        now_provider=TimeSequence(
            times or [dt.datetime(2026, 7, 1, 0, 0, 0)] * len(counters)
        ),
        send_alert=send_alert,
        sample_interval_seconds=300,
    )


async def test_first_sample_builds_baseline_without_usage(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path, counters=[(1000, 2000)])

    usage = await recorder.sample()

    assert usage.month == "2026-07"
    assert usage.upload_bytes == 0
    assert usage.download_bytes == 0
    assert (tmp_path / PLUGIN_STATE_FILE).exists()
    saved = json.loads((tmp_path / PLUGIN_STATE_FILE).read_text("utf-8"))
    assert "schema_version" not in saved[TRAFFIC_STATE_NAMESPACE]


async def test_same_month_samples_accumulate_deltas(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path, counters=[(1000, 2000), (1600, 2500)])

    await recorder.sample()
    usage = await recorder.sample()

    assert usage.upload_bytes == 600
    assert usage.download_bytes == 500
    assert usage.total_bytes == 1100


async def test_month_change_resets_usage_and_rebuilds_baseline(
    tmp_path: Path,
) -> None:
    recorder = _recorder(
        tmp_path,
        counters=[(100, 100), (200, 300), (500, 900)],
        times=[
            dt.datetime(2026, 7, 31, 23, 55, 0),
            dt.datetime(2026, 7, 31, 23, 59, 0),
            dt.datetime(2026, 8, 1, 0, 4, 0),
        ],
    )

    await recorder.sample()
    july_usage = await recorder.sample()
    august_usage = await recorder.sample()

    assert july_usage.month == "2026-07"
    assert july_usage.total_bytes == 300
    assert august_usage.month == "2026-08"
    assert august_usage.total_bytes == 0


async def test_counter_reset_does_not_create_negative_usage(
    tmp_path: Path,
) -> None:
    recorder = _recorder(
        tmp_path,
        counters=[(1000, 1000), (900, 950), (1000, 1050)],
    )

    await recorder.sample()
    reset_usage = await recorder.sample()
    next_usage = await recorder.sample()

    assert reset_usage.total_bytes == 0
    assert next_usage.upload_bytes == 100
    assert next_usage.download_bytes == 100


async def test_corrupted_state_file_recovers_with_new_baseline(
    tmp_path: Path,
) -> None:
    (tmp_path / PLUGIN_STATE_FILE).write_text("{bad json", encoding="utf-8")
    recorder = _recorder(tmp_path, counters=[(100, 200)])

    usage = await recorder.sample()
    saved = json.loads((tmp_path / PLUGIN_STATE_FILE).read_text("utf-8"))

    assert usage.total_bytes == 0
    assert saved[TRAFFIC_STATE_NAMESPACE]["month"] == "2026-07"


async def test_alert_is_sent_once_per_month(tmp_path: Path) -> None:
    sent_alerts: list[tuple[str, str]] = []

    async def send_alert(umo: str, text: str) -> None:
        sent_alerts.append((umo, text))

    recorder = _recorder(
        tmp_path,
        counters=[(0, 0), (800, 800), (1200, 1200)],
        config=_config(
            alert_enabled=True,
            alert_threshold_gb=0.000001,
            alert_target_umo="aiocqhttp:group:123456",
        ),
        send_alert=send_alert,
    )

    await recorder.sample()
    await recorder.sample()
    await recorder.sample()

    assert len(sent_alerts) == 1
    assert sent_alerts[0][0] == "aiocqhttp:group:123456"
    assert "本月流量提醒" in sent_alerts[0][1]
    assert "2026-07" in sent_alerts[0][1]


async def test_alert_text_preserves_decimal_threshold() -> None:
    text = build_alert_text(
        MonthlyTrafficUsage(
            month="2026-07",
            upload_bytes=10,
            download_bytes=20,
        ),
        threshold_gb=0.02,
    )

    assert "阈值: 0.02 GiB" in text


async def test_card_text_uses_month_abbreviation() -> None:
    usage = MonthlyTrafficUsage(
        month="2026-07",
        upload_bytes=1024**3,
        download_bytes=2 * 1024**3,
    )

    assert usage.card_text == "Jul  ↑ 1.0 GiB | ↓ 2.0 GiB"
