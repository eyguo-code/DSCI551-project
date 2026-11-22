@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0Start-Demo.ps1" %*
exit /b %errorlevel%
