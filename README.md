# AimBot Warna 🤖🎨🔊
### Robot Pembidik Sasaran — modifikasi: **Tebak Warna + Audio Feedback**

Proyek alat + kode program yang dibuat mengikuti poster workshop **"Implementasi Object Detection pada Robot Pembidik Sasaran"** (Rizky Project / Rizky Dermawan), dengan **satu perubahan utama**: robot tidak lagi menebak *jenis objek*, melainkan **menebak WARNA**. **Begitu warna terdeteksi dan stabil, robot langsung memberi suara audio yang khas untuk warna itu** — nada + ucapan Bahasa Indonesia di PC, serta melodi buzzer + nyala LED RGB di board Arduino.

**Versi terkini (Streamlit): Kamera Realtime + Full Warna.** Video dari kamera HP/laptop diproses terus-menerus (bukan sekadar memotret), **12 warna** dikenali, dan **semua warna yang muncul dalam satu frame dideteksi sekaligus** — masing-masing diberi kotak + label, lalu nada/ucapan dipicu saat kumpulan warna berubah.

Semua kerangka teknis poster tetap dipertahankan: Python environment → OpenCV image processing → (opsional) YOLO → object tracking di PC; IDE Arduino → hardware → serial data communication → PID controller di robot.

---

## 1. Perubahan dari gambar

| Aspek | Poster asli | Proyek ini |
|---|---|---|
| Target | Objek (bounding box YOLO, label kelas) | **Warna dominan + multi-warna** (HSV + kontur, 12 warna sekaligus) |
| Output utama | Kotak deteksi + bidikan | Banyak kotak deteksi (satu per warna) + bidikan **+ suara** |
| Umpan balik | Visual di monitor | **Audio per warna**, ucapan TTS, buzzer, LED RGB |
| Label HUD | `Red 50%`, `Green 97%`, `Blue 95%` | `MERAH 77%`, `HIJAU 77%`, ... + `AUDIO: MERAH / 440 Hz` |
| Kamera | webcam PC | webcam PC **atau Kamera Realtime di browser HP** (getUserMedia, 20 FPS) |
| Chapter 1.3 | YOLO Object Detection | Tetap tersedia sebagai **opsi** `--detector yolo` (fallback otomatis) |
| Chapter 2.4 | PID Controller | Tetap, plus PID versi Python untuk mode simulasi |
| Hardware | 4WD + webcam + pan-tilt + Arduino | Sama, **tambah buzzer pasif + LED RGB** |

> Prinsip desain: **satu tabel warna** (`config/colors.json`) dipakai bersama oleh Python, Arduino, Streamlit, dan komponen kamera realtime, supaya id warna ↔ nama ↔ nada ↔ warna LED tidak pernah beda sendiri.

---

## 2. Alur sistem

```
  [ Kamera / webcam ]  atau  [ sumber sintetis ]
            │  frame BGR
            ▼
  ┌──────────────────────── PC: Python + OpenCV ────────────────────────┐
  │ 1. Gaussian blur → BGR2HSV                                          │
  │ 2. Threshold 12 warna (MERAH pakai 2 rentang: hue wrap-around)      │
  │ 3. Label priority: tiap piksel hanya diklaim 1 warna (tanpa dobel)  │
  │ 4. Morfologi → kontur per warna → centroid + bounding box           │
  │    detect_all() = SEMUA warna dalam 1 frame                         │
  │ 5. ColorVoter: voting 7 frame (anti kedip / histeresis)              │
  │ 6. Tracker: error ternormalisasi −100..100 (0 = tepat di tengah)     │
  └────────┬──────────────────────────────────────┬─────────────────────┘
           │ kumpulan warna STABIL berubah         │ T,err_x,err_y,id,conf
           ▼                                       ▼  (USB Serial 115200)
  ┌────────────────────────┐            ┌────────────────────────────────┐
  │ AUDIO (fitur baru)     │            │ ARDUINO Uno/Nano               │
  │ • <warna>.wav (nada)   │            │ • PID pan/tilt + slew limit    │
  │   digabung berurutan   │            │ • servo PAN D9 / TILT D10      │
  │ • TTS "Warna           │◄─ EVT ─────│ • LED RGB D3/D5/D6             │
  │   terdeteksi, merah"   │   POS      │ • buzzer D11: melodi per warna │
  │ • cooldown 1,2 detik   │            │ • LED LOCK D12 + failsafe      │
  │ • hanya saat BERUBAH   │            │ • tabel 12 warna (COLOR_COUNT) │
  └────────────────────────┘            └────────────────────────────────┘
```

