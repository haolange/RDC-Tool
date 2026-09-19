# Install

`rdx-tools` GA artifacts are self-contained Windows x64 packages. Users should not install Python, create a virtual environment, or run a package manager before using the CLI.

## Install or Upgrade

Extract `rdx-tools-<version>-windows-x64.zip`, then run:

```powershell
./install.cmd -Action install -InstallDir "$env:LOCALAPPDATA\Programs\rdx-tools" -AddToPath
./install.cmd -Action upgrade -InstallDir "$env:LOCALAPPDATA\Programs\rdx-tools" -AddToPath
```

Use `-DryRun` to inspect the file and PATH actions first.

## Doctor

```powershell
./install.cmd -Action doctor -InstallDir "$env:LOCALAPPDATA\Programs\rdx-tools"
rdx --json doctor
```

## Uninstall

```powershell
./install.cmd -Action uninstall -InstallDir "$env:LOCALAPPDATA\Programs\rdx-tools"
```

The install script only copies `rdx-tools`, updates the user PATH when requested, and refuses to remove a directory that does not contain `bin/rdx.cmd`.


## Windows entrypoints and host binding

Double-click `install.cmd` to install and add this installation's `bin` directory to the user PATH. `install.cmd` accepts the installer parameters above; it never runs CLI operations. CLI users run `rdx` through thin `bin/rdx.cmd`, which selects the adjacent bundled Python, forwards standard streams/arguments and preserves the exit code. Missing bundled Python fails without system-Python fallback. Unix `bin/rdx` is unchanged.

Upgrade removes only this installation's former root PATH entry and two replaced launcher files; unrelated installations, PATH entries and shortcuts are untouched. No old-name forwarding files remain. Installer PowerShell is confined to installation/upgrade/uninstall/doctor, never the CLI hot path.

RDC-Agent command must be the absolute `<installation>/binaries/windows/x64/python/python.exe`, paired with that installation's `cli/run_cli.py` as its sole argument prefix. Shell wrappers and cross-installation pairs are rejected. Saved invalid settings remain visible for manual correction; they do not silently migrate.
