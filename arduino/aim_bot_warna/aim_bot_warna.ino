/*
  ============================================================
  AimBot Warna - Firmware Arduino Uno/Nano (AVR)
  Robot Pembidik Sasaran: PC (Python/OpenCV) mendeteksi WARNA,
  Arduino menjalankan PID pan-tilt + umpan balik LED & audio.
  Protokol v1 | Serial 115200 8N1 | tiap perintah diakhiri '\n'
  Hanya memakai library Servo bawaan; tanpa library tambahan.
  ============================================================

  WIRING (ringkas)
  ------------------------------------------------------------
  D9   -> servo PAN    (tengah 90, rentang 20..160)
  D10  -> servo TILT   (tengah 90, rentang 30..150)
  D3   -> LED RGB merah  (PWM)  \
  D5   -> LED RGB hijau  (PWM)   > katoda bersama (common CATHODE)
  D6   -> LED RGB biru   (PWM)  /
  D11  -> buzzer pasif   (tone)
  D12  -> LED LOCK       (HIGH saat warna terkunci)
  D13  -> LED status onboard
  5V/GND -> servo & modul (pakai catu terpisah bila perlu)
  ------------------------------------------------------------
  Catatan: tone() memakai Timer2 yang sama dengan PWM D3/D11;
           kanal merah dapat berkedip sesaat saat buzzer berbunyi.

  CONTOH PERINTAH (Serial Monitor: 115200, kirim dengan newline)
  ------------------------------------------------------------
  PING                      -> balasan PONG
  T,12,-5,2,88              -> err_x, err_y, color_id, conf
  CENTER                    -> reset PID, servo ke 90, LED mati
  BUZZ,3                    -> mainkan melodi warna 3 sekali
  RGB,255,0,0               -> set LED manual (0..255)
  GAIN,0.18,0.005,0.03      -> ubah Kp,Ki,Kd saat jalan
  ------------------------------------------------------------
  BALASAN: EVT,COLOR,<id>,<nama> | POS,<pan>,<tilt>,<id> | LOG,<pesan>
*/

#include <Servo.h>
#include <string.h>   // strtok, strcmp
#include <stdlib.h>   // atof, atoi

// ---- Pin ----
#define PIN_PAN     9
#define PIN_TILT    10
#define PIN_R       3
#define PIN_G       5
#define PIN_B       6
#define PIN_BUZZ    11
#define PIN_LOCK    12
#define PIN_STATUS  13

// ---- Batas sudut servo (derajat) ----
#define PAN_CENTER  90
#define PAN_MIN     20
#define PAN_MAX     160
#define TILT_CENTER 90
#define TILT_MIN    30
#define TILT_MAX    150

// ---- Waktu (ms) ----
#define PID_DT      20      // interval PID tetap
#define TELE_DT     200     // interval telemetri
#define TIMEOUT_T   1500    // failsafe bila tak ada perintah T

// ---- PID: default stabil, mudah diubah di sini ----
#define KP_DEFAULT  0.18f
#define KI_DEFAULT  0.005f
#define KD_DEFAULT  0.03f
#define I_LIMIT     2000.0f // clamp integral (anti-windup)
#define SLEW_MAX    3.0f    // perubahan sudut maks per siklus (derajat)
#define SLEW_RETURN 1.0f    // langkah kembali ke tengah saat timeout
#define ARAH_PAN    1       // ganti ke -1 bila arah servo terbalik
#define ARAH_TILT   1

// ---- Histeresis warna ----
#define CONF_MIN    45      // conf minimum agar warna dianggap valid
#define KONFIRMASI  3       // jumlah perintah T identik sebelum berubah
#define COLOR_COUNT 7

// ---- Serial & melodi ----
#define BUF_MAX     64
#define MAX_STEPS   12

// ============================================================
// Tabel warna: id, nama, nada dasar (Hz), komponen LED R,G,B
// ============================================================
struct Warna {
  byte id;
  const char* nama;
  unsigned int nada;
  byte r, g, b;
};

const Warna warna[COLOR_COUNT] = {
  {0, "Tidak ada",   0,   0,   0,   0},
  {1, "Merah",     440, 255,  25,  25},
  {2, "Hijau",     523,  25, 255,  60},
  {3, "Biru",      587,  25,  90, 255},
  {4, "Kuning",    659, 255, 210,  25},
  {5, "Oranye",    698, 255, 130,  20},
  {6, "Ungu",      784, 170,  45, 255}
};