**Cabang browser (Kamera Realtime / Streamlit, §13)**: `getUserMedia` → konversi RGB→HSV per piksel di `<canvas>` → connected components → HUD banyak kotak → Web Audio + Web Speech. Logika warna identik dengan Python, tapi frame **tidak dikirim ke server**, sehingga tetap lancar di HP dan tidak butuh TURN/WebRTC di Streamlit Cloud.

---

## 3. Struktur folder

```
AimBot-Warna-Audio/
├── README.md                      ← dokumen ini
├── run.py                         ← launcher Python/OpenCV (python run.py ...)
├── run_streamlit.py               ← launcher Streamlit (tidak butuh PATH streamlit.exe)
├── streamlit_app.py               ← aplikasi browser: Kamera Realtime, 12 warna, HP & online
├── requirements.txt               ← dependensi lokal (OpenCV lengkap)
├── requirements-streamlit.txt     ← dependensi cloud (OpenCV headless, ringan)
├── requirements-optional.txt
├── packages.txt                   ← paket apt opsional untuk Streamlit Cloud
├── .streamlit/config.toml         ← tema terang + pengaturan server
├── .github/workflows/ci.yml       ← GitHub Actions: compile + 46 unit test
├── config/
│   ├── colors.json                ← TABEL 12 WARNA (HSV, grup, nada, LED, ucapan)
│   └── settings.json              ← kamera, deteksi, PID, serial, audio, HUD
├── python/
│   ├── main.py                    ← entry point / orkestrator loop
│   ├── vision/
│   │   ├── colors.py              ← ColorPalette (single source of truth, as_web_config)
│   │   ├── color_detector.py      ← HSV + kontur + detect_all() + ColorVoter
│   │   ├── tracker.py             ← centroid → error → TargetCommand
│   │   ├── pid.py                 ← PID anti-windup (mode simulasi)
│   │   ├── hud.py                 ← draw_hud() & draw_hud_multi() (banyak kotak)
│   │   └── yolo_detector.py       ← Chapter 1.3 opsional (fallback aman)
│   ├── audio/
│   │   ├── speaker.py             ← pemicu audio saat warna berubah + TTS
│   │   └── tone_factory.py        ← generator WAV + concat_wav_bytes()
│   ├── hardware/serial_link.py    ← protokol serial + MODE MOCK
│   ├── utils/                     ← paths (deteksi root otomatis), logger
│   └── tools/
│       ├── calibrate_color.py     ← kalibrasi HSV pakai trackbar
│       ├── generate_sounds.py     ← buat/refresh semua WAV
│       └── serial_monitor.py      ← tes Arduino manual dari PC
├── web/realtime.html              ← KOMPONEN KAMERA REALTIME (HTML/JS di iframe)
├── arduino/aim_bot_warna/aim_bot_warna.ino   ← firmware 12 warna (Servo library saja)
├── demo/index.html                ← SIMULATOR WEB lama, tanpa hardware sama sekali
├── assets/sounds/*.wav            ← 15 file suara (12 warna + startup/lock/lost)
├── tests/test_pipeline.py         ← unit test vision/audio/serial + multi-warna
├── tests/test_bootstrap.py        ← test layout folder, tanpa argumen, IDLE, fallback
├── tests/test_streamlit_app.py    ← test deploy Streamlit/GitHub + AppTest
└── tests/realtime_js_harness.js   ← uji logika deteksi JS (Node) untuk 12 warna
```

---

## 4. Komponen & wiring

| No | Komponen | Jumlah | Keterangan |
|---|---|---|---|
| 1 | Arduino Uno / Nano | 1 | board utama |
| 2 | Webcam USB | 1 | dipasang di mount pan-tilt |
| 3 | Servo MG995 / SG90 | 2 | PAN & TILT |
| 4 | LED RGB common cathode + resistor 220 Ω | 1 | indikator warna |
| 5 | Buzzer pasif | 1 | melodi per warna (bukan buzzer aktif) |
| 6 | LED + resistor | 1 | indikator LOCK |
| 7 | Rangka 4WD + motor driver + baterai | 1 | sesuai poster (opsional untuk versi meja) |
| 8 | Kabel USB | 1 | serial PC ↔ Arduino |

| Arduino | Ke | Arduino | Ke |
|---|---|---|---|
| D9 | servo PAN (sinyal) | D11 | buzzer pasif (+) |
| D10 | servo TILT (sinyal) | D12 | LED LOCK |
| D3 | LED RGB → R | D13 | LED onboard status |
| D5 | LED RGB → G | 5V / GND | servo, LED, buzzer |
| D6 | LED RGB → B | GND | **wajib common** dengan PC/USB |

