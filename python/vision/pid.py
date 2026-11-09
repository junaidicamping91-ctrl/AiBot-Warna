"""PID controller (Chapter 2.4 poster) - versi Python untuk mode simulasi.

Di mode hardware, PID yang benar-benar menggerakkan servo ada di Arduino
(``arduino/aim_bot_warna/aim_bot_warna.ino``). Implementasi ini dipakai saat
``--mock`` supaya HUD tetap menampilkan arah bidikan yang realistis, dan untuk
keperluan unit test / tuning konstanta sebelum dikirim ke board.
"""
from __future__ import annotations

import time


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class PID:
    """PID diskrit dengan anti-windup dan pembatasan output."""

    def __init__(self, kp: float = 0.18, ki: float = 0.005, kd: float = 0.03,
                 output_limit: float = 100.0, integral_limit: float | None = None):
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)
        self.output_limit = abs(float(output_limit))
        self.integral_limit = integral_limit if integral_limit is not None else (
            self.output_limit / self.ki if self.ki > 0 else self.output_limit
        )
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_t = time.perf_counter()

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_t = time.perf_counter()

    def compute(self, setpoint: float, measured: float, dt: float | None = None) -> float:
        """Hitung koreksi. error = setpoint - measured."""
        now = time.perf_counter()
        if dt is None:
            dt = now - self._last_t
        self._last_t = now
        dt = clamp(dt, 1e-4, 1.0)

        error = setpoint - measured
        p = self.kp * error

        self._integral = clamp(self._integral + error * dt, -self.integral_limit, self.integral_limit)
        i = self.ki * self._integral

        d = self.kd * (error - self._prev_error) / dt
        self._prev_error = error

        return clamp(p + i + d, -self.output_limit, self.output_limit)
