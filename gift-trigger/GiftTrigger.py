#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GiftTrigger - Trigger gift TikTok Live berbasis deteksi layar (100% lokal).

Fitur:
- Banyak aturan gift (rule): setiap gift punya gambar, tombol F1-F10, dan
  jumlah tekan sendiri.
- Deteksi gambar gift dengan template matching multi-skala (cepat).
- Deteksi nama gift dan jumlah kirim (mis. "Mawar x20") lewat OCR Windows.
- Suara ucapan lokal (TTS SAPI): "Thank you <username> for your <gift>",
  bisa memilih suara pria atau wanita.
- Sapaan otomatis "Welcome to the stream" setiap N detik (default 15 detik).
- Pemilihan area pantau dengan drag di layar.
- Test deteksi + preview sebelum mulai.
- Konfigurasi tersimpan otomatis (config.json).

Tidak memerlukan koneksi internet atau API TikTok.
"""

import os
import sys
import re
import json
import time
import queue
import threading
import traceback
import ctypes

# ----------------------------------------------------------------------------
# DPI awareness HARUS diatur sebelum Tk dibuat agar koordinat layar akurat.
# ----------------------------------------------------------------------------
def _enable_dpi_awareness():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi_awareness()

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
import numpy as np
import mss

# keyboard & sound bersifat opsional; aplikasi tetap bisa jalan tanpa sound.
try:
    import keyboard
    HAS_KEYBOARD = True
except Exception:
    HAS_KEYBOARD = False

try:
    import winsound
    HAS_SOUND = True
except Exception:
    HAS_SOUND = False

# OCR bawaan Windows (Windows 10/11). Jika tidak tersedia, fitur OCR dinonaktifkan.
HAS_OCR = False
OCR_IMPORT_ERROR = ""
try:
    import asyncio
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import (
        SoftwareBitmap,
        BitmapPixelFormat,
        BitmapAlphaMode,
    )
    from winrt.windows.storage.streams import DataWriter
    HAS_OCR = True
except Exception as exc:  # pragma: no cover
    OCR_IMPORT_ERROR = str(exc)

# TTS lokal memakai SAPI5 lewat comtypes (suara bawaan Windows).
HAS_TTS = False
TTS_IMPORT_ERROR = ""
try:
    import comtypes
    import comtypes.client
    # Jangan menulis modul hasil generate ke disk (penting saat jadi EXE).
    try:
        comtypes.client.gen_dir = None
    except Exception:
        pass
    HAS_TTS = True
except Exception as exc:  # pragma: no cover
    TTS_IMPORT_ERROR = str(exc)

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False


# ============================================================================
# Lokasi aplikasi & konfigurasi
# ============================================================================
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

VALID_KEYS = ["f" + str(i) for i in range(1, 11)]

RULE_DEFAULTS = {
    "name": "",
    "template_path": "",
    "key": "f1",
    "count_mode": "ocr",       # "ocr" atau "fixed"
    "fixed_count": 1,
    "enabled": True,
}

DEFAULT_CONFIG = {
    "rules": [],
    "sound_enabled": True,
    "sound_file": "success.wav",
    "tts_enabled": True,
    "tts_gender": "female",       # "female" atau "male"
    "tts_voice": "",              # deskripsi suara; kosong = otomatis
    "tts_rate": 0,                # -10 .. 10
    "tts_volume": 100,            # 0 .. 100
    "tts_gift_text": "Thank you {username} for your {gift}",
    "welcome_enabled": True,
    "welcome_interval": 15.0,     # detik
    "welcome_text": "Welcome to the stream",
    "use_fullscreen": True,
    "gift_region": None,          # [x, y, w, h]
    "ocr_region": None,           # [x, y, w, h]
    "threshold": 0.82,
    "press_delay_ms": 80,
    "cooldown_s": 1.5,
    "confirm_frames": 2,
    "once_per_appearance": True,
    "target_window": "",
}


def log_error(text):
    try:
        with open(os.path.join(APP_DIR, "error_log.txt"), "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass


def new_mss():
    """mss() lama masih jalan tetapi memunculkan DeprecationWarning."""
    try:
        return mss.MSS()
    except Exception:
        return mss.mss()


# ============================================================================
# OCR helper (Windows.Media.Ocr)
# ============================================================================
def _ocr_sync(bgr_image, upscale=2):
    """Menjalankan OCR pada numpy BGR image secara sinkron. Return string."""
    if not HAS_OCR or bgr_image is None:
        return ""
    try:
        if upscale != 1:
            bgr_image = cv2.resize(
                bgr_image, None, fx=upscale, fy=upscale,
                interpolation=cv2.INTER_CUBIC,
            )
        bgra = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2BGRA)
        h, w = bgra.shape[:2]
        writer = DataWriter()
        writer.write_bytes(bgra.tobytes())
        buffer = writer.detach_buffer()
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            buffer, BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED
        )

        async def _run():
            engine = OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                return None
            return await engine.recognize_async(bitmap)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        if result is None:
            return ""
        return (result.text or "").strip()
    except Exception as exc:
        log_error("OCR error: " + str(exc))
        return ""


# ============================================================================
# Template matching multi-skala (grayscale, dipercepat)
# ============================================================================
MATCH_SCALES = [0.80, 0.90, 1.00, 1.10, 1.25]


def load_template(path):
    """Memuat template. Jika PNG transparan, area transparan diisi abu-abu netral."""
    if not path or not os.path.exists(path):
        return None
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        bgr = img[:, :, :3].astype(np.float32)
        bgr = bgr * alpha + 128.0 * (1.0 - alpha)
        img = bgr.astype(np.uint8)
    elif img.ndim == 3 and img.shape[2] == 3:
        pass
    else:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


def find_gift(screen_bgr, template_bgr):
    """Cari template di layar dengan beberapa skala.

    Return (best_score, best_rect) dengan rect = (x, y, w, h) koordinat layar.
    """
    if screen_bgr is None or template_bgr is None:
        return 0.0, None

    sh, sw = screen_bgr.shape[:2]
    th, tw = template_bgr.shape[:2]
    if th < 6 or tw < 6:
        return 0.0, None

    # Perkecil layar besar agar cepat, tapi jaga template tidak terlalu kecil.
    factor = 1.0
    max_dim = max(sw, sh)
    if max_dim > 1000:
        factor = 1000.0 / max_dim
    min_side = min(tw, th)
    if min_side * factor < 14:
        factor = min(1.0, 14.0 / max(1, min_side))

    gray_screen = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    gray_tmpl = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
    if factor != 1.0:
        gray_screen = cv2.resize(
            gray_screen, None, fx=factor, fy=factor,
            interpolation=cv2.INTER_AREA,
        )

    screen_h, screen_w = gray_screen.shape[:2]
    best_score = 0.0
    best_rect = None

    for scale in MATCH_SCALES:
        tw_s = max(8, int(round(tw * scale * factor)))
        th_s = max(8, int(round(th * scale * factor)))
        if tw_s > screen_w or th_s > screen_h:
            continue
        try:
            t = cv2.resize(gray_tmpl, (tw_s, th_s), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(gray_screen, t, cv2.TM_CCOEFF_NORMED)
        except Exception:
            continue
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = float(max_val)
            ox = int(round(max_loc[0] / factor))
            oy = int(round(max_loc[1] / factor))
            ow = int(round(tw_s / factor))
            oh = int(round(th_s / factor))
            best_rect = (ox, oy, ow, oh)
        if best_score >= 0.97:
            break

    return best_score, best_rect


# ============================================================================
# Parsing OCR, validasi nama, dan tebakan username
# ============================================================================
def normalize_text(text):
    t = (text or "").lower()
    return re.sub(r"[^a-z0-9]", "", t)


def parse_count(text):
    """Ambil angka jumlah kirim dari teks OCR, mis. 'Mawar x20' -> 20."""
    if not text:
        return 0
    t = text.replace("\u00d7", "x").replace("\u0425", "x")

    patterns = (
        r"(\d{1,4})[xX]",           # 20x
        r"[xX](\d{1,4})",           # x20
        r"(\d{1,4})\s+[xX]",        # 20 x
        r"[xX]\s+(\d{1,4})",        # x 20
        r"(\d{1,4})\s*kali",        # 20 kali
    )
    for pat in patterns:
        found = re.findall(pat, t)
        nums = []
        for c in found:
            try:
                n = int(c)
            except Exception:
                continue
            if 0 < n <= 9999:
                nums.append(n)
        if nums:
            return min(max(nums), 999)

    # Angka tanpa penanda 'x': terima hanya jika teks bersih berisi angka.
    m = re.fullmatch(r"\s*(\d{1,4})\s*[xX]?\s*", t)
    if m:
        return min(int(m.group(1)), 999)
    return 0


def expected_name_list(expected_names):
    raw = (expected_names or "").replace("|", ",")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def validate_name(ocr_text, expected_names):
    """Return (ok, matched_name). Jika daftar kosong, validasi dilewati."""
    exp = expected_name_list(expected_names)
    if not exp:
        return True, ""
    hay = normalize_text(ocr_text)
    for name in exp:
        needle = normalize_text(name)
        if needle and needle in hay:
            return True, name
    return False, ""


NOISE_WORDS = {
    "sent", "send", "sends", "mengirim", "mengirimkan", "kirim",
    "gift", "gifts", "give", "gave", "given", "terima", "kasih",
    "thanks", "thank", "you", "for", "your", "the", "a", "an",
    "from", "kepada", "ke", "di", "dan", "and", "on", "at",
    "kali", "tiktok", "live", "user", "username", "dari", "ini",
}


def guess_username(text, gift_name=""):
    """Tebak username dari teks alert gift.

    Contoh OCR: 'budi123 sent Mawar x20' -> 'budi123'
    """
    raw = text or ""
    raw = re.sub(r"\d{1,4}\s*[xX]\b", " ", raw)
    raw = re.sub(r"\b[xX]\s*\d{1,4}\b", " ", raw)

    gift_norms = {
        normalize_text(p)
        for p in str(gift_name).replace("|", ",").split(",")
        if p.strip()
    }
    candidate = ""
    for chunk in re.split(r"\s+", raw.strip()):
        token = re.sub(r"[^A-Za-z0-9._@]", "", chunk).lstrip("@")
        if len(token) < 2 or token.isdigit():
            continue
        low = token.lower()
        if low in NOISE_WORDS:
            continue
        # Nama gift boleh muncul setelah username; lewati jika sudah dapat kandidat.
        if normalize_text(token) in gift_norms and candidate:
            continue
        candidate = token
        break

    if candidate and normalize_text(candidate) in gift_norms:
        return ""
    return candidate


def build_tts_message(template, username, gift, count=1):
    """Isi placeholder {username}, {gift}, {count} dengan aman."""
    t = (template or "").strip() or "Thank you {username} for your {gift}"
    user = (username or "").strip()
    gift_name = (gift or "").strip() or "gift"
    msg = t.replace("{username}", user)
    msg = msg.replace("{gift}", gift_name)
    msg = msg.replace("{count}", str(count))
    msg = re.sub(r"\s+", " ", msg).strip()
    return msg


# ============================================================================
# Fokus jendela target (Windows)
# ============================================================================
def focus_window_by_title(substr):
    """Fokuskan jendela Windows pertama yang judulnya mengandung substr."""
    if os.name != "nt" or not substr:
        return None
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = []

    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if substr.lower() in title.lower():
            found.append((hwnd, title))
            return False
        return True

    try:
        user32.EnumWindows(EnumProc(_callback), 0)
    except Exception:
        return None

    if not found:
        return None
    hwnd, title = found[0]
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    return title


# ============================================================================
# TTS lokal (SAPI5 via comtypes)
# ============================================================================
class SapiTTS:
    """Antrean ucapan dengan satu worker thread agar tidak saling tabrak."""

    def __init__(self, log_func):
        self.log = log_func
        self.queue = queue.Queue()
        self.settings = {
            "enabled": True,
            "gender": "female",
            "voice": "",
            "rate": 0,
            "volume": 100,
        }
        self.welcome = {
            "enabled": True,
            "interval": 15.0,
            "text": "Welcome to the stream",
        }
        self.running = threading.Event()
        self._stop = threading.Event()
        self._last_welcome = 0.0
        self.thread = None
        if HAS_TTS:
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()

    # ----------------------------- pengaturan -----------------------------
    def configure(self, **kwargs):
        new = dict(self.settings)
        new.update(kwargs)
        self.settings = new

    def configure_welcome(self, **kwargs):
        new = dict(self.welcome)
        new.update(kwargs)
        self.welcome = new

    @staticmethod
    def list_voices():
        """Daftar suara SAPI yang terpasang di Windows."""
        if not HAS_TTS:
            return []
        out = []
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        try:
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            tokens = voice.GetVoices()
            for i in range(tokens.Count):
                token = tokens.Item(i)
                desc = token.GetDescription()
                try:
                    gender = token.GetAttribute("Gender") or ""
                except Exception:
                    gender = ""
                out.append({"index": i, "desc": desc, "gender": gender})
        except Exception as exc:
            log_error("TTS list voices: " + str(exc))
        return out

    # -------------------------------- API ----------------------------------
    def say(self, text):
        if not HAS_TTS or not text:
            return
        if not self.settings.get("enabled", True):
            return
        self.queue.put(("say", text))

    def start_stream(self):
        self.running.set()
        self._last_welcome = 0.0

    def stop_stream(self):
        self.running.clear()
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass
        self.queue.put(("purge", None))

    def shutdown(self):
        self._stop.set()
        self.queue.put(("quit", None))

    # ------------------------------- worker --------------------------------
    def _apply_voice(self, voice, cfg):
        key = (
            str(cfg.get("gender", "")),
            str(cfg.get("voice", "")),
            int(cfg.get("rate", 0)),
            int(cfg.get("volume", 100)),
        )
        tokens = voice.GetVoices()
        idx = -1
        want = str(cfg.get("voice", "") or "").strip().lower()
        gender = str(cfg.get("gender", "female") or "female").lower()

        if want:
            for i in range(tokens.Count):
                desc = tokens.Item(i).GetDescription()
                if want == desc.lower() or want in desc.lower():
                    idx = i
                    break
        if idx < 0:
            for i in range(tokens.Count):
                try:
                    g = (tokens.Item(i).GetAttribute("Gender") or "").lower()
                except Exception:
                    g = ""
                if gender.startswith("f") and g.startswith("f"):
                    idx = i
                    break
                if gender.startswith("m") and g.startswith("m"):
                    idx = i
                    break
        if idx < 0 and tokens.Count > 0:
            idx = 0
        try:
            if idx >= 0:
                voice.Voice = tokens.Item(idx)
        except Exception as exc:
            log_error("TTS set voice: " + str(exc))
        try:
            voice.Rate = max(-10, min(10, int(cfg.get("rate", 0))))
        except Exception:
            pass
        try:
            voice.Volume = max(0, min(100, int(cfg.get("volume", 100))))
        except Exception:
            pass
        return key

    def _worker(self):
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        try:
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
        except Exception as exc:
            self.log("TTS tidak bisa dimulai: %s" % exc)
            return

        applied = None
        while not self._stop.is_set():
            try:
                cmd, payload = self.queue.get(timeout=0.5)
            except queue.Empty:
                cmd, payload = None, None

            try:
                if cmd == "quit":
                    break
                if cmd == "purge":
                    try:
                        voice.Speak("", 2)  # purge antrean SAPI
                    except Exception:
                        pass
                    continue
                if cmd == "say":
                    cfg = dict(self.settings)
                    applied = self._apply_voice(voice, cfg)
                    voice.Speak(payload, 0)
                    continue

                # timeout: cek sapaan otomatis
                if self.running.is_set():
                    w = dict(self.welcome)
                    if w.get("enabled") and w.get("text"):
                        interval = max(3.0, float(w.get("interval", 15.0)))
                        now = time.time()
                        if now - self._last_welcome >= interval:
                            self._last_welcome = now
                            self._apply_voice(voice, dict(self.settings))
                            voice.Speak(w["text"], 0)
            except Exception as exc:
                log_error("TTS worker: " + str(exc))

        try:
            voice.Speak("", 2)
        except Exception:
            pass
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass


# ============================================================================
# Pemilih area dengan drag di layar
# ============================================================================
class RegionSelector(tk.Toplevel):
    def __init__(self, master, on_done):
        super().__init__(master)
        self.on_done = on_done
        self.start = None
        self.rect_id = None
        self.cancelled = False

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.28)
        except Exception:
            pass
        self.geometry("%dx%d+0+0" % (
            self.winfo_screenwidth(), self.winfo_screenheight()
        ))
        self.configure(bg="black", cursor="crosshair")

        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", self._on_cancel)
        self.focus_force()
        self.grab_set()

        self.canvas.create_text(
            20, 20, anchor="nw", fill="white",
            font=("Segoe UI", 14, "bold"),
            text="Tarik mouse untuk memilih area. ESC untuk batal.",
        )

    def _on_press(self, event):
        self.start = (event.x_root, event.y_root)
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#00ff88", width=3,
        )

    def _on_drag(self, event):
        if not self.start or not self.rect_id:
            return
        x0 = self.start[0]
        y0 = self.start[1]
        self.canvas.coords(
            self.rect_id,
            x0, y0, event.x_root, event.y_root,
        )

    def _on_release(self, event):
        if not self.start:
            self.destroy()
            return
        x0, y0 = self.start
        x1, y1 = event.x_root, event.y_root
        left, top = min(x0, x1), min(y0, y1)
        w, h = abs(x1 - x0), abs(y1 - y0)
        self.destroy()
        if w < 8 or h < 8:
            self.on_done(None)
        else:
            self.on_done((int(left), int(top), int(w), int(h)))

    def _on_cancel(self, _event=None):
        self.cancelled = True
        self.destroy()
        self.on_done(None)


# ============================================================================
# Dialog tambah/edit aturan gift
# ============================================================================
class RuleDialog(tk.Toplevel):
    def __init__(self, master, app, rule, on_save, title="Gift"):
        super().__init__(master)
        self.app = app
        self.on_save = on_save
        self.path = rule.get("template_path", "")
        self.template = None
        self._photo = None

        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        try:
            self.grab_set()
        except Exception:
            pass

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)

        self.var_enabled = tk.BooleanVar(value=bool(rule.get("enabled", True)))
        ttk.Checkbutton(
            body, text="Aktif (rule ini dipakai saat MULAI)",
            variable=self.var_enabled,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Label(body, text="Nama gift (validasi + ucapan):").grid(
            row=1, column=0, sticky="w", pady=4)
        self.var_name = tk.StringVar(value=rule.get("name", ""))
        ttk.Entry(body, textvariable=self.var_name, width=42).grid(
            row=1, column=1, sticky="we", pady=4)
        ttk.Label(
            body, text="Contoh: Mawar. Boleh beberapa nama dipisah koma.",
            foreground="#777",
        ).grid(row=2, column=1, sticky="w")

        ttk.Label(body, text="Tombol keyboard:").grid(
            row=3, column=0, sticky="w", pady=4)
        key = rule.get("key", "f1")
        self.var_key = tk.StringVar(value=key if key in VALID_KEYS else "f1")
        ttk.Combobox(
            body, textvariable=self.var_key, values=VALID_KEYS,
            state="readonly", width=8,
        ).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(body, text="Jumlah tekan:").grid(
            row=4, column=0, sticky="w", pady=4)
        mode_row = ttk.Frame(body)
        mode_row.grid(row=4, column=1, sticky="w", pady=4)
        self.var_mode = tk.StringVar(
            value="fixed" if rule.get("count_mode") == "fixed" else "ocr")
        ttk.Radiobutton(
            mode_row, text="Baca dari layar (OCR)", variable=self.var_mode,
            value="ocr", command=self._on_mode,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_row, text="Tetap", variable=self.var_mode,
            value="fixed", command=self._on_mode,
        ).pack(side="left", padx=(10, 4))
        self.var_fixed = tk.IntVar(value=max(1, int(rule.get("fixed_count", 1))))
        self.spin_fixed = ttk.Spinbox(
            mode_row, from_=1, to=999, textvariable=self.var_fixed, width=6)
        self.spin_fixed.pack(side="left")

        ttk.Label(body, text="Gambar gift (template):").grid(
            row=5, column=0, sticky="w", pady=(10, 4))
        file_row = ttk.Frame(body)
        file_row.grid(row=5, column=1, sticky="we", pady=(10, 4))
        self.var_path = tk.StringVar(value=self.path)
        ttk.Entry(file_row, textvariable=self.var_path, state="readonly").pack(
            side="left", fill="x", expand=True)
        ttk.Button(file_row, text="Pilih...", command=self._browse).pack(
            side="left", padx=(6, 0))

        self.preview = tk.Label(
            body, text="(belum ada gambar)", bg="#f2f2f2",
            width=30, height=8, relief="groove",
        )
        self.preview.grid(row=6, column=0, columnspan=2, pady=8)

        ttk.Label(
            body,
            text="Tips: crop HANYA ikon gift dari screenshot TikTok Studio.",
            foreground="#777",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 10))

        btns = ttk.Frame(body)
        btns.grid(row=8, column=0, columnspan=2)
        ttk.Button(btns, text="Simpan", command=self._save, width=14).pack(
            side="left", padx=6)
        ttk.Button(btns, text="Batal", command=self.destroy, width=10).pack(
            side="left", padx=6)

        body.columnconfigure(1, weight=1)

        if self.path:
            self.template = load_template(app._resolve_path(self.path))
        self._update_preview()
        self._on_mode()

        self.update_idletasks()
        try:
            x = master.winfo_rootx() + 60
            y = master.winfo_rooty() + 60
            self.geometry("+%d+%d" % (x, y))
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_mode(self):
        state = "normal" if self.var_mode.get() == "fixed" else "disabled"
        self.spin_fixed.configure(state=state)

    def _browse(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Pilih gambar template gift",
            filetypes=[("Gambar", "*.png *.jpg *.jpeg *.bmp"),
                       ("Semua file", "*.*")],
        )
        if not path:
            return
        tmpl = load_template(path)
        if tmpl is None:
            messagebox.showerror("Gagal", "Gambar tidak dapat dibaca.", parent=self)
            return
        self.path = path
        self.template = tmpl
        self.var_path.set(path)
        self._update_preview()

    def _update_preview(self):
        if not HAS_PIL or self.template is None:
            self.preview.configure(
                text="(preview tidak tersedia)" if not HAS_PIL else "(belum ada gambar)")
            return
        try:
            h, w = self.template.shape[:2]
            scale = min(220.0 / max(1, w), 150.0 / max(1, h), 1.0)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            small = cv2.resize(self.template, (nw, nh), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.preview.configure(image=self._photo, text="",
                                   width=nw, height=nh)
        except Exception as exc:
            log_error("rule preview: " + str(exc))

    def _save(self):
        if not self.path or not os.path.exists(self.app._resolve_path(self.path)):
            messagebox.showerror(
                "Gambar belum dipilih",
                "Pilih gambar template gift terlebih dahulu.", parent=self)
            return
        if self.template is None:
            messagebox.showerror(
                "Gambar tidak valid",
                "File gambar tidak bisa dibaca. Pilih file lain.", parent=self)
            return
        rule = {
            "name": self.var_name.get().strip(),
            "template_path": self.path,
            "key": self.var_key.get() if self.var_key.get() in VALID_KEYS else "f1",
            "count_mode": "fixed" if self.var_mode.get() == "fixed" else "ocr",
            "fixed_count": max(1, int(self.var_fixed.get() or 1)),
            "enabled": bool(self.var_enabled.get()),
        }
        self.on_save(rule)
        self.destroy()


# ============================================================================
# Aplikasi utama
# ============================================================================
class GiftTriggerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GiftTrigger - TikTok Live (Lokal)")
        self.root.geometry("880x860")
        self.root.minsize(780, 720)

        self.config = dict(DEFAULT_CONFIG)
        self.config["rules"] = []
        self._load_config()

        self.running = False
        self.stop_event = threading.Event()
        self.worker = None
        self.ui_queue = queue.Queue()

        self.tts = SapiTTS(self._log)
        self.voice_descriptions = []

        self._build_ui()
        self._apply_config_to_ui()
        self._register_hotkeys()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._poll_ui)

    # ----------------------------- konfigurasi -----------------------------
    def _normalize_rule(self, rule):
        out = dict(RULE_DEFAULTS)
        if isinstance(rule, dict):
            for k, v in RULE_DEFAULTS.items():
                out[k] = rule.get(k, v)
        out["enabled"] = bool(out.get("enabled", True))
        out["key"] = out["key"] if out.get("key") in VALID_KEYS else "f1"
        out["count_mode"] = "fixed" if out.get("count_mode") == "fixed" else "ocr"
        try:
            out["fixed_count"] = max(1, int(out.get("fixed_count", 1)))
        except Exception:
            out["fixed_count"] = 1
        out["name"] = str(out.get("name", "") or "")
        out["template_path"] = str(out.get("template_path", "") or "")
        return out

    def _load_config(self):
        data = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:
                log_error("load config: " + str(exc))
                data = {}

        for k, v in DEFAULT_CONFIG.items():
            if k == "rules":
                continue
            self.config[k] = data.get(k, v)

        rules = data.get("rules")
        if isinstance(rules, list):
            self.config["rules"] = [self._normalize_rule(r) for r in rules]
        else:
            self.config["rules"] = []
            # Migrasi dari versi lama (satu template / satu tombol).
            old_tmpl = data.get("template_path", "")
            if old_tmpl:
                names = expected_name_list(data.get("expected_names", ""))
                self.config["rules"] = [self._normalize_rule({
                    "name": names[0] if names else "",
                    "template_path": old_tmpl,
                    "key": data.get("key_to_press", "f1"),
                    "count_mode": data.get("count_mode", "ocr"),
                    "fixed_count": data.get("fixed_count", 1),
                    "enabled": True,
                })]

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as exc:
            log_error("save config: " + str(exc))

    def _resolve_path(self, path):
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        return os.path.join(APP_DIR, path)

    # -------------------------------- UI -----------------------------------
    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="GiftTrigger", font=("Segoe UI", 18, "bold")).pack(
            side="left")
        ttk.Label(
            head, text="  deteksi gift di layar, banyak tombol, suara ucapan",
            foreground="#666",
        ).pack(side="left", pady=(6, 0))
        ttk.Label(
            head, text="100% lokal, tanpa API", foreground="#2e7d32",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="right", pady=(6, 0))

        self.nb = ttk.Notebook(outer)
        self.nb.pack(fill="both", expand=True, pady=(8, 6))

        self._build_tab_rules(self.nb)
        self._build_tab_detect(self.nb)
        self._build_tab_voice(self.nb)
        self._build_tab_log(self.nb)

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x")
        self.lbl_status = ttk.Label(
            bottom, text="Siap", foreground="#1565c0",
            font=("Segoe UI", 10, "bold"))
        self.lbl_status.pack(side="left")
        ttk.Label(
            bottom, text="   Ctrl+Alt+S = stop   |   Ctrl+Alt+Q = keluar",
            foreground="#777",
        ).pack(side="left")
        self.btn_start = ttk.Button(bottom, text="MULAI", command=self._toggle_run)
        self.btn_start.pack(side="right", ipadx=26, ipady=6)

    # --------------------------- tab 1: rules ------------------------------
    def _build_tab_rules(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="  Gift & Tombol  ")

        ttk.Label(
            tab,
            text="Setiap gift punya gambar, tombol, dan jumlah tekan sendiri. "
                 "Tambahkan satu baris untuk setiap gift.",
            foreground="#555",
        ).pack(anchor="w", pady=(0, 6))

        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Button(bar, text="+ Tambah Gift", command=self._add_rule).pack(
            side="left")
        ttk.Button(bar, text="Edit", command=self._edit_rule).pack(
            side="left", padx=4)
        ttk.Button(bar, text="Hapus", command=self._delete_rule).pack(side="left")
        ttk.Button(bar, text="Naik", command=lambda: self._move_rule(-1)).pack(
            side="left", padx=(16, 2))
        ttk.Button(bar, text="Turun", command=lambda: self._move_rule(1)).pack(
            side="left")
        ttk.Button(bar, text="Test Gift Ini",
                   command=self._test_selected_rule).pack(side="right")

        wrap = ttk.Frame(tab)
        wrap.pack(fill="both", expand=True, pady=8)
        cols = ("aktif", "nama", "tombol", "jumlah", "gambar")
        self.tree = ttk.Treeview(
            wrap, columns=cols, show="headings", height=14, selectmode="browse")
        headings = {
            "aktif": "Aktif", "nama": "Nama Gift", "tombol": "Tombol",
            "jumlah": "Jumlah", "gambar": "Template",
        }
        widths = {
            "aktif": 60, "nama": 210, "tombol": 80, "jumlah": 140, "gambar": 300,
        }
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(
                c, width=widths[c],
                anchor="w" if c in ("nama", "gambar") else "center",
                stretch=(c in ("nama", "gambar")),
            )
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("off", foreground="#999")
        self.tree.bind("<Double-1>", lambda e: self._edit_rule())

        ttk.Label(
            tab,
            text="Tips: klik dua kali untuk mengubah. Gunakan \"Test Gift Ini\" "
                 "untuk memastikan gambar gift terbaca.",
            foreground="#777",
        ).pack(anchor="w")

    # -------------------------- tab 2: deteksi -----------------------------
    def _build_tab_detect(self, nb):
        tab = ttk.Frame(nb, padding=12)
        nb.add(tab, text="  Deteksi  ")

        area = ttk.LabelFrame(tab, text="1. Area yang dipantau")
        area.pack(fill="x", pady=(0, 8))

        self.var_fullscreen = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            area, text="Pantau seluruh layar (paling mudah)",
            variable=self.var_fullscreen,
            command=self._on_fullscreen_toggle,
        ).pack(anchor="w", padx=10, pady=(8, 4))

        row = ttk.Frame(area)
        row.pack(fill="x", padx=10, pady=2)
        self.btn_pick_gift_region = ttk.Button(
            row, text="Pilih Area Gift...", command=self._pick_gift_region)
        self.btn_pick_gift_region.pack(side="left")
        self.lbl_gift_region = ttk.Label(row, text="Layar penuh")
        self.lbl_gift_region.pack(side="left", padx=10)

        row = ttk.Frame(area)
        row.pack(fill="x", padx=10, pady=(2, 10))
        ttk.Button(
            row, text="Pilih Area Teks/Username (opsional)...",
            command=self._pick_ocr_region,
        ).pack(side="left")
        self.lbl_ocr_region = ttk.Label(
            row, text="Otomatis di sekitar gift", foreground="#666")
        self.lbl_ocr_region.pack(side="left", padx=10)

        match = ttk.LabelFrame(tab, text="2. Pencocokan gambar")
        match.pack(fill="x", pady=8)

        row = ttk.Frame(match)
        row.pack(fill="x", padx=10, pady=(10, 2))
        ttk.Label(row, text="Cocok minimal (0.50 - 0.99):").pack(side="left")
        self.var_threshold = tk.DoubleVar(value=0.82)
        self.scale_threshold = ttk.Scale(
            row, from_=0.50, to=0.99, variable=self.var_threshold,
            command=self._on_threshold_change, length=260)
        self.scale_threshold.pack(side="left", padx=8)
        self.lbl_threshold = ttk.Label(row, text="0.82")
        self.lbl_threshold.pack(side="left")

        row = ttk.Frame(match)
        row.pack(fill="x", padx=10, pady=2)
        ttk.Label(row, text="Konfirmasi (frame):").pack(side="left")
        self.var_confirm = tk.IntVar(value=2)
        ttk.Spinbox(row, from_=1, to=10, width=6,
                    textvariable=self.var_confirm).pack(side="left", padx=(6, 18))
        self.var_once = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row, text="Trigger sekali per kemunculan gift",
            variable=self.var_once,
        ).pack(side="left")

        row = ttk.Frame(match)
        row.pack(fill="x", padx=10, pady=(2, 10))
        ttk.Button(row, text="Test Deteksi Semua Gift",
                   command=self._test_detection).pack(side="left")

        speed = ttk.LabelFrame(tab, text="3. Kecepatan & jendela target")
        speed.pack(fill="x", pady=8)

        row = ttk.Frame(speed)
        row.pack(fill="x", padx=10, pady=(10, 2))
        ttk.Label(row, text="Jeda antar tekan (ms):").pack(side="left")
        self.var_delay = tk.IntVar(value=80)
        ttk.Spinbox(row, from_=0, to=1000, increment=10, width=7,
                    textvariable=self.var_delay).pack(side="left", padx=(6, 24))
        ttk.Label(row, text="Jeda antar trigger (detik):").pack(side="left")
        self.var_cooldown = tk.DoubleVar(value=1.5)
        ttk.Spinbox(row, from_=0.2, to=60.0, increment=0.1, width=7,
                    textvariable=self.var_cooldown).pack(side="left", padx=6)

        row = ttk.Frame(speed)
        row.pack(fill="x", padx=10, pady=(6, 2))
        ttk.Label(row, text="Fokus jendela (judul, opsional):").pack(side="left")
        self.var_target_window = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.var_target_window, width=28).pack(
            side="left", padx=6)

        ttk.Label(
            speed,
            text="Contoh: TikTok. Saat MULAI, aplikasi meminimalkan diri dan "
                 "memfokuskan jendela ini agar tombol diterima.",
            foreground="#666",
        ).pack(anchor="w", padx=10, pady=(0, 10))

    # --------------------------- tab 3: suara ------------------------------
    def _build_tab_voice(self, nb):
        tab = ttk.Frame(nb, padding=12)
        nb.add(tab, text="  Suara & Ucapan  ")

        snd = ttk.LabelFrame(tab, text="1. Suara saat gift terdeteksi")
        snd.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(snd)
        row.pack(fill="x", padx=10, pady=(8, 2))
        self.var_sound_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Aktifkan suara file",
                        variable=self.var_sound_enabled).pack(side="left")

        row = ttk.Frame(snd)
        row.pack(fill="x", padx=10, pady=(4, 10))
        ttk.Label(row, text="File WAV:").pack(side="left")
        self.var_sound = tk.StringVar(value="success.wav")
        ttk.Entry(row, textvariable=self.var_sound, width=44).pack(
            side="left", padx=6)
        ttk.Button(row, text="...", width=3,
                   command=self._browse_sound).pack(side="left")
        ttk.Button(row, text="Test", command=self._test_sound).pack(
            side="left", padx=(6, 0))

        tts = ttk.LabelFrame(tab, text="2. Suara ucapan (TTS lokal, pria/wanita)")
        tts.pack(fill="both", expand=True, pady=8)

        row = ttk.Frame(tts)
        row.pack(fill="x", padx=10, pady=(8, 4))
        self.var_tts_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Aktifkan ucapan",
                        variable=self.var_tts_enabled,
                        command=self._on_tts_toggle).pack(side="left")
        ttk.Label(row, text="   Jenis suara:").pack(side="left")
        self.var_tts_gender = tk.StringVar(value="female")
        ttk.Radiobutton(row, text="Wanita", variable=self.var_tts_gender,
                        value="female").pack(side="left", padx=(6, 0))
        ttk.Radiobutton(row, text="Pria", variable=self.var_tts_gender,
                        value="male").pack(side="left", padx=(6, 0))

        row = ttk.Frame(tts)
        row.pack(fill="x", padx=10, pady=4)
        ttk.Label(row, text="Suara terpasang:").pack(side="left")
        self.var_voice = tk.StringVar(value="Otomatis (sesuai jenis suara)")
        self.cmb_voice = ttk.Combobox(row, textvariable=self.var_voice,
                                      state="readonly", width=46)
        self.cmb_voice.pack(side="left", padx=6)
        ttk.Button(row, text="Muat ulang", command=self._reload_voices).pack(
            side="left")

        row = ttk.Frame(tts)
        row.pack(fill="x", padx=10, pady=4)
        ttk.Label(row, text="Kecepatan:").pack(side="left")
        self.var_tts_rate = tk.DoubleVar(value=0)
        ttk.Scale(row, from_=-5, to=5, variable=self.var_tts_rate, length=150,
                  command=lambda v: self.lbl_rate.configure(
                      text="%+d" % int(round(float(v))))).pack(
            side="left", padx=6)
        self.lbl_rate = ttk.Label(row, text="+0")
        self.lbl_rate.pack(side="left")
        ttk.Label(row, text="   Volume:").pack(side="left", padx=(16, 0))
        self.var_tts_volume = tk.DoubleVar(value=100)
        ttk.Scale(row, from_=0, to=100, variable=self.var_tts_volume, length=150,
                  command=lambda v: self.lbl_volume.configure(
                      text="%d" % int(round(float(v))))).pack(
            side="left", padx=6)
        self.lbl_volume = ttk.Label(row, text="100")
        self.lbl_volume.pack(side="left")

        row = ttk.Frame(tts)
        row.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(row, text="Kalimat saat gift:").pack(side="left")
        self.var_tts_text = tk.StringVar(
            value="Thank you {username} for your {gift}")
        ttk.Entry(row, textvariable=self.var_tts_text).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Test", command=self._test_tts).pack(side="left")

        ttk.Label(
            tts,
            text="Placeholder: {username} = nama pengirim, {gift} = nama gift, "
                 "{count} = jumlah. Contoh: Thank you {username} for your {gift}",
            foreground="#666",
        ).pack(anchor="w", padx=10, pady=(0, 8))

        welcome = ttk.LabelFrame(tab, text="3. Sapaan otomatis")
        welcome.pack(fill="x", pady=(0, 4))

        row = ttk.Frame(welcome)
        row.pack(fill="x", padx=10, pady=(8, 2))
        self.var_welcome_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row, text="Ucapkan sapaan berkala saat MULAI",
            variable=self.var_welcome_enabled,
        ).pack(side="left")
        ttk.Label(row, text="   Setiap (detik):").pack(side="left", padx=(16, 0))
        self.var_welcome_interval = tk.DoubleVar(value=15.0)
        ttk.Spinbox(row, from_=3, to=600, increment=1, width=7,
                    textvariable=self.var_welcome_interval).pack(
            side="left", padx=6)

        row = ttk.Frame(welcome)
        row.pack(fill="x", padx=10, pady=(4, 10))
        ttk.Label(row, text="Kalimat sapaan:").pack(side="left")
        self.var_welcome_text = tk.StringVar(value="Welcome to the stream")
        ttk.Entry(row, textvariable=self.var_welcome_text).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Test", command=self._test_welcome).pack(side="left")

        if not HAS_TTS:
            ttk.Label(
                tab,
                text="TTS tidak tersedia. Jalankan install.bat untuk memasang "
                     "paket comtypes.",
                foreground="#a00",
            ).pack(anchor="w", pady=(6, 0))

    # ---------------------------- tab 4: log -------------------------------
    def _build_tab_log(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="  Log  ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(
            bar, text="Catatan kejadian: deteksi, OCR, tombol, ucapan.",
            foreground="#555",
        ).pack(side="left")
        ttk.Button(bar, text="Bersihkan", command=self._clear_log).pack(
            side="right")

        wrap = ttk.Frame(tab)
        wrap.pack(fill="both", expand=True)
        self.txt_log = tk.Text(
            wrap, height=18, wrap="word", state="disabled",
            font=("Consolas", 9))
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.txt_log.yview)
        sb.pack(side="right", fill="y")
        self.txt_log.configure(yscrollcommand=sb.set)

    # ------------------------- terapkan konfigurasi ------------------------
    def _apply_config_to_ui(self):
        c = self.config
        self.var_fullscreen.set(bool(c.get("use_fullscreen", True)))
        self.var_threshold.set(float(c.get("threshold", 0.82)))
        self.lbl_threshold.configure(text="%.2f" % float(c.get("threshold", 0.82)))
        self.var_confirm.set(int(c.get("confirm_frames", 2)))
        self.var_once.set(bool(c.get("once_per_appearance", True)))
        self.var_delay.set(int(c.get("press_delay_ms", 80)))
        self.var_cooldown.set(float(c.get("cooldown_s", 1.5)))
        self.var_target_window.set(c.get("target_window", ""))

        self.var_sound_enabled.set(bool(c.get("sound_enabled", True)))
        self.var_sound.set(c.get("sound_file", "success.wav"))

        self.var_tts_enabled.set(bool(c.get("tts_enabled", True)))
        gender = c.get("tts_gender", "female")
        self.var_tts_gender.set("male" if gender == "male" else "female")
        self.var_tts_rate.set(float(c.get("tts_rate", 0)))
        self.var_tts_volume.set(float(c.get("tts_volume", 100)))
        self.lbl_rate.configure(text="%+d" % int(round(float(c.get("tts_rate", 0)))))
        self.lbl_volume.configure(text="%d" % int(round(float(c.get("tts_volume", 100)))))
        self.var_tts_text.set(c.get("tts_gift_text", "Thank you {username} for your {gift}"))

        self.var_welcome_enabled.set(bool(c.get("welcome_enabled", True)))
        self.var_welcome_interval.set(float(c.get("welcome_interval", 15.0)))
        self.var_welcome_text.set(c.get("welcome_text", "Welcome to the stream"))

        self._reload_voices()
        self._on_tts_toggle()
        self._refresh_rules_tree()
        self._update_region_labels()
        self._on_fullscreen_toggle()

    def _reload_voices(self):
        self.voice_descriptions = [v["desc"] for v in SapiTTS.list_voices()]
        values = ["Otomatis (sesuai jenis suara)"] + self.voice_descriptions
        self.cmb_voice.configure(values=values)
        current = self.config.get("tts_voice", "")
        if current and current in self.voice_descriptions:
            self.var_voice.set(current)
        else:
            self.var_voice.set(values[0])

    def _selected_voice_desc(self):
        v = self.var_voice.get()
        if not v or v.startswith("Otomatis"):
            return ""
        return v

    def _on_tts_toggle(self):
        state = "normal" if self.var_tts_enabled.get() else "disabled"
        for w in (self.cmb_voice,):
            try:
                w.configure(state=state if state == "disabled" else "readonly")
            except Exception:
                pass

    def _on_threshold_change(self, _value=None):
        try:
            self.lbl_threshold.configure(text="%.2f" % float(self.var_threshold.get()))
        except Exception:
            pass

    def _on_fullscreen_toggle(self):
        full = bool(self.var_fullscreen.get())
        state = "disabled" if full else "normal"
        self.btn_pick_gift_region.configure(state=state)
        if full:
            self.lbl_gift_region.configure(text="Layar penuh")
        else:
            self._update_region_labels()

    def _update_region_labels(self):
        g = self.config.get("gift_region")
        if self.config.get("use_fullscreen", True) or not g:
            self.lbl_gift_region.configure(text="Layar penuh")
        else:
            self.lbl_gift_region.configure(
                text="x=%d y=%d w=%d h=%d" % tuple(g))
        o = self.config.get("ocr_region")
        if not o:
            self.lbl_ocr_region.configure(
                text="Otomatis di sekitar gift", foreground="#666")
        else:
            self.lbl_ocr_region.configure(
                text="x=%d y=%d w=%d h=%d" % tuple(o), foreground="#333")

    # ------------------------------ log & status --------------------------
    def _log(self, message):
        self.ui_queue.put(("log", str(message)))

    def _set_status(self, text, color="#1565c0"):
        self.ui_queue.put(("status", text, color))

    def _append_log(self, message):
        try:
            self.txt_log.configure(state="normal")
            self.txt_log.insert(
                "end", time.strftime("[%H:%M:%S] ") + message + "\n")
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        except Exception:
            pass

    def _clear_log(self):
        try:
            self.txt_log.configure(state="normal")
            self.txt_log.delete("1.0", "end")
            self.txt_log.configure(state="disabled")
        except Exception:
            pass

    def _poll_ui(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append_log(item[1])
                elif kind == "status":
                    try:
                        self.lbl_status.configure(text=item[1], foreground=item[2])
                    except Exception:
                        pass
                elif kind == "stop":
                    self._stop_run(item[1])
                elif kind == "quit":
                    self._on_close()
                    return
        except queue.Empty:
            pass
        try:
            self.root.after(120, self._poll_ui)
        except Exception:
            pass

    # ----------------------------- aksi rules ------------------------------
    def _refresh_rules_tree(self):
        try:
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            for i, r in enumerate(self.config.get("rules", [])):
                if r.get("count_mode") == "ocr":
                    count_txt = "Dari layar (OCR)"
                else:
                    count_txt = "%dx tetap" % int(r.get("fixed_count", 1))
                tmpl = os.path.basename(r.get("template_path", "") or "-")
                self.tree.insert(
                    "", "end", iid=str(i),
                    values=(
                        "Ya" if r.get("enabled", True) else "Tidak",
                        r.get("name") or "(tanpa nama)",
                        str(r.get("key", "f1")).upper(),
                        count_txt,
                        tmpl,
                    ),
                    tags=() if r.get("enabled", True) else ("off",),
                )
        except Exception as exc:
            log_error("refresh tree: " + str(exc))

    def _selected_rule_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def _add_rule(self):
        rule = dict(RULE_DEFAULTS)
        rule["name"] = ""

        def save(new_rule):
            self.config.setdefault("rules", []).append(new_rule)
            self._refresh_rules_tree()
            self._save_config()
            self._log("Rule ditambahkan: %s -> %s" % (
                new_rule.get("name") or "(tanpa nama)",
                str(new_rule.get("key", "f1")).upper()))

        RuleDialog(self.root, self, rule, save, title="Tambah Gift")

    def _edit_rule(self):
        idx = self._selected_rule_index()
        if idx is None:
            messagebox.showinfo("Info", "Pilih salah satu gift di daftar dulu.")
            return
        rules = self.config.get("rules", [])
        if not (0 <= idx < len(rules)):
            return

        def save(new_rule):
            rules[idx] = new_rule
            self._refresh_rules_tree()
            self._save_config()
            self._log("Rule diperbarui: %s -> %s" % (
                new_rule.get("name") or "(tanpa nama)",
                str(new_rule.get("key", "f1")).upper()))

        RuleDialog(self.root, self, rules[idx], save,
                   title="Edit Gift: %s" % (rules[idx].get("name") or "tanpa nama"))

    def _delete_rule(self):
        idx = self._selected_rule_index()
        if idx is None:
            messagebox.showinfo("Info", "Pilih gift yang ingin dihapus.")
            return
        rules = self.config.get("rules", [])
        if not (0 <= idx < len(rules)):
            return
        name = rules[idx].get("name") or "(tanpa nama)"
        if not messagebox.askyesno("Hapus", "Hapus rule gift '%s'?" % name):
            return
        rules.pop(idx)
        self._refresh_rules_tree()
        self._save_config()
        self._log("Rule dihapus: %s" % name)

    def _move_rule(self, delta):
        idx = self._selected_rule_index()
        if idx is None:
            return
        rules = self.config.get("rules", [])
        new_idx = idx + delta
        if not (0 <= new_idx < len(rules)):
            return
        rules[idx], rules[new_idx] = rules[new_idx], rules[idx]
        self._refresh_rules_tree()
        try:
            self.tree.selection_set(str(new_idx))
            self.tree.focus(str(new_idx))
        except Exception:
            pass
        self._save_config()

    def _test_selected_rule(self):
        idx = self._selected_rule_index()
        if idx is None:
            self._test_detection()
        else:
            self._test_detection(rule_index=idx)

    # --------------------------- aksi area/suara ---------------------------
    def _pick_gift_region(self):
        self._pick_region("gift_region", "Area gift")

    def _pick_ocr_region(self):
        self._pick_region("ocr_region", "Area teks/username")

    def _pick_region(self, key, label):
        self.root.withdraw()

        def done(region):
            self.root.deiconify()
            self.root.lift()
            if region:
                self.config[key] = list(region)
                self._update_region_labels()
                self._log("%s dipilih: %s" % (label, region))
                self._save_config()
            elif key == "ocr_region":
                self.config[key] = None
                self._update_region_labels()
                self._save_config()

        RegionSelector(self.root, done)

    def _browse_sound(self):
        path = filedialog.askopenfilename(
            title="Pilih file suara",
            filetypes=[("WAV", "*.wav"), ("Semua file", "*.*")],
        )
        if path:
            self.var_sound.set(path)

    def _test_sound(self):
        self._play_sound(self.var_sound.get(), test=True)

    def _play_sound(self, path, test=False):
        if not HAS_SOUND:
            if test:
                messagebox.showwarning("Suara", "winsound tidak tersedia.")
            return
        path = self._resolve_path(path)
        if not path or not os.path.exists(path):
            if test:
                messagebox.showwarning(
                    "Suara", "File tidak ditemukan:\n" + str(path))
            return
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as exc:
            if test:
                messagebox.showerror(
                    "Suara", "Gagal memutar (gunakan .wav):\n" + str(exc))

    # ------------------------------- TTS test ------------------------------
    def _apply_tts_settings(self):
        self.tts.configure(
            enabled=bool(self.var_tts_enabled.get()),
            gender=self.var_tts_gender.get(),
            voice=self._selected_voice_desc(),
            rate=int(round(self.var_tts_rate.get())),
            volume=int(round(self.var_tts_volume.get())),
        )
        self.tts.configure_welcome(
            enabled=bool(self.var_welcome_enabled.get()),
            interval=float(self.var_welcome_interval.get()),
            text=self.var_welcome_text.get(),
        )

    def _test_tts(self):
        if not HAS_TTS:
            messagebox.showwarning("TTS", "Paket comtypes tidak terpasang.")
            return
        self._apply_tts_settings()
        self.tts.configure(enabled=True)
        msg = build_tts_message(
            self.var_tts_text.get(), "Budi", "Mawar", 1)
        self.tts.say(msg)
        self._log("Test ucapan: " + msg)

    def _test_welcome(self):
        if not HAS_TTS:
            messagebox.showwarning("TTS", "Paket comtypes tidak terpasang.")
            return
        self._apply_tts_settings()
        self.tts.configure(enabled=True)
        text = self.var_welcome_text.get() or "Welcome to the stream"
        self.tts.say(text)
        self._log("Test sapaan: " + text)

    # --------------------------- test deteksi ------------------------------
    def _capture(self, sct, region):
        if region:
            x, y, w, h = region
            monitor = {"top": int(y), "left": int(x),
                       "width": int(w), "height": int(h)}
            shot = np.array(sct.grab(monitor))
        else:
            shot = np.array(sct.grab(sct.monitors[1]))
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    def _ocr_crop(self, screen, match_rect):
        """Ambil area sekitar hasil match, lebih lebar ke kanan (nama+jumlah)."""
        if match_rect is None:
            return None
        x, y, w, h = match_rect
        pad_left = int(w * 1.5)
        pad_right = int(w * 7.0)
        pad_top = int(h * 2.0)
        pad_bottom = int(h * 2.0)
        x0 = max(0, x - pad_left)
        y0 = max(0, y - pad_top)
        x1 = min(screen.shape[1], x + w + pad_right)
        y1 = min(screen.shape[0], y + h + pad_bottom)
        if x1 <= x0 or y1 <= y0:
            return None
        return screen[y0:y1, x0:x1].copy()

    def _ocr_image(self, sct, screen, match_rect):
        """Ambil gambar untuk OCR (area teks pilihan user, atau sekitar gift)."""
        configured = self.config.get("ocr_region")
        if configured:
            try:
                x, y, w, h = [int(v) for v in configured]
                monitor = {"top": y, "left": x,
                           "width": max(1, w), "height": max(1, h)}
                shot = np.array(sct.grab(monitor))
                return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
            except Exception as exc:
                log_error("ocr region grab: " + str(exc))
                return None
        return self._ocr_crop(screen, match_rect)

    def _test_detection(self, rule_index=None):
        if self.running:
            messagebox.showinfo("Info", "Hentikan trigger terlebih dahulu.")
            return

        rules = self.config.get("rules", [])
        if rule_index is not None:
            if not (0 <= rule_index < len(rules)):
                return
            targets = [(rule_index, rules[rule_index])]
        else:
            targets = [(i, r) for i, r in enumerate(rules) if r.get("enabled", True)]

        if not targets:
            messagebox.showerror(
                "Error", "Belum ada gift. Tambahkan dulu di tab 'Gift & Tombol'.")
            return

        try:
            threshold = float(self.var_threshold.get())
            region = None if self.var_fullscreen.get() else self._gift_region()
            if not self.var_fullscreen.get() and region is None:
                messagebox.showerror("Error", "Pilih area gift terlebih dahulu.")
                return

            with new_mss() as sct:
                screen = self._capture(sct, region)

            best = None
            for idx, rule in targets:
                path = self._resolve_path(rule.get("template_path", ""))
                tmpl = load_template(path)
                name = rule.get("name") or "(tanpa nama)"
                if tmpl is None:
                    self._log("Test [%s]: template tidak ditemukan (%s)" % (
                        name, path or "-"))
                    continue
                score, rect = find_gift(screen, tmpl)
                self._log("Test [%s]: skor=%.3f %s" % (
                    name, score, "COCOK" if score >= threshold else "tidak cocok"))
                if best is None or score > best[0]:
                    best = (score, rect, rule, name)

            if best is None:
                messagebox.showerror(
                    "Error", "Semua template gift tidak bisa dibaca.")
                return

            score, rect, rule, name = best
            ocr_text = ""
            if score >= threshold and rect:
                with new_mss() as sct:
                    crop = self._ocr_image(sct, screen, rect)
                if crop is not None:
                    ocr_text = _ocr_sync(crop, upscale=2)
                count = parse_count(ocr_text)
                name_ok, _matched = validate_name(ocr_text, rule.get("name", ""))
                username = guess_username(ocr_text, rule.get("name", ""))
                self._log(
                    "OCR [%s]: '%s' -> jumlah=%d, nama=%s, username='%s'" % (
                        name, ocr_text if ocr_text else "(kosong)", count,
                        "OK" if name_ok else "tidak cocok", username))

            self._show_debug_preview(
                screen, rect, score, threshold, "Test: " + name)
        except Exception as exc:
            log_error("test detection: " + traceback.format_exc())
            messagebox.showerror("Error", str(exc))

    def _gift_region(self):
        if self.var_fullscreen.get():
            return None
        region = self.config.get("gift_region")
        if not region:
            return None
        return tuple(int(v) for v in region)

    def _show_debug_preview(self, screen, rect, score, threshold, title="Preview"):
        if not HAS_PIL:
            return
        try:
            img = screen.copy()
            if rect:
                x, y, w, h = rect
                color = (0, 200, 0) if score >= threshold else (0, 0, 220)
                cv2.rectangle(img, (x, y), (x + w, y + h), color, 3)
                cv2.putText(img, "%.2f" % score, (x, max(18, y - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

            max_w, max_h = 920, 620
            h, w = img.shape[:2]
            scale = min(max_w / max(1, w), max_h / max(1, h), 1.0)
            if scale < 1.0:
                img = cv2.resize(img, (int(w * scale), int(h * scale)),
                                 interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            photo = ImageTk.PhotoImage(Image.fromarray(rgb))

            top = tk.Toplevel(self.root)
            top.title("%s - skor %.3f" % (title, score))
            top.attributes("-topmost", True)
            lbl = tk.Label(top, image=photo)
            lbl.image = photo
            lbl.pack()
            ttk.Label(
                top,
                text="Hijau = cocok (>= %.2f), Merah = belum cocok." % threshold,
            ).pack(pady=4)
        except Exception as exc:
            log_error("debug preview: " + str(exc))

    # ------------------------------- runner --------------------------------
    def _collect_settings(self):
        c = self.config
        c["use_fullscreen"] = bool(self.var_fullscreen.get())
        c["threshold"] = float(self.var_threshold.get())
        c["confirm_frames"] = max(1, int(self.var_confirm.get()))
        c["once_per_appearance"] = bool(self.var_once.get())
        c["press_delay_ms"] = max(0, int(self.var_delay.get()))
        c["cooldown_s"] = max(0.2, float(self.var_cooldown.get()))
        c["target_window"] = self.var_target_window.get().strip()

        c["sound_enabled"] = bool(self.var_sound_enabled.get())
        c["sound_file"] = self.var_sound.get()

        c["tts_enabled"] = bool(self.var_tts_enabled.get())
        c["tts_gender"] = self.var_tts_gender.get()
        c["tts_voice"] = self._selected_voice_desc()
        c["tts_rate"] = int(round(self.var_tts_rate.get()))
        c["tts_volume"] = int(round(self.var_tts_volume.get()))
        c["tts_gift_text"] = self.var_tts_text.get()
        c["welcome_enabled"] = bool(self.var_welcome_enabled.get())
        c["welcome_interval"] = float(self.var_welcome_interval.get())
        c["welcome_text"] = self.var_welcome_text.get()

    def _toggle_run(self):
        if self.running:
            self._stop_run("Dihentikan oleh pengguna")
            return

        rules = [r for r in self.config.get("rules", []) if r.get("enabled", True)]
        if not rules:
            messagebox.showerror(
                "Error", "Tambahkan minimal satu gift dan aktifkan rule-nya.")
            return
        missing = []
        for r in rules:
            path = self._resolve_path(r.get("template_path", ""))
            if not path or not os.path.exists(path):
                missing.append(r.get("name") or "(tanpa nama)")
        if missing:
            messagebox.showerror(
                "Error",
                "Template gift belum ada untuk: " + ", ".join(missing))
            return
        if not HAS_KEYBOARD:
            messagebox.showerror("Error", "Modul 'keyboard' tidak tersedia.")
            return
        if not self.var_fullscreen.get() and not self.config.get("gift_region"):
            messagebox.showerror("Error", "Pilih area gift terlebih dahulu.")
            return

        self._collect_settings()
        self._save_config()
        self._apply_tts_settings()

        self.running = True
        self.stop_event.clear()

        self.btn_start.configure(text="STOP")
        self._set_status("Berjalan...", "#c62828")
        self._log("Mulai memantau %d gift. Tekan STOP atau Ctrl+Alt+S untuk berhenti."
                  % len(rules))

        target = self.config.get("target_window", "").strip()
        if target:
            title = focus_window_by_title(target)
            if title:
                self._log("Fokus ke jendela: " + title)
            else:
                self._log("Jendela target tidak ditemukan: " + target)
        try:
            self.root.iconify()
        except Exception:
            pass

        if HAS_TTS and self.var_tts_enabled.get():
            self.tts.start_stream()

        self.worker = threading.Thread(target=self._run_loop, daemon=True)
        self.worker.start()

    def _stop_run(self, message="Berhenti"):
        if not self.running:
            return
        self.running = False
        self.stop_event.set()
        try:
            self.tts.stop_stream()
        except Exception:
            pass
        try:
            self.root.deiconify()
            self.root.lift()
        except Exception:
            pass
        try:
            self.btn_start.configure(text="MULAI")
        except Exception:
            pass
        self._set_status(message, "#c62828")
        self._log(message)

    def _run_loop(self):
        try:
            s = dict(self.config)
            threshold = float(s.get("threshold", 0.82))
            cooldown = max(0.2, float(s.get("cooldown_s", 1.5)))
            confirm = max(1, int(s.get("confirm_frames", 2)))
            delay_ms = max(0, int(s.get("press_delay_ms", 80)))
            once = bool(s.get("once_per_appearance", True))
            sound_enabled = bool(s.get("sound_enabled", True))
            sound_file = s.get("sound_file", "success.wav")
            tts_enabled = bool(s.get("tts_enabled", True))
            tts_template = s.get("tts_gift_text", "")
            region = None if s.get("use_fullscreen", True) else s.get("gift_region")

            items = []
            for rule in s.get("rules", []):
                if not rule.get("enabled", True):
                    continue
                name = rule.get("name") or "(tanpa nama)"
                path = self._resolve_path(rule.get("template_path", ""))
                tmpl = load_template(path)
                if tmpl is None:
                    self._log("Lewati rule '%s': template tidak ada (%s)" % (
                        name, path or "-"))
                    continue
                key = rule.get("key", "f1")
                if key not in VALID_KEYS:
                    key = "f1"
                items.append({
                    "name": rule.get("name", ""),
                    "template": tmpl,
                    "key": key,
                    "count_mode": rule.get("count_mode", "ocr"),
                    "fixed_count": max(1, int(rule.get("fixed_count", 1))),
                })

            if not items:
                self._log("Tidak ada rule aktif dengan template valid.")
                self.ui_queue.put(("stop", "Tidak ada rule aktif"))
                return

            state = [{"streak": 0, "armed": True, "disarm": 0, "last": 0.0}
                     for _ in items]
            last_any = 0.0

            with new_mss() as sct:
                while not self.stop_event.is_set():
                    screen = self._capture(sct, region)
                    now = time.time()
                    candidates = []

                    for i, item in enumerate(items):
                        st = state[i]
                        score, rect = find_gift(screen, item["template"])

                        if score >= threshold:
                            st["streak"] += 1
                        else:
                            st["streak"] = 0

                        if once and not st["armed"]:
                            if score < (threshold - 0.12):
                                st["disarm"] += 1
                            else:
                                st["disarm"] = 0
                            if st["disarm"] >= 4:
                                st["armed"] = True
                                st["disarm"] = 0
                                self._log(
                                    "Gift [%s] hilang, siap trigger lagi."
                                    % (item["name"] or "?"))

                        if score < threshold or st["streak"] < confirm:
                            continue
                        if once and not st["armed"]:
                            continue
                        if now - st["last"] < cooldown:
                            continue
                        if now - last_any < cooldown:
                            continue
                        candidates.append((score, i, rect))

                    if candidates:
                        candidates.sort(key=lambda x: x[0], reverse=True)
                        ocr_text = None
                        for score, i, rect in candidates:
                            item = items[i]
                            if ocr_text is None:
                                crop = self._ocr_image(sct, screen, rect)
                                ocr_text = (_ocr_sync(crop, upscale=2)
                                            if crop is not None else "")
                            ok, _matched = validate_name(
                                ocr_text, item["name"])
                            if not ok:
                                self._log(
                                    "Cocok [%s] skor %.2f tapi nama tidak sesuai. OCR: '%s'"
                                    % (item["name"] or "?", score, ocr_text))
                                continue

                            parsed = parse_count(ocr_text)
                            if item["count_mode"] == "ocr":
                                count = parsed if parsed > 0 else item["fixed_count"]
                            else:
                                count = item["fixed_count"]
                            count = max(1, min(count, 999))

                            self._fire(
                                item, count, delay_ms, sound_enabled,
                                sound_file, tts_enabled, tts_template,
                                score, ocr_text)

                            st = state[i]
                            st["last"] = time.time()
                            last_any = st["last"]
                            if once:
                                st["armed"] = False
                                st["disarm"] = 0
                            break

                    time.sleep(0.03)
        except Exception:
            log_error("runner: " + traceback.format_exc())
            self._log("Error pada runner (lihat error_log.txt).")
            self.ui_queue.put(("stop", "Error - berhenti"))

    def _fire(self, item, count, delay_ms, sound_enabled, sound_file,
              tts_enabled, tts_template, score, ocr_text):
        name = item["name"] or "(tanpa nama)"
        self._log("TRIGGER [%s] skor=%.2f jumlah=%d tombol=%s OCR='%s'" % (
            name, score, count, item["key"].upper(), ocr_text))
        try:
            for _ in range(count):
                if self.stop_event.is_set():
                    break
                keyboard.press_and_release(item["key"])
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)
        except Exception as exc:
            log_error("keyboard: " + str(exc))

        if sound_enabled:
            self._play_sound(sound_file)

        if tts_enabled:
            username = guess_username(ocr_text, item["name"])
            msg = build_tts_message(tts_template, username, item["name"], count)
            self.tts.say(msg)
            self._log("Ucapan: " + msg)

        self._set_status(
            "Trigger! [%s] %dx %s" % (name, count, item["key"].upper()),
            "#2e7d32")

    # ------------------------------ hotkeys --------------------------------
    def _register_hotkeys(self):
        if not HAS_KEYBOARD:
            return
        try:
            keyboard.add_hotkey(
                "ctrl+alt+s",
                lambda: self.ui_queue.put(("stop", "Dihentikan (hotkey)")))
            keyboard.add_hotkey(
                "ctrl+alt+q",
                lambda: self.ui_queue.put(("quit",)))
            self._log("Hotkey aktif: Ctrl+Alt+S = stop, Ctrl+Alt+Q = keluar.")
        except Exception as exc:
            log_error("hotkeys: " + str(exc))

    # ------------------------------- close ---------------------------------
    def _on_close(self):
        try:
            if not self.running:
                try:
                    self._collect_settings()
                except Exception:
                    pass
            self._save_config()
        except Exception:
            pass
        try:
            self.running = False
            self.stop_event.set()
            try:
                self.tts.stop_stream()
            except Exception:
                pass
            try:
                self.tts.shutdown()
            except Exception:
                pass
            if HAS_KEYBOARD:
                try:
                    keyboard.clear_all_hotkeys()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


# ============================================================================
# Self-test (berguna untuk memastikan EXE membawa semua komponen)
# ============================================================================
def run_selftest():
    lines = []

    def add(text):
        lines.append(str(text))

    try:
        add("has_ocr=%s" % HAS_OCR)
        add("ocr_error=%s" % OCR_IMPORT_ERROR)
        add("has_tts=%s" % HAS_TTS)
        add("tts_error=%s" % TTS_IMPORT_ERROR)
        add("has_keyboard=%s" % HAS_KEYBOARD)
        add("has_sound=%s" % HAS_SOUND)

        screen = np.full((600, 900, 3), 40, np.uint8)
        cv2.circle(screen, (300, 250), 35, (0, 0, 220), -1)
        cv2.circle(screen, (300, 250), 20, (0, 220, 220), -1)
        tmpl = screen[205:295, 255:345].copy()
        score, rect = find_gift(screen, tmpl)
        add("find_gift_score=%.3f rect=%s" % (score, rect))

        img = np.full((150, 720, 3), 20, np.uint8)
        cv2.putText(img, "budi123 sent Mawar x20", (15, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 4)
        txt = _ocr_sync(img, upscale=2)
        add("ocr_text=%s" % txt)
        add("parsed_count=%d" % parse_count(txt))
        add("name_ok=%s" % str(validate_name(txt, "Mawar")[0]))
        add("username=%s" % guess_username(txt, "Mawar"))
        add("tts_message=%s" % build_tts_message(
            "Thank you {username} for your {gift}", "budi123", "Mawar", 20))

        voices = SapiTTS.list_voices()
        add("voice_count=%d" % len(voices))
        for v in voices:
            add("voice: %s (%s)" % (v["desc"], v["gender"]))
    except Exception:
        add("EXCEPTION\n" + traceback.format_exc())

    try:
        with open(os.path.join(APP_DIR, "selftest_result.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def main():
    if "--selftest" in sys.argv:
        run_selftest()
        return
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    GiftTriggerApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error("fatal: " + traceback.format_exc())
        try:
            messagebox.showerror("Error Fatal", traceback.format_exc())
        except Exception:
            pass
