@echo off
setlocal
set "PYTHONHOME="
set "PYTHONPATH="
if not exist "%~dp0..\binaries\windows\x64\python\python.exe" (
  echo Bundled Python is missing. Repair this RDC-Tool installation. 1>&2
  exit /b 2
)
"%~dp0..\binaries\windows\x64\python\python.exe" -s "%~dp0..\cli\run_cli.py" %*
exit /b %ERRORLEVEL%