// ============================================================
// Variabel global
// ============================================================
Servo servoPan, servoTilt;

float Kp = KP_DEFAULT, Ki = KI_DEFAULT, Kd = KD_DEFAULT;

float panAngle  = PAN_CENTER, tiltAngle = TILT_CENTER;
float errX = 0, errY = 0;                  // error ternormalisasi -100..100
float integX = 0, integY = 0;
float prevErrX = 0, prevErrY = 0;

int  currentColorId = 0;                   // warna yang sudah disahkan
int  candidateId = -1;                     // kandidat untuk konfirmasi
byte candidateCount = 0;

unsigned long lastTCmd = 0;                // waktu perintah T terakhir
unsigned long lastPid  = 0;
unsigned long lastTele = 0;
bool timeoutAktif = false;

// Pembaca baris Serial (char array, bukan String)
char lineBuf[BUF_MAX + 1];
byte lineLen = 0;
bool lineOverflow = false;
bool lineReady = false;

// Mesin melodi non-blocking
unsigned int stepFreq[MAX_STEPS];         // 0 = jeda (silent)
unsigned int stepDur[MAX_STEPS];          // durasi langkah (ms)
byte stepLen = 0, stepIdx = 0;
unsigned long stepMulai = 0;
bool melodiAktif = false;

// ============================================================
// Keluaran: LED, event, reset
// ============================================================

// Katoda bersama: nilai PWM = terang langsung (255 = menyala penuh).
void setColorLED(int id) {
  analogWrite(PIN_R, warna[id].r);
  analogWrite(PIN_G, warna[id].g);
  analogWrite(PIN_B, warna[id].b);
}

void sendColorEvent(int id) {
  Serial.print(F("EVT,COLOR,"));
  Serial.print(id);
  Serial.print(',');
  Serial.println(warna[id].nama);
}

void resetPID() {
  errX = errY = 0;
  integX = integY = 0;
  prevErrX = prevErrY = 0;
}

void resetKonfirmasi() {
  candidateId = -1;
  candidateCount = 0;
}

// ============================================================
// Melodi: state machine millis(), tanpa delay(), PID tetap jalan
//   id 1..5 : jumlah beep = id pada nada dasar
//   id 6    : arpeggio naik-turun (pola berbeda)
//   id 0    : mati
// ============================================================
void stopMelody() {
  melodiAktif = false;
  noTone(PIN_BUZZ);
}

void startMelody(int id) {
  noTone(PIN_BUZZ);
  melodiAktif = false;
  if (id <= 0 || id >= COLOR_COUNT) return;

  unsigned int f0 = warna[id].nada;
  stepLen = 0;

  if (id == 6) {
    const unsigned int arp[6] = {
      f0, (unsigned)(f0 * 5 / 4), (unsigned)(f0 * 3 / 2),
      (unsigned)(f0 * 2), (unsigned)(f0 * 3 / 2), (unsigned)(f0 * 5 / 4)
    };
    for (byte i = 0; i < 6; i++) {
      stepFreq[stepLen] = arp[i];  stepDur[stepLen++] = 90;
      stepFreq[stepLen] = 0;      stepDur[stepLen++] = 45;  // jeda
    }
  } else {
    for (byte i = 0; i < id; i++) {
      stepFreq[stepLen] = f0;      stepDur[stepLen++] = 110;
      stepFreq[stepLen] = 0;      stepDur[stepLen++] = 70;  // jeda antar beep
    }
  }

  stepIdx = 0;
  stepMulai = millis();
  melodiAktif = true;
  tone(PIN_BUZZ, stepFreq[0]);            // nada pertama langsung
}

// Ganti nada bila durasi langkah habis; dipanggil tiap loop().
void updateMelody() {
  if (!melodiAktif) return;
  unsigned long now = millis();
  if (now - stepMulai < stepDur[stepIdx]) return;
  noTone(PIN_BUZZ);
  stepIdx++;
  if (stepIdx >= stepLen) { melodiAktif = false; return; }
  stepMulai = now;
  if (stepFreq[stepIdx] > 0) tone(PIN_BUZZ, stepFreq[stepIdx]);
}

// Terapkan warna baru: LED, LOCK, melodi, dan EVT (sekali perubahan).
void applyColor(int id, bool emitEvt) {
  currentColorId = id;
  setColorLED(id);
  digitalWrite(PIN_LOCK, id > 0 ? HIGH : LOW);
  if (id > 0) startMelody(id);
  else stopMelody();
  if (emitEvt) sendColorEvent(id);
}

