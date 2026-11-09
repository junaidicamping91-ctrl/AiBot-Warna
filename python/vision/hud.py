"""HUD ala monitor di poster: bounding box, label warna, crosshair, FPS, PID."""
from __future__ import annotations

import cv2
import numpy as np

from .colors import ColorPalette


def _bgr(spec) -> tuple[int, int, int]:
    return (int(spec.bgr[0]), int(spec.bgr[1]), int(spec.bgr[2]))


def draw_hud(frame: np.ndarray, detection, fps: float, cmd,
             palette: ColorPalette, status: str = "MOCK",
             last_audio: str = "-") -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    spec = palette.get(detection.color_id)

    # Panel atas (dibuat semi transparan)
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (w, 62), (24, 32, 48), -1)
    cv2.addWeighted(overlay, 0.72, out, 0.28, 0, out)

    cv2.putText(out, "AIMBOT WARNA  |  COLOR TRACKING", (14, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 242, 255), 1, cv2.LINE_AA)
    cv2.putText(out, f"STATUS: {status}", (14, 47),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 210, 255), 1, cv2.LINE_AA)
    cv2.putText(out, f"FPS {fps:5.1f}", (w - 130, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 255, 180), 1, cv2.LINE_AA)
    cv2.putText(out, f"TRACKING" if detection.found else "SEARCHING", (w - 130, 47),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (120, 255, 150) if detection.found else (140, 180, 255), 1, cv2.LINE_AA)

    # Crosshair di tengah frame
    cx, cy = w // 2, h // 2
    cv2.drawMarker(out, (cx, cy), (200, 220, 255), cv2.MARKER_CROSS, 26, 1, cv2.LINE_AA)
    cv2.circle(out, (cx, cy), 60, (110, 140, 180), 1, cv2.LINE_AA)

    if detection.found and detection.bbox is not None:
        color = _bgr(spec)
        x, y, bw, bh = detection.bbox
        cv2.rectangle(out, (x, y), (x + bw, y + bh), color, 2)
        # sudut kotak (corner brackets)
        k = 16
        for px, py, sx, sy in [(x, y, 1, 1), (x + bw, y, -1, 1),
                               (x, y + bh, 1, -1), (x + bw, y + bh, -1, -1)]:
            cv2.line(out, (px, py), (px + k * sx, py), color, 3)
            cv2.line(out, (px, py), (px, py + k * sy), color, 3)

        label = f"{spec.name} {detection.confidence:.0f}%"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        ly = max(70, y - 10)
        cv2.rectangle(out, (x, ly - th - 8), (x + tw + 14, ly + 6), color, -1)
        cv2.putText(out, label, (x + 7, ly - 2), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2, cv2.LINE_AA)

        # garis bidikan dari tengah ke centroid
        tx, ty = int(detection.centroid[0]), int(detection.centroid[1])
        cv2.line(out, (cx, cy), (tx, ty), color, 1, cv2.LINE_AA)
        cv2.drawMarker(out, (tx, ty), color, cv2.MARKER_CROSS, 18, 2, cv2.LINE_AA)
    else:
        cv2.putText(out, "MENCARI WARNA...", (w // 2 - 120, h // 2 + 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 180, 220), 1, cv2.LINE_AA)

    # Panel bawah: telemetry
    overlay = out.copy()
    cv2.rectangle(overlay, (0, h - 78), (w, h), (24, 32, 48), -1)
    cv2.addWeighted(overlay, 0.72, out, 0.28, 0, out)
    cv2.putText(out, f"WARNA : {spec.name}", (14, h - 54),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, _bgr(spec), 1, cv2.LINE_AA)
    cv2.putText(out, f"PAN {cmd.pan:5.1f}   TILT {cmd.tilt:5.1f}   ERR {cmd.err_x:+.0f},{cmd.err_y:+.0f}",
                (14, h - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (220, 232, 250), 1, cv2.LINE_AA)
    cv2.putText(out, f"AUDIO : {last_audio}", (14, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.44, (170, 210, 255), 1, cv2.LINE_AA)
    cv2.putText(out, f"JARAK~ {detection.estimated_distance():.2f} m (est.)",
                (w - 230, h - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                (200, 220, 245), 1, cv2.LINE_AA)
    cv2.putText(out, "Q = keluar", (w - 110, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 165, 190), 1, cv2.LINE_AA)
    return out


def draw_hud_multi(frame, detections, fps: float, cmd, palette: ColorPalette,
                   status: str = "MOCK", last_audio: str = "-") -> np.ndarray:
    """HUD mode FULL WARNA: SATU kotak + label untuk TIAP warna yang hadir.

    Berbeda dari ``draw_hud`` (satu target untuk PID), versi ini menggambar
    semua deteksi hasil ``ColorDetector.detect_all()``. Warna dominan tetap
    dipakai sebagai sasaran bidikan / garis vektor.
    """
    out = frame.copy()
    h, w = out.shape[:2]
    found = [d for d in (detections or []) if d.found and d.bbox is not None]

    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (w, 66), (24, 32, 48), -1)
    cv2.addWeighted(overlay, 0.74, out, 0.26, 0, out)
    cv2.putText(out, "AIMBOT WARNA  |  FULL COLOR / MULTI-DETECTION", (14, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (235, 242, 255), 1, cv2.LINE_AA)
    cv2.putText(out, f"STATUS: {status}", (14, 46),
                cv2.FONT_HERSHEY_SIMPLEX, 0.44, (150, 210, 255), 1, cv2.LINE_AA)
    cv2.putText(out, f"FPS {fps:5.1f}", (w - 130, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 255, 180), 1, cv2.LINE_AA)
    cv2.putText(out, f"{len(found)} WARNA", (w - 130, 46),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 214, 120), 1, cv2.LINE_AA)

    cx, cy = w // 2, h // 2
    cv2.drawMarker(out, (cx, cy), (200, 220, 255), cv2.MARKER_CROSS, 26, 1, cv2.LINE_AA)
    cv2.circle(out, (cx, cy), 60, (110, 140, 180), 1, cv2.LINE_AA)

    used_labels: list[tuple[int, int]] = []
    for det in found:
        spec = palette.get(det.color_id)
        color = _bgr(spec)
        x, y, bw, bh = det.bbox  # type: ignore[misc]
        cv2.rectangle(out, (x, y), (x + bw, y + bh), color, 2)

        label = f"{spec.name} {det.confidence:.0f}%"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ly = max(76, y - 8)
        # Geser label ke bawah bila bertabrakan dengan label warna lain.
        while any(abs(ly - oy) < th + 10 and abs(x - ox) < tw + 14
                  for ox, oy in used_labels):
            ly += th + 12
        used_labels.append((x, ly))
        cv2.rectangle(out, (x, ly - th - 6), (x + tw + 12, ly + 5), color, -1)
        cv2.putText(out, label, (x + 6, ly - 2), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)

        tx, ty = int(det.centroid[0]), int(det.centroid[1])  # type: ignore[index]
        cv2.drawMarker(out, (tx, ty), color, cv2.MARKER_CROSS, 14, 1, cv2.LINE_AA)

    if found:
        dominant = found[0]
        cv2.line(out, (cx, cy),
                 (int(dominant.centroid[0]), int(dominant.centroid[1])),  # type: ignore[index]
                 _bgr(palette.get(dominant.color_id)), 1, cv2.LINE_AA)
    else:
        cv2.putText(out, "MENCARI WARNA...", (w // 2 - 120, h // 2 + 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 180, 220), 1, cv2.LINE_AA)

    overlay = out.copy()
    cv2.rectangle(overlay, (0, h - 84), (w, h), (24, 32, 48), -1)
    cv2.addWeighted(overlay, 0.74, out, 0.26, 0, out)
    names = ", ".join(d.name for d in found[:6]) or "-"
    if len(found) > 6:
        names += f" +{len(found) - 6}"
    cv2.putText(out, f"TERDETEKSI ({len(found)}): {names}"[:64], (14, h - 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 220, 140), 1, cv2.LINE_AA)
    cv2.putText(out, f"PAN {cmd.pan:5.1f}   TILT {cmd.tilt:5.1f}   ERR {cmd.err_x:+.0f},{cmd.err_y:+.0f}",
                (14, h - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 232, 250), 1, cv2.LINE_AA)
    cv2.putText(out, f"AUDIO : {last_audio}"[:70], (14, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (170, 210, 255), 1, cv2.LINE_AA)
    return out
