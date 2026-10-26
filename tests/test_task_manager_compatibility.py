import os
import time
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt5.QtWidgets import QApplication
from studio.qt_tasks import TaskManager


def drain(app, values, timeout=5):
    end = time.monotonic() + timeout
    while not values and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)


def test_finished_bool_matches_legacy_semantics(tmp_path):
    app = QApplication.instance() or QApplication([])
    manager = TaskManager()
    events = []
    done = []
    logs = []
    manager.message.connect(events.append)
    manager.finished.connect(done.append)
    manager.log.connect(logs.append)
    manager.start(dict(kind='model_info', run=str(tmp_path/'missing'), model=str(tmp_path/'missing.pt'),
                       project=str(tmp_path), session=None, request=None))
    deadline = time.monotonic() + 40
    while manager.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    drain(app, done)
    assert not manager.busy
    assert done == [False]
    assert any(e['event'] == 'error' for e in events)
    assert (tmp_path/'missing'/'process.log').exists()
    assert manager.last_task['kind'] == 'model_info'
    assert str(manager.run) == str(tmp_path/'missing')


def test_cancel_writes_marker_and_process_manager_tails_log(tmp_path):
    app = QApplication.instance() or QApplication([])
    manager = TaskManager()
    done = []
    manager.finished.connect(done.append)
    manager.start(dict(kind='model_info', run=str(tmp_path/'cancelrun'), model=str(tmp_path/'cancelrun/none.pt'),
                       project=str(tmp_path), session=None, request=None))
    manager.cancel()
    deadline = time.monotonic() + 40
    while manager.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    drain(app, done)
    assert (tmp_path/'cancelrun'/'cancel').exists()
    assert done == [False]
