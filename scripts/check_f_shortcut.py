"""Validate F through the packaged Qt shortcut and completion flow."""
import sys,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.app import main
from studio.domain import save_json,unique_id
from studio.review import ReviewStore
from PyQt5.QtCore import Qt,QTimer,QEvent
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication,QMainWindow
root=Path(__file__).resolve().parents[1];out=root/'acceptance'/'f_shortcut';out.mkdir(exist_ok=True)
original=QApplication.exec_
def run():
    app=QApplication.instance();w=next(x for x in app.topLevelWidgets() if isinstance(x,QMainWindow))
    def check():
        try:
            w.load_project(out/unique_id());w.project.labels.set_classes(['person'])
            for n in range(3):shutil.copy2(root/'acceptance/sam/input.jpg',w.project.images/f'{n}.jpg')
            w.refresh();w.annotate_selected(w.files.item(0));w.activateWindow();w.canvas.setFocus();app.processEvents()
            first=w.current_image
            QApplication.sendEvent(w.canvas,QKeyEvent(QEvent.KeyPress,Qt.Key_F,Qt.NoModifier))
            QApplication.sendEvent(w.canvas,QKeyEvent(QEvent.KeyRelease,Qt.Key_F,Qt.NoModifier))
            assert w.current_image!=first and ReviewStore(w.project).status(first.name)=='confirmed'
            second=w.current_image
            QApplication.sendEvent(w.canvas,QKeyEvent(QEvent.KeyPress,Qt.Key_F,Qt.NoModifier,'f',True,1))
            assert w.current_image==second and not w.completion_shortcut.autoRepeat()
            assert 'F' in w.completion_button.text()
            save_json(out/'gui.json',dict(ok=True,frozen=getattr(sys,'frozen',False),confirmed=True,no_repeat=True))
            app.quit()
        except Exception as e:
            import traceback
            save_json(out/'gui.json',dict(ok=False,error=traceback.format_exc()));app.exit(1)
    QTimer.singleShot(0,check)
    return original()
QApplication.exec_=staticmethod(run)
main()