> ⚠️ **Catu daya**: servo jangan diambil dari pin 5V Arduino saat berbeban — pakai supply terpisah 5V 2A dan **sambungkan GND-nya ke GND Arduino**.
> ℹ️ `tone()` memakai Timer2 yang berbagi dengan PWM D3/D11; kanal merah LED bisa berkedip sesaat saat buzzer bunyi (normal, sudah dicatat di header `.ino`).

---

## 5. Instalasi

```bash
# 1) Python 3.10+ (diuji pada 3.13)
cd AimBot-Warna-Audio
python -m venv .venv
.venv\Scripts\activate            # Windows  |  Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt   # termasuk Streamlit + Pillow untuk versi browser

# 2) Cek instalasi & port
python run.py --list-ports                    # launcher dari ROOT (paling aman)
python python/main.py --list-ports           # atau langsung
python -m unittest discover -s tests -v      # harus: Ran 46 tests ... OK

# 3) Arduino
#    Buka arduino/aim_bot_warna/aim_bot_warna.ino di Arduino IDE
#    Board: Arduino Uno/Nano | Port: COMx | Upload | Serial Monitor 115200, newline
```

### Error umum: `ModuleNotFoundError: No module named 'audio.speaker'`

Penyebabnya hampir selalu **hanya `main.py` yang disalin**, tanpa paket `audio/`, `vision/`, `hardware/`, `utils/` (misal dikopi ke `C:\Robot tebak warna\main.py` lalu di-Run dari IDLE). Membuat folder kosong bernama `audio` atau `audio.speaker` **tidak** menyelesaikannya — yang dibutuhkan adalah file `audio/speaker.py` dan kawan-kawan.

`main.py` versi sekarang mencari paket secara otomatis (marker file, bukan posisi folder), jadi dua layout ini sama-sama valid:

```
A. Rilis asli                      B. Folder rata (semua di satu level)
   AimBot-Warna-Audio/               Robot tebak warna/
   ├── run.py                        ├── main.py
   ├── config/                       ├── colors.json
   ├── assets/                       ├── settings.json
   └── python/                       ├── audio/  vision/  hardware/  utils/  tools/
       ├── main.py                   ├── assets/sounds/
       └── audio/ vision/ ...        ├── realtime.html  (dari web/)
       └── web/realtime.html         └── index.html  README.md
```

Cara paling aman menjalankan (pilih salah satu):

```bash
cd AimBot-Warna-Audio
python run.py --synthetic --mock --headless       # dari ROOT, via launcher
python python/main.py --synthetic --mock          # langsung

cd "C:\Robot tebak warna"
python main.py --synthetic --mock --headless      # layout rata juga didukung
```

Kalau paket memang belum ada, program **tidak** lagi memunculkan traceback mentah; ia mencetak daftar folder yang diperiksa dan petunjuk menyalin seluruh isi proyek, lalu keluar dengan kode 2.

> Untuk mode **Kamera Realtime**, `streamlit_app.py` mencari `web/realtime.html` **atau** `realtime.html` di root — jadi layout rata tetap jalan asal file komponen ikut disalin.

Aset suara sudah ada di `assets/sounds/` (15 WAV). Untuk membuat ulang:

```bash
python python/tools/generate_sounds.py --overwrite
python python/tools/generate_sounds.py --speech     # Windows: SAPI → *_ucapan.wav
```

---

## 6. Cara menjalankan

### Mode 0 — Cukup tekan Run (IDLE / PyCharm), tanpa argumen
```bash
python python/main.py
# atau dari ROOT proyek:
python run.py
```
Kamera memakai `camera.index` dari `settings.json` (default 0). Kalau tidak ada webcam, otomatis **fallback ke bola warna sintetis** — tidak error. Serial otomatis MODE MOCK bila Arduino tidak tersambung. Tekan **Q** di jendela HUD untuk keluar.

### Mode A — Paling cepat: simulator web (0 instalasi, 0 hardware)
Buka `demo/index.html` di browser. Ada kamera → deteksi warna real-time; tidak ada kamera / izin ditolak → otomatis memakai **6 kartu warna yang bisa diklik** sebagai target virtual. Termasuk HUD pembidik, Web Audio, ucapan `id-ID`, log serial, dan simulasi PID. *(Simulator mandiri ini sengaja tetap 6 kartu; tabel **12 warna penuh** ada di mode Streamlit §6 Mode E.)*

### Mode B — Python tanpa Arduino & tanpa webcam (disarankan untuk pertama kali)
```bash
python python/main.py --synthetic --mock --headless --max-frames 120
```
Bola warna buatan berganti tiap 3 detik; log menampilkan `LOCK warna #N`, `EVT,COLOR,...`, error bidikan, dan status audio.

