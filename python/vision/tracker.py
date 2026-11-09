"""Chapter 1.4 - Object Tracking: ubah centroid jadi error bidikan & perintah serial."""
from __future__ import annotations

from dataclasses import dataclass

from .pid import PID, clamp


@dataclass
class TargetCommand:
    err_x: float = 0.0
    err_y: float = 0.0
    pan: float = 90.0
    tilt: float = 90.0
    color_id: int = 0
    confidence: float = 0.0

    def to_serial(self) -> str:
        """Protokol: T,<err_x>,<err_y>,<color_id>,<conf>\\n"""
        return "T,{:.1f},{:.1f},{:d},{:.0f}\n".format(
            self.err_x, self.err_y, self.color_id, self.confidence
        )


class Tracker:
    """Hitung error ternormalisasi (-100..100) dan sudut servo simulasi.

    Di mode hardware Arduino menjalankan PID sendiri; `pan`/`tilt` di sini hanya
    untuk tampilan HUD. Di mode `--mock` nilai ini benar-benar dipakai sebagai
    posisi bidikan virtual.
    """

    def __init__(self, frame_size: tuple[int, int], settings: dict | None = None):
        cfg = (settings or {}).get("tracking", settings or {})
        pid_cfg = cfg.get("pid", {})
        self.deadzone = float(cfg.get("deadzone", 6.0))
        self.center = float(cfg.get("servo_center", 90))
        self.pan_limits = tuple(cfg.get("pan_limits", [20, 160]))
        self.tilt_limits = tuple(cfg.get("tilt_limits", [30, 150]))
        self.pid_x = PID(**pid_cfg) if pid_cfg else PID()
        self.pid_y = PID(**pid_cfg) if pid_cfg else PID()
        self.frame_size = frame_size
        self.pan = self.center
        self.tilt = self.center
        self.locked = False

    def reset(self) -> None:
        self.pid_x.reset()
        self.pid_y.reset()
        self.pan = self.center
        self.tilt = self.center
        self.locked = False

    def _deadzone(self, value: float) -> float:
        return 0.0 if abs(value) < self.deadzone else value

    def update(self, detection, color_id: int | None = None,
               dt: float | None = None) -> TargetCommand:
        cid = detection.color_id if color_id is None else int(color_id)
        if not detection.found or cid == 0:
            self.locked = False
            # Perlahan kembali ke tengah saat kehilangan sasaran
            self.pan += (self.center - self.pan) * 0.08
            self.tilt += (self.center - self.tilt) * 0.08
            return TargetCommand(pan=round(self.pan, 1), tilt=round(self.tilt, 1),
                                 color_id=0, confidence=0.0)

        ex, ey = detection.error_from_center()
        ex, ey = self._deadzone(ex), self._deadzone(ey)
        self.locked = abs(ex) < 10 and abs(ey) < 10

        # error = setpoint(0) - measured(-ex) = ex  -> koreksi searah target
        out_x = self.pid_x.compute(0.0, -ex, dt=dt)
        out_y = self.pid_y.compute(0.0, -ey, dt=dt)
        self.pan = clamp(self.center + out_x, *self.pan_limits)
        self.tilt = clamp(self.center + out_y, *self.tilt_limits)

        return TargetCommand(
            err_x=round(ex, 1),
            err_y=round(ey, 1),
            pan=round(self.pan, 1),
            tilt=round(self.tilt, 1),
            color_id=cid,
            confidence=round(float(detection.confidence), 1),
        )
