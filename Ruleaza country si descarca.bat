@echo off
title Country Top si Descarcare saptamanala
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"

echo.
echo === Generez topul country ===
python country_top_200.py
if errorlevel 1 (
    echo.
    echo Generarea topului a esuat. Descarcarea nu va porni.
    pause
    exit /b 1
)

echo.
echo === Descarc melodiile saptamanii ===
python descarca_saptamana.py

pause
