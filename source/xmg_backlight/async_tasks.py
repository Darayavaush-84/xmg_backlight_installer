"""Small Qt worker adapter; business logic remains in pure callable functions."""

from __future__ import annotations

import threading

from PySide6 import QtCore


class TaskSignals(QtCore.QObject):
    completed = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    finished = QtCore.Signal()


class FunctionTask(QtCore.QRunnable):
    def __init__(self, function, *, task_key=None):
        super().__init__()
        self.function = function
        self.task_key = task_key
        self.signals = TaskSignals()
        self._cancelled = threading.Event()
        self._started = threading.Event()

    def cancel_if_pending(self):
        if self._started.is_set():
            return False
        self._cancelled.set()
        return True

    @QtCore.Slot()
    def run(self):
        self._started.set()
        if self._cancelled.is_set():
            self.signals.finished.emit()
            return
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.completed.emit(result)
        finally:
            self.signals.finished.emit()


def submit_task(
    pool,
    function,
    completed,
    failed,
    *,
    finished=None,
    task_key=None,
    auto_start=True,
):
    task = FunctionTask(function, task_key=task_key)
    task.signals.completed.connect(completed)
    task.signals.failed.connect(failed)
    if finished is not None:
        task.signals.finished.connect(finished)
    if auto_start:
        pool.start(task)
    return task
