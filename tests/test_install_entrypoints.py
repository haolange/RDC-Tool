import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
PS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows entrypoints")


def powershell(code):
    return subprocess.run([PS, "-NoProfile", "-Command", code], capture_output=True, text=True, encoding="utf-8", timeout=30)


def installer_functions():
    script = str(ROOT / "scripts/rdc_tool_install.ps1").replace("'", "''")
    return f"$ErrorActionPreference='Stop'; $ast=[System.Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$null,[ref]$null); $ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]}},$false) | ForEach-Object {{. ([scriptblock]::Create($_.Extent.Text))}}; $DryRun=$false; "


def test_path_convergence_preserves_other_installations():
    code = installer_functions() + r"""
$script:entries=@('C:\other\bin','C:\chosen','C:\chosen\bin','C:\custom');
function Get-UserPathEntries { return $script:entries }
function Set-UserPathEntries { param([string[]]$Entries) $script:entries=$Entries }
Add-RdcToolToPath -TargetRoot 'C:\chosen' | Out-Null
if (($script:entries -join ';') -ne 'C:\other\bin;C:\custom;C:\chosen\bin') {throw 'bad upgrade PATH'}
Remove-RdcToolFromPath -TargetRoot 'C:\chosen' | Out-Null
if (($script:entries -join ';') -ne 'C:\other\bin;C:\custom') {throw 'bad uninstall PATH'}
"""
    result = powershell(code)
    assert result.returncode == 0, result.stderr


def test_upgrade_removes_owned_launchers_and_preserves_unrelated_files(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    for root in (source, target):
        (root / 'cli').mkdir(parents=True)
        (root / 'cli/run_cli.py').write_text('entry', encoding='utf-8')
    (target / 'scripts').mkdir()
    (target / 'rdc-tool.bat').write_text('obsolete')
    (target / 'scripts/rdc_tool_bat_launcher.ps1').write_text('obsolete')
    (target / 'notes.txt').write_text('keep')
    result = powershell(installer_functions() + f"Copy-RdcToolTools -SourceRoot '{source}' -TargetRoot '{target}'")
    assert result.returncode == 0, result.stderr
    assert not (target / 'rdc-tool.bat').exists()
    assert not (target / 'scripts/rdc_tool_bat_launcher.ps1').exists()
    assert (target / 'notes.txt').read_text() == 'keep'


def test_thin_launcher_forwards_unicode_json_cwd_and_exit(tmp_path):
    root = tmp_path / 'space 中文'
    (root / 'bin').mkdir(parents=True)
    (root / 'cli').mkdir()
    (root / 'binaries/windows/x64').mkdir(parents=True)
    shutil.copyfile(ROOT / 'bin/rdc-tool.cmd', root / 'bin/rdc-tool.cmd')
    junction = root / 'binaries/windows/x64/python'
    made = subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(junction),str(ROOT/'binaries/windows/x64/python')],capture_output=True)
    assert made.returncode == 0
    try:
        (root / 'cli/run_cli.py').write_text('import sys,json,os\nprint(json.dumps({"args":sys.argv[1:],"cwd":os.getcwd()}))\nsys.exit(7)\n',encoding='utf-8')
        args = ['space 中文', '{"text":"a b"}']
        result = subprocess.run('cmd.exe /d /s /c "' + subprocess.list2cmdline([str(root/'bin/rdc-tool.cmd'), *args]) + '"',cwd=tmp_path,capture_output=True,text=True,timeout=20)
        assert result.returncode == 7, result.stderr
        payload=json.loads(result.stdout)
        assert payload['args'] == args
        assert Path(payload['cwd']) == tmp_path
    finally:
        os.rmdir(junction)
    result = subprocess.run('cmd.exe /d /s /c "' + subprocess.list2cmdline([str(root/'bin/rdc-tool.cmd'), 'version']) + '"',capture_output=True,text=True,timeout=20)
    assert result.returncode == 2 and 'Python' in result.stderr
