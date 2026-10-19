@echo off
rem Opens the CoH Art Bridge app (model browser + live preview bridge). No console window stays open.
cd /d "%~dp0.."
start "" pythonw tools\art_bridge_app.py %*