### Mode C — Webcam + PC saja
```bash
python python/main.py --camera 0 --mock
```
Jendela HUD muncul, tekan **Q** untuk keluar.

### Mode D — Robot lengkap (webcam + Arduino)
```bash
python python/main.py --port COM3
```
Arduino otomatis terdeteksi bila `--port` tidak diisi.

### Mode E — Streamlit: Kamera Realtime + 12 warna (browser HP, bisa online)
```bash
python run_streamlit.py            # paling aman; streamlit.exe tidak perlu ada di PATH
# atau:
streamlit run streamlit_app.py
```
Buka `http://localhost:8501` di PC. Untuk HP di WiFi yang sama, launcher sudah
otomatis bind `0.0.0.0` → buka `http://<IP-WiFi-komputer>:8501`.

| Sumber gambar | Perilaku |
|---|---|
| **Kamera Realtime** *(bawaan)* | Video langsung, **bukan foto**. `getUserMedia` → HSV per piksel → **semua warna sekaligus** per frame → banyak kotak HUD → nada + ucapan saat kumpulan warna berubah. Kamera depan/belakang bisa dipilih di sidebar. |
| **Upload / Foto** | Satu foto / gambar; `ColorDetector.detect_all()` memeriksa **12 warna sekaligus** lewat OpenCV Python. |
| **Simulasi** | 12 kartu warna + tombol **Semua warna sekaligus** (grid 12 bola → 12 kotak deteksi + 12 nada berurutan). |

Sidebar: mode suara (keduanya/nada/ucapan/mati), ambang luas warna, voting anti-kedip,
**sertakan warna netral** (putih/hitam/abu — matikan bila latar ramai), kamera HP,
HUD, dan reset sesi. Detail deploy online ada di **§13**.

### Perintah berguna lainnya
```bash
python python/main.py --test-audio                      # mainkan 12 nada berurutan
python python/main.py --list-ports                     # daftar port serial
python python/main.py --calibrate merah                # kalibrasi HSV trackbar
python python/main.py --detector yolo --camera 0       # YOLO + warna (perlu ultralytics)
python python/main.py --synthetic --mock --no-audio    # CI / tanpa speaker
python python/tools/serial_monitor.py --port COM3      # ketik perintah manual
python run_streamlit.py --server.port 8600            # Streamlit di port lain
```

| Flag | Fungsi |
|---|---|
| `--synthetic` | sumber frame buatan, ganti warna tiap 3 detik |
| `--mock` / `--port` | paksa simulasi / pilih port Arduino |
| `--audio-mode tones\|speech\|both\|off` | pilih nada, ucapan, keduanya, atau mati |
| `--headless` | tanpa jendela OpenCV (server, CI, SSH) |
| `--max-frames N` | berhenti otomatis setelah N frame |
| `--calibrate KEY` | kalibrasi warna tertentu |
| `--detector yolo` | YOLO untuk region, warna diklasifikasi di dalam box |
| `--log-level DEBUG` | lihat semua frame `T,...` yang dikirim |

---

## 7. Protokol serial (115200 8N1, diakhiri `\n`)

**PC → Arduino**

| Perintah | Contoh | Arti |
|---|---|---|
| Target | `T,12.5,-3.0,1,97` | err_x, err_y (−100..100), id warna (1–12), confidence |
| Ping | `PING` | balasan `PONG` |
| Tengah | `CENTER` | reset PID, servo ke 90°, LED mati |
| Tes buzzer | `BUZZ,3` | mainkan melodi BIRU |
| Tes LED | `RGB,255,0,0` | set LED manual |
| Tuning | `GAIN,0.2,0.005,0.03` | ubah Kp, Ki, Kd saat jalan |

**Arduino → PC**: `EVT,COLOR,1,MERAH` (saat warna berubah) · `POS,92,88,1` (telemetri 200 ms) · `LOG,<pesan>` · `PONG`.

**Keamanan firmware**: konfirmasi 3 perintah identik sebelum warna dianggap berubah, `conf >= 45`, PID interval tetap 20 ms, anti-windup + slew rate, melodi non-blocking (`millis()`, tanpa `delay()`), dan **failsafe 1500 ms** — bila PC berhenti mengirim, servo kembali ke tengah, LED & buzzer mati.

---

## 8. Peta warna → suara → LED (12 warna)

