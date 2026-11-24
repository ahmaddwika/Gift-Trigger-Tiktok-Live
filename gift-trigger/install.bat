@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo  GiftTrigger - Instalasi Dependensi
echo ============================================
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python tidak ditemukan di PATH.
  echo Install Python 3.10 - 3.13 dari https://www.python.org/downloads/
  echo Pastikan centang "Add Python to PATH", lalu jalankan file ini lagi.
  pause
  exit /b 1
)
echo Memperbarui pip...
python -m pip install --upgrade pip
echo.
echo Memasang dependensi inti...
python -m pip install opencv-python numpy keyboard mss pillow comtypes pyinstaller
echo.
echo Memasang OCR bawaan Windows (winrt)...
python -m pip install winrt-runtime winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Globalization
echo.
echo Selesai. Silakan jalankan run.bat
pause
