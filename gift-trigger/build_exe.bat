@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo  Membuat GiftTrigger.exe (onefile)
echo ============================================
taskkill /f /im GiftTrigger.exe >nul 2>nul
python -m PyInstaller --noconfirm --clean --onefile --windowed --name GiftTrigger ^
  --hidden-import winrt.windows.media.ocr ^
  --hidden-import winrt.windows.graphics.imaging ^
  --hidden-import winrt.windows.storage.streams ^
  --hidden-import winrt.windows.foundation ^
  --hidden-import winrt.windows.foundation.collections ^
  --hidden-import winrt.windows.globalization ^
  --collect-binaries winrt ^
  --hidden-import comtypes ^
  --hidden-import comtypes.client ^
  --collect-submodules comtypes ^
  GiftTrigger.py
echo.
if exist dist\GiftTrigger.exe (
  echo BERHASIL: dist\GiftTrigger.exe
  copy /y gift_template.png dist\ >nul
  copy /y success.wav dist\ >nul
) else (
  echo GAGAL membuat EXE. Lihat pesan di atas.
)
pause
