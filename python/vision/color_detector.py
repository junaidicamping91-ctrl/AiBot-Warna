"""Chapter 1.2 - OpenCV Image Processing: deteksi & klasifikasi warna.

Alur: blur -> BGR2HSV -> threshold per warna -> morfologi -> kontur terbesar
-> centroid/bounding box -> voting multi-frame (anti kedip).

Modifikasi dari poster: yang dicari bukan lagi objek hasil YOLO, melainkan
WARNA dominan. Hasilnya dipakai untuk (a) audio, (b) error bidikan ke Arduino.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .colors import ColorPalette, ColorSpec


@dataclass
class Detection:
    """Hasil satu frame."""
    color_id: int = 0
    name: str = "TIDAK ADA"
    confidence: float = 0.0
    centroid: tuple[float, float] | None = None
    bbox: tuple[int, int, int, int] | None = None   # x, y, w, h
    area_ratio: float = 0.0
    frame_size: tuple[int, int] = (0, 0)            # width, height
    mask: Any = field(default=None, repr=False)

    @property
    def found(self) -> bool:
        return self.color_id != 0 and self.centroid is not None

    def error_from_center(self) -> tuple[float, float]:
        """Normalisasi -100..100; (0, 0) berarti sasaran tepat di tengah."""
        if not self.found or not all(self.frame_size):
            return 0.0, 0.0
        w, h = self.frame_size
        cx, cy = self.centroid  # type: ignore[misc]
        ex = max(-100.0, min(100.0, (cx - w / 2) / (w / 2) * 100.0))
        ey = max(-100.0, min(100.0, (cy - h / 2) / (h / 2) * 100.0))
        return ex, ey

    def estimated_distance(self, reference_area: float = 0.12) -> float:
        """Estimasi jarak semu (bukan pengukuran nyata) dari luas blob, untuk HUD."""
        if self.area_ratio <= 0:
            return 0.0
        return round(max(0.2, (reference_area / self.area_ratio) ** 0.5), 2)

    def as_dict(self) -> dict:
        return {
            "color_id": self.color_id,
            "name": self.name,
            "confidence": round(self.confidence, 1),
            "centroid": self.centroid,
            "bbox": self.bbox,
            "area_ratio": round(self.area_ratio, 4),
        }


class ColorVoter:
    """Mayoritas N frame terakhir agar warna tidak berganti-ganti karena noise."""

    def __init__(self, window: int = 7, min_votes: int = 4):
        self.window = max(1, int(window))
        self.min_votes = min(self.window, max(1, int(min_votes)))
        self._history: deque[int] = deque(maxlen=self.window)
        self._stable = 0

    @property
    def stable(self) -> int:
        return self._stable

    def vote(self, color_id: int) -> int:
        self._history.append(int(color_id))
        if len(self._history) < self.min_votes:
            return self._stable
        winner, count = Counter(self._history).most_common(1)[0]
        if count >= self.min_votes:
            self._stable = winner
        # kalau tidak ada mayoritas, pertahankan warna sebelumnya (histeresis)
        return self._stable

    def reset(self) -> None:
        self._history.clear()
        self._stable = 0


class ColorDetector:
    """Deteksi warna dominan pada frame BGR."""

    def __init__(self, palette: ColorPalette, settings: dict | None = None):
        self.palette = palette
        cfg = (settings or {}).get("detection", settings or {})
        self.min_area_ratio = float(cfg.get("min_area_ratio", 0.005))
        self.blur_kernel = int(cfg.get("blur_kernel", 5)) | 1
        self.morph_iterations = int(cfg.get("morph_iterations", 2))
        self.confidence_ref = float(cfg.get("confidence_ref_ratio", 0.15))
        self.confidence_threshold = float(cfg.get("confidence_threshold", 45.0))

    # ------------------------------------------------------------------ internal
    def _build_mask(self, hsv: np.ndarray, spec: ColorSpec) -> np.ndarray:
        import cv2

        combined = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for lo, hi in spec.hsv_ranges:
            lower = np.array(lo, dtype=np.uint8)
            upper = np.array(hi, dtype=np.uint8)
            combined = cv2.bitwise_or(combined, cv2.inRange(hsv, lower, upper))
        if self.morph_iterations > 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel,
                                        iterations=self.morph_iterations)
            combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel,
                                        iterations=self.morph_iterations)
        return combined

    # ------------------------------------------------------------------ public
    def detect(self, frame: np.ndarray) -> Detection:
        import cv2

        if frame is None or frame.size == 0:
            return Detection()
        h, w = frame.shape[:2]
        frame_area = float(w * h)

        blurred = cv2.GaussianBlur(frame, (self.blur_kernel, self.blur_kernel), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

        best: tuple[ColorSpec, float, list, np.ndarray] | None = None
        for spec in self.palette:
            if not spec.hsv_ranges:
                continue
            raw_mask = self._build_mask(hsv, spec)
            contours, _ = cv2.findContours(raw_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            min_blob = max(40.0, frame_area * self.min_area_ratio * 0.25)
            kept = [c for c in contours if cv2.contourArea(c) >= min_blob]
            if not kept:
                continue
            total = float(sum(cv2.contourArea(c) for c in kept))
            if best is None or total > best[1]:
                best = (spec, total, kept, raw_mask)

        if best is None:
            return Detection(frame_size=(w, h))

        spec, total, kept, raw_mask = best
        area_ratio = total / frame_area
        if area_ratio < self.min_area_ratio:
            return Detection(frame_size=(w, h), area_ratio=area_ratio)

        clean = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(clean, kept, -1, 255, thickness=cv2.FILLED)

        moments = cv2.moments(clean)
        if moments["m00"] <= 0:
            return Detection(frame_size=(w, h), area_ratio=area_ratio)
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]

        x, y, bw, bh = cv2.boundingRect(np.vstack(kept))
        confidence = min(99.0, 50.0 + 50.0 * min(1.0, area_ratio / self.confidence_ref))

        return Detection(
            color_id=spec.id,
            name=spec.name,
            confidence=round(confidence, 1),
            centroid=(round(float(cx), 1), round(float(cy), 1)),
            bbox=(int(x), int(y), int(bw), int(bh)),
            area_ratio=area_ratio,
            frame_size=(w, h),
            mask=clean,
        )

    def detect_stable(self, frame: np.ndarray, voter: ColorVoter,
                      min_confidence: float | None = None) -> tuple[Detection, int]:
        """Deteksi + voting. Mengembalikan (deteksi mentah, id warna stabil)."""
        gate = self.confidence_threshold if min_confidence is None else min_confidence
        raw = self.detect(frame)
        candidate = raw.color_id if raw.found and raw.confidence >= gate else 0
        stable = voter.vote(candidate)
        return raw, stable
