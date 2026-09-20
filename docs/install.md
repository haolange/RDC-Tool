# Install

`rdc-tool` GA artifacts are self-contained Windows x64 packages. Users should not install Python, create a virtual environment, or run a package manager before using the CLI.

## Install or Upgrade

RDC-Agent users may simply extract the zip and select the contained `rdc-tool` folder in Settings → Tools, then verify and apply. No PATH change or system Python installation is required. Detection uses the existing default installation `%LOCALAPPDATA%\Programs\rdc-tool`.

Extract `rdc-tool-<version>-windows-x64.zip`, then run:

```powershell
./install.cmd -Action install -InstallDir "$env:LOCALAPPDATA\Programs\rdc-tool" -AddToPath
./install.cmd -Action upgrade -InstallDir "$env:LOCALAPPDATA\Programs\rdc-tool" -AddToPath
```

Use `-DryRun` to inspect the file and PATH actions first.

## Doctor

```powershell
./install.cmd -Action doctor -InstallDir "$env:LOCALAPPDATA\Programs\rdc-tool"
rdc-tool --json doctor
```

## Uninstall

```powershell
./install.cmd -Action uninstall -InstallDir "$env:LOCALAPPDATA\Programs\rdc-tool"
```

The install script only copies `rdc-tool`, updates the user PATH when requested, and refuses to remove a directory that does not contain `bin/rdc-tool.cmd`.


## Windows entrypoints and host binding

Double-click `install.cmd` to install and add this installation's `bin` directory to the user PATH. `install.cmd` accepts the installer parameters above; it never runs CLI operations. CLI users run `rdc-tool` through thin `bin/rdc-tool.cmd`, which selects the adjacent bundled Python, forwards standard streams/arguments and preserves the exit code. Missing bundled Python fails without system-Python fallback. Unix `bin/rdc-tool` is unchanged.

Upgrade removes only this installation's former root PATH entry and two replaced launcher files; unrelated installations, PATH entries and shortcuts are untouched. No old-name forwarding files remain. Installer PowerShell is confined to installation/upgrade/uninstall/doctor, never the CLI hot path.

RDC-Agent command must be the absolute `<installation>/binaries/windows/x64/python/python.exe`, paired with that installation's `cli/run_cli.py` as its sole argument prefix. Shell wrappers and cross-installation pairs are rejected. Saved invalid settings remain visible for manual correction; they do not silently migrate.

## Source and runtime integrity

Run `git lfs pull` after cloning. Both Windows and Android files under `binaries/` are replay runtime and must remain available. The self-contained release zip includes them; pip-installed RenderDoc is not a replacement. The default installation is `%LOCALAPPDATA%\Programs\rdc-tool`.

Installation doctor rejects an outdated layout. The installer does not discover, copy or silently run a retired installation. Configure RDC-Agent with the new installation's absolute bundled Python path and its `cli/run_cli.py`.
