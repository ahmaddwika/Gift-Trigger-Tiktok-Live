GIFTTRIGGER - TRIGGER GIFT TIKTOK LIVE (LOKAL, TANPA API)
========================================================

Aplikasi Windows untuk memantau layar TikTok Live Studio, mendeteksi BANYAK
gift sekaligus, lalu otomatis menekan tombol keyboard (F1-F10) sesuai gift
masing-masing, memutar suara, dan mengucapkan terima kasih dengan suara lokal
(pria/wanita). Bisa juga mengucapkan sapaan "Welcome to the stream" setiap
N detik. Semua berjalan lokal di komputer (tanpa API/internet).


FITUR UTAMA
-----------
- Multi gift: setiap gift punya gambar, tombol, dan jumlah tekan sendiri.
- Deteksi nama gift + jumlah kirim (mis. "Mawar x20") lewat OCR Windows.
- TTS lokal: "Thank you <username> for your <gift>" (suara pria/wanita).
- Sapaan otomatis berkala, default setiap 15 detik.
- Pilih area pantau (layar penuh atau kotak tertentu).
- Test deteksi + preview sebelum mulai.
- Fokus otomatis ke jendela TikTok saat MULAI.
- Hotkey stop/keluar.
- Konfigurasi tersimpan otomatis di config.json.


