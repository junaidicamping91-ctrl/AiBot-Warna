"""Tabel warna tunggal (single source of truth) untuk Python, Arduino, dan web.

Data diambil dari ``config/colors.json``. Semua modul lain wajib memakai kelas ini
supaya id warna, nama, frekuensi nada, dan warna HUD tidak pernah beda sendiri.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from utils.paths import COLORS_FILE, load_json


@dataclass(frozen=True)
class ColorSpec:
    id: int
    key: str
    name: str
    speech: str
    hex: str
    bgr: tuple[int, int, int]
    rgb: tuple[int, int, int]
    tone_hz: int
    beeps: int
    group: str = "kromatik"                                        # kromatik | netral
    hsv_ranges: tuple[tuple[list[int], list[int]], ...] = field(default_factory=tuple)

    @property
    def found(self) -> bool:
        return self.id != 0


UNKNOWN = ColorSpec(
    id=0,
    key="none",
    name="TIDAK ADA",
    speech="tidak ada warna",
    hex="#94A3B8",
    bgr=(148, 163, 184),
    rgb=(148, 163, 184),
    tone_hz=0,
    beeps=0,
    group="none",
)


class ColorPalette:
    """Kumpulan ColorSpec yang bisa dicari berdasarkan id atau key."""

    def __init__(self, specs: list[ColorSpec]):
        self._specs = list(specs)
        self._by_id = {s.id: s for s in self._specs}
        self._by_key = {s.key: s for s in self._specs}

    @classmethod
    def from_json(cls, path: str | Path | None = None) -> "ColorPalette":
        data = load_json(path or COLORS_FILE, default={})
        specs: list[ColorSpec] = []
        for item in data.get("colors", []):
            ranges = []
            if item.get("hsv"):
                ranges.append((item["hsv"][0], item["hsv"][1]))
            if item.get("hsv2"):
                ranges.append((item["hsv2"][0], item["hsv2"][1]))
            specs.append(
                ColorSpec(
                    id=int(item["id"]),
                    key=item["key"],
                    name=item["name"],
                    speech=item.get("speech", item["name"].lower()),
                    hex=item.get("hex", "#000000"),
                    bgr=tuple(item.get("bgr", [0, 0, 0])),
                    rgb=tuple(item.get("rgb", [0, 0, 0])),
                    tone_hz=int(item.get("tone_hz", 440)),
                    beeps=int(item.get("beeps", 1)),
                    group=item.get("group", "kromatik"),
                    hsv_ranges=tuple(ranges),
                )
            )
        return cls(specs)

    def get(self, color_id: int) -> ColorSpec:
        return self._by_id.get(int(color_id), UNKNOWN)

    def by_key(self, key: str) -> ColorSpec:
        return self._by_key.get(key, UNKNOWN)

    @property
    def specs(self) -> list[ColorSpec]:
        return list(self._specs)

    @property
    def chromatic(self) -> list[ColorSpec]:
        """Warna berwarna saja (ID 1-9) — default untuk bidikan Arduino."""
        return [s for s in self._specs if s.group != "netral"]

    @property
    def neutral(self) -> list[ColorSpec]:
        """Putih / hitam / abu — hanya dipakai saat mode FULL WARNA aktif."""
        return [s for s in self._specs if s.group == "netral"]

    def for_detection(self, include_neutral: bool = False) -> list[ColorSpec]:
        return self.specs if include_neutral else self.chromatic

    def as_web_config(self) -> list[dict]:
        """Tabel warna untuk komponen realtime berbasis JavaScript.

        Modul web tidak bisa mengimpor Python, jadi tabel yang SAMA dikirim
        sebagai JSON. `hsv_ranges` tetap memakai skala OpenCV (H 0-179).
        """
        return [
            {
                "id": s.id,
                "key": s.key,
                "name": s.name,
                "speech": s.speech,
                "group": s.group,
                "hex": s.hex,
                "rgb": list(s.rgb),
                "tone_hz": s.tone_hz,
                "beeps": s.beeps,
                "hsv": [list(r) for r in s.hsv_ranges],
            }
            for s in self._specs
        ]

    def __iter__(self):
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def summary(self) -> str:
        return ", ".join(f"{s.id}={s.name}({s.tone_hz}Hz)" for s in self._specs)
