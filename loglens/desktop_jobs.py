"""Single worker, cancellable requests, and generation-checked GUI delivery."""

from concurrent.futures import CancelledError, ThreadPoolExecutor
from queue import Empty, SimpleQueue
from threading import Event

from PySide6.QtCore import QObject, QTimer, Signal


class Jobs(QObject):
    activity = Signal(str)
    progress = Signal(int)
    error = Signal(str)
    idle = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="loglens")
        self.results = SimpleQueue()
        self.generation = 0
        self.pending = None
        self.token = Event()
        self.active = False
        self.label = ""
        self.timer = QTimer(self, interval=14)
        self.timer.timeout.connect(self.drain)

    def start(self, label, work, deliver):
        self.cancel(announce=False)
        generation = self.generation
        self.token = token = Event()
        self.active = True
        self.label = label
        self.activity.emit(label)

        def report(percent):
            self.results.put((generation, "progress", percent))

        self.pending = self.executor.submit(work, token, report)
        self.pending.add_done_callback(lambda future: self.results.put((generation, deliver, future)))
        self.timer.start()

    def cancel(self, announce=True):
        self.token.set()
        self.generation += 1
        if self.pending:
            self.pending.cancel()
        was_busy, self.active = self.active, False
        if announce and was_busy:
            self.activity.emit("Cancelled")
            self.idle.emit()

    def drain(self):
        while True:
            try:
                generation, target, value = self.results.get_nowait()
            except Empty:
                break
            if generation != self.generation:
                continue
            if target == "progress":
                self.progress.emit(value)
                continue
            self.active = False
            try:
                result = value.result()
            except CancelledError:
                pass
            except Exception as exc:
                self.error.emit(str(exc) or "Operation cancelled.")
            else:
                target(result)
            if not self.active:
                self.idle.emit()
        if not self.active and (not self.pending or self.pending.done()):
            self.timer.stop()

    def shutdown(self):
        self.cancel(False)
        self.timer.stop()
        self.executor.shutdown(wait=True, cancel_futures=True)
