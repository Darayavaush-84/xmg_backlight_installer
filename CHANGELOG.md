# Changelog

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
