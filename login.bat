@echo off
title Meta AI Manual Login Helper
cd /d "%~dp0"
echo =============================================================
echo   META AI MANUAL LOGIN HELPER
echo =============================================================
echo.
echo This helper will open a browser window on your desktop.
echo.
echo 1. In the opened browser, log in to WhatsApp Web (scan the QR code).
echo 2. Once you successfully log in and see your chats,
echo    come back to this black terminal window and press ENTER.
echo.
echo Launching browser...
python bot.py --login-whatsapp
echo.
echo Session saved successfully! You can close this window now.
pause
