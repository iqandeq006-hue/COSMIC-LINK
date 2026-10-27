@echo off
:: Run this file as Administrator to unblock Cosmic Link in Windows Defender Firewall
echo =====================================================================
echo  COSMIC LINK - WINDOWS FIREWALL CONFIGURATION
echo =====================================================================
echo Requesting administrator privileges...

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [!] Please right-click this file and select 'Run as administrator'.
    echo.
    pause
    exit /b 1
)

echo [+] Allowing Cosmic Link Inbound TCP Port 5051 (Private & Public)...
netsh advfirewall firewall delete rule name="Cosmic Link TCP 5051" >nul 2>&1
netsh advfirewall firewall add rule name="Cosmic Link TCP 5051" dir=in action=allow protocol=TCP localport=5051 profile=any

echo [+] Allowing Cosmic Link Inbound UDP Port 5052 (Private & Public)...
netsh advfirewall firewall delete rule name="Cosmic Link UDP 5052" >nul 2>&1
netsh advfirewall firewall add rule name="Cosmic Link UDP 5052" dir=in action=allow protocol=UDP localport=5052 profile=any

echo [+] Allowing Python executable through Windows Firewall...
for /f "delims=" %%i in ('where python 2^>nul') do (
    netsh advfirewall firewall add rule name="Cosmic Link Python" dir=in action=allow program="%%i" profile=any >nul 2>&1
)

echo.
echo =====================================================================
echo  SUCCESS! Windows Firewall is now configured for Cosmic Link.
echo  High-speed Wi-Fi beaming is now unblocked on this laptop.
echo =====================================================================
echo.
pause
