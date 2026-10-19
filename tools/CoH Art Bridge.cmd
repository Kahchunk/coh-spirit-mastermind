@echo off
title CoH Art Bridge
cd /d "%~dp0.."
echo CoH Art Bridge - open a part's .psd from art\work in Photoshop and it shows up in Blender.
echo Leave this window open while you work. Close it to stop.
echo.
python tools\art_bridge.py run
echo.
echo The bridge stopped. Press any key to close.
pause >nul
