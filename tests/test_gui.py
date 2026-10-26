import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PyQt5.QtWidgets import QApplication
from studio.app import Window


def test_window_and_annotation(tmp_path,monkeypatch):
    from PIL import Image
    from studio import config
    monkeypatch.setattr(config,'CONFIG_ROOT',tmp_path/'settings')
    app=QApplication.instance() or QApplication([])
    window=Window();window.load_project(tmp_path/'中文项目')
    window.show();app.processEvents()
    window.project.labels.set_classes(['物体'])
    Image.new('RGB',(100,100)).save(window.project.images/'图片.png')
    window.refresh();window.annotate_selected(window.files.item(0));window.save_annotation()
    assert not (window.project.labels.folder/'图片.txt').exists()
    assert window.workspace_stack.count()==3
    assert window.nav.item(3).text()=='视频追踪标注'
    window.nav.setCurrentRow(3);app.processEvents()
    assert window.data_stack.currentWidget() is window.tracking_window
    portrait=tmp_path/'portrait.png';Image.new('RGB',(360,640)).save(portrait)
    canvas=window.tracking_window.canvas;canvas.load(portrait,[],['物体']);app.processEvents()
    window.resize(1600,1050);app.processEvents();app.processEvents()
    shown=canvas.transform().mapRect(canvas.sceneRect())
    assert shown.height()<=canvas.viewport().height()
    assert shown.height()>canvas.viewport().height()*.90
    window.nav.setCurrentRow(2)
    window.sam_request='new';window.sam_class=0
    window.task.last_task={'kind':'sam'}
    result={'image':str(window.current_image),'request':'old','boxes':[dict(cls=0,x1=.1,y1=.1,x2=.5,y2=.5,origin='AI',score=None)]}
    window.on_event({'event':'result','result':result})
    assert not window.canvas.boxes()
    result['request']='new'
    window.on_event({'event':'result','result':result})
    assert len(window.canvas.boxes())==1
    window.close()
