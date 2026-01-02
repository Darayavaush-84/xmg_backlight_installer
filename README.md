# XMG Backlight Installer

Installer and deployment helper for the **backlight-linux** GUI that controls the ITE 8291 RGB keyboard on XMG/Tongfang laptops. It ships the GUI, systemd user services, and system-level resume hooks so that the keyboard backlight is restored automatically after suspend/hibernate.

## Repository layout

| Path | Purpose |
| --- | --- |
| `source/` | Upstream scripts (GUI, restore helper, power monitor). |
| `install.py` | Top-level installer script to run with sudo. |
| `.gitignore` | Local development exclusions (bytecode, build artifacts, IDE files, etc.). |

## Requirements

* Linux distribution with `systemd` (tested on Fedora; other distros may need tweaks).
* Python 3.10+ with `pip`.
* Root privileges to deploy files under `/usr/share`, `/usr/local/bin`, `/etc/systemd`, etc.
* USB access to the keyboard controller (ensure `ite8291r3`-ctl works on your device).

## Installation

1. Clone the repository and enter the project directory:
   ```bash
   git clone https://github.com/Darayavaush-84/xmg_backlight_installer.git
   cd xmg_backlight_installer
   ```
2. Run the installer as root:
   ```bash
   sudo python3 install.py
   ```
3. Launch **XMG Backlight Management** from your desktop menu and enable the automation toggles (resume + power monitor) if desired.

## Uninstallation

To completely remove the installed files and configurations:

```bash
sudo python3 install.py --uninstall
```

This removes:
- GUI scripts from `/usr/share/xmg-backlight`
- Launcher wrapper at `/usr/local/bin/xmg-backlight`
- Desktop entry and autostart files
- System-sleep hook and systemd drop-ins

**Note:** pip packages (`ite8291r3-ctl`, `PySide6`) are **not** removed automatically. To remove them:
```bash
pip uninstall ite8291r3-ctl PySide6
```

The installer performs these actions:
* Ensures `ite8291r3-ctl` and `PySide6` are installed via `pip`.
* Copies the GUI scripts (`keyboard_backlight.py`, `restore_profile.py`, `power_state_monitor.py`) into `/usr/share/xmg-backlight`.
* Creates a launcher wrapper at `/usr/local/bin/xmg-backlight` and a desktop entry under `/usr/share/applications`.
* Installs `/etc/systemd/system-sleep/xmg-backlight-restore` and a helper `/usr/local/lib/xmg-backlight-resume-hook.sh`.
* Adds drop-ins for `systemd-suspend*` services so the resume hook runs automatically, then reloads `systemd`.
* Probes for compatible ITE 8291 keyboards; if none are found you can abort safely and the just-installed driver will be removed automatically.

## System tray & notifications

The GUI now exposes two user-facing preferences (stored under `~/.config/backlight-linux/settings.json`):

- **Add in systray** – start the application minimized to the system tray and keep it running even when the window is closed. A tray icon provides quick actions (Show/Hide window, Turn on/off, Load last profile, Quit).
- **Show notifications** – toggle desktop toasts emitted by the tray commands (short messages such as “Minimized to tray”).

Both options live in the “Automation helpers” card on the right-hand side of the GUI.

## Testing the resume hook

1. Trigger a suspend/resume cycle from your desktop environment.
2. After resume, confirm the keyboard lights restored automatically.
3. Inspect the log for troubleshooting:
   ```bash
   sudo tail -n 40 /tmp/xmg-backlight-resume.log
   ```
4. For additional diagnostics check:
   ```bash
   journalctl -b | grep xmg-backlight-hook
   ```

If the keyboard stays dark but manual restore works (`python3 /usr/share/xmg-backlight/restore_profile.py`), inspect the log file above to understand which phase failed.

## Development workflow

* Use the files under `source/` as the canonical payload: modify them there, then re-run the installer to copy updates into `/usr/share/xmg-backlight`.
* Keep the installer idempotent; re-running it should refresh dependencies and hooks without breaking existing installs.
* When adding system-level integrations (systemd units, hooks), place the generator logic in `installer/install.py` so that deployments remain reproducible.
* Run `python3 -m pytest` (if you add tests) or manual smoke tests: start the GUI, toggle automation, run suspend/resume, and inspect `/tmp/xmg-backlight-resume.log`.

## Credits

This installer/GUI bundle builds on top of the excellent [`pobrn/ite8291r3-ctl`](https://github.com/pobrn/ite8291r3-ctl) userspace driver.  
- **Driver & low-level tooling:** © [Barnabás Pőcze](https://github.com/pobrn) and contributors (GPL licensed).  
- **GUI + automatic installer:** developed by @Darayavaush-84 to provide a PySide-based interface, user services, and system-level hooks that simplify deployments on XMG/Tongfang laptops.

## License

* **GUI + installer code** (authored by **Dario Barbarino**): released under the **GNU General Public License v3.0**.  
* **Underlying driver (`ite8291r3-ctl`)**: distributed under **GNU GPL v2.0** per the upstream project. Its license text is stored in [`source/LICENSE`](source/LICENSE).

When contributing, keep your changes compatible with GPL v3 for the GUI/installer and respect the upstream GPL v2 requirements for the driver portion.
