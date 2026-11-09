"""Chapter 2.3 - Serial Data Communication (Python <-> Arduino, 115200 8N1).

Mode ``mock`` membuat seluruh proyek bisa dijalankan TANPA Arduino: setiap
perintah tetap dibentuk, dicatat ke log, dan telemetry POS disintesis supaya
pipeline vision -> tracking -> audio bisa diuji di PC biasa.
"""
from __future__ import annotations

import logging
import time

from vision.colors import ColorPalette
from vision.tracker import TargetCommand

log = logging.getLogger("aimbot")


class SerialLink:
    def __init__(self, settings: dict | None = None, palette: ColorPalette | None = None):
        cfg = (settings or {}).get("serial", settings or {})
        self.cfg = dict(cfg)
        self.baud = int(cfg.get("baud", 115200))
        self.timeout = float(cfg.get("timeout", 0.02))
        self.send_interval = float(cfg.get("send_every_ms", 50)) / 1000.0
        self.mock = bool(cfg.get("mock", False)) or not bool(cfg.get("enabled", True))
        self.palette = palette
        self._ser = None
        self._last_send = 0.0
        self._last_mock_log = 0.0
        self._last_telemetry = 0.0
        self._pending: list[str] = []
        self._mock_color = 0
        self._mock_pan = 90.0
        self._mock_tilt = 90.0

    # ------------------------------------------------------------------ setup
    @staticmethod
    def list_ports() -> list[str]:
        try:
            from serial.tools import list_ports  # type: ignore
            return [p.device for p in list_ports.comports()]
        except Exception:
            return []

    @staticmethod
    def _autodetect() -> str | None:
        try:
            from serial.tools import list_ports  # type: ignore
            ports = list(list_ports.comports())
            for p in ports:
                text = f"{p.description} {p.manufacturer or ''} {p.device}".lower()
                if any(k in text for k in ("arduino", "ch340", "usb serial", "acm", "ftdi")):
                    return p.device
            return ports[0].device if len(ports) == 1 else None
        except Exception:
            return None

    def connect(self) -> bool:
        if self.mock:
            log.info("Serial: MODE MOCK (tidak ada Arduino) - pipeline tetap berjalan")
            return True
        try:
            import serial  # type: ignore
        except ImportError:
            log.warning("pyserial belum terpasang -> pindah ke MODE MOCK  (pip install pyserial)")
            self.mock = True
            return True

        port = self.cfg.get("port") or (self._autodetect() if self.cfg.get("auto_detect", True) else None)
        if not port:
            log.warning("Port serial tidak ditemukan -> MODE MOCK. Tersedia: %s",
                        self.list_ports() or "tidak ada")
            self.mock = True
            return True
        try:
            self._ser = serial.Serial(port, self.baud, timeout=self.timeout)
            time.sleep(1.8)  # tunggu reset bootloader Arduino
            log.info("Serial terhubung: %s @ %d baud", port, self.baud)
            self.send("PING\n", force=True)
            return True
        except Exception as exc:
            log.warning("Gagal buka %s (%s) -> MODE MOCK", port, exc)
            self.mock = True
            return True

    # ------------------------------------------------------------------ kirim
    def send(self, line: str, force: bool = False) -> None:
        if not line.endswith("\n"):
            line += "\n"
        if self.mock:
            now = time.monotonic()
            if force or now - self._last_mock_log > 1.0:
                log.debug("TX(mock) %s", line.strip())
                self._last_mock_log = now
            return
        if self._ser is None or not self._ser.is_open:
            return
        try:
            self._ser.write(line.encode("ascii", errors="ignore"))
        except Exception as exc:
            log.warning("Gagal kirim serial: %s -> MODE MOCK", exc)
            self.mock = True

    def send_target(self, cmd: TargetCommand, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now - self._last_send < self.send_interval:
            return False
        self._last_send = now
        self.send(cmd.to_serial(), force=force)
        self._mock_pan, self._mock_tilt = cmd.pan, cmd.tilt
        if self.mock and cmd.color_id != self._mock_color:
            name = self.palette.get(cmd.color_id).name if self.palette else str(cmd.color_id)
            self._pending.append(f"EVT,COLOR,{cmd.color_id},{name}")
            self._mock_color = cmd.color_id
        return True

    # ------------------------------------------------------------------ terima
    def read_lines(self) -> list[str]:
        lines: list[str] = []
        if self.mock:
            now = time.monotonic()
            if now - self._last_telemetry > 0.2:
                self._last_telemetry = now
                self._pending.append(
                    f"POS,{self._mock_pan:.0f},{self._mock_tilt:.0f},{self._mock_color}"
                )
        elif self._ser is not None and self._ser.is_open:
            try:
                while self._ser.in_waiting:
                    raw = self._ser.readline()
                    if not raw:
                        break
                    lines.append(raw.decode("utf-8", errors="ignore").strip())
            except Exception:
                return []
        lines.extend(self._pending)
        self._pending.clear()
        for line in lines:
            if line:
                log.debug("RX %s", line)
        return [l for l in lines if l]

    # ------------------------------------------------------------------ util
    @property
    def status(self) -> str:
        if self.mock:
            return "MOCK"
        return "SERIAL" if self._ser is not None and self._ser.is_open else "OFFLINE"

    def buzz(self, color_id: int) -> None:
        self.send(f"BUZZ,{color_id}\n", force=True)

    def center(self) -> None:
        self.send("CENTER\n", force=True)

    def close(self) -> None:
        try:
            if not self.mock and self._ser is not None and self._ser.is_open:
                self.send("CENTER\n", force=True)
                time.sleep(0.05)
                self._ser.close()
                log.info("Serial ditutup, servo kembali ke tengah")
        except Exception:
            pass
