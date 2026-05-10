from __future__ import annotations

import json
import os
import subprocess
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .constants import *
from .driver import TOOL, apply_effect_with_fallback, format_cli_error, format_log, run_cmd
from .services import *
from .storage import *
from .translations import detect_system_language, load_translations
from .ui_helpers import build_flag_icon, clamp_int, normalize_language_code, sanitize_choice, set_combo_by_data

class ExportMixin:
    def on_github_clicked(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(GITHUB_REPO_URL))

    def on_export_logs_clicked(self):
        import zipfile
        import tempfile
        from datetime import datetime
        
        # Ask user where to save the ZIP
        default_name = f"xmg-backlight-logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("dialogs.export_logs.title"),
            os.path.expanduser(f"~/{default_name}"),
            self.tr("dialogs.export_logs.filter")
        )
        if not file_path:
            return
        
        try:
            with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 1. Resume hook log
                if os.path.exists(RESUME_LOG_PATH):
                    try:
                        zf.write(RESUME_LOG_PATH, "resume-hook.log")
                    except Exception:
                        pass

                # 2. Installer log
                if os.path.exists(INSTALLER_LOG_PATH):
                    try:
                        zf.write(INSTALLER_LOG_PATH, "installer.log")
                    except Exception:
                        pass
                
                # 3. Power monitor journal
                try:
                    result = subprocess.run(
                        ["journalctl", "--user", "-u", "keyboard-backlight-power-monitor", 
                         "--since", "24 hours ago", "--no-pager"],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.stdout.strip():
                        zf.writestr("power-monitor.log", result.stdout)
                except Exception:
                    pass
                
                # 4. Resume service journal
                try:
                    result = subprocess.run(
                        ["journalctl", "--user", "-u", "keyboard-backlight-resume.service",
                         "--since", "24 hours ago", "--no-pager"],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.stdout.strip():
                        zf.writestr("resume-service.log", result.stdout)
                except Exception:
                    pass
                
                # 5. User config files
                if os.path.isdir(CONFIG_DIR):
                    for config_file in ["settings.json", "profile.json"]:
                        config_path = os.path.join(CONFIG_DIR, config_file)
                        if os.path.isfile(config_path):
                            zf.write(config_path, f"config/{config_file}")

                # 6. Activity log
                if hasattr(self, "activity_log_buffer") and self.activity_log_buffer:
                    log_text = "\n".join(self.activity_log_buffer) + "\n"
                    zf.writestr("activity-log.txt", log_text)

                # 7. System info
                system_info = []
                system_info.append(f"Export date: {datetime.now().isoformat()}")
                system_info.append(f"App version: {APP_VERSION}")
                try:
                    result = subprocess.run(["uname", "-a"], capture_output=True, text=True, timeout=5)
                    system_info.append(f"System: {result.stdout.strip()}")
                except Exception:
                    pass
                try:
                    tool_cmd = TOOL or "ite8291r3-ctl"
                    result = subprocess.run([tool_cmd, "--version"], capture_output=True, text=True, timeout=5)
                    system_info.append(f"Driver: {result.stdout.strip() or result.stderr.strip()}")
                except Exception:
                    system_info.append("Driver: not found")
                zf.writestr("system-info.txt", "\n".join(system_info))
            
            QtWidgets.QMessageBox.information(
                self,
                self.tr("dialogs.export_logs.complete_title"),
                self.tr("dialogs.export_logs.complete_message", path=file_path),
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialogs.export_logs.failed_title"),
                self.tr("dialogs.export_logs.failed_message", error=str(e)),
            )
