@echo off
setlocal
if "%~1"=="" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\rdx_install.ps1" -Action install -AddToPath
) else (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\rdx_install.ps1" %*
)
set "RDX_INSTALL_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RDX_INSTALL_EXIT%
