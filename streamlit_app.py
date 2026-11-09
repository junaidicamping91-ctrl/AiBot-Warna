#!/usr/bin/env python3
"""AimBot Warna - versi Streamlit (bisa dibuka di HP & online lewat GitHub).

Pipeline identik dengan main.py (OpenCV HSV -> voting -> tracking -> audio),
tetapi seluruh antarmuka berjalan di browser, sehingga bisa dipakai dari HP.

Jalankan lokal : python run_streamlit.py   (atau: streamlit run streamlit_app.py)
Satu WiFi (HP): python run_streamlit.py --server.address 0.0.0.0
Online gratis  : push repo ke GitHub -> deploy di share.streamlit.io
                 (lihat README.md bagian "Streamlit, HP & online lewat GitHub")

Catatan: di cloud tidak ada Arduino, jadi komunikasi serial berstatus MODE MOCK.
"""
from __future__ import annotations

import json
import math
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "python" if (ROOT / "python" / "vision" / "colors.py").is_file() else ROOT
for _p in (str(PKG), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("AIMBOT_ROOT", str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import streamlit as st  # noqa: E402
from PIL import Image  # noqa: E402

from audio.tone_factory import generate_all  # noqa: E402
from utils.paths import COLORS_FILE, SETTINGS_FILE, SOUND_DIR, load_json  # noqa: E402
from vision.color_detector import ColorDetector, ColorVoter  # noqa: E402
from vision.colors import ColorPalette  # noqa: E402
from vision.hud import draw_hud  # noqa: E402
from vision.tracker import Tracker  # noqa: E402

# --------------------------------------------------------------------- halaman
st.set_page_config(
    page_title="AimBot Warna | Deteksi Warna + Audio",
    layout="centered",
    initial_sidebar_state="collapsed",
    menu_items={"About": "AimBot Warna - Python/OpenCV + Streamlit + Arduino"},
)

st.markdown(
    """
    <style>
      .block-container{padding-top:1.1rem;padding-bottom:2rem;max-width:780px}
      h1{font-size:1.7rem !important;margin-bottom:.2rem}
      .aim-badge{display:inline-block;background:#e6f1fb;color:#185fa5;border:1px solid #cfe0f7;
        border-radius:999px;padding:3px 10px;font-size:12px;font-weight:600;margin-bottom:.6rem}
      .aim-swatch{height:16px;border-radius:5px;border:1px solid rgba(0,0,0,.08);margin-bottom:6px}
      .aim-note{font-size:13px;color:#475569;line-height:1.6}
      .stButton>button{border-radius:10px;min-height:42px}
      div[data-testid="metric-container"]{background:#fff;border:1px solid #e3e9f2;
        border-radius:12px;padding:8px 10px}
    </style>
    """,
    unsafe_allow_html=True,
)

# Kompatibilitas Streamlit lama (>=1.33) vs baru (>=1.45): `use_container_width`
# dan `components.html` sudah deprecated, tapi `width=` / `st.iframe` belum ada
# di rilis lama. Proxy: versi yang punya st.iframe juga punya argumen width.
_MODERN_ST = hasattr(st, "iframe")


def stretch() -> dict:
    """Argumen 'lebar penuh' yang aman untuk dua generasi API Streamlit."""
    return {"width": "stretch"} if _MODERN_ST else {"use_container_width": True}


def embed_html(html: str, height: int = 56) -> None:
    """Embed HTML ber-JS (Web Speech) lewat st.iframe, fallback components.html."""
    if _MODERN_ST:
        st.iframe(html, height=height)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=height)


# --------------------------------------------------------------------- data & state
@st.cache_resource(show_spinner=False)
def get_palette() -> ColorPalette:
    return ColorPalette.from_json(COLORS_FILE)


@st.cache_data(show_spinner=False)
def get_settings() -> dict:
    return load_json(SETTINGS_FILE, default={})


@st.cache_data(show_spinner=False)
def wav_bytes(color_id: int) -> bytes:
    """Ambil WAV nada untuk warna; generate bila belum ada (mis. di cloud)."""
    palette = get_palette()
    path = SOUND_DIR / f"{palette.get(color_id).key}.wav"
    if not path.exists():
        generate_all(SOUND_DIR, palette)
    return path.read_bytes() if path.exists() else b""


def lan_ip() -> str:
    """IP LAN komputer, untuk ditunjukkan sebagai alamat yang dibuka di HP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


palette = get_palette()
ss = st.session_state
ss.setdefault("voter", None)
ss.setdefault("tracker", None)
ss.setdefault("last_color", 0)
ss.setdefault("sim_key", "merah")
ss.setdefault("last_audio", "-")
ss.setdefault("log", ["LOG,AimBot Warna Streamlit siap",
                      "LOG,MODE,MOCK (Arduino tidak tersambung di browser)"])
ss.setdefault("seq", 0)
ss.setdefault("frames", 0)
ss.setdefault("auto_cycle", False)


def push_log(*lines: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    for line in lines:
        ss.log.append(f"[{stamp}] {line}")
    ss.log = ss.log[-40:]


# --------------------------------------------------------------------- helper UI
def tts_html(text: str, auto: bool = True) -> str:
    """Web Speech API id-ID di dalam iframe, dengan tombol untuk unblock HP."""
    payload = json.dumps({"text": text, "auto": bool(auto)}, ensure_ascii=False)
    return """
    <div style="font-family:system-ui,sans-serif;display:flex;align-items:center;gap:10px">
      <button id="say" style="background:#2563eb;color:#fff;border:0;border-radius:9px;
        padding:8px 14px;font-size:13px;cursor:pointer">Ucapkan warna</button>
      <span id="hint" style="font-size:12px;color:#64748b">Web Speech id-ID</span>
    </div>
    <script>
      const cfg = __DATA__;
      function speak(){
        try{
          if(!('speechSynthesis' in window)){document.getElementById('hint').textContent='TTS tidak didukung';return;}
          const u = new SpeechSynthesisUtterance(cfg.text);
          u.lang='id-ID'; u.rate=0.95; u.pitch=1.0;
          window.speechSynthesis.cancel();
          window.speechSynthesis.speak(u);
          document.getElementById('hint').textContent='Berbicara: ' + cfg.text;
        }catch(e){document.getElementById('hint').textContent='TTS diblokir browser';}
      }
      document.getElementById('say').addEventListener('click', speak);
      if(cfg.auto){ setTimeout(speak, 300); }
    </script>
    """.replace("__DATA__", payload)


def make_synthetic_frame(spec, width: int = 640, height: int = 480) -> np.ndarray:
    """Bola warna bergerak untuk mode simulasi (tanpa kamera)."""
    frame = np.full((height, width, 3), (246, 247, 250), dtype=np.uint8)
    for x in range(0, width, 40):
        cv2.line(frame, (x, 0), (x, height), (232, 235, 241), 1)
    for y in range(0, height, 40):
        cv2.line(frame, (0, y), (width, y), (232, 235, 241), 1)
    t = time.monotonic()
    cx = int(width / 2 + math.sin(t * 0.8) * width * 0.26)
    cy = int(height / 2 + math.cos(t * 0.6) * height * 0.22)
    cv2.circle(frame, (cx, cy), 62, tuple(int(v) for v in spec.bgr), -1)
    cv2.circle(frame, (cx, cy), 62, (70, 70, 70), 2)
    cv2.putText(frame, "MODE SIMULASI", (16, height - 92),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (110, 120, 140), 1, cv2.LINE_AA)
    return frame


def file_to_bgr(uploaded) -> np.ndarray | None:
    if uploaded is None:
        return None
    try:
        img = Image.open(uploaded).convert("RGB")
        img.thumbnail((960, 960))
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    except Exception as exc:
        st.warning(f"Gambar tidak bisa dibaca: {exc}")
        return None


# --------------------------------------------------------------------- header
st.title("AimBot Warna")
st.markdown('<span class="aim-badge">STREAMLIT · SIAP HP · ONLINE</span>',
            unsafe_allow_html=True)
st.caption("Robot pembidik yang menebak warna lalu memberi suara audio sesuai warna. "
           "Python/OpenCV + Arduino (MODE MOCK di browser).")

sumber = st.radio(
    "Sumber gambar",
    ["Kamera HP", "Upload gambar", "Simulasi"],
    index=2,
    horizontal=True,
    label_visibility="collapsed",
)

with st.sidebar:
    st.header("Pengaturan")
    mode_suara = st.selectbox("Mode suara", ["keduanya", "nada", "ucapan", "mati"], index=0)
    sensitivitas = st.slider("Ambang luas warna (%)", 0.2, 5.0, 0.5, 0.1,
                             help="Makin kecil = makin sensitif terhadap benda kecil")
    vote_n = st.slider("Voting frame (anti kedip)", 1, 15, 5, 1,
                       help="Di browser satu foto = satu burst frame. Naikkan bila "
                            "ingin vote lebih banyak kalau memakai sumber video.")
    show_hud = st.checkbox("Tampilkan HUD pembidik", value=True)
    st.divider()
    st.markdown('<p class="aim-note">Di cloud tidak ada port serial. '
                'Log <code>T,...</code> tetap dibuat sebagai simulasi Arduino.</p>',
                unsafe_allow_html=True)
    if st.button("Reset sesi", **stretch()):
        for key in ("voter", "tracker", "last_color", "log", "seq", "frames", "last_audio"):
            ss.pop(key, None)
        st.rerun()


# --------------------------------------------------------------------- ambil frame
frame = None
if sumber == "Kamera HP":
    st.caption("Ketuk tombol kamera di bawah untuk mengambil frame. "
               "Ulangi untuk mendeteksi warna berikutnya. "
               "**Kamera butuh HTTPS** — otomatis terpenuhi saat online via Streamlit Cloud.")
    shot = st.camera_input("Ambil foto warna")
    frame = file_to_bgr(shot)
elif sumber == "Upload gambar":
    upl = st.file_uploader("Pilih foto (jpg/png)", type=["jpg", "jpeg", "png", "webp"])
    frame = file_to_bgr(upl)
else:
    st.caption("Tanpa kamera: ketuk kartu warna untuk mengganti target virtual.")
    cols = st.columns(3)
    for i, spec in enumerate(palette):
        with cols[i % 3]:
            st.markdown(
                f'<div class="aim-swatch" style="background:{spec.hex}"></div>',
                unsafe_allow_html=True,
            )
            if st.button(spec.name, key=f"sim_{spec.key}", **stretch()):
                ss.sim_key = spec.key
                ss.auto_cycle = False
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Ganti warna", **stretch()):
            idx = next((i for i, s in enumerate(palette) if s.key == ss.sim_key), 0)
            ss.sim_key = palette[(idx + 1) % len(palette)].key
            ss.auto_cycle = False
    with c2:
        ss.auto_cycle = st.checkbox("Acak tiap refresh", value=bool(ss.auto_cycle))
    if st.button("Frame berikutnya / refresh", **stretch()):
        st.rerun()
    if ss.auto_cycle:
        ss.sim_key = palette[int(time.monotonic() // 2) % len(palette)].key
    frame = make_synthetic_frame(palette.by_key(ss.sim_key))


# --------------------------------------------------------------------- deteksi
settings = dict(get_settings())
det_cfg = dict(settings.get("detection", {}))
det_cfg["min_area_ratio"] = float(sensitivitas) / 100.0
det_cfg["vote_window"] = int(vote_n)
det_cfg["min_votes"] = max(1, int(vote_n) // 2)
settings["detection"] = det_cfg

if frame is None:
    st.info("Belum ada gambar. Ambil foto, upload gambar, atau pakai mode Simulasi.")
    st.stop()

t0 = time.perf_counter()
detector = ColorDetector(palette, settings)
if ss.voter is None or ss.voter.window != int(vote_n):
    ss.voter = ColorVoter(int(vote_n), max(1, int(vote_n) // 2))

raw = detector.detect(frame)
gate = float(det_cfg.get("confidence_threshold", 45.0))
candidate = raw.color_id if raw.found and raw.confidence >= gate else 0

# Di browser tiap interaksi = satu foto, bukan aliran 30 FPS. Kandidat yang sama
# dimasukkan sebagai satu "burst" frame agar ColorVoter langsung memberi keputusan,
# jadi pengguna HP tidak perlu memotret 4-7 kali sebelum warna & audio muncul.
stable = 0
for _ in range(max(1, int(vote_n))):
    stable = ss.voter.vote(candidate)

h, w = frame.shape[:2]
if ss.tracker is None or ss.tracker.frame_size != (w, h):
    ss.tracker = Tracker((w, h), settings)
# dt tetap 20 ms seperti interval PID di firmware Arduino. Tanpa ini, frame
# pertama browser (jarak antar-rerun bisa beberapa detik) membuat spike derivatif.
cmd = ss.tracker.update(raw, stable, dt=0.05)
fps = 1.0 / max(1e-3, time.perf_counter() - t0)
ss.frames += 1

triggered = stable != ss.last_color
if triggered:
    ss.seq += 1
    ss.last_color = stable
    spec_now = palette.get(stable)
    ss.last_audio = (f"{spec_now.name} / {spec_now.tone_hz} Hz / {spec_now.beeps} beep"
                     if stable else "warna hilang")
    if stable:
        push_log(f"EVT,COLOR,{stable},{spec_now.name}",
                 f"T,{cmd.err_x:.1f},{cmd.err_y:.1f},{stable},{raw.confidence:.0f}",
                 f"POS,{cmd.pan:.0f},{cmd.tilt:.0f},{stable}",
                 f"AUDIO,{spec_now.key},{spec_now.tone_hz}Hz")
    else:
        push_log("EVT,COLOR,0,TIDAK ADA", "AUDIO,lost")


# --------------------------------------------------------------------- tampilan
view = (draw_hud(frame, raw, fps, cmd, palette, status="CLOUD/MOCK",
                 last_audio=ss.last_audio) if show_hud else frame)
st.image(cv2.cvtColor(view, cv2.COLOR_BGR2RGB), channels="RGB",
         **stretch(),
         caption="HUD pembidik - kotak warna, crosshair, dan vektor bidikan")

spec = palette.get(stable)
c1, c2, c3 = st.columns(3)
c1.metric("Warna", spec.name)
c2.metric("Keyakinan", f"{raw.confidence:.0f}%")
c3.metric("PAN / TILT", f"{cmd.pan:.0f} / {cmd.tilt:.0f}")

# ---- AUDIO: otomatis saat warna STABIL berubah + tombol ulang untuk HP ----
st.subheader("Audio sesuai warna")
if mode_suara == "mati":
    st.caption("Audio dimatikan lewat pengaturan di sidebar.")
elif stable == 0:
    st.caption("Belum ada warna terdeteksi. Suara akan diputar otomatis saat warna muncul.")
else:
    spec = palette.get(stable)
    ucapan = f"Warna terdeteksi, {spec.speech}"
    if mode_suara in ("nada", "keduanya"):
        data = wav_bytes(stable)
        if data:
            st.caption(f"Nada {spec.name}: {spec.tone_hz} Hz, {spec.beeps} beep")
            st.audio(data, format="audio/wav", autoplay=bool(triggered))
        else:
            st.warning("File WAV tidak tersedia.")
    if mode_suara in ("ucapan", "keduanya"):
        st.caption(f"Ucapan: \"{ucapan}\"")
        embed_html(tts_html(ucapan, auto=bool(triggered)))
    st.caption("HP memblokir audio otomatis sampai ada sentuhan. "
               "Kalau nada tidak bunyi, ketuk tombol di bawah atau 'Ucapkan warna'.")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Putar ulang nada", **stretch()):
            data = wav_bytes(stable)
            if data:
                st.audio(data, format="audio/wav", autoplay=True)
    with b2:
        if st.button("Uji semua warna", **stretch()):
            for item in palette:
                st.caption(f"{item.name}: {item.tone_hz} Hz / {item.beeps} beep")
            embed_html(tts_html(
                "Menguji enam warna: merah, hijau, biru, kuning, oranye, ungu",
                auto=True))

with st.expander("Peta warna -> suara -> LED"):
    st.dataframe(
        {
            "ID": [s.id for s in palette],
            "Warna": [s.name for s in palette],
            "Nada": [f"{s.tone_hz} Hz" for s in palette],
            "Beep": [s.beeps for s in palette],
            "LED RGB": ["/".join(str(v) for v in s.rgb) for s in palette],
            "HSV": [" + ".join(f"{r[0][0]}-{r[1][0]}" for r in s.hsv_ranges)
                    for s in palette],
        },
        hide_index=True,
        **stretch(),
    )

with st.expander("Log serial (simulasi Arduino)"):
    st.code("\n".join(ss.log[-14:]), language="text")
    st.caption("Protokol: T,err_x,err_y,id,conf | balasan: EVT,COLOR / POS / LOG")

with st.expander("Cara pakai di HP & online"):
    st.markdown(
        f"""
        **Lokal, satu WiFi (HP & komputer di jaringan yang sama)**
        ```bash
        python run_streamlit.py
        # atau:
        streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
        ```
        Lalu buka `http://{lan_ip()}:8501` di browser HP. Izinkan port 8501
        di firewall Windows bila tidak bisa diakses. Lewat **HTTP LAN**, kamera HP
        umumnya diblokir browser — pakai mode **Upload gambar** atau **Simulasi**.

        **Online gratis (disarankan — HTTPS otomatis, kamera HP aktif)**
        1. Buat repo GitHub, lalu `git add . && git commit -m "AimBot Warna" && git push`.
        2. Buka <https://share.streamlit.io> → **New app** → pilih repo & branch `main`.
        3. Main file: `streamlit_app.py`.
        4. Advanced settings → Python **3.11** → dependencies: `requirements-streamlit.txt`
           (memakai `opencv-python-headless`, lebih ringan di cloud).
        5. Deploy → dapat URL `https://<nama>.streamlit.app`. Buka di HP, lalu
           **Add to Home Screen** supaya terasa seperti aplikasi.

        `packages.txt` menyediakan `libgl1` bila tetap memakai `requirements.txt`
        (OpenCV versi lengkap). GitHub Pages **tidak bisa** menjalankan Python/Streamlit
        karena hanya melayani file statis — untuk itu tetap pakai `demo/index.html`.
        """
    )

st.divider()
st.caption(f"Frame #{ss.frames} | deteksi {fps:.0f} FPS (per frame) | "
           "Python/OpenCV/Streamlit | Arduino: MODE MOCK")
