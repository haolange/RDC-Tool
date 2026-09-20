@echo off
setlocal
for %%I in ("%~dp0..") do set "RDC_TOOL_ROOT=%%~fI"
set "RDC_TOOL_LAUNCHER_PROG=rdc-tool"
set "RDC_TOOL_PYTHON=%RDC_TOOL_ROOT%\binaries\windows\x64\python\python.exe"
if not exist "%RDC_TOOL_PYTHON%" (
  echo Bundled Python is missing. Repair this RDC-Tool installation. 1>&2
  exit /b 2
)
"%RDC_TOOL_PYTHON%" "%RDC_TOOL_ROOT%\cli\run_cli.py" %*
exit /b %ERRORLEVEL%