| ID | Warna | Grup | Nada | Pola | Ucapan | LED RGB | Rentang HSV (OpenCV) |
|---:|---|---|---:|---|---|---|---|
| 0 | TIDAK ADA | — | — | sweep turun | — | mati | — |
| 1 | MERAH | kromatik | 440 Hz | 1 beep | "merah" | 255,25,25 | 0–9 **dan** 170–179 |
| 2 | HIJAU | kromatik | 523 Hz | 2 beep | "hijau" | 25,255,60 | 36–84 |
| 3 | BIRU | kromatik | 587 Hz | 3 beep | "biru" | 25,90,255 | 95–130 |
| 4 | KUNING | kromatik | 659 Hz | 4 beep | "kuning" | 255,210,25 | 20–35 |
| 5 | ORANYE | kromatik | 698 Hz | 5 beep | "oranye" | 255,130,20 | 10–19 |
| 6 | UNGU | kromatik | 784 Hz | 6 beep | "ungu" | 170,45,255 | 131–149 |
| 7 | CYAN | kromatik | 880 Hz | 1 beep + arpeggio | "sian" | 25,220,230 | 85–94 |
| 8 | MAGENTA | kromatik | 988 Hz | 2 beep + arpeggio | "magenta" | 255,60,180 | 150–169 |
| 9 | COKLAT | kromatik | 1047 Hz | 3 beep + arpeggio | "coklat" | 110,65,35 | 8–20 (V 40–135) |
| 10 | PUTIH | netral | 1175 Hz | 4 beep + arpeggio | "putih" | 240,240,240 | S 0–45, V 200–255 |
| 11 | HITAM | netral | 1319 Hz | 5 beep + arpeggio | "hitam" | 20,20,20 | V 0–45 |
| 12 | ABU | netral | 1397 Hz | 6 beep + arpeggio | "abu abu" | 128,128,128 | S 0–45, V 60–190 |

**ID 1–6** = warna workshop asli; **ID 7–9** = cyan/magenta/coklat (ekspansi kromatik); **ID 10–12** = grup **netral**. Nada (440→1397 Hz) **dan** jumlah beep dibedakan supaya warna masih bisa dikenali tanpa melihat layar. Di `main.py` / Arduino hanya grup kromatik yang aktif secara bawaan (`include_neutral: false` di `settings.json`); mode **FULL WARNA** Streamlit menyalakan 12 warna, dan sidebar bisa mematikan grup netral bila latar ruangan terlalu ramai.

**Deteksi multi-warna tanpa dobel hitung**: tiap piksel diklaim oleh warna **pertama** yang cocok sesuai urutan tabel (label priority), sehingga rentang HSV yang tumpang tindih (mis. oranye/kuning/coklat, ungu/magenta/merah) tidak menghasilkan dua kotak untuk objek yang sama.

Audio **hanya dipicu saat kumpulan warna stabil berubah** (`ColorVoter` + cooldown 1,2 s) — tidak berbunyi 30× per detik. Bila beberapa warna muncul bareng, nada digabung **berurutan** jadi satu WAV (`concat_wav_bytes`) dan ucapan menyebut semua warna.

Ubah tabel di `config/colors.json`, lalu samakan array `warna[]` di file `.ino` bila mengubah id/nada.

---

## 9. Kalibrasi HSV & tuning PID

**Kalibrasi** (pencahayaan sangat berpengaruh):
```bash
python python/tools/calibrate_color.py --camera 0 --color-key merah
```
Arahkan kamera ke benda, geser `Low H/S/V` & `High H/S/V` sampai mask putih hanya menutupi benda, tekan **S** → tersimpan ke `config/colors.json`. Ulangi untuk warna lain.

**PID** (`config/settings.json` → `tracking.pid`, dan `KP_DEFAULT/KI_DEFAULT/KD_DEFAULT` di `.ino`):

| Gejala | Tindakan |
|---|---|
| Servo bergetar / overshoot | turunkan `kp`, naikkan `kd` |
| Bidikan meleset terus (steady-state error) | naikkan `ki` (hati-hati windup) |
| Gerakan tersendat / menyentak | kecilkan `SLEW_MAX`, turunkan `kp` |
| Arah servo terbalik | ubah `ARAH_PAN` / `ARAH_TILT` jadi `-1` |
| Terlalu sensitif saat target di tengah | besarkan `tracking.deadzone` |

Nilai error sudah ternormalisasi −100..100 sehingga **tidak bergantung resolusi kamera**.

---

## 10. Pemetaan chapter poster

