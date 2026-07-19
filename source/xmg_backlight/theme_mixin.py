from __future__ import annotations

from PySide6 import QtCore, QtWidgets

class ThemeMixin:
    def on_dark_mode_toggled(self, checked):
        checked = bool(checked)
        if self.settings.get("dark_mode") == checked:
            return
        previous = self.settings.get("dark_mode", True)
        self.settings["dark_mode"] = checked
        if not self.save_settings():
            self.settings["dark_mode"] = previous
            blocker = QtCore.QSignalBlocker(self.dark_mode_checkbox)
            try:
                self.dark_mode_checkbox.setChecked(previous)
            finally:
                del blocker
            return
        self.apply_styles()

    def apply_styles(self):
        base = """
        #MainView {
            background-color: #f6f8fb;
        }
        #logWindow {
            background-color: #eef2f7;
            background-image: radial-gradient(circle at 15% 15%, rgba(59, 130, 246, 0.12), transparent 55%);
        }
        #AppSurface {
            background-color: transparent;
        }
        QLabel, QCheckBox, QToolButton {
            color: #1f2933;
            font-size: 13px;
        }
        #heroTitle {
            font-size: 28px;
            font-weight: 700;
            color: #0f172a;
        }
        #heroSubtitle {
            font-size: 14px;
            color: #52606d;
        }
        #heroCard {
            background-color: #ffffff;
            border-radius: 20px;
            border: 1px solid rgba(15, 33, 55, 0.08);
            background-image: radial-gradient(circle at 15% 20%, rgba(79, 209, 197, 0.25), transparent 60%),
                              radial-gradient(circle at 85% 10%, rgba(99, 102, 241, 0.2), transparent 45%);
        }
        #heroCaption {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #738095;
        }
        #hardwareBadge {
            padding: 6px 12px;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.12);
            color: #1d4ed8;
            font-weight: 600;
        }
        #pillButton {
            padding: 9px 18px;
            border-radius: 999px;
            font-weight: 600;
            border: 1px solid rgba(148,163,184,0.45);
            color: #0f172a;
            background-color: #ffffff;
        }
        #pillButton:checked {
            background-color: #3b82f6;
            border: none;
            color: #ffffff;
        }
        #surfaceCard {
            background-color: #ffffff;
            border-radius: 20px;
            border: 1px solid rgba(15, 23, 42, 0.05);
        }
        #sectionTitle {
            font-size: 17px;
            font-weight: 600;
            color: #111827;
        }
        #sectionSubtitle {
            font-size: 13px;
            color: #5f6b7a;
        }
        QComboBox, QSpinBox, QTextEdit {
            padding: 8px 12px;
            border-radius: 12px;
            border: 1px solid rgba(148, 163, 184, 0.4);
            background-color: #f9fafc;
            color: #1f2933;
        }
        QComboBox::drop-down {
            border: none;
        }
        QSlider::groove:horizontal {
            height: 6px;
            border-radius: 3px;
            background: rgba(148, 163, 184, 0.35);
        }
        QSlider::handle:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #34d399, stop:1 #60a5fa);
            border: 2px solid #22c55e;
            border-radius: 10px;
            width: 20px;
            margin: -7px 0;
        }
        QSlider::sub-page:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #38bdf8, stop:1 #a855f7);
            border-radius: 3px;
        }
        QPushButton {
            padding: 11px 18px;
            border-radius: 12px;
            font-weight: 600;
            border: 1px solid rgba(37, 99, 235, 0.15);
            background: #ffffff;
            color: #1f2933;
        }
        QPushButton:hover {
            border-color: rgba(37, 99, 235, 0.4);
        }
        QPushButton:pressed {
            background: #e2e8f0;
        }
        QPushButton:disabled {
            border: 1px solid rgba(148, 163, 184, 0.3);
            background: #f1f5f9;
            color: rgba(57, 77, 96, 0.6);
        }
        QPushButton:focus {
            outline: 0;
            border-color: rgba(99, 102, 241, 0.8);
        }
        #powerButton {
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 0.02em;
            border: none;
            color: #ffffff;
        }
        #powerButton[powerState="off"] {
            background-color: #16a34a;
        }
        #powerButton[powerState="on"] {
            background-color: #dc2626;
        }
        QTextEdit {
            min-height: 160px;
        }
        #logView {
            background-color: #0b1120;
            color: #e2e8f0;
            border: 1px solid rgba(15, 23, 42, 0.6);
        }
        #helperRow {
            background-color: #f9fafc;
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.35);
        }
        #helperInfoButton {
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.3);
            color: #0f172a;
            font-weight: 700;
        }
        #helperLabel {
            font-weight: 600;
            color: #1f2933;
        }
        #helperFlag {
            font-weight: 600;
        }
        #helperDetail {
            color: #4b5563;
            font-size: 12px;
        }
        QCheckBox::indicator {
            width: 20px;
            height: 20px;
        }
        QCheckBox::indicator:unchecked {
            border-radius: 6px;
            border: 1px solid rgba(148, 163, 184, 0.7);
            background-color: #ffffff;
        }
        QCheckBox::indicator:checked {
            border-radius: 6px;
            border: none;
            background-color: #3b82f6;
        }
        QPushButton#helperFlag {
            padding: 8px 22px;
            border-radius: 16px;
            border: 2px solid #94a3b8;
            background-color: #ffffff;
            font-weight: 600;
            color: #1f2933;
        }
        QPushButton#helperFlag:checked {
            border: 2px solid #16a34a;
            color: #ffffff;
            background-color: #16a34a;
        }
        QPushButton#helperFlag:disabled {
            background-color: #f1f5f9;
            color: #94a3b8;
            border: 2px solid #cbd5e1;
        }
        QPushButton#applyButton {
            padding: 8px 22px;
            border-radius: 16px;
            border: 2px solid #94a3b8;
            background-color: #ffffff;
            font-weight: 600;
            color: #1f2933;
        }
        QPushButton#applyButton:enabled {
            border: 2px solid #16a34a;
            color: #ffffff;
            background-color: #16a34a;
        }
        QPushButton#applyButton:disabled {
            background-color: #f1f5f9;
            color: #94a3b8;
            border: 2px solid #cbd5e1;
        }
        """
        dark = """
        #MainView {
            background-color: #0f172a;
        }
        #logWindow {
            background-color: #0b1220;
            background-image: radial-gradient(circle at 15% 15%, rgba(59, 130, 246, 0.18), transparent 55%);
        }
        #AppSurface {
            background-color: transparent;
        }
        QLabel, QCheckBox, QToolButton {
            color: #e2e8f0;
            font-size: 13px;
        }
        #heroTitle {
            font-size: 28px;
            font-weight: 700;
            color: #f1f5f9;
        }
        #heroSubtitle {
            font-size: 14px;
            color: #94a3b8;
        }
        #heroCard {
            background-color: #1e293b;
            border-radius: 20px;
            border: 1px solid rgba(148, 163, 184, 0.15);
            background-image: radial-gradient(circle at 15% 20%, rgba(79, 209, 197, 0.15), transparent 60%),
                              radial-gradient(circle at 85% 10%, rgba(99, 102, 241, 0.12), transparent 45%);
        }
        #heroCaption {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #64748b;
        }
        #hardwareBadge {
            padding: 6px 12px;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.2);
            color: #60a5fa;
            font-weight: 600;
        }
        #pillButton {
            padding: 9px 18px;
            border-radius: 999px;
            font-weight: 600;
            border: 1px solid rgba(148,163,184,0.3);
            color: #e2e8f0;
            background-color: #1e293b;
        }
        #pillButton:checked {
            background-color: #3b82f6;
            border: none;
            color: #ffffff;
        }
        #surfaceCard {
            background-color: #1e293b;
            border-radius: 20px;
            border: 1px solid rgba(148, 163, 184, 0.1);
        }
        #sectionTitle {
            font-size: 17px;
            font-weight: 700;
            color: #f1f5f9;
        }
        #sectionSubtitle {
            font-size: 13px;
            color: #94a3b8;
        }
        QComboBox {
            padding: 10px 14px;
            border-radius: 10px;
            border: 1px solid rgba(148, 163, 184, 0.3);
            background-color: #0f172a;
            color: #e2e8f0;
            font-size: 13px;
        }
        QComboBox:hover {
            border-color: rgba(99, 102, 241, 0.5);
        }
        QComboBox::drop-down {
            border: none;
        }
        QSlider::groove:horizontal {
            height: 6px;
            border-radius: 3px;
            background: rgba(148, 163, 184, 0.25);
        }
        QSlider::handle:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #34d399, stop:1 #60a5fa);
            border: 2px solid #22c55e;
            border-radius: 10px;
            width: 20px;
            margin: -7px 0;
        }
        QSlider::sub-page:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #38bdf8, stop:1 #a855f7);
            border-radius: 3px;
        }
        QSpinBox {
            padding: 10px 14px;
            border-radius: 10px;
            border: 1px solid rgba(148, 163, 184, 0.3);
            background-color: #0f172a;
            color: #e2e8f0;
            font-size: 13px;
        }
        QPushButton {
            padding: 11px 18px;
            border-radius: 12px;
            font-weight: 600;
            border: 1px solid rgba(148, 163, 184, 0.3);
            background: #1e293b;
            color: #e2e8f0;
        }
        QPushButton:hover {
            border-color: rgba(99, 102, 241, 0.5);
        }
        QPushButton:pressed {
            background: #334155;
            color: #e2e8f0;
        }
        QPushButton:disabled {
            border: 1px solid rgba(148, 163, 184, 0.2);
            background: #1e293b;
            color: rgba(148, 163, 184, 0.5);
        }
        QPushButton:focus {
            outline: 0;
            border-color: rgba(99, 102, 241, 0.8);
        }
        #powerButton {
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 0.02em;
            border: none;
            color: #ffffff;
        }
        #powerButton[powerState="off"] {
            background-color: #16a34a;
        }
        #powerButton[powerState="on"] {
            background-color: #dc2626;
        }
        QTextEdit {
            min-height: 160px;
        }
        #logView {
            background-color: #020617;
            color: #e2e8f0;
            border: 1px solid rgba(148, 163, 184, 0.2);
        }
        #helperRow {
            background-color: #0f172a;
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.2);
        }
        #helperInfoButton {
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.2);
            color: #e2e8f0;
            font-weight: 700;
        }
        #helperLabel {
            font-weight: 600;
            color: #e2e8f0;
        }
        #helperFlag {
            font-weight: 600;
        }
        #helperDetail {
            color: #94a3b8;
            font-size: 12px;
        }
        QCheckBox::indicator {
            width: 20px;
            height: 20px;
        }
        QCheckBox::indicator:unchecked {
            border-radius: 6px;
            border: 1px solid rgba(148, 163, 184, 0.5);
            background-color: #1e293b;
        }
        QCheckBox::indicator:checked {
            border-radius: 6px;
            border: none;
            background-color: #3b82f6;
        }
        QPushButton#helperFlag {
            padding: 8px 22px;
            border-radius: 16px;
            border: 2px solid #64748b;
            background-color: #1e293b;
            font-weight: 600;
            color: #e2e8f0;
        }
        QPushButton#helperFlag:checked {
            border: 2px solid #16a34a;
            color: #ffffff;
            background-color: #16a34a;
        }
        QPushButton#helperFlag:disabled {
            background-color: #1e293b;
            color: #64748b;
            border: 2px solid #334155;
        }
        QPushButton#applyButton {
            padding: 8px 22px;
            border-radius: 16px;
            border: 2px solid #64748b;
            background-color: #1e293b;
            font-weight: 600;
            color: #e2e8f0;
        }
        QPushButton#applyButton:enabled {
            border: 2px solid #16a34a;
            color: #ffffff;
            background-color: #16a34a;
        }
        QPushButton#applyButton:disabled {
            background-color: #1e293b;
            color: #64748b;
            border: 2px solid #334155;
        }
        QMessageBox {
            background-color: #1e293b;
            color: #e2e8f0;
        }
        QMessageBox QLabel {
            color: #e2e8f0;
        }
        QMessageBox QPushButton {
            min-width: 80px;
            padding: 8px 16px;
        }
        QInputDialog {
            background-color: #1e293b;
            color: #e2e8f0;
        }
        QInputDialog QLabel {
            color: #e2e8f0;
        }
        QInputDialog QLineEdit {
            padding: 10px 14px;
            border-radius: 10px;
            border: 1px solid rgba(148, 163, 184, 0.3);
            background-color: #0f172a;
            color: #e2e8f0;
            font-size: 13px;
        }
        """
        if self.settings.get("dark_mode", False):
            self.setStyleSheet(dark)
            self._style_combobox_views("#1e293b", "#e2e8f0")
        else:
            self.setStyleSheet(base)
            self._style_combobox_views("#ffffff", "#1f2933")
        if hasattr(self, "log_window"):
            self.log_window.setStyleSheet(self.styleSheet())
            if self.log_window.isVisible():
                self._fit_log_window()

    def _style_combobox_views(self, bg_color, text_color):
        """Style all ComboBox dropdown views to remove white borders."""
        comboboxes = [
            self.mode, self.static_color, self.color, self.direction,
            self.profile_combo, self.ac_profile_combo, self.battery_profile_combo,
            self.language_combo,
        ]
        for combo in comboboxes:
            view = combo.view()
            if view:
                view.setFrameShape(QtWidgets.QFrame.NoFrame)
                view.setStyleSheet(f"background-color: {bg_color}; color: {text_color}; border: none;")
                parent = view.parentWidget()
                if parent:
                    parent.setStyleSheet(
                        f"background-color: {bg_color}; "
                        "border: 1px solid rgba(148, 163, 184, 0.3);"
                    )
