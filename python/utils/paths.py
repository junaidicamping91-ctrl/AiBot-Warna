"""Lokasi absolut folder proyek, AMAN untuk dua macam layout:

  A. Layout asli : ROOT/python/utils/paths.py + ROOT/config/ + ROOT/assets/
  B. Layout rata : ROOT/utils/paths.py + ROOT/colors.json + ROOT/assets/

Root dicari dari marker file (bukan jumlah parent yang tetap), sehingga
memindah / mengganti nama folder proyek tidak merusak impor. Bisa juga
ditentukan lewat environment variable AIMBOT_ROOT (di-set oleh main.py).
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _find_root() -> Path:
    env = os.environ.get("AIMBOT_ROOT")
    if env:
        candidate = Path(env).resolve()
        if candidate.is_dir():
            return candidate

    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        if ((base / "config" / "colors.json").is_file()
                or (base / "colors.json").is_file()
                or (base / "assets" / "sounds").is_dir()):
            return base
    return here.parents[2] if len(here.parents) > 2 else here.parent


ROOT = _find_root()

# Layout asli memakai config/, layout rata menaruh JSON di root.
CONFIG_DIR = ROOT / "config" if (ROOT / "config" / "colors.json").is_file() else ROOT
SOUND_DIR = ROOT / "assets" / "sounds"

SETTINGS_FILE = (CONFIG_DIR / "settings.json" if (CONFIG_DIR / "settings.json").is_file()
                 else ROOT / "settings.json")
COLORS_FILE = (CONFIG_DIR / "colors.json" if (CONFIG_DIR / "colors.json").is_file()
               else ROOT / "colors.json")


def load_json(path: str | Path, default=None):
    """Baca JSON; kembalikan `default` bila file tidak ada."""
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return {} if default is None else default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: str | Path, data) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def ensure_sound_dir() -> Path:
    SOUND_DIR.mkdir(parents=True, exist_ok=True)
    return SOUND_DIR
