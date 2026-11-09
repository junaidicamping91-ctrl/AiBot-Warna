#!/usr/bin/env python3
"""AimBot Warna - versi Streamlit (HP & online lewat GitHub).

MODE UTAMA: **Kamera Realtime** — video langsung dari kamera HP/laptop,
deteksi SEMUA warna sekaligus per frame, kotak HUD per warna, serta audio
nada + ucapan yang dipicu saat kumpulan warna stabil berubah. Deteksi HSV dan
connected-components dijalankan di browser (lihat ``web/realtime.html``)
supaya tidak ada round-trip video ke server: tetap lancar di HP dan bekerja
di Streamlit Community Cloud tanpa TURN/WebRTC.

MODE LAIN: **Upload / Foto** dan **Simulasi** memakai pipeline Python/OpenCV
yang sama dengan ``main.py`` (``ColorDetector.detect_all`` + ``draw_hud_multi``).

Jalankan lokal : python run_streamlit.py   (atau: streamlit run streamlit_app.py)
Satu WiFi (HP): python run_streamlit.py --server.address 0.0.0.0
Online gratis  : push repo ke GitHub -> deploy di share.streamlit.io

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

from audio.tone_factory import concat_wav_bytes, generate_all  # noqa: E402
from utils.paths import COLORS_FILE, SETTINGS_FILE, SOUND_DIR, load_json  # noqa: E402
from vision.color_detector import ColorDetector, ColorVoter, Detection  # noqa: E402
from vision.colors import ColorPalette  # noqa: E402
from vision.hud import draw_hud_multi  # noqa: E402
from vision.tracker import Tracker  # noqa: E402

# --------------------------------------------------------------------- halaman
st.set_page_config(
    page_title="AimBot Warna | Kamera Realtime + Full Warna",
    layout="centered",
    initial_sidebar_state="collapsed",
    menu_items={"About": "AimBot Warna - Python/OpenCV + Streamlit + Arduino"},
)

st.markdown(
    """
    <style>
      .block-container{padding-top:1.1rem;padding-bottom:2rem;max-width:820px}
      h1{font-size:1.7rem !important;margin-bottom:.2rem}
      .aim-badge{display:inline-block;background:#e6f1fb;color:#185fa5;border:1px solid #cfe0f7;
        border-radius:999px;padding:3px 10px;font-size:12px;font-weight:600;margin-bottom:.6rem}
      .aim-swatch{height:14px;border-radius:5px;border:1px solid rgba(0,0,0,.08);margin-bottom:5px}
      .aim-note{font-size:13px;color:#475569;line-height:1.6}
      .stButton>button{border-radius:10px;min-height:40px}
      div[data-testid="metric-container"]{background:#fff;border:1px solid #e3e9f2;
        border-radius:12px;padding:8px 10px}
      .aim-chip{display:inline-flex;align-items:center;gap:5px;background:#fff;
        border:1px solid #dbe3ef;border-radius:999px;padding:3px 9px;margin:2px 4px 2px 0;
        font-size:12px;font-weight:600;color:#1d3557}
      .aim-chip i{width:10px;height:10px;border-radius:50%;display:inline-block;
        border:1px solid rgba(0,0,0,.12)}
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


def embed_realtime(html: str) -> None:
    """Embed komponen kamera realtime (butuh izin `camera` pada iframe)."""
    if _MODERN_ST:
        # "content" mengukur tinggi isi srcdoc secara otomatis di HP.
        st.iframe(html, height="content")
    else:
        import streamlit.components.v1 as components
        components.html(html, height=720)


def realtime_asset() -> Path:
    """Cari komponen realtime baik di layout asli maupun layout folder rata."""
    for candidate in (ROOT / "web" / "realtime.html", ROOT / "realtime.html"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "web/realtime.html tidak ditemukan. Salin folder web/ ke direktori proyek."
    )


def realtime_html(cfg: dict) -> str:
    """Suntikkan tabel warna + pengaturan ke komponen HTML/JS."""
    payload = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    return realtime_asset().read_text(encoding="utf-8").replace("__CONFIG__", payload)


# --------------------------------------------------------------------- data & state
@st.cache_resource(show_spinner=False)
def get_palette() -> ColorPalette:
    return ColorPalette.from_json(COLORS_FILE)


@st.cache_data(show_spinner=False)
def get_settings() -> dict:
    return load_json(SETTINGS_FILE, default={})


@st.cache_data(show_spinner=False)
def wav_bytes_multi(color_ids: tuple[int, ...]) -> bytes:
    """Satu file WAV berisi nada BERURUTAN untuk semua warna yang terdeteksi."""
    palette = get_palette()
    paths = []
    for cid in color_ids:
        path = SOUND_DIR / f"{palette.get(cid).key}.wav"
        if not path.exists():
            generate_all(SOUND_DIR, palette)
        if path.is_file():
            paths.append(path)
    return concat_wav_bytes(paths)


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
ss.setdefault("last_ids", [])
ss.setdefault("sim_key", "merah")
ss.setdefault("sim_mode", "satu")
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


def chips_html(color_ids) -> str:
    parts = []
    for cid in color_ids:
        spec = palette.get(cid)
        parts.append(f'<span class="aim-chip"><i style="background:{spec.hex}"></i>'
                     f'{spec.name}</span>')
    return "".join(parts) or '<span class="aim-note">Belum ada warna terdeteksi.</span>'


# Latar (52,58,68) BGR: S~60 -> tidak termasuk grup netral (S<=45) maupun
# kromatik (S>=80), sehingga benar-benar dianggap latar tanpa warna.
BG_BGR = (52, 58, 68)


def make_synthetic_frame(specs, show_all: bool = False,
                         width: int = 640, height: int = 480) -> np.ndarray:
    """Satu bola warna bergerak, ATAU grid berisi SEMUA warna sekaligus."""
    frame = np.full((height, width, 3), BG_BGR, dtype=np.uint8)
    for x in range(0, width, 40):
        cv2.line(frame, (x, 0), (x, height), (62, 68, 78), 1)
    for y in range(0, height, 40):
        cv2.line(frame, (0, y), (width, y), (62, 68, 78), 1)

    if show_all:
        cols = 4
        rows = max(1, math.ceil(len(specs) / cols))
        cw, ch = width / cols, height / rows
        radius = int(min(cw, ch) * 0.30)
        for i, spec in enumerate(specs):
            cx = int((i % cols + 0.5) * cw)
            cy = int((i // cols + 0.5) * ch)
            cv2.circle(frame, (cx, cy), radius,
                       tuple(int(v) for v in spec.bgr), -1)
            cv2.circle(frame, (cx, cy), radius, (70, 75, 85), 2)
        cv2.putText(frame, "MODE SIMULASI - SEMUA WARNA", (16, height - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (120, 130, 150), 1, cv2.LINE_AA)
        return frame

    spec = specs[0]
    t = time.monotonic()
    cx = int(width / 2 + math.sin(t * 0.8) * width * 0.26)
    cy = int(height / 2 + math.cos(t * 0.6) * height * 0.22)
    cv2.circle(frame, (cx, cy), 62, tuple(int(v) for v in spec.bgr), -1)
    cv2.circle(frame, (cx, cy), 62, (70, 75, 85), 2)
    cv2.putText(frame, "MODE SIMULASI", (16, height - 14),
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
st.markdown('<span class="aim-badge">REALTIME · 12 WARNA · SIAP HP · ONLINE</span>',
            unsafe_allow_html=True)
st.caption("Robot pembidik yang menebak warna lalu memberi suara audio sesuai warna. "
           "Kamera realtime mendeteksi **semua warna sekaligus** dalam satu frame.")

sumber = st.radio(
    "Sumber gambar",
    ["Kamera Realtime", "Upload / Foto", "Simulasi"],
    index=0,
    horizontal=True,
    label_visibility="collapsed",
)

with st.sidebar:
    st.header("Pengaturan")
    mode_suara = st.selectbox("Mode suara", ["keduanya", "nada", "ucapan", "mati"], index=0)
    sensitivitas = st.slider("Ambang luas warna (%)", 0.2, 5.0, 0.5, 0.1,
                             help="Makin kecil = makin sensitif terhadap benda kecil")
    vote_n = st.slider("Voting frame (anti kedip)", 1, 15, 5, 1)
    include_netral = st.checkbox(
        "Sertakan warna netral (putih/hitam/abu)", value=True,
        help="Mode FULL WARNA = 12 warna. Matikan bila latar ruangan terlalu ramai.")
    facing = st.selectbox("Kamera HP", ["belakang", "depan"], index=0)
    show_hud = st.checkbox("Tampilkan HUD pembidik (mode Upload/Simulasi)", value=True)
    st.divider()
    st.markdown('<p class="aim-note">Di cloud tidak ada port serial. '
                'Log <code>T,...</code> tetap dibuat sebagai simulasi Arduino.</p>',
                unsafe_allow_html=True)
    if st.button("Reset sesi", **stretch()):
        for key in ("voter", "tracker", "last_ids", "log", "seq", "frames", "last_audio"):
            ss.pop(key, None)
        st.rerun()

# --------------------------------------------------------------------- konfigurasi
settings = dict(get_settings())
det_cfg = dict(settings.get("detection", {}))
det_cfg["min_area_ratio"] = float(sensitivitas) / 100.0
det_cfg["vote_window"] = int(vote_n)
det_cfg["min_votes"] = max(1, int(vote_n) // 2)
det_cfg["include_neutral"] = bool(include_netral)
settings["detection"] = det_cfg

rt_config = {
    "colors": palette.as_web_config(),
    "min_area_ratio": float(sensitivitas) / 100.0,
    "confidence_threshold": float(det_cfg.get("confidence_threshold", 45.0)),
    "confidence_ref_ratio": float(det_cfg.get("confidence_ref_ratio", 0.15)),
    "vote_frames": max(1, int(vote_n)),
    "sound_mode": mode_suara,
    "include_neutral": bool(include_netral),
    "facing": "environment" if facing == "belakang" else "user",
    "max_fps": 20,
}

# ============================================================ MODE REALTIME
if sumber == "Kamera Realtime":
    st.caption(
        "Ketuk **Aktifkan kamera realtime** di dalam panel → izinkan kamera. "
        "Video diproses terus-menerus (bukan foto): setiap warna yang muncul "
        "langsung diberi kotak + label, dan nada/ucapan dipicu saat kumpulan "
        "warna berubah. Kamera butuh **HTTPS** (otomatis di Streamlit Cloud) "
        "atau **localhost**."
    )
    embed_realtime(realtime_html(rt_config))
    st.markdown(
        '<p class="aim-note">Panel di atas berjalan penuh di browser HP: '
        '<code>getUserMedia</code> → HSV → connected components → HUD → '
        'Web Audio + Web Speech. Tidak ada frame video yang dikirim ke server, '
        'jadi tetap responsif walau jaringan lambat. Tabel warna &amp; nada '
        'diambil dari <code>config/colors.json</code> yang sama dengan '
        'Python/OpenCV dan firmware Arduino.</p>',
        unsafe_allow_html=True,
    )
    with st.expander("Kenapa bukan `streamlit-webrtc` / `camera_input`?"):
        st.markdown(
            "- `st.camera_input` hanya mengambil **satu foto** per ketukan — "
            "bukan video realtime.\n"
            "- `streamlit-webrtc` mengirim tiap frame ke server Python dan butuh "
            "STUN/TURN + `av`; di Streamlit Cloud & jaringan seluler sering gagal.\n"
            "- Komponen ini memproses frame **lokal di browser**, jadi 20 FPS "
            "tetap lancar, audio tidak tertunda, dan tidak ada ketergantungan baru. "
            "Mode **Upload / Foto** dan **Simulasi** tetap memakai OpenCV Python "
            "asli bila Anda ingin memeriksa hasil deteksi lewat pipeline PC."
        )

# ============================================================ MODE UPLOAD / SIMULASI
else:
    frame = None
    if sumber == "Upload / Foto":
        st.caption("Ambil satu foto lewat kamera HP atau upload gambar. "
                   "Semua warna di dalam foto akan dideteksi sekaligus.")
        shot = st.camera_input("Ambil foto (opsional)")
        upl = st.file_uploader("Atau pilih foto (jpg/png/webp)",
                               type=["jpg", "jpeg", "png", "webp"])
        frame = file_to_bgr(shot) or file_to_bgr(upl)
    else:
        st.caption("Tanpa kamera: ketuk kartu warna, atau pakai "
                   "**Semua warna sekaligus** untuk menguji multi-deteksi.")
        if st.button("Semua warna sekaligus", **stretch()):
            ss.sim_mode = "semua"
            ss.auto_cycle = False
        cols = st.columns(4)
        for i, spec in enumerate(palette):
            with cols[i % 4]:
                st.markdown(
                    f'<div class="aim-swatch" style="background:{spec.hex}"></div>',
                    unsafe_allow_html=True,
                )
                if st.button(spec.name, key=f"sim_{spec.key}", **stretch()):
                    ss.sim_mode = "satu"
                    ss.sim_key = spec.key
                    ss.auto_cycle = False
        ss.auto_cycle = st.checkbox("Acak tiap refresh", value=bool(ss.auto_cycle))
        if st.button("Frame berikutnya / refresh", **stretch()):
            st.rerun()
        if ss.auto_cycle:
            ss.sim_mode = "satu"
            ss.sim_key = palette[int(time.monotonic() // 2) % len(palette)].key
        frame = make_synthetic_frame(
            palette.specs if ss.sim_mode == "semua" else [palette.by_key(ss.sim_key)],
            show_all=(ss.sim_mode == "semua"),
        )

    if frame is None:
        st.info("Belum ada gambar. Ambil foto, upload gambar, atau pakai mode Simulasi.")
        st.stop()

    # -------------------------------------------------- deteksi SEMUA warna
    t0 = time.perf_counter()
    detector = ColorDetector(palette, settings)
    detections = detector.detect_all(frame)
    gate = float(det_cfg.get("confidence_threshold", 45.0))
    detections = [d for d in detections if d.confidence >= gate]
    ids = sorted(d.color_id for d in detections)
    raw: Detection = detections[0] if detections else Detection(frame_size=(frame.shape[1], frame.shape[0]))

    if ss.voter is None or ss.voter.window != int(vote_n):
        ss.voter = ColorVoter(int(vote_n), max(1, int(vote_n) // 2))
    candidate = raw.color_id if raw.found else 0
    stable = 0
    # Di browser tiap interaksi = satu foto, bukan aliran 30 FPS. Kandidat yang
    # sama dimasukkan sebagai satu "burst" frame agar voting langsung memutus.
    for _ in range(max(1, int(vote_n))):
        stable = ss.voter.vote(candidate)

    h, w = frame.shape[:2]
    if ss.tracker is None or ss.tracker.frame_size != (w, h):
        ss.tracker = Tracker((w, h), settings)
    cmd = ss.tracker.update(raw, stable, dt=0.05)
    fps = 1.0 / max(1e-3, time.perf_counter() - t0)
    ss.frames += 1

    triggered = ids != ss.last_ids
    if triggered:
        ss.seq += 1
        ss.last_ids = ids
        names = ", ".join(palette.get(i).name for i in ids) or "tidak ada"
        ss.last_audio = names
        for cid in ids:
            spec = palette.get(cid)
            push_log(f"EVT,COLOR,{cid},{spec.name}",
                     f"AUDIO,{spec.key},{spec.tone_hz}Hz")
        if raw.found:
            push_log(f"T,{cmd.err_x:.1f},{cmd.err_y:.1f},{raw.color_id},{raw.confidence:.0f}",
                     f"POS,{cmd.pan:.0f},{cmd.tilt:.0f},{raw.color_id}")
        else:
            push_log("EVT,COLOR,0,TIDAK ADA")

    # ------------------------------------------------------------ tampilan
    view = (draw_hud_multi(frame, detections, fps, cmd, palette,
                           status="CLOUD/MOCK", last_audio=ss.last_audio)
            if show_hud else frame)
    st.image(cv2.cvtColor(view, cv2.COLOR_BGR2RGB), channels="RGB",
             **stretch(),
             caption="HUD FULL WARNA - satu kotak untuk tiap warna yang terdeteksi")

    c1, c2, c3 = st.columns(3)
    c1.metric("Jumlah warna", len(ids))
    c2.metric("Dominan", raw.name)
    c3.metric("PAN / TILT", f"{cmd.pan:.0f} / {cmd.tilt:.0f}")
    st.markdown(chips_html(ids), unsafe_allow_html=True)

    # ------------------------------------------------------------- AUDIO
    st.subheader("Audio sesuai semua warna")
    if mode_suara == "mati":
        st.caption("Audio dimatikan lewat pengaturan di sidebar.")
    elif not ids:
        st.caption("Belum ada warna terdeteksi. Suara diputar otomatis saat warna muncul.")
    else:
        ucapan = "Warna terdeteksi, " + ", ".join(palette.get(i).speech for i in ids)
        if mode_suara in ("nada", "keduanya"):
            data = wav_bytes_multi(tuple(ids))
            if data:
                st.caption("Nada berurutan: " + " → ".join(
                    f"{palette.get(i).name} {palette.get(i).tone_hz} Hz" for i in ids))
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
            if st.button("Putar ulang semua nada", **stretch()):
                data = wav_bytes_multi(tuple(ids))
                if data:
                    st.audio(data, format="audio/wav", autoplay=True)
        with b2:
            if st.button("Uji semua warna", **stretch()):
                all_ids = tuple(s.id for s in palette)
                data = wav_bytes_multi(all_ids)
                if data:
                    st.audio(data, format="audio/wav", autoplay=True)
                embed_html(tts_html(
                    "Menguji dua belas warna: " + ", ".join(s.speech for s in palette),
                    auto=True))

# ============================================================ bagian bersama
with st.expander(f"Peta warna lengkap ({len(palette)} warna) → suara → LED"):
    st.dataframe(
        {
            "ID": [s.id for s in palette],
            "Warna": [s.name for s in palette],
            "Grup": [s.group for s in palette],
            "Nada": [f"{s.tone_hz} Hz" for s in palette],
            "Beep": [s.beeps for s in palette],
            "LED RGB": ["/".join(str(v) for v in s.rgb) for s in palette],
            "HSV": [" + ".join(f"{r[0][0]}-{r[1][0]}" for r in s.hsv_ranges)
                    for s in palette],
        },
        hide_index=True,
        **stretch(),
    )
    st.caption("ID 1-6 = warna workshop asli (kompatibel Arduino). "
               "ID 7-9 = cyan/magenta/coklat. ID 10-12 = netral; matikan lewat "
               "sidebar bila latar terlalu ramai.")

with st.expander("Log serial (simulasi Arduino)"):
    st.code("\n".join(ss.log[-14:]), language="text")
    st.caption("Protokol: T,err_x,err_y,id,conf | balasan: EVT,COLOR / POS / LOG. "
               "Panel realtime juga punya log langsung di browser.")

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
        di firewall Windows bila tidak bisa diakses. Lewat **HTTP LAN**, kamera
        umumnya diblokir browser — pakai `http://localhost:8501` di komputer,
        atau deploy online supaya HTTPS aktif.

        **Online gratis (disarankan — HTTPS otomatis, kamera HP aktif)**
        1. Buat repo GitHub, lalu `git add . && git commit -m "AimBot Warna" && git push`.
        2. Buka <https://share.streamlit.io> → **New app** → pilih repo & branch `main`.
        3. Main file: `streamlit_app.py`.
        4. Advanced settings → Python **3.11** → dependencies: `requirements-streamlit.txt`
           (memakai `opencv-python-headless`, lebih ringan di cloud).
        5. Deploy → dapat URL `https://<nama>.streamlit.app`. Buka di HP, ketuk
           **Aktifkan kamera realtime**, lalu **Add to Home Screen**.

        `packages.txt` menyediakan `libgl1` bila tetap memakai `requirements.txt`.
        GitHub Pages **tidak bisa** menjalankan Python/Streamlit karena hanya
        melayani file statis — untuk itu tetap pakai `demo/index.html`.
        """
    )

st.divider()
st.caption(f"Frame Python #{ss.frames} | mode: {sumber} | "
           f"{len(palette)} warna | Python/OpenCV/Streamlit | Arduino: MODE MOCK")