KEBUTUHAN
---------
- Windows 10 atau Windows 11 (64-bit).
- Python 3.10 - 3.13 (https://www.python.org/downloads/).
  Saat instal Python, centang "Add Python to PATH".
- OCR Windows: Settings > Time & Language > Language > tambahkan English
  (US/UK) beserta opsi "Optical character recognition".
- Suara TTS: suara bawaan Windows (mis. Microsoft Zira = wanita,
  Microsoft David = pria). Jika belum ada, buka Settings > Time & Language >
  Speech > Add voices.
- (Disarankan) jalankan tanpa mode admin.


INSTALASI (sekali saja)
-----------------------
1. Buka folder ini.
2. Klik dua kali: install.bat
3. Tunggu sampai selesai.


MENJALANKAN
-----------
- Klik dua kali: run.bat
- Atau lewat CMD:  python GiftTrigger.py

Aplikasi harus tetap terbuka saat live. Minimize boleh.


PANDUAN CEPAT
-------------
1. Tambahkan gift di tab "Gift & Tombol".
2. Atur area pantau di tab "Deteksi".
3. Atur suara & ucapan di tab "Suara & Ucapan".
4. Klik "Test Deteksi Semua Gift".
5. Klik MULAI.


TAB 1: GIFT & TOMBOL
--------------------
Setiap baris = satu gift.

- "+ Tambah Gift" : membuat rule baru.
- Edit / klik dua kali : mengubah rule.
- Hapus : menghapus rule.
- Naik / Turun : mengubah prioritas (yang atas dicek lebih dulu).
- Test Gift Ini : menguji satu gift saja.

Isi rule:
- Nama gift : untuk validasi kedua + diucapkan TTS.
  Boleh beberapa nama dipisah koma, mis. "Mawar, Rose".
  Jika dikosongkan, validasi nama dilewati.
- Tombol : F1 sampai F10.
- Jumlah tekan :
    * "Baca dari layar (OCR)" = membaca mis. "Mawar x20" lalu menekan 20x.
      Jika angka tidak terbaca, memakai jumlah tetap di sebelahnya.
    * "Tetap" = selalu menekan sejumlah angka yang diisi.
- Gambar gift : crop HANYA ikon gift dari screenshot TikTok Studio.
  Gunakan Snipping Tool (Win+Shift+S), simpan PNG/JPG, lalu "Pilih...".
- Aktif : rule dipakai saat MULAI.

Tips gambar: crop rapi dari layar (bukan gambar transparan), ukuran ikon
kurang lebih 40-120 piksel. Hindari bagian yang beranimasi/berubah.


TAB 2: DETEKSI
--------------
Area yang dipantau:
- "Pantau seluruh layar" : paling mudah, sedikit lebih berat.
- Hilangkan centang lalu "Pilih Area Gift..." untuk membatasi area
  tempat gift muncul (lebih cepat dan akurat).
- "Pilih Area Teks/Username (opsional)" : tarik kotak yang mencakup
  nama pengirim + nama gift + "x20". Ini dipakai untuk membaca jumlah
  dan username. Jika dibiarkan, aplikasi otomatis membaca di sekitar ikon.

Pencocokan:
- Cocok minimal (0.50-0.99) : naikkan bila sering salah deteksi,
  turunkan bila gift tidak terdeteksi. Gunakan Test Deteksi untuk melihat skor.
- Konfirmasi (frame) : jumlah frame berturut-turut yang harus cocok.
- "Trigger sekali per kemunculan gift" : setelah trigger, gift harus hilang
  dulu sebelum bisa trigger lagi. Jika dimatikan, trigger berulang setiap
  jeda selama gift masih tampak.

Kecepatan:
- Jeda antar tekan (ms) : 80 ms default. Naikkan bila aplikasi target
  melewatkan sebagian tekanan.
- Jeda antar trigger (detik) : minimal 1.5 detik.
- Fokus jendela : isi judul jendela target, mis. "TikTok". Saat MULAI,
  aplikasi meminimalkan diri dan memfokuskan jendela tersebut agar tombol
  diterima. Kosongkan bila tidak perlu.


TAB 3: SUARA & UCAPAN
---------------------
1. Suara file
   - Centang "Aktifkan suara file", pilih WAV (default success.wav).
   - Klik Test untuk mencoba.

2. Suara ucapan (TTS lokal)
   - Centang "Aktifkan ucapan".
   - Jenis suara: Wanita / Pria.
   - Suara terpasang: pilih otomatis atau suara spesifik.
     Klik "Muat ulang" setelah menambah suara di Windows.
   - Kecepatan dan volume bisa diatur.
   - Kalimat saat gift, contoh:
       Thank you {username} for your {gift}
     Placeholder:
       {username} = nama pengirim hasil OCR
       {gift}     = nama gift dari rule
       {count}    = jumlah kirim
     Jika username tidak terbaca, kalimat menjadi
       "Thank you for your Mawar".
   - Klik Test untuk mendengar contoh.

3. Sapaan otomatis
   - Centang "Ucapkan sapaan berkala saat MULAI".
   - Setiap (detik): default 15.
   - Kalimat sapaan: default "Welcome to the stream".
   - Sapaan pertama langsung diucapkan saat MULAI, lalu setiap N detik.
   - Klik Test untuk mencoba kalimatnya.

Catatan: TTS memakai suara SAPI bawaan Windows. Jika suara pria/wanita
belum tersedia, buka Settings > Time & Language > Speech > Add voices.


TEST DAN MULAI
--------------
- "Test Deteksi Semua Gift" : mengambil screenshot, menghitung skor setiap
  rule, menampilkan preview kotak hijau/merah, dan menulis hasil OCR
  (teks, jumlah, validasi nama, username) ke tab Log.
- "Test Gift Ini" : menguji rule yang sedang dipilih.
- "MULAI" : mulai memantau. Aplikasi minimize + fokus ke jendela target.
- "STOP" : berhenti dan membuka kembali jendela aplikasi.

HOTKEY:
   Ctrl + Alt + S  = STOP
   Ctrl + Alt + Q  = Keluar aplikasi


CONFIG.JSON
-----------
Semua pengaturan disimpan otomatis di config.json (dekat script/EXE).
Tutup aplikasi dulu bila ingin mengedit manual.

Contoh:
{
    "rules": [
        {
            "name": "Mawar",
            "template_path": "gift_mawar.png",
            "key": "f1",
            "count_mode": "ocr",
            "fixed_count": 1,
            "enabled": true
        },
        {
            "name": "Rose",
            "template_path": "gift_rose.png",
            "key": "f2",
            "count_mode": "fixed",
            "fixed_count": 5,
            "enabled": true
        }
    ],
    "sound_enabled": true,
    "sound_file": "success.wav",
    "tts_enabled": true,
    "tts_gender": "female",
    "tts_voice": "",
    "tts_rate": 0,
    "tts_volume": 100,
    "tts_gift_text": "Thank you {username} for your {gift}",
    "welcome_enabled": true,
    "welcome_interval": 15.0,
    "welcome_text": "Welcome to the stream",
    "use_fullscreen": true,
    "gift_region": null,
    "ocr_region": null,
    "threshold": 0.82,
    "press_delay_ms": 80,
    "cooldown_s": 1.5,
    "confirm_frames": 2,
    "once_per_appearance": true,
    "target_window": "TikTok"
}

Keterangan:
- gift_region / ocr_region : [x, y, lebar, tinggi] piksel layar, atau null.
- count_mode : "ocr" atau "fixed".
- tts_gender : "female" atau "male".
- tts_voice : deskripsi suara persis; "" = otomatis sesuai gender.
- once_per_appearance : true = sekali sampai gift hilang.
- welcome_interval : detik.


MEMBUAT FILE EXE (OPSIONAL)
---------------------------
1. Klik dua kali: build_exe.bat
2. Tunggu proses selesai (beberapa menit).
3. Hasil: dist\GiftTrigger.exe
4. gift_template.png dan success.wav otomatis disalin ke dist.
5. Jika EXE dipindah folder, salin juga gambar template & suara, atau pilih
   ulang lewat aplikasi.

EXE sudah membawa OCR Windows (winrt) dan TTS (comtypes). Suara TTS tetap
memakai suara yang terpasang di Windows.


TROUBLESHOOTING
---------------
- Gift tidak terdeteksi:
  * Pastikan template di-crop rapi, tidak terlalu besar/kecil.
  * Turunkan "Cocok minimal" (mis. 0.72).
  * Pastikan area pantau mencakup ikon gift. Coba layar penuh dulu.
  * Gunakan "Test Gift Ini" untuk melihat skor tiap gift.
- Salah gift terdeteksi:
  * Naikkan "Cocok minimal" (mis. 0.88).
  * Gunakan template yang khas (hindari ikon yang mirip gift lain).
- Angka jumlah tidak terbaca:
  * Pilih "Area Teks/Username" yang mencakup badge "x20" + nama gift.
  * Perbesar UI TikTok Studio.
  * Gunakan mode "Tetap" bila tetap gagal.
- Username salah/tidak terbaca:
  * Pilih area teks yang mencakup nama pengirim.
  * Perbesar UI live.
  * Bila tetap salah, ganti kalimat TTS tanpa {username},
    mis. "Thank you for your gift".
- Nama tidak cocok:
  * Pastikan area teks mencakup tulisan nama gift.
  * Gunakan nama persis seperti yang tampil, atau kosongkan nama rule.
- Tombol tidak tertekan:
  * Isi "Fokus jendela" (mis. TikTok) agar aplikasi fokus ke jendela target.
  * Pastikan F1-F10 tidak dipakai shortcut lain.
  * Bila perlu, jalankan sebagai administrator.
- Suara file tidak keluar:
  * Gunakan WAV (bukan MP3). Klik Test. Periksa volume Windows.
- TTS tidak bersuara:
  * Pastikan "Aktifkan ucapan" tercentang dan volume > 0.
  * Cek Settings > Time & Language > Speech (pasang suara).
  * Klik "Muat ulang" pada daftar suara.
- OCR tidak tersedia:
  * Pasang bahasa Inggris + OCR di Windows Settings > Language.
  * Atau gunakan mode "Tetap" (tanpa OCR).
- Error lain:
  * Lihat error_log.txt di folder aplikasi.


CATATAN PENTING
---------------
- Deteksi berbasis tampilan layar, jadi jangan menutupi/meminimize jendela
  TikTok Studio saat trigger berjalan. Aplikasi ini sendiri boleh minimize.
- Gunakan area pantau kecil agar CPU ringan dan deteksi cepat.
- TTS mengucapkan username hasil OCR; akurasi tergantung kejelasan teks.
- Aplikasi hanya menekan tombol keyboard dan bersuara secara lokal; tidak
  mengakses akun TikTok maupun API apa pun.
