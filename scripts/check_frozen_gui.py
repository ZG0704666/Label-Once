"""Run with the packaged EXE's script launcher; validate GUI -> QProcess -> model."""
import json
import sys
from pathlib import Path
from studio.app import main
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication,QMainWindow

root=Path(__file__).resolve().parents[1]
report=root/'acceptance/frozen/gui.json'
original_exec=QApplication.exec_
def check():
    app=QApplication.instance()
    window=next(w for w in app.topLevelWidgets() if isinstance(w,QMainWindow))
    window.load_project(root/'acceptance/验证项目')
    assert window.workspace_stack.count()==3
    assert window.nav.item(3).text()=='视频追踪标注'
    window.nav.setCurrentRow(3);app.processEvents()
    canvas=window.tracking_window.canvas
    canvas.load(root/'acceptance/portrait_preview.png',[],['物体'])
    app.processEvents();app.processEvents()
    shown=canvas.transform().mapRect(canvas.sceneRect())
    assert canvas.viewport().height()*.90<shown.height()<=canvas.viewport().height()
    assert window.tracking_window.start_button.isVisible()
    events=[]
    window.task.message.connect(events.append)
    def finished(ok):
        report.write_text(json.dumps(dict(frozen=getattr(sys,'frozen',False),ok=ok,model_count=window.train_model.count(),events=events),ensure_ascii=False,indent=2),encoding='utf-8')
        QTimer.singleShot(0,app.quit)
    window.task.finished.connect(finished)
    model=Path(sys.executable).parent/'models/yolov8n.pt'
    QTimer.singleShot(0,lambda:window.start_task('predict',model=str(model),source=str(root/'acceptance/验证项目/Main/测试_00.jpg'),mode='image',device='cpu'))
    QTimer.singleShot(60000,app.quit)
    return original_exec()
QApplication.exec_=staticmethod(check)
main()
