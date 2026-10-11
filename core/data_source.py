from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import platform
import shutil
import subprocess
import time
from pathlib import Path

import psutil

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context

from .logger import logger
from .models import Metric

SYSTEM_INFO_COMMAND_TIMEOUT_SECONDS = 2.0


class SystemDataSource:
    """
    系统数据源，用于获取系统状态信息
    """

    def __init__(self, context: Context, base_dir: Path):
        self.context = context
        self.base_dir = base_dir
        self._last_net_bytes_sent = 0
        self._last_net_bytes_recv = 0
        self._last_net_sample_ts = 0.0
        try:
            import os

            process = psutil.Process(os.getpid())
            self._system_start = dt.datetime.fromtimestamp(process.create_time())
        except Exception as e:
            logger.debug(f"Failed to get process start time: {e}, fallback to now")
            self._system_start = dt.datetime.now()

    def get_metrics(self) -> list[Metric]:
        """
        获取所有系统指标
        :return: 指标列表
        """
        cpu_pct = self._cpu_percent()
        mem_used_gb, mem_total_gb, mem_pct = self._memory_usage()
        swap_used_gb, swap_total_gb, swap_pct = self._swap_usage()
        disk_used_gb, disk_total_gb, disk_pct = self._disk_usage()
        load_pct = self._load_percent(cpu_pct)

        return [
            Metric(
                icon_class="icon-cpu",
                label="CPU",
                value=self._cpu_display(cpu_pct),
                offset=self._offset(cpu_pct),
            ),
            Metric(
                icon_class="icon-ram",
                label="RAM",
                value=f"{mem_used_gb:.2f} / {mem_total_gb:.2f} GB",
                offset=self._offset(mem_pct),
            ),
            Metric(
                icon_class="icon-swap",
                label="SWAP",
                value=f"{swap_used_gb:.2f} / {swap_total_gb:.2f} GB",
                offset=self._offset(swap_pct),
            ),
            Metric(
                icon_class="icon-disk",
                label="DISK",
                value=f"{disk_used_gb:.2f} / {disk_total_gb:.2f} GB",
                offset=self._offset(disk_pct),
            ),
            Metric(
                icon_class="icon-load",
                label="LOAD",
                value=f"{load_pct:.1f}% / 100%",
                offset=self._offset(load_pct),
            ),
        ]

    async def get_cpu_name(self) -> str:
        """获取完整的 CPU 型号名称，展示层负责截断。"""
        system = platform.system()
        if system == "Linux":
            cpu_name = self._get_cpu_name_linux()
        elif system == "Windows":
            cpu_name = await self._get_cpu_name_windows()
        elif system == "Darwin":
            cpu_name = await self._get_cpu_name_macos()
        else:
            cpu_name = self._get_cpu_name_generic()
        return cpu_name

    def _get_cpu_name_linux(self) -> str:
        """在Linux上获取CPU名称"""
        try:
            # 尝试从/proc/cpuinfo读取
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
                    # ARM处理器可能用不同的字段
                    if line.startswith("Hardware"):
                        return line.split(":", 1)[1].strip()
        except Exception as e:
            logger.debug(f"Failed to get CPU name on Linux: {e}")
        return self._get_cpu_name_generic()

    async def _get_cpu_name_windows(self) -> str:
        """在Windows上获取CPU名称"""
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "wmic",
                "cpu",
                "get",
                "Name",
                "/value",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)

            if proc.returncode != 0:
                return self._get_cpu_name_generic()

            for line in stdout.decode("utf-8", errors="ignore").splitlines():
                if line.startswith("Name="):
                    cpu_name = line.split("=", 1)[1].strip()
                    if cpu_name:
                        return cpu_name
                    break

        except asyncio.TimeoutError:
            logger.debug("Timeout getting CPU name on Windows")
            if proc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Failed to get CPU name on Windows: {e}")

        return self._get_cpu_name_generic()

    async def _get_cpu_name_macos(self) -> str:
        """在 macOS 上获取准确芯片名称和核心/线程数量。"""
        chip_name = await self._get_macos_chip_name()
        if not chip_name:
            chip_name = await self._get_macos_sysctl_text("machdep.cpu.brand_string")

        if not chip_name:
            return self._get_cpu_name_generic()

        return chip_name

    async def _get_macos_chip_name(self) -> str:
        """从 system_profiler 读取 Apple Silicon 的 Chip 字段。"""
        try:
            stdout = await self._run_command_stdout(
                "system_profiler",
                "SPHardwareDataType",
            )
        except Exception as e:
            logger.debug(f"Failed to get macOS chip name from system_profiler: {e}")
            return ""

        for line in stdout.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() in {"Chip", "Processor Name"}:
                name = value.strip()
                if name:
                    return name
        return ""

    async def _get_macos_sysctl_text(self, key: str) -> str:
        """读取 macOS sysctl 单个键，部分沙盒环境可能不允许访问。"""
        try:
            return (await self._run_command_stdout("sysctl", "-n", key)).strip()
        except Exception as e:
            logger.debug(f"Failed to get macOS sysctl {key}: {e}")
            return ""

    async def _run_command_stdout(self, *args: str) -> str:
        """运行只读系统信息命令并返回 stdout 文本。"""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            # 系统信息命令只用于增强展示，超时后应让状态卡继续走通用回退链。
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=SYSTEM_INFO_COMMAND_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.debug(
                f"Command {args!r} timed out after "
                f"{SYSTEM_INFO_COMMAND_TIMEOUT_SECONDS:.1f}s "
                "while collecting system info"
            )
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            return ""

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore").strip()
            raise subprocess.CalledProcessError(
                proc.returncode,
                args,
                output=stdout,
                stderr=err,
            )
        return stdout.decode("utf-8", errors="ignore")

    @staticmethod
    def _get_cpu_name_generic() -> str:
        """通用方式获取CPU名称（使用psutil或platform）"""
        # 尝试用psutil
        try:
            freq = psutil.cpu_freq()
            cores = psutil.cpu_count() or 1
            if freq and freq.current:
                ghz = freq.current / 1000.0
                return f"{cores} Core @ {ghz:.2f}GHz"
        except Exception as e:
            logger.debug(f"Failed to get CPU info from psutil: {e}")

        # 回退到platform
        cpu_name = platform.processor()
        if cpu_name:
            return cpu_name

        return "Unknown CPU"

    def get_os_name(self) -> str:
        """获取完整的操作系统名称，展示层负责截断。"""
        os_name = f"{platform.system()} {platform.release()}"
        return os_name

    def get_project_version(self, _event: AstrMessageEvent) -> str:
        """获取AstrBot项目版本"""
        try:
            # 尝试从astrbot获取版本
            from astrbot import __version__ as astr_ver

            if astr_ver:
                return f"AstrBot v{astr_ver}"
        except ImportError:
            pass

        try:
            from astrbot.cli import __version__ as cli_ver

            if cli_ver:
                return f"AstrBot v{cli_ver}"
        except ImportError:
            pass

        try:
            from astrbot.core import __version__ as core_ver

            if core_ver:
                return f"AstrBot v{core_ver}"
        except ImportError:
            pass

        return "AstrBot"

    async def get_plugin_counts(self) -> int:
        """获取插件的数量"""
        getter = getattr(self.context, "get_all_stars", None)
        if not callable(getter):
            return 0
        try:
            stars = getter()
            # 处理异步返回的情况，使用 inspect.isawaitable 进行标准判定
            if inspect.isawaitable(stars):
                stars = await stars
            if not isinstance(stars, list):
                return 0
            return len(stars)
        except Exception as e:
            logger.debug(f"Failed to get plugin counts: {e}")
            return 0

    def get_net_speed_kbs(self) -> tuple[float, float]:
        """获取上传和下载速度 (KB/s)"""
        now = time.monotonic()
        try:
            io = psutil.net_io_counters()
            if self._last_net_sample_ts <= 0:
                self._last_net_sample_ts = now
                self._last_net_bytes_sent = int(io.bytes_sent)
                self._last_net_bytes_recv = int(io.bytes_recv)
                return 0.0, 0.0

            elapsed = max(0.001, now - self._last_net_sample_ts)
            up = max(0, int(io.bytes_sent) - self._last_net_bytes_sent)
            down = max(0, int(io.bytes_recv) - self._last_net_bytes_recv)

            self._last_net_sample_ts = now
            self._last_net_bytes_sent = int(io.bytes_sent)
            self._last_net_bytes_recv = int(io.bytes_recv)

            return up / elapsed / 1024.0, down / elapsed / 1024.0
        except Exception as e:
            logger.debug(f"Failed to get network speed: {e}")
            return 0.0, 0.0

    def get_uptime_text(self) -> str:
        """获取系统运行时间文本"""
        delta = dt.datetime.now() - self._system_start
        total = int(delta.total_seconds())
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        if days > 0:
            return f"{days}天{hours}小时{minutes}分"
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _cpu_display(self, cpu_pct: float) -> str:
        try:
            freq = psutil.cpu_freq()
            physical = psutil.cpu_count(logical=False) or 0
            logical = psutil.cpu_count(logical=True) or 0
            cpu_count = self._format_cpu_count_text(physical, logical)
            mhz = 0.0
            if freq is not None:
                mhz = float(freq.current or freq.max or 0.0)
            ghz = mhz / 1000.0 if mhz > 0 else 0.0
            if ghz > 0:
                return f"{cpu_pct:.1f}% - {ghz:.2f}GHz [{cpu_count}]"
            return f"{cpu_pct:.1f}% [{cpu_count}]"
        except Exception as e:
            logger.debug(f"Failed to get CPU display info: {e}")
            return f"{cpu_pct:.1f}%"

    @staticmethod
    def _format_cpu_count_text(physical: int, logical: int) -> str:
        if physical > 0 and logical > 0 and physical != logical:
            return f"{physical} Cores / {logical} Threads"
        if physical > 0:
            return SystemDataSource._pluralize_cpu_unit(physical, "Core")
        if logical > 0:
            return SystemDataSource._pluralize_cpu_unit(logical, "Thread")
        return "1 Thread"

    @staticmethod
    def _pluralize_cpu_unit(count: int, unit: str) -> str:
        suffix = "" if count == 1 else "s"
        return f"{count} {unit}{suffix}"

    def _cpu_percent(self) -> float:
        try:
            return float(psutil.cpu_percent(interval=None))
        except Exception as e:
            logger.debug(f"Failed to get CPU percent: {e}")
            return 0.0

    def _memory_usage(self) -> tuple[float, float, float]:
        try:
            vm = psutil.virtual_memory()
            used = (vm.total - vm.available) / (1024**3)
            total = vm.total / (1024**3)
            return used, total, float(vm.percent)
        except Exception as e:
            logger.debug(f"Failed to get memory usage: {e}")
            return 0.0, 0.0, 0.0

    def _swap_usage(self) -> tuple[float, float, float]:
        try:
            sm = psutil.swap_memory()
            used = sm.used / (1024**3)
            total = sm.total / (1024**3)
            pct = float(sm.percent if sm.total else 0.0)
            return used, total, pct
        except Exception as e:
            logger.debug(f"Failed to get swap usage: {e}")
            return 0.0, 0.0, 0.0

    def _disk_usage(self) -> tuple[float, float, float]:
        try:
            du = shutil.disk_usage(str(Path.cwd()))
            used = du.used / (1024**3)
            total = du.total / (1024**3)
            pct = (used / total) * 100 if total else 0.0
            return used, total, pct
        except Exception as e:
            logger.debug(f"Failed to get disk usage: {e}")
            return 0.0, 0.0, 0.0

    def _load_percent(self, cpu_pct: float) -> float:
        """计算系统负载百分比，Windows 下回退到 CPU 使用率"""
        try:
            # psutil.getloadavg() 仅在 Unix 系统上可用
            if hasattr(psutil, "getloadavg"):
                la1, _, _ = psutil.getloadavg()
                cpu_count = psutil.cpu_count() or 1
                return min(100.0, max(cpu_pct, (la1 / cpu_count) * 100))
            # Windows 不支持 getloadavg，直接使用 CPU 使用率
            return cpu_pct
        except Exception as e:
            logger.debug(f"Failed to get load percent: {e}")
            return cpu_pct

    def _offset(self, percent: float) -> float:
        p = min(100.0, max(0.0, percent))
        return 339.29 * (1.0 - (p / 100.0))
