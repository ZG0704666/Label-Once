import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from studio.canvas import AnnotationCanvas, RectItem
from studio.domain import Box, Labels, mask_box


def test_contour_persistence_and_geometry(tmp_path):
    from PIL import Image
    app=QApplication.instance() or QApplication([])
    mask=np.zeros((100,100),dtype=np.uint8)
    mask[10:80,10:25]=1;mask[65:80,10:80]=1
    box=mask_box(mask)
    assert box.polygons and len(box.polygons[0])>4
    labels=Labels(tmp_path/'labels');labels.set_classes(['object']);labels.save('a',[box])
    loaded=labels.load('a')[0];assert loaded.polygons==box.polygons
    image=tmp_path/'a.png';Image.new('RGB',(100,100)).save(image)
    canvas=AnnotationCanvas();canvas.load(image,[loaded],['object'])
    item=next(i for i in canvas.scene().items() if isinstance(i,RectItem))
    item.moveBy(10,0)
    assert abs(canvas.boxes()[0].polygons[0][0][0]-box.polygons[0][0][0]-.1)<1e-6
    canvas.changed.emit();canvas.history_step(-1)
    assert np.allclose(canvas.boxes()[0].polygons,box.polygons)
    labels.reorder(['renamed'],{0:0});assert labels.load('a')[0].polygons==box.polygons
    # External TXT edits must invalidate stale outlines.
    (labels.folder/'a.txt').write_text('0 .5 .5 .2 .2\n')
    from studio.annotations import AnnotationConflict
    import pytest
    with pytest.raises(AnnotationConflict):
        labels.load('a')
    canvas.close()


def test_held_keys_release_and_focus(tmp_path):
    app=QApplication.instance() or QApplication([])
    canvas=AnnotationCanvas();canvas.show();canvas.setFocus();app.processEvents()
    steps=[];canvas.navigate.connect(steps.append)
    QTest.keyPress(canvas,Qt.Key_D);QTest.qWait(580)
    assert len(steps)>=3 and set(steps)=={1}
    QTest.keyRelease(canvas,Qt.Key_D);count=len(steps);QTest.qWait(180)
    assert len(steps)==count
    QTest.keyPress(canvas,Qt.Key_A);assert steps[-1]==-1
    canvas.hide();count=len(steps);QTest.qWait(400);assert len(steps)==count
    canvas.close()


def test_video_navigation_drafts_and_start_frame(tmp_path,monkeypatch):
    import cv2
    from studio.app import Window
    from studio import config
    monkeypatch.setattr(config,'CONFIG_ROOT',tmp_path/'config')
    app=QApplication.instance() or QApplication([])
    window=Window();window.load_project(tmp_path/'project');window.project.labels.set_classes(['object'])
    video=tmp_path/'short.avi';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(100,100))
    for n in range(5):writer.write(np.full((100,100,3),n*40,dtype=np.uint8))
    writer.release();view=window.tracking_window;view.load_video(video)
    view.canvas.add_box(Box(0,.1,.1,.5,.5));view.canvas.changed.emit()
    view.navigate_frame(1);assert view.current_frame==1 and not view.targets
    view.navigate_frame(-1);assert view.current_frame==0 and len(view.targets)==1
    view.navigate_frame(99);assert view.current_frame==4
    view.canvas.add_box(Box(0,.2,.2,.6,.6));view.canvas.changed.emit();view.method.setCurrentIndex(0)
    calls=[];monkeypatch.setattr(window,'start_task',lambda kind,**kwargs:calls.append((kind,kwargs)))
    view.start();assert calls[0][1]['start_frame']==4
    window.close()


def test_f_confirms_only_canvas_without_repeat(tmp_path,monkeypatch):
    from PIL import Image
    from PyQt5.QtWidgets import QLineEdit
    from studio.app import Window
    from studio.review import ReviewStore
    from studio import config
    monkeypatch.setattr(config,'CONFIG_ROOT',tmp_path/'config')
    app=QApplication.instance() or QApplication([])
    w=Window();w.load_project(tmp_path/'project');w.project.labels.set_classes(['object'])
    source=tmp_path/'source';source.mkdir()
    for n in range(3):Image.new('RGB',(100,100)).save(source/f'{n}.png')
    w.import_materials(source.iterdir());w.show();w.canvas.setFocus();app.processEvents()
    first=w.current_image
    QTest.keyClick(w.canvas,Qt.Key_F)
    assert ReviewStore(w.project).status(first.name)=='confirmed' and w.current_image!=first
    assert not w.completion_shortcut.autoRepeat()
    current=w.current_image
    edit=QLineEdit(w);edit.show();edit.setFocus();app.processEvents();QTest.keyClick(edit,Qt.Key_F)
    assert edit.text()=='f' and w.current_image==current
    w.close()
