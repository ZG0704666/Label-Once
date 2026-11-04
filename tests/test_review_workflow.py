import os
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


def test_real_user_output_import(tmp_path):
    run=Path(os.environ.get('YOLOTRAIN_HISTORICAL_RUN', str(tmp_path/'missing_historical_run')))
    if not run.exists():pytest.skip('User result not available')
    project=Project(tmp_path/'review');result=import_video(project,run)
    assert result['count']>0
    assert all(project.labels.load(Path(n).stem) for n in result['names'])