// Histeresis: conf >= 45, butuh 3 frame identik sebelum warna berubah.
void prosesFrame(int cid, int conf) {
  int observed;
  if (cid == 0) {
    observed = 0;                         // "tidak ada" selalu valid
  } else if (conf >= CONF_MIN) {
    observed = cid;
  } else {
    return;                               // frame kurang yakin, diabaikan
  }

  if (observed == candidateId) {
    if (candidateCount < KONFIRMASI) candidateCount++;
  } else {
    candidateId = observed;
    candidateCount = 1;
  }

  if (candidateCount >= KONFIRMASI && observed != currentColorId) {
    applyColor(observed, true);
  }
}

// ============================================================
// Parser perintah: strtok pada char array (heap tidak terfragmentasi)
// ============================================================
void parseCommand(char* line) {
  char* cmd = strtok(line, ",");
  if (cmd == NULL) return;

  if (strcmp(cmd, "PING") == 0) {
    Serial.println(F("PONG"));

  } else if (strcmp(cmd, "T") == 0) {
    char* sx = strtok(NULL, ",");
    char* sy = strtok(NULL, ",");
    char* sc = strtok(NULL, ",");
    char* sf = strtok(NULL, ",");
    if (!sx || !sy || !sc || !sf) { Serial.println(F("LOG,T format salah")); return; }
    errX = constrain(atof(sx), -100.0f, 100.0f);
    errY = constrain(atof(sy), -100.0f, 100.0f);
    int cid  = constrain(atoi(sc), 0, COLOR_COUNT - 1);
    int conf = constrain(atoi(sf), 0, 100);
    lastTCmd = millis();                  // tanda ada data T baru
    prosesFrame(cid, conf);

  } else if (strcmp(cmd, "CENTER") == 0) {
    resetPID();
    panAngle = PAN_CENTER;
    tiltAngle = TILT_CENTER;
    servoPan.write(PAN_CENTER);
    servoTilt.write(TILT_CENTER);
    resetKonfirmasi();
    applyColor(0, currentColorId != 0);  // LED mati + EVT bila warna berubah

  } else if (strcmp(cmd, "BUZZ") == 0) {
    char* sc = strtok(NULL, ",");
    if (!sc) { Serial.println(F("LOG,BUZZ butuh color_id")); return; }
    startMelody(constrain(atoi(sc), 0, COLOR_COUNT - 1));

  } else if (strcmp(cmd, "RGB") == 0) {
    char* sr = strtok(NULL, ",");
    char* sg = strtok(NULL, ",");
    char* sb = strtok(NULL, ",");
    if (!sr || !sg || !sb) { Serial.println(F("LOG,RGB butuh 3 nilai")); return; }
    analogWrite(PIN_R, constrain(atoi(sr), 0, 255));
    analogWrite(PIN_G, constrain(atoi(sg), 0, 255));
    analogWrite(PIN_B, constrain(atoi(sb), 0, 255));

  } else if (strcmp(cmd, "GAIN") == 0) {
    char* skp = strtok(NULL, ",");
    char* ski = strtok(NULL, ",");
    char* skd = strtok(NULL, ",");
    if (!skp || !ski || !skd) { Serial.println(F("LOG,GAIN butuh 3 nilai")); return; }
    Kp = constrain(atof(skp), 0.0f, 5.0f);
    Ki = constrain(atof(ski), 0.0f, 5.0f);
    Kd = constrain(atof(skd), 0.0f, 5.0f);
    Serial.println(F("LOG,gain diperbarui"));

  } else {
    Serial.print(F("LOG,perintah tak dikenal: "));
    Serial.println(cmd);
  }
}

// Baca per karakter: '\r' diabaikan, panjang buffer dibatasi (anti-overflow).
void readSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (!lineOverflow) {
        lineBuf[lineLen] = '\0';
        lineReady = true;                 // satu baris siap diproses
      }
      lineLen = 0;
      lineOverflow = false;
      return;                            // jangan proses 2 baris sekaligus
    }
    if (lineLen < BUF_MAX) lineBuf[lineLen++] = c;
    else lineOverflow = true;            // kelebihan: baris dibuang
  }
}

// ============================================================
// PID, telemetri, failsafe
// ============================================================

