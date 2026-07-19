from __future__ import annotations

import time

from PySide6 import QtCore, QtGui, QtWidgets

from .driver import format_log

class ActivityLogMixin:
    def _append_activity_log_lines(self, text, level, timestamp):
        if not hasattr(self, "activity_log_buffer"):
            return
        prefix = f"[{timestamp}] [{level}] "
        lines = str(text).splitlines() or [""]
        self.activity_log_buffer.append(prefix + lines[0])
        indent = " " * len(prefix)
        for line in lines[1:]:
            self.activity_log_buffer.append(indent + line)

    def log(self, text, level="info"):
        timestamp = time.strftime("%H:%M:%S")
        self._append_activity_log_lines(text, level, timestamp)
        entry = format_log(f"[{timestamp}] {text}", level)
        self.console.append(entry)
        sb = self.console.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())
        if hasattr(self, "log_window") and self.log_window.isVisible():
            self._fit_log_window()

    def on_log_toggle_toggled(self, checked):
        if not hasattr(self, "log_window"):
            return
        if checked:
            self.log_window.show()
            self.log_window.raise_()
            self.log_window.activateWindow()
            self._fit_log_window()
        else:
            self.log_window.hide()
        if hasattr(self, "log_toggle_button"):
            self.log_toggle_button.setText(
                self.tr("buttons.hide_activity_log")
                if checked
                else self.tr("buttons.show_activity_log")
            )

    def on_log_close_clicked(self):
        if hasattr(self, "log_window"):
            self.log_window.close()

    def on_log_window_closed(self, _result=None):
        if not hasattr(self, "log_toggle_button"):
            return
        blocker = QtCore.QSignalBlocker(self.log_toggle_button)
        try:
            self.log_toggle_button.setChecked(False)
            self.log_toggle_button.setText(self.tr("buttons.show_activity_log"))
        finally:
            del blocker

    def _fit_log_window(self):
        if not hasattr(self, "log_window") or not self.log_window.isVisible():
            return
        screen = self.log_window.screen()
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        outer_margin = 48
        max_width = min(900, max(520, available.width() - outer_margin))
        target_width = max_width
        window_layout = self.log_window.layout()
        window_margins = window_layout.contentsMargins() if window_layout else QtCore.QMargins()
        card_layout = self.log_card.layout() if hasattr(self, "log_card") else None
        card_margins = card_layout.contentsMargins() if card_layout else QtCore.QMargins()
        header_height = 0
        if card_layout and card_layout.count() > 0:
            header_item = card_layout.itemAt(0)
            if header_item:
                header_height = header_item.sizeHint().height()

        text_width = (
            target_width
            - window_margins.left() - window_margins.right()
            - card_margins.left() - card_margins.right()
        )
        if text_width < 320:
            text_width = 320
        self.console.setFixedWidth(text_width)
        self.console.document().setTextWidth(self.console.viewport().width())
        self.console.document().adjustSize()

        max_height = available.height() - outer_margin
        max_text_height = (
            max_height
            - window_margins.top() - window_margins.bottom()
            - card_margins.top() - card_margins.bottom()
            - header_height
        )
        if max_text_height < 120:
            max_text_height = 120
        self._trim_log_to_fit(max_text_height)
        self.console.document().adjustSize()
        doc_height = int(self.console.document().size().height())
        text_height = min(doc_height, max_text_height)
        self.console.setFixedHeight(max(80, text_height + 4))

        target_height = (
            window_margins.top() + window_margins.bottom()
            + card_margins.top() + card_margins.bottom()
            + header_height + text_height + 4
        )
        if target_height < 260:
            target_height = 260
        if target_height > max_height:
            target_height = max_height

        self.log_window.resize(target_width, target_height)
        self._clamp_log_window_to_screen(available)

    def _trim_log_to_fit(self, max_text_height):
        doc = self.console.document()
        doc.setTextWidth(self.console.viewport().width())
        doc.adjustSize()
        if doc.size().height() <= max_text_height:
            return
        while doc.size().height() > max_text_height and doc.blockCount() > 1:
            cursor = QtGui.QTextCursor(doc)
            cursor.movePosition(QtGui.QTextCursor.Start)
            cursor.movePosition(QtGui.QTextCursor.NextBlock, QtGui.QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.deleteChar()
            doc.setTextWidth(self.console.viewport().width())
            doc.adjustSize()

    def _clamp_log_window_to_screen(self, available):
        frame = self.log_window.frameGeometry()
        new_frame = QtCore.QRect(frame)
        if new_frame.left() < available.left():
            new_frame.moveLeft(available.left())
        if new_frame.top() < available.top():
            new_frame.moveTop(available.top())
        if new_frame.right() > available.right():
            new_frame.moveRight(available.right())
        if new_frame.bottom() > available.bottom():
            new_frame.moveBottom(available.bottom())
        if new_frame != frame:
            self.log_window.move(new_frame.topLeft())

    def set_status(self, t, level="info"):
        self.log(t, level=level)
