from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.support import (
    ROOT,
    create_core_package,
    install_astrbot_stubs,
    install_psutil_stub,
    load_core_module,
)

PACKAGE_NAME = "status_core_data_source_tests"

install_astrbot_stubs(include_event=True)
install_psutil_stub()
create_core_package(PACKAGE_NAME)

load_core_module(PACKAGE_NAME, "logger")
load_core_module(PACKAGE_NAME, "models")
data_source_module = load_core_module(PACKAGE_NAME, "data_source")

SystemDataSource = data_source_module.SystemDataSource
SYSTEM_INFO_COMMAND_TIMEOUT_SECONDS = (
    data_source_module.SYSTEM_INFO_COMMAND_TIMEOUT_SECONDS
)
platform_module = data_source_module.platform
psutil_module = data_source_module.psutil


def _data_source() -> SystemDataSource:
    return SystemDataSource(SimpleNamespace(), ROOT)


def test_os_name_preserves_long_release_for_text_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = "6.12.74+deb13+1-cloud-amd64-extended"
    monkeypatch.setattr(platform_module, "system", lambda: "Linux")
    monkeypatch.setattr(platform_module, "release", lambda: release)

    assert _data_source().get_os_name() == f"Linux {release}"


@pytest.mark.asyncio
async def test_macos_cpu_name_uses_system_profiler_chip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _data_source()
    values = {
        ("system_profiler", "SPHardwareDataType"): """
Hardware:

    Hardware Overview:

      Model Name: MacBook Pro
      Chip: Apple M5
""",
    }

    async def fake_run_command_stdout(*args: str) -> str:
        return values[args]

    monkeypatch.setattr(platform_module, "system", lambda: "Darwin")
    monkeypatch.setattr(source, "_run_command_stdout", fake_run_command_stdout)

    assert await source.get_cpu_name() == "Apple M5"


@pytest.mark.asyncio
async def test_macos_cpu_name_falls_back_to_brand_string_when_chip_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _data_source()
    values = {
        ("system_profiler", "SPHardwareDataType"): "Hardware:\n",
        ("sysctl", "-n", "machdep.cpu.brand_string"): "Intel Core i9\n",
    }

    async def fake_run_command_stdout(*args: str) -> str:
        return values[args]

    monkeypatch.setattr(platform_module, "system", lambda: "Darwin")
    monkeypatch.setattr(source, "_run_command_stdout", fake_run_command_stdout)

    assert await source.get_cpu_name() == "Intel Core i9"


@pytest.mark.asyncio
async def test_macos_cpu_detail_name_does_not_include_core_or_thread_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _data_source()
    values = {
        ("system_profiler", "SPHardwareDataType"): "Chip: Apple M5\n",
    }

    async def fake_run_command_stdout(*args: str) -> str:
        return values[args]

    monkeypatch.setattr(platform_module, "system", lambda: "Darwin")
    monkeypatch.setattr(source, "_run_command_stdout", fake_run_command_stdout)

    cpu_name = await source.get_cpu_name()
    assert cpu_name == "Apple M5"
    assert "Core" not in cpu_name
    assert "Thread" not in cpu_name


@pytest.mark.asyncio
async def test_run_command_stdout_times_out_without_blocking_status_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _data_source()

    class FakeProc:
        returncode = None

        def __init__(self) -> None:
            self.killed = False

        async def communicate(self) -> tuple[bytes, bytes]:
            await data_source_module.asyncio.sleep(60)
            return b"late", b""

        def kill(self) -> None:
            self.killed = True

        async def wait(self) -> None:
            return None

    proc = FakeProc()

    async def fake_create_subprocess_exec(*args: str, **kwargs: object) -> FakeProc:
        return proc

    monkeypatch.setattr(
        data_source_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(data_source_module, "SYSTEM_INFO_COMMAND_TIMEOUT_SECONDS", 0.01)

    assert await source._run_command_stdout("slow-command") == ""
    assert proc.killed is True

    monkeypatch.setattr(
        data_source_module,
        "SYSTEM_INFO_COMMAND_TIMEOUT_SECONDS",
        SYSTEM_INFO_COMMAND_TIMEOUT_SECONDS,
    )


def test_cpu_display_uses_physical_core_and_logical_thread_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _data_source()

    monkeypatch.setattr(
        psutil_module,
        "cpu_freq",
        lambda: SimpleNamespace(current=0.0, max=0.0),
    )
    monkeypatch.setattr(
        psutil_module,
        "cpu_count",
        lambda logical=True: 20 if logical else 10,
    )

    assert source._cpu_display(12.3) == "12.3% [10 Cores / 20 Threads]"


def test_cpu_count_text_uses_english_singular_labels() -> None:
    assert SystemDataSource._format_cpu_count_text(1, 1) == "1 Core"
    assert SystemDataSource._format_cpu_count_text(0, 1) == "1 Thread"


@pytest.mark.parametrize(
    ("physical", "logical", "expected"),
    [
        (2, 2, "2 Cores"),
        (0, 2, "2 Threads"),
        (0, 0, "1 Thread"),
    ],
)
def test_cpu_count_text_covers_plural_and_empty_fallbacks(
    physical: int,
    logical: int,
    expected: str,
) -> None:
    assert SystemDataSource._format_cpu_count_text(physical, logical) == expected


def test_cpu_display_falls_back_when_psutil_cpu_count_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _data_source()

    monkeypatch.setattr(
        psutil_module,
        "cpu_freq",
        lambda: SimpleNamespace(current=0.0, max=0.0),
    )
    monkeypatch.setattr(psutil_module, "cpu_count", lambda logical=True: None)

    assert source._cpu_display(12.3) == "12.3% [1 Thread]"