// PID inkremental: error ternormalisasi (-100..100) -> koreksi derajat servo.
void updatePID() {
  if (currentColorId == 0) {            // tak ada sasaran: tahan, integral direset
    integX = integY = 0;
    prevErrX = errX;
    prevErrY = errY;
    return;
  }
  const float dt = PID_DT / 1000.0f;    // 0,02 s

  integX = constrain(integX + errX * dt, -I_LIMIT, I_LIMIT);   // anti-windup
  float ux = Kp * errX + Ki * integX + Kd * ((errX - prevErrX) / dt);
  ux = constrain(ux, -SLEW_MAX, SLEW_MAX);                    // clamp + slew rate
  prevErrX = errX;

  integY = constrain(integY + errY * dt, -I_LIMIT, I_LIMIT);
  float uy = Kp * errY + Ki * integY + Kd * ((errY - prevErrY) / dt);
  uy = constrain(uy, -SLEW_MAX, SLEW_MAX);
  prevErrY = errY;

  panAngle  = constrain(panAngle  + ARAH_PAN  * ux, PAN_MIN,  PAN_MAX);
  tiltAngle = constrain(tiltAngle + ARAH_TILT * uy, TILT_MIN, TILT_MAX);
  servoPan.write((int)panAngle);
  servoTilt.write((int)tiltAngle);
}

void sendTelemetry() {
  Serial.print(F("POS,"));
  Serial.print((int)panAngle);
  Serial.print(',');
  Serial.print((int)tiltAngle);
  Serial.print(',');
  Serial.println(currentColorId);
}

float mendekati(float v, float target, float langkah) {
  if (v < target) return min(v + langkah, target);
  if (v > target) return max(v - langkah, target);
  return v;
}

// Tanpa perintah T > TIMEOUT_T: matikan output, LOG sekali (tidak spam).
// Pergerakan kembali ke 90 dilakukan di tick PID pada loop().
void failsafe(unsigned long now) {
  bool habis = (now - lastTCmd > TIMEOUT_T);
  if (habis && !timeoutAktif) {
    timeoutAktif = true;
    applyColor(0, currentColorId != 0);   // LED/LOCK/buzzer mati + EVT ke 0
    resetKonfirmasi();
    resetPID();
    Serial.println(F("LOG,timeout"));
  } else if (!habis && timeoutAktif) {
    timeoutAktif = false;
    Serial.println(F("LOG,sinyal kembali"));
  }
}

// ============================================================
// Startup
// ============================================================
void setup() {
  Serial.begin(115200);

  pinMode(PIN_R, OUTPUT);
  pinMode(PIN_G, OUTPUT);
  pinMode(PIN_B, OUTPUT);
  pinMode(PIN_BUZZ, OUTPUT);
  pinMode(PIN_LOCK, OUTPUT);
  pinMode(PIN_STATUS, OUTPUT);

  servoPan.attach(PIN_PAN);
  servoTilt.attach(PIN_TILT);
  servoPan.write(PAN_CENTER);
  servoTilt.write(TILT_CENTER);

  setColorLED(0);
  digitalWrite(PIN_LOCK, LOW);
  digitalWrite(PIN_STATUS, LOW);

  // Kedip D13 singkat; delay hanya di setup, tidak pernah di loop().
  for (byte i = 0; i < 2; i++) {
    digitalWrite(PIN_STATUS, HIGH);
    delay(70);
    digitalWrite(PIN_STATUS, LOW);
    delay(70);
  }

  Serial.println(F("LOG,AimBot Warna siap"));
  Serial.println(F("LOG,PROTOCOL,1"));

  lastTCmd = millis();   // cegah timeout langsung sehabis boot
  lastPid  = lastTCmd;
  lastTele = lastTCmd;
}

// ============================================================
// Loop utama: tanpa delay(), semua dijadwalkan lewat millis()
// ============================================================
void loop() {
  readSerial();
  if (lineReady) {
    lineReady = false;
    parseCommand(lineBuf);
  }

  unsigned long now = millis();   // diambil setelah parsing agar now >= lastTCmd

  failsafe(now);
  updateMelody();                 // tidak pernah mem-blok PID

  if (now - lastPid >= PID_DT) {
    lastPid = now;
    if (timeoutAktif) {
      // Kembali perlahan ke tengah saat failsafe.
      panAngle  = mendekati(panAngle,  PAN_CENTER,  SLEW_RETURN);
      tiltAngle = mendekati(tiltAngle, TILT_CENTER, SLEW_RETURN);
      servoPan.write((int)panAngle);
      servoTilt.write((int)tiltAngle);
    } else {
      updatePID();
    }
  }

  if (now - lastTele >= TELE_DT) {
    lastTele = now;
    sendTelemetry();
  }
}
