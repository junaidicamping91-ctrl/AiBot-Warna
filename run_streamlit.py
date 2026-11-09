#!/usr/bin/env python3
"""Launcher Streamlit AimBot Warna - tidak bergantung pada perintah `streamlit`.

Di Windows, `streamlit.exe` sering terpasang di folder Scripts yang tidak ada di
PATH, sehingga `streamlit run ...` gagal. Script ini memanggil CLI Streamlit
langsung lewat Python, dan otomatis bind ke 0.0.0.0 supaya bisa dibuka dari HP
yang tersambung ke WiFi yang sama.

    python run_streamlit.py
    python run_streamlit.py --server.port 8600
    python run_streamlit.py --server.address 127.0.0.1   # lokal saja
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "streamlit_app.py"


def _has(flag: str, argv: list[str]) -> bool:
    return any(a == flag or a.startswith(flag + "=") for a in argv)


def main() -> int:
    if not APP.is_file():
        print(f"streamlit_app.py tidak ditemukan di {ROOT}")
        return 2
    try:
        from streamlit.web.cli import main as streamlit_main
    except ImportError:
        print("Streamlit belum terpasang. Jalankan: pip install -r requirements.txt")
        return 2

    extra = list(sys.argv[1:])
    if not _has("--server.address", extra):
        extra += ["--server.address", "0.0.0.0"]
    if not _has("--server.port", extra):
        extra += ["--server.port", "8501"]

    port = "8501"
    for i, arg in enumerate(extra):
        if arg == "--server.port" and i + 1 < len(extra):
            port = extra[i + 1]
        elif arg.startswith("--server.port="):
            port = arg.split("=", 1)[1]

    sys.argv = ["streamlit", "run", str(APP), *extra]
    print(f"AimBot Warna -> http://localhost:{port}  (dari HP: http://<IP-WiFi>:{port})")
    return int(streamlit_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
