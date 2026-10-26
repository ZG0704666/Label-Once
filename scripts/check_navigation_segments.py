"""Source / frozen GUI check using real SAM masks and video preview."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.app import main
from studio.domain import Box,read_json,unique_id,save_json
from studio.imports import import_images
from PyQt5.QtCore import QTimer,Qt,QEventLoop,QEvent
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication,QMainWindow
root=Path(__file__).resolve().parents[1]
out=root/'acceptance'/'navigation_segments';out.mkdir(exist_ok=True)
original=QApplication.exec_

def run():
    app=QApplication.instance();w=next(x for x in app.topLevelWidgets() if isinstance(x,QMainWindow))
    def check():
        try:
            w.load_project(out/('project_'+unique_id()));w.project.labels.set_classes(['person'])
            import_images(w.project,[root/'acceptance/sam/input.jpg'])
            result=read_json(root/'acceptance/sam/sam_result.json');boxes=[Box(**b) for b in result['boxes']]
            assert boxes and boxes[0].polygons
            w.project.labels.save('input',boxes);w.refresh();w.annotate_selected(w.files.item(0));w.canvas.setFocus();app.processEvents()
            assert w.canvas.boxes()[0].polygons
            w.grab().save(str(out/'sam_polygon.png'))
            t=w.tracking_window;w.route(3);t.load_video(root/'acceptance/sam/pair.mp4');t.canvas.setFocus();app.processEvents()
            t.navigate_frame(1);assert t.current_frame==1
            QApplication.sendEvent(t.canvas,QKeyEvent(QEvent.KeyPress,Qt.Key_D,Qt.NoModifier))
            loop=QEventLoop();QTimer.singleShot(650,loop.quit);loop.exec_()
            QApplication.sendEvent(t.canvas,QKeyEvent(QEvent.KeyRelease,Qt.Key_D,Qt.NoModifier))
            assert t.current_frame>=4
            stopped=t.current_frame;loop=QEventLoop();QTimer.singleShot(250,loop.quit);loop.exec_();assert t.current_frame==stopped
            assert t.next_frame_button.autoRepeat() and w.next_image_button.autoRepeat()
            w.grab().save(str(out/'video_navigation.png'))
            save_json(out/'gui.json',dict(ok=True,frozen=getattr(sys,'frozen',False),polygons=True,held_key=True,release=True,frame=stopped))
            app.quit()
        except Exception as error:
            save_json(out/'gui.json',dict(ok=False,error=str(error)));app.exit(1)
    QTimer.singleShot(0,check)
    return original()
QApplication.exec_=staticmethod(run)
main()