| Chapter poster | Implementasi di proyek |
|---|---|
| 1.1 Python Environment Setup | `requirements.txt`, venv, `python/main.py` |
| 1.2 OpenCV Image Processing | `vision/color_detector.py` (`detect`, **`detect_all`**), `tools/calibrate_color.py` |
| 1.3 YOLO Object Detection | `vision/yolo_detector.py` (opsional, fallback aman) |
| 1.4 Object Tracking | `vision/tracker.py`, `vision/color_detector.py::ColorVoter`, `hud.py` (`draw_hud_multi`) |
| 2.1 IDE Arduino Setup | `arduino/aim_bot_warna/aim_bot_warna.ino` (library Servo saja, 12 warna) |
| 2.2 Hardware Setup | Tabel wiring di §4 & header `.ino` |
| 2.3 Serial Data Communication | `hardware/serial_link.py`, `tools/serial_monitor.py`, §7 |
| 2.4 PID Controller | `updatePID()` di `.ino`, `vision/pid.py`, §9 |
| **Tambahan** | `audio/speaker.py`, `audio/tone_factory.py`, `assets/sounds/`, `demo/index.html` |
| **Kamera Realtime / full warna** | `web/realtime.html` (getUserMedia + HSV + connected components + Web Audio/Speech), `tests/realtime_js_harness.js` |
| **Antarmuka browser / HP** | `streamlit_app.py`, `run_streamlit.py`, `.streamlit/config.toml`, `requirements-streamlit.txt` (pipeline §1.2/1.4 dipakai ulang, bukan ditulis ulang) |

---

## 11. Troubleshooting

| Masalah | Solusi |
|---|---|
| `ModuleNotFoundError: No module named 'audio.speaker'` | hanya `main.py` yang tersalin; salin **seluruh** paket `audio/ vision/ hardware/ utils/`. Lihat §5 |
| `TypeError: int() argument must be ... not 'NoneType'` di `open_source` | versi lama saat dijalankan tanpa argumen; `main.py` terbaru sudah memakai `camera.index` dari `settings.json` dan fallback ke sumber sintetis |
| `Kamera 0 tidak bisa dibuka` | sekarang otomatis fallback ke **sumber sintetis** (bola warna bergerak); coba `--camera 1` untuk kamera lain, atau `--synthetic` untuk menegaskan |
| `The function is not implemented` / `cv2.imshow` error | build `opencv-python-headless` tidak punya jendela; HUD otomatis dimatikan. Pakai `demo/index.html` untuk tampilan, atau `pip install opencv-python` |
| Warna sering salah di lampu kuning | kalibrasi ulang HSV; naikkan `Low S`/`Low V`; pakai latar netral |
| MERAH tidak terdeteksi | pastikan `hsv2` (170–179) masih ada di `colors.json` |
| Terlalu banyak warna netral (dinding/meja ikut terdeteksi) | matikan **Sertakan warna netral** di sidebar Streamlit, atau `include_neutral: false` di `settings.json` |
| Dua kotak untuk satu objek | urutan tabel `colors.json` = prioritas; pindahkan warna yang lebih spesifik ke atas |
| Suara tidak terdengar | cek `--no-audio`/`--audio-mode off`; jalankan `--test-audio`; di Windows pastikan `winsound` tersedia |
| Ucapan TTS lambat | jalankan `generate_sounds.py --speech` agar WAV ucapan di-render lebih dulu |
| `pyserial belum terpasang` | `pip install pyserial`; tanpa itu proyek otomatis masuk MODE MOCK |
| Port COM tidak muncul | cek driver CH340/FTDI, kabel USB data (bukan kabel charge), `--list-ports` |
| Servo berdengung di tengah | besarkan `deadzone`, turunkan `kp`, atau perbaiki catu daya |
| `ultralytics` tidak ada | normal; `--detector yolo` otomatis fallback ke HSV penuh |
| `streamlit: command not found` / `streamlit.exe` tidak dikenal | pakai `python run_streamlit.py` (memanggil CLI lewat modul, tidak bergantung PATH) |
| `ImportError: libGL.so.1` saat deploy cloud | pilih `requirements-streamlit.txt` di Advanced settings, atau biarkan `packages.txt` memasang `libgl1` |
| **Panel Kamera Realtime kosong / tombol kamera tidak menyala** | butuh **HTTPS** atau `localhost`; deploy ke Streamlit Cloud (§13.2). Cek juga izin kamera browser & tidak ada aplikasi lain yang memakai kamera |
| **Kamera realtime tertutup / `getUserMedia` diblokir di iframe** | komponen di-embed lewat `st.iframe` dengan izin `camera`; bila browser lama memblokir, buka URL Streamlit langsung (bukan tab tersemat) atau pakai **Upload / Foto** |
| `web/realtime.html tidak ditemukan` | salin folder `web/` (atau `realtime.html` ke root untuk layout rata) ke direktori proyek |
| Kamera HP tidak mau menyala lewat `http://<IP>:8501` | HTTP LAN diblokir browser untuk `getUserMedia`; pakai `http://localhost:8501` di PC, atau deploy online (HTTPS) |
| Suara tidak bunyi di HP | iOS/Android memblokir autoplay sampai ada sentuhan; ketuk **Putar ulang semua nada** atau **Ucapkan warna** |
| HP tidak bisa buka `http://<IP>:8501` | samakan WiFi, izinkan port 8501 di firewall Windows, pastikan server bind `0.0.0.0` |

