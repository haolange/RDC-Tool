@echo off
setlocal
for %%I in ("%~dp0..") do set "RDX_TOOLS_ROOT=%%~fI"
set "RDX_LAUNCHER_PROG=rdx"
set "RDX_PYTHON=%RDX_TOOLS_ROOT%\binaries\windows\x64\python\python.exe"
if not exist "%RDX_PYTHON%" (
  echo Bundled Python is missing. Repair this RDX installation. 1>&2
  exit /b 2
)
"%RDX_PYTHON%" "%RDX_TOOLS_ROOT%\cli\run_cli.py" %*
exit /b %ERRORLEVEL%
