# Changelog

## v1.4.0 – 2026-01-04
### Installer
- Resume restore now uses the GUI-managed user service only (system-level hooks are no longer installed).
- Partial uninstall now removes per-user services and autostart entries to avoid stale launchers.
- The installer now closes any running GUI instance before install/uninstall.
- The installer now saves logs to `/var/log/xmg-backlight/installer.log`.
- Launcher/autostart now use the same Python interpreter used to run the installer.
- Pip dependencies are installed only if missing (no forced upgrades).

### GUI
- Log exports now include the installer log when available.
- Sync device state when opening/activating the GUI or interacting with the system tray (click/menu), logging the result in the activity log.

## v1.3 – 2026-01-03
### Installer
- Added `--purge` flag for `--uninstall` to also remove pip packages (ite8291r3-ctl, PySide6, shiboken6).
- Added `--purge-user-data` flag to remove user profiles, systemd user services, and autostart entries.
- Interactive uninstall: when run without flags, prompts user to choose between partial or full removal.
- Full uninstall now removes all user-created files: `~/.config/backlight-linux/`, `~/.config/systemd/user/keyboard-backlight-*`, and `~/.config/autostart/keyboard-backlight-*`.
- Increased resume hook delay from 5s to 8s for better USB stability after suspend.

### GUI
- Added "Export logs" button to collect all logs (resume hook, power monitor, config files) into a ZIP file for easy troubleshooting.

## v1.2.1 – 2026-01-02
### GUI
- Added a GitHub shortcut button in the hero card linking to the repository.
- Unified power monitor log messages to English for consistent diagnostics.

## v1.2 – 2026-01-02
### New features
- **Profiles menu in system tray**: Switch between profiles directly from the tray icon without opening the GUI.
- **Power-based profiles**: Configure different profiles for AC and battery power. The power monitor automatically switches to the appropriate profile when the power source changes.
- **New profile button**: Added "New…" button to create a fresh profile with default settings.

### GUI
- Added "On AC" and "On Battery" dropdowns in the Smart automations section to assign profiles per power source.
- Tray menu now shows all available profiles with a checkmark on the active one.
- Dark mode now applies consistently to all dialogs (QMessageBox, QInputDialog).

### Fixes
- Fixed `restore_profile.py` not reading the active profile correctly from the new multi-profile JSON structure.

## v1.1.1 – 2026-01-02
### Installer
- Added `--uninstall` option to cleanly remove all installed files and configurations.
- Implemented log rotation for `/tmp/xmg-backlight-resume.log` (auto-truncates at 512 KB).

### GUI stability fixes
- Fixed lock file not being released on application exit (could cause "already running" errors after crash).
- Fixed race condition in profile file watcher (check for ignore flag before re-watching).
- Wrapped main execution in `if __name__ == "__main__":` guard for safe module imports.
- Added cleanup of orphan `.tmp` files when profile/settings write fails.
- Removed unused `label_text` variables in refresh functions.
- Added error handling in `on_profile_file_changed` and `on_profile_directory_changed`.

## v1.1 – 2026-01-01
- Updated installer with smarter file deployment, hardware probing, and cleanup when aborted.
- Added system tray icon with quick actions and notification controls in the GUI.

## v1.0 – 2026-01-01
- Initial public release.