---

## 12. Pengujian

```bash
python -m unittest discover -s tests -v     # 46 test, tidak butuh kamera/Arduino
python python/main.py                       # tanpa argumen juga harus jalan
python python/main.py --synthetic --mock --headless --max-frames 95
```
Cakupan: tabel **12 warna** & keunikan nada, grup kromatik/netral, wrap-around merah, `detect_all()` untuk seluruh palette, **deteksi multi-warna simultan** (6 bola → 6 kotak, tanpa id dobel), frame kosong, error bidikan, voting anti-kedip, PID + anti-windup, format protokol serial, mode mock, fallback YOLO, validasi & penggabungan file WAV, **deteksi root untuk layout rata/asli**, **menjalankan dari folder & working directory lain**, **IDLE/`runpy`**, **pesan jelas bila paket hilang**, **default kamera tanpa argumen + fallback sintetis**, **kelengkapan file deploy Streamlit/GitHub**, **AppTest** (mode bawaan = Kamera Realtime, komponen iframe tampil, simulasi semua warna → 12 deteksi + audio), serta **harness Node** yang menguji klasifikasi HSV 12 warna di `web/realtime.html` (diskip otomatis bila Node tidak tersedia).

---

## 13. Streamlit, HP & online lewat GitHub

Versi **Streamlit** (`streamlit_app.py`) memakai **tabel warna yang sama persis** dengan `main.py` dan firmware:
`config/colors.json` → `ColorPalette.as_web_config()` untuk komponen browser, dan
`ColorDetector.detect_all()` + `draw_hud_multi()` + `concat_wav_bytes()` untuk mode
Upload/Simulasi. Jadi id warna, nada, protokol `T,err_x,err_y,id,conf`, dan aturan
"audio hanya saat warna stabil berubah" tetap identik dengan versi desktop & Arduino.

| | Desktop `main.py` | Browser `streamlit_app.py` |
|---|---|---|
| Tampilan | jendela OpenCV (`cv2.imshow`) | halaman web Streamlit + panel `iframe` |
| Sumber | webcam / video / sintetis | **Kamera Realtime (video)** / upload / 12 kartu simulasi |
| Deteksi | `detect()` dominan, `detect_all()` tersedia | **semua warna sekaligus per frame** (JS di browser & OpenCV di server) |
| Audio | WAV + SAPI TTS | Web Audio / `st.audio` + Web Speech API `id-ID` |
| Arduino | serial USB 115200 | **MODE MOCK** (log `T,...` disimulasikan) |
| Akses | PC yang menjalankan script | HP, tablet, atau siapa pun lewat URL HTTPS |

> Arduino **tidak** bisa dicolokkan ke server cloud. Untuk robot fisik tetap pakai
> Mode C/D di PC; versi online berfungsi penuh sebagai **dashboard deteksi + audio**.

### 13.1 Kenapa Kamera Realtime bukan `camera_input`

| Pendekatan | Hasil |
|---|---|
| `st.camera_input` | hanya **satu foto** per ketukan — bukan video. ❌ tidak memenuhi realtime |
| `streamlit-webrtc` | tiap frame dikirim ke server Python, butuh STUN/TURN + `av`; sering gagal di Cloud & jaringan seluler |
| **`web/realtime.html` (dipakai)** | `getUserMedia` → HSV + connected components **lokal di browser HP** → HUD banyak kotak → Web Audio + Web Speech. ~20 FPS, tanpa frame bolak-balik ke server, tanpa dependensi baru |

Komponen di-embed dengan `st.iframe` (izin `camera`), dan menerima konfigurasi
(12 warna, HSV, nada, voting, kamera depan/belakang, mode suara) yang disuntikkan
dari Python. `st.iframe(html, height="content")` dipakai bila tersedia, dengan
fallback `components.html` untuk Streamlit lama.

### 13.2 Lokal — dibuka di HP satu WiFi

```bash
pip install -r requirements.txt
python run_streamlit.py
# setara dengan:
streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

1. Cek IP WiFi komputer (`ipconfig` → *Wireless LAN adapter Wi-Fi* → IPv4, mis. `192.168.1.7`).
2. Di HP, buka `http://192.168.1.7:8501`.
3. Kalau tidak tersambung: samakan WiFi, izinkan **port 8501** di Windows Defender
   Firewall, dan pastikan tidak ada `--server.address 127.0.0.1`.

