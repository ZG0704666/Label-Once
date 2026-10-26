import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import pytest
from PIL import Image
from studio.domain import Project,Labels,Box,save_json
from studio.review import ReviewStore,import_video
from studio.dataset import DatasetStore


def run_fixture(tmp_path,manual=False):
    run=tmp_path/'run';images=run/'video_images';images.mkdir(parents=True)
    labels=Labels(run/'video_images_labels');labels.set_classes(['car','person'])
    outputs=[]
    for i in range(3):
        p=images/f'frame_{i:06d}_f{i}_t{i*100}.jpg';Image.new('RGB',(64,48),'red').save(p)
        labels.save(p.stem,[Box(0,.1,.2,.5,.7,'AI')])
        outputs.append(dict(frame=i,image=str(p)))
    save_json(run/'task.json',dict(kind='extract' if manual else 'tracking'))
    save_json(run/'frame_manifest.json',dict(outputs=outputs))
    return run


def test_import_review_training(tmp_path):
    run=run_fixture(tmp_path);project=Project(tmp_path/'project');project.labels.set_classes(['person','car'])
    result=import_video(project,run);name=result['names'][0];store=ReviewStore(project)
    assert project.labels.load(Path(name).stem)[0].cls==1
    assert store.status(name)=='pending'
    with pytest.raises(ValueError,match='没有已审核'):DatasetStore(project).create()
    store.confirm(result['names']);version=DatasetStore(project).create()
    assert len(DatasetStore(project).manifest(version)['images'])==3
    project.labels.save(Path(name).stem,[])
    assert store.status(name)=='pending'
    assert import_video(project,run)==result
    assert not project.labels.load(Path(name).stem)
    other=DatasetStore(project).create();assert len(DatasetStore(project).manifest(other)['images'])==2
    assert DatasetStore(project).manifest(other)['excluded_pending']==1
    store.confirm([name]);assert store.status(name)=='confirmed'
    project.batch_rename('renamed_');assert all(store.status(p.name)=='confirmed' for p in project.image_paths())
    assert import_video(project,run)['names']==[p.name for p in project.image_paths()]


def test_invalid_import_and_manual(tmp_path):
    run=run_fixture(tmp_path);project=Project(tmp_path/'project')
    next((run/'video_images_labels').glob('frame*.txt')).unlink()
    with pytest.raises(ValueError,match='缺少同名'):import_video(project,run)
    assert not project.image_paths()
    save_json(run/'task.json',dict(kind='extract'))
    result=import_video(project,run)
    assert len(result['names'])==3
    assert all(ReviewStore(project).status(n)=='pending' for n in result['names'])


def test_canvas_targets_history_and_readonly(tmp_path,monkeypatch):
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt,QPoint,QPointF
    from PyQt5.QtTest import QTest
    from studio.app import Window
    from studio import config
    monkeypatch.setattr(config,'CONFIG_ROOT',tmp_path/'settings')
    app=QApplication.instance() or QApplication([]);window=Window();window.load_project(tmp_path/'project')
    window.project.labels.set_classes(['car']);window.refresh();window.nav.setCurrentRow(3);window.show();app.processEvents()
    canvas=window.tracking_window.canvas;p=tmp_path/'image.png';Image.new('RGB',(640,480)).save(p)
    canvas.load(p,[],['car']);app.processEvents();canvas.mode='draw'
    assert canvas.cursor().shape()==Qt.CrossCursor
    a=canvas.mapFromScene(QPointF(150,100));b=canvas.mapFromScene(QPointF(350,280))
    QTest.mousePress(canvas.viewport(),Qt.LeftButton,pos=a);QTest.mouseMove(canvas.viewport(),b,20);QTest.mouseRelease(canvas.viewport(),Qt.LeftButton,pos=b)
    assert len(window.tracking_window.targets)==1 and canvas.mode=='select'
    item=next(i for i in canvas.scene().items() if hasattr(i,'target_id'));item.setSelected(True)
    canvas.delete_selected();assert not window.tracking_window.targets
    canvas.history_step(-1);assert len(window.tracking_window.targets)==1
    canvas.history_step(1);assert not window.tracking_window.targets
    canvas.set_read_only(True);canvas.history_step(-1);assert not canvas.boxes()
    window.close()


def test_real_user_output_import(tmp_path):
    run=Path(os.environ.get('YOLOTRAIN_HISTORICAL_RUN', str(tmp_path/'missing_historical_run')))
    if not run.exists():pytest.skip('User result not available')
    project=Project(tmp_path/'review');result=import_video(project,run)
    assert result['count']>0
    assert all(project.labels.load(Path(n).stem) for n in result['names'])

def test_review_gui_and_stale_preview(tmp_path,monkeypatch):
    from PyQt5.QtWidgets import QApplication
    from studio.app import Window
    from studio import config
    monkeypatch.setattr(config,'CONFIG_ROOT',tmp_path/'settings')
    app=QApplication.instance() or QApplication([]);window=Window();window.load_project(tmp_path/'project')
    result=import_video(window.project,run_fixture(tmp_path));window.open_review_batch(result)
    assert len(window.canvas.boxes())==1 and window.nav.currentRow()==2
    first=window.current_image;window.confirm_next()
    assert ReviewStore(window.project).status(first.name)=='confirmed'
    window.review_filter.setCurrentIndex(1);assert len(window.images)==2
    window.canvas.scene().clearSelection()
    item=next(i for i in window.canvas.scene().items() if hasattr(i,'target_id'));item.setSelected(True)
    window.canvas.delete_selected();assert window.project.labels.load(window.current_image.stem)==[]
    window.show_image();assert not window.canvas.boxes()
    t=window.tracking_window;t.session='new';t.run='run';t.state='paused';t.current_frame=t.preview_frame=10
    event=dict(event='tracking_frame',session='old',run='run',frame=11,path='missing',boxes={})
    t.on_event(event);event.update(session='new',frame=9);t.on_event(event)
    event['frame']=10;t.on_event(event)
    assert t.current_frame==10
    window.close()
