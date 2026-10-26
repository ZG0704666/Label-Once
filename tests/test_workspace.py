import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PIL import Image
from PyQt5.QtWidgets import QApplication,QMessageBox
from studio.app import Window
from studio.domain import Box,Project
from studio.review import ReviewStore
from studio.imports import import_images


def test_import_map_and_pending(tmp_path):
    source=Project(tmp_path/'source');source.labels.set_classes(['猫','狗'])
    Image.new('RGB',(200,100)).save(source.images/'1.png')
    source.labels.save('1',[Box(1,.1,.1,.8,.8)])
    target=Project(tmp_path/'target');target.labels.set_classes(['狗'])
    names=import_images(target,source.image_paths()+source.image_paths())
    assert names==['1.png'] and target.labels.load('1')[0].cls==0
    assert ReviewStore(target).status('1.png')=='pending'
    target.labels.save('1',[])
    assert import_images(target,source.image_paths())==[]
    assert target.labels.load('1')==[]
    other=tmp_path/'other';other.mkdir();Image.new('RGB',(200,100),'red').save(other/'1.png')
    renamed=import_images(target,[other/'1.png'])
    assert len(renamed)==1 and renamed[0]!='1.png'
    assert len(target.image_paths())==2 and target.labels.load('1')==[]


def test_resume_completion_and_failure(tmp_path,monkeypatch):
    from studio import config
    monkeypatch.setattr(config,'CONFIG_ROOT',tmp_path/'settings')
    monkeypatch.setattr(QMessageBox,'exec_',lambda *a:QMessageBox.Ok)
    app=QApplication.instance() or QApplication([])
    w=Window();w.load_project(tmp_path/'project')
    source=tmp_path/'source';source.mkdir()
    for name in ['a.png','b.png','c.png']:Image.new('RGB',(100,100)).save(source/name)
    w.import_materials(source.iterdir());w.navigate_image(1)
    assert w.current_image.name=='b.png'
    assert not (w.project.labels.folder/'a.txt').exists()
    w.close();w=Window();w.load_project(tmp_path/'project')
    assert w.current_image.name=='b.png' and w.workspace_stack.currentIndex()==0 and w.data_stack.currentIndex()==1
    w.confirm_next();assert ReviewStore(w.project).status('b.png')=='confirmed'
    assert w.project.labels.load('b')==[] and w.current_image.name=='c.png'
    old=w.current_image
    original=w.label_store.save
    monkeypatch.setattr(w.label_store,'save',lambda *a:(_ for _ in ()).throw(OSError('disk error')))
    import pytest
    with pytest.raises(OSError):w.confirm_next()
    assert w.current_image==old
    monkeypatch.setattr(w.label_store,'save',original)
    w.confirm_next();w.confirm_next()
    assert all(ReviewStore(w.project).status(p.name)=='confirmed' for p in w.project.image_paths())
    assert w.data_stack.currentIndex()==0
    w.close()