⚠️ Lewat **HTTP** (LAN), browser HP umumnya memblokir `getUserMedia`, jadi
**Kamera Realtime** tidak aktif. Gunakan **Upload / Foto** atau **Simulasi**, atau
buka `http://localhost:8501` di komputer itu sendiri. Supaya kamera betul-betul
hidup di HP, butuh **HTTPS** → deploy online (§13.3).

### 13.3 Online gratis — GitHub + Streamlit Community Cloud

GitHub **menyimpan kodenya**; Streamlit Cloud **menjalankan Python-nya**. Keduanya
gratis untuk repo publik.

```bash
# 1) Dari folder proyek
git init
git add .
git commit -m "AimBot Warna: Kamera Realtime + 12 warna + audio + Streamlit"
git branch -M main
git remote add origin https://github.com/<username>/aimbot-warna.git
git push -u origin main
```

2. Buka <https://share.streamlit.io> → login dengan akun GitHub → **New app**.
3. Isi: **Repository** `<username>/aimbot-warna`, **Branch** `main`,
   **Main file path** `streamlit_app.py`.
4. **Advanced settings** → Python **3.11** → *Python dependencies file*
   `requirements-streamlit.txt` (wajib: `opencv-python-headless`, tidak butuh `libGL`).
   Biarkan `packages.txt` apa adanya (cadangan `libgl1` kalau memakai `requirements.txt`).
5. Klik **Deploy**. Tunggu 2–5 menit → URL `https://<nama>.streamlit.app`.
6. Buka URL itu di HP → ketuk **Aktifkan kamera realtime**, izinkan kamera. Audio &
   kamera aktif karena **HTTPS**. Browser menu → **Add to Home Screen / Tambahkan
   ke Layar Utama** agar tampil seperti aplikasi.

**Checklist file yang ikut ter-push** (jangan di-`gitignore`):

```
streamlit_app.py  run_streamlit.py  run.py
requirements.txt  requirements-streamlit.txt  packages.txt
.streamlit/config.toml
config/colors.json  config/settings.json
web/realtime.html                     ← komponen Kamera Realtime (wajib!)
assets/sounds/*.wav                   ← 15 file WAV, kalau hilang aplikasi generate otomatis
python/**/*.py                        ← vision/ audio/ hardware/ utils/
.github/workflows/ci.yml
```

**Catatan penting**

- **GitHub Pages tidak bisa menjalankan Python/Streamlit** — hanya file statis HTML/CSS/JS.
  Kalau ingin Pages, aktifkan untuk `demo/index.html` (simulator murni browser, sudah
  punya Web Audio + Web Speech + HUD). Tapi untuk `streamlit_app.py`, pakai Streamlit Cloud.
- `.github/workflows/ci.yml` otomatis menjalankan `py_compile` + seluruh **46 unit test**
  pada Python 3.10/3.11/3.12 setiap `push`. Kalau ada yang merah, perbaiki sebelum deploy.
- Update kode cukup `git push`; Streamlit Cloud mendeteksi perubahan dan redeploy sendiri.
- Repo privat butuh akun Streamlit Cloud berbayar; repo publik gratis.
- Bila deploy gagal dengan `ImportError: libGL.so.1`, pastikan Advanced settings
  menunjuk `requirements-streamlit.txt`, bukan `requirements.txt`.

### 13.4 Perilaku audio & deteksi di browser

| Situasi | Hasil |
|---|---|
| Beberapa warna muncul bareng | **semua** diberi kotak + chip; nada digabung berurutan jadi satu WAV; ucapan menyebut semua warna |
| Kumpulan warna stabil **berubah** | nada + ucapan `Warna terdeteksi, <warna1>, <warna2>, ...` dipicu |
| Kumpulan warna sama berulang | **tidak** berbunyi ulang (histeresis voting) |
| Warna hilang semua | `EVT,COLOR,0,TIDAK ADA`, audio berhenti |
| Grup netral dimatikan | hanya 9 warna kromatik yang dipantau (berguna untuk latar ramai) |
| HP memblokir autoplay | tombol **Putar ulang semua nada** / **Uji semua warna** / **Ucapkan warna** tersedia |
| Satu foto di browser | dianggap satu *burst* frame agar voting langsung memutuskan (tidak perlu memotret 5×) |

---

### Kredit
Struktur & silabus mengikuti poster **"Implementasi Object Detection pada Robot Pembidik Sasaran"** — Rizky Project (Rizky Dermawan). Modifikasi deteksi warna + umpan balik audio, ekspansi 12 warna, kamera realtime, kode, firmware, simulator, dan dokumentasi dibuat untuk proyek ini. Python/OpenCV, Arduino, Streamlit, dan Web APIs adalah merek dari pemiliknya masing-masing.
