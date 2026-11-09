"""Pembuat file WAV per warna - murni Python standard library.

Tidak butuh internet, tidak butuh TTS, tidak butuh library audio: nada dibentuk
dari gelombang sinus + envelope ADSR sederhana dan ditulis sebagai PCM 16-bit.
Tiap warna punya frekuensi DAN jumlah beep berbeda supaya mudah dibedakan
meski tanpa layar (berguna untuk robot / tunanetra).
"""
from __future__ import annotations

import io
import math
import wave
from array import array
from pathlib import Path

SAMPLE_RATE = 22050


def _envelope(i: int, total: int) -> float:
    """Attack 8 ms, decay linear, release 25 ms - menghilangkan 'klik'."""
    attack = int(SAMPLE_RATE * 0.008)
    release = int(SAMPLE_RATE * 0.025)
    if i < attack:
        return i / max(1, attack)
    if i > total - release:
        return max(0.0, (total - i) / max(1, release))
    return 0.85 + 0.15 * math.exp(-3.0 * i / max(1, total))


def _write_wav(path: Path, samples: array) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())
    return path


def make_beeps(path: Path, hz: float, beeps: int, volume: float = 0.6,
               beep_s: float = 0.11, gap_s: float = 0.075) -> Path:
    total_per_beep = int(SAMPLE_RATE * beep_s)
    gap = array("h", [0] * int(SAMPLE_RATE * gap_s))
    out = array("h")
    for _ in range(max(1, beeps)):
        tone = array("h")
        for i in range(total_per_beep):
            t = i / SAMPLE_RATE
            # fundamental + harmonik ringan supaya terdengar seperti "bel"
            value = math.sin(2 * math.pi * hz * t) + 0.22 * math.sin(4 * math.pi * hz * t)
            amp = volume * _envelope(i, total_per_beep)
            tone.append(int(max(-1.0, min(1.0, value * amp)) * 26000))
        out.extend(tone)
        out.extend(gap)
    return _write_wav(path, out)


def make_sweep(path: Path, f0: float, f1: float, duration: float = 0.35,
               volume: float = 0.5) -> Path:
    total = int(SAMPLE_RATE * duration)
    out = array("h")
    phase = 0.0
    for i in range(total):
        t = i / SAMPLE_RATE
        frac = i / max(1, total)
        freq = f0 + (f1 - f0) * frac
        phase += 2 * math.pi * freq / SAMPLE_RATE
        amp = volume * _envelope(i, total)
        out.append(int(math.sin(phase) * amp * 26000))
    return _write_wav(path, out)


def make_dual(path: Path, hz_a: float, hz_b: float, volume: float = 0.5) -> Path:
    """Dua nada pendek berurutan (dipakai untuk 'lock')."""
    a = make_beeps(path.with_suffix(".tmp.wav"), hz_a, 1, volume, 0.07, 0.03)
    tmp = array("h")
    with wave.open(str(a), "rb") as wav:
        tmp.frombytes(wav.readframes(wav.getnframes()))
    b = make_beeps(path.with_suffix(".tmp2.wav"), hz_b, 1, volume, 0.10, 0.01)
    with wave.open(str(b), "rb") as wav:
        tmp.frombytes(wav.readframes(wav.getnframes()))
    a.unlink(missing_ok=True)
    b.unlink(missing_ok=True)
    return _write_wav(path, tmp)


def generate_all(sound_dir: Path, palette, volume: float = 0.6,
                 overwrite: bool = False) -> list[Path]:
    sound_dir = Path(sound_dir)
    made: list[Path] = []

    for spec in palette:
        target = sound_dir / f"{spec.key}.wav"
        if overwrite or not target.exists():
            made.append(make_beeps(target, spec.tone_hz, spec.beeps, volume))

    extras = [
        (sound_dir / "startup.wav", lambda p: make_sweep(p, 330, 880, 0.35, volume)),
        (sound_dir / "lost.wav", lambda p: make_sweep(p, 660, 220, 0.28, volume * 0.7)),
        (sound_dir / "lock.wav", lambda p: make_dual(p, 880, 1175, volume * 0.7)),
    ]
    for path, factory in extras:
        if overwrite or not path.exists():
            made.append(factory(path))
    return made


def concat_wav_bytes(paths, gap_s: float = 0.06) -> bytes:
    """Gabungkan beberapa WAV nada menjadi SATU audio untuk multi-warna.

    Dipakai mode FULL WARNA: bila 4 warna terdeteksi bersamaan, keempat nada
    diputar berurutan dalam satu ``st.audio`` (browser biasanya hanya
    mengizinkan satu elemen audio autoplay per interaksi).

    Semua WAV hasil ``make_beeps`` bermono/16-bit/22050 Hz, jadi frame PCM-nya
    bisa langsung disambung tanpa resample.
    """
    frames = bytearray()
    gap = array("h", [0] * int(SAMPLE_RATE * gap_s)).tobytes()
    for path in paths:
        if not Path(path).is_file():
            continue
        with wave.open(str(path), "rb") as wav:
            frames += wav.readframes(wav.getnframes())
            frames += gap
    if not frames:
        return b""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(bytes(frames))
    return buf.getvalue()


def list_sounds(sound_dir: Path) -> list[Path]:
    return sorted(Path(sound_dir).glob("*.wav"))
