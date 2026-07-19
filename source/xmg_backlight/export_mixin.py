from __future__ import annotations

import os
from datetime import datetime

from PySide6 import QtCore, QtGui, QtWidgets

from .constants import GITHUB_REPO_URL
from .diagnostics import create_diagnostics_archive


class ExportMixin:
    def on_github_clicked(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(GITHUB_REPO_URL))

    def on_export_logs_clicked(self):
        default_name = (
            f"xmg-backlight-logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        )
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("dialogs.export_logs.title"),
            os.path.expanduser(f"~/{default_name}"),
            self.tr("dialogs.export_logs.filter"),
        )
        if not file_path:
            return
        try:
            report = create_diagnostics_archive(
                file_path,
                activity_lines=list(self.activity_log_buffer),
            )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialogs.export_logs.failed_title"),
                self.tr("dialogs.export_logs.failed_message", error=str(exc)),
            )
            return
        message = self.tr("dialogs.export_logs.complete_message", path=file_path)
        if report["errors"]:
            message += "\n\n" + "\n".join(report["errors"])
        QtWidgets.QMessageBox.information(
            self,
            self.tr("dialogs.export_logs.complete_title"),
            message,
        )
