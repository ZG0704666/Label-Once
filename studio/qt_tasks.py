"""Qt-compatible facade over the single ProcessManager supervisor."""
from pathlib import Path
from PyQt5.QtCore import QObject, pyqtSignal
from .domain import atomic_write, save_json
from .processes import ProcessManager


class TaskManager(QObject):
    message = pyqtSignal(dict)
    log = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._failed = False
        self._received_terminal = False
        self.last_task = None
        self.run = None
        self.manager = ProcessManager(self._on_event, self._on_log)

    def _on_event(self, event):
        name = event.get('event')
        if name in ('result', 'error', 'cancelled'):
            self._received_terminal = True
            if name == 'error':
                self._failed = True
        if name == 'finished':
            self.finished.emit(not self._failed and event.get('exit_code') == 0 and self._received_terminal)
            return
        self.message.emit(dict(event))

    def _on_log(self, text):
        self.log.emit(text)

    @property
    def busy(self):
        return self.manager.busy

    def start(self, task):
        self._failed = self._received_terminal = False
        self.last_task = task
        self.run = Path(task['run'])
        self.manager.start(task)

    def cancel(self, _clicked=False):
        if self.manager.busy:
            self.manager.cancel()
        elif self.run:
            atomic_write(self.run/'cancel', 'cancel')

    def control(self, command):
        if self.run:
            # Match the legacy Qt facade: a fresh command supersedes an unread one.
            save_json(self.run/'control.json', command)

    def kill(self):
        if self.busy:
            self.manager.cancel(force=True)

    def close(self):
        self.manager.close()
