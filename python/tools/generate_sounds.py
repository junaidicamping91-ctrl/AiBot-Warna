#!/usr/bin/env python3
"""Buat ulang seluruh aset suara WAV (nada + opsional ucapan TTS).

    python python/tools/generate_sounds.py
    python python/tools/generate_sounds.py --overwrite --speech

`--speech` memakai SAPI Windows untuk merender "Warna terdeteksi, <warna>"
menjadi <key>_ucapan.wav; bila tidak tersedia, ucapan tetap berjalan live
lewat PowerShell/pyttsx3 saat runtime.
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[1]  # berisi audio/, utils/, vision/
for _p in (str(PKG_DIR), str(PKG_DIR.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audio.tone_factory import SAMPLE_RATE, generate_all, list_sounds  # noqa: E402
from utils.paths import ROOT, SOUND_DIR  # noqa: E402
from vision.colors import ColorPalette  # noqa: E402


def render_speech(sound_dir: Path, palette, template: str) -> int:
    if platform.system() != "Windows":
        print("Lewati --speech: SAPI hanya ada di Windows (runtime tetap bisa TTS).")
        return 0
    made = 0
    for spec in palette:
        target = sound_dir / f"{spec.key}_ucapan.wav"
        if target.exists():
            continue
        text = template.format(warna=spec.speech).replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.SetOutputToWaveFile('{str(target).replace(chr(39), chr(39) * 2)}'); "
            f"$s.Speak('{text}'); $s.Dispose()"
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           check=True, capture_output=True, timeout=30)
            if target.exists() and target.stat().st_size > 1000:
                made += 1
                print(f"  + {target.name}")
            else:
                target.unlink(missing_ok=True)
        except Exception as exc:
            target.unlink(missing_ok=True)
            print(f"  ! ucapan {spec.key} gagal: {exc}")
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(SOUND_DIR))
    ap.add_argument("--volume", type=float, default=0.6)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--speech", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    palette = ColorPalette.from_json()
    made = generate_all(out, palette, volume=args.volume, overwrite=args.overwrite)
    print(f"Folder : {out}")
    print(f"Dibuat : {len(made)} file nada (regenerasi diminta: {args.overwrite})")
    print(f"Sample rate: {SAMPLE_RATE} Hz, mono, PCM 16-bit\n")
    print(f"{'WARNA':<10}{'ID':>3}{'NADA':>9}{'BEEP':>6}  FILE")
    for spec in palette:
        print(f"{spec.name:<10}{spec.id:>3}{spec.tone_hz:>7}Hz{spec.beeps:>6}  {spec.key}.wav")
    for path in list_sounds(out):
        print(f"  aset: {path.name} ({path.stat().st_size // 1024} KB)")

    if args.speech:
        print("\nMerender ucapan TTS:")
        n = render_speech(out, palette, "Warna terdeteksi, {warna}")
        print(f"  {n} file ucapan dibuat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
