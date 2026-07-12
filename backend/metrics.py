"""システムメトリクスの収集ロジック。

psutil の累積カウンタ（ネットワーク・ディスクIO）は差分から速度を算出する必要が
あるため、Sampler が一定間隔でサンプリングして最新の速度を保持する。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil


# ラズパイの CPU 温度が読めるパス候補（環境によって異なる）
_THERMAL_PATHS = [
    "/sys/class/thermal/thermal_zone0/temp",
]


def _read_cpu_temp() -> float | None:
    """CPU 温度（摂氏）を返す。取得できなければ None。"""
    # まず psutil の sensors_temperatures を試す
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, NotImplementedError):
        temps = {}
    for entries in temps.values():
        for entry in entries:
            if entry.current:
                return round(float(entry.current), 1)

    # フォールバック: sysfs を直接読む（ラズパイ）
    for path in _THERMAL_PATHS:
        try:
            raw = Path(path).read_text().strip()
            return round(int(raw) / 1000.0, 1)
        except (OSError, ValueError):
            continue
    return None


@dataclass
class Rates:
    """差分から算出した速度（バイト/秒）。"""

    net_sent_bps: float = 0.0
    net_recv_bps: float = 0.0
    disk_read_bps: float = 0.0
    disk_write_bps: float = 0.0


@dataclass
class _Counters:
    net_sent: int = 0
    net_recv: int = 0
    disk_read: int = 0
    disk_write: int = 0
    ts: float = field(default_factory=time.monotonic)


class Sampler:
    """バックグラウンドで累積カウンタをサンプリングし、最新の速度を保持する。"""

    def __init__(self, interval: float = 1.0) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._rates = Rates()
        self._prev = self._snapshot_counters()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def _snapshot_counters() -> _Counters:
        net_sent, net_recv = _net_bytes()
        disk = psutil.disk_io_counters()
        return _Counters(
            net_sent=net_sent,
            net_recv=net_recv,
            disk_read=disk.read_bytes if disk else 0,
            disk_write=disk.write_bytes if disk else 0,
        )

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            current = self._snapshot_counters()
            elapsed = current.ts - self._prev.ts
            if elapsed <= 0:
                continue
            rates = Rates(
                net_sent_bps=max(0.0, (current.net_sent - self._prev.net_sent) / elapsed),
                net_recv_bps=max(0.0, (current.net_recv - self._prev.net_recv) / elapsed),
                disk_read_bps=max(0.0, (current.disk_read - self._prev.disk_read) / elapsed),
                disk_write_bps=max(0.0, (current.disk_write - self._prev.disk_write) / elapsed),
            )
            with self._lock:
                self._rates = rates
            self._prev = current

    def rates(self) -> Rates:
        with self._lock:
            return self._rates


def collect(sampler: Sampler) -> dict:
    """現在のメトリクスをまとめて dict で返す。"""
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    load1, load5, load15 = _loadavg()
    rates = sampler.rates()

    return {
        "timestamp": time.time(),
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "per_cpu": psutil.cpu_percent(interval=None, percpu=True),
            "count": psutil.cpu_count(logical=True),
            "freq_mhz": _cpu_freq(),
            "temp_c": _read_cpu_temp(),
            "load_avg": [load1, load5, load15],
        },
        "memory": {
            "total": vm.total,
            "used": vm.used,
            "available": vm.available,
            "percent": vm.percent,
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_percent": swap.percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
            "read_bps": rates.disk_read_bps,
            "write_bps": rates.disk_write_bps,
        },
        "network": {
            "sent_bps": rates.net_sent_bps,
            "recv_bps": rates.net_recv_bps,
        },
        "uptime_sec": time.time() - psutil.boot_time(),
    }


# 集計対象のネットワークインターフェース（既定は有線 eth0）。
# 環境変数 NET_IFACE で変更可能（例: Wi-Fi なら NET_IFACE=wlan0）。
_NET_IFACE = os.environ.get("NET_IFACE", "eth0")


def _net_bytes() -> tuple[int, int]:
    """対象インターフェース(_NET_IFACE)の (送信バイト, 受信バイト) を返す。

    該当インターフェースが存在しない場合は (0, 0)。
    """
    counters = psutil.net_io_counters(pernic=True).get(_NET_IFACE)
    if counters is None:
        return 0, 0
    return counters.bytes_sent, counters.bytes_recv


def _cpu_freq() -> float | None:
    try:
        freq = psutil.cpu_freq()
        return round(freq.current, 0) if freq else None
    except (AttributeError, NotImplementedError, OSError):
        return None


def _loadavg() -> tuple[float, float, float]:
    try:
        return psutil.getloadavg()
    except (AttributeError, OSError):
        return (0.0, 0.0, 0.0)
