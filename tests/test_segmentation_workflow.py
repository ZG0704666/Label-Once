from dataclasses import replace
import numpy as np
import pytest
from PIL import Image

from studio.domain import Project, Box, mask_box, read_json, save_json
from studio.annotations import AnnotationConflict, AnnotationStore
from studio.review import ReviewStore
from studio.segmentation import export_segmentation


def project(tmp_path):
    p = Project(tmp_path/'project')
    p.labels.set_classes(['object'])
    Image.new('RGB', (4032,3024)).save(p.images/'sample.png')
    return p


def test_pixel_roundtrip_review_and_export(tmp_path):
    p = project(tmp_path)
    ring = [[.123456789123,.234567891234],[.81,.25],[.72,.78]]
    box = Box(0,.1,.2,.9,.9,polygons=[ring],object_id='stable')
    doc = p.labels.save('sample',[box],0)
    assert doc['size'] == [4032,3024]
    assert doc['objects'][0]['polygons'][0][0][0] == ring[0][0]*4032
    assert p.labels.load('sample')[0].object_id == 'stable'
    review = ReviewStore(p);review.confirm(['sample.png'])
    result = export_segmentation(p)
    assert result['exported']
    from pathlib import Path
    label = next((Path(result['folder'])/'labels').rglob('*.txt'))
    points = np.array(list(map(float,label.read_text().split()[1:]))).reshape(-1,2)
    assert np.max(np.abs((points-np.array(ring))*[4032,3024]))<.01
    changed = p.labels.load('sample')[0];changed.polygons[0][0][0]+=.001
    p.labels.save('sample',[changed],1)
    assert review.status('sample.png') == 'pending'
    with pytest.raises(AnnotationConflict):p.labels.save('sample',[box],1)


def test_projection_repair_and_external_conflict(tmp_path, monkeypatch):
    p=project(tmp_path)
    import studio.annotations as module
    write=module.atomic_write
    def fail(path,text):
        if str(path).endswith('.segments.json'):raise OSError('disk failure')
        return write(path,text)
    monkeypatch.setattr(module,'atomic_write',fail)
    with pytest.raises(OSError):p.labels.save('sample',[Box(0,.1,.1,.8,.8)])
    assert (p.labels.folder/'sample.sync.json').exists()
    monkeypatch.setattr(module,'atomic_write',write)
    assert len(p.labels.load('sample'))==1
    assert read_json(p.labels.folder/'sample.sync.json')['repaired']
    retry=p.labels.load('sample')
    assert p.labels.save('sample',retry,0)['revision']==1
    assert not (p.labels.folder/'sample.sync.json').exists()
    (p.labels.folder/'sample.txt').write_text('0 .5 .5 .2 .2\n')
    with pytest.raises(AnnotationConflict):p.labels.save('sample',[])


def test_backfill_protects_review_and_human_and_survives_restart(tmp_path):
    from studio.tracking_backfill import SampleBackfill
    from studio.annotations import fingerprint
    p=project(tmp_path);p.labels.save('sample',[])
    ReviewStore(p).write({'sample.png':dict(frame=5,run='source',sample_id='stable',import_complete=True,status='pending')})
    run=tmp_path/'tracking';run.mkdir()
    task=dict(project=str(p.root),sample_run='source',sample_versions={'sample.png':fingerprint(p.labels,'sample')})
    automatic=Box(0,.1,.1,.8,.8,'AI',polygons=[[[.1,.1],[.8,.1],[.5,.8]]],target_id=7)
    assert SampleBackfill(task,run).update(5,[automatic])
    first=p.labels.load('sample')[0];assert first.target_id==7
    assert SampleBackfill(task,run).update(5,[automatic])
    assert p.labels.load('sample')[0].object_id==first.object_id
    first.origin='人工';p.labels.save('sample',[first])
    assert not SampleBackfill(task,run).update(5,[automatic])
    assert p.labels.load('sample')[0].origin=='人工'
    ReviewStore(p).confirm(['sample.png'])
    assert not SampleBackfill(task,run).update(5,[automatic])
    assert 'sample.png' in read_json(run/'backfill_conflicts.json')


def test_unchanged_save_preserves_review_and_geometry_revision(tmp_path):
    p=project(tmp_path);p.labels.save('sample',[Box(0,.1,.1,.8,.8,object_id='stable')])
    ReviewStore(p).confirm(['sample.png'])
    before=read_json(p.labels.folder/'sample.annotation.json')
    after=p.labels.save('sample',p.labels.load('sample'),1)
    assert before==after
    assert ReviewStore(p).status('sample.png')=='confirmed'


def test_topology_export_gate_and_explicit_negative(tmp_path):
    p=project(tmp_path)
    mask=np.zeros((100,100),dtype=np.uint8);mask[10:90,10:90]=1;mask[30:60,30:60]=0
    box=mask_box(mask)
    assert box.holes and box.raw_polygons
    p.labels.save('sample',[box]);ReviewStore(p).confirm(['sample.png'])
    assert not export_segmentation(p)['exported']
    assert export_segmentation(p,fill_holes=True)['exported']
    p.labels.save('sample',[Box(0,.1,.1,.8,.8)]);ReviewStore(p).confirm(['sample.png'])
    assert '真实轮廓' in export_segmentation(p)['issues'][0]['reason']
    p.labels.save('sample',[]);ReviewStore(p).confirm(['sample.png'])
    assert export_segmentation(p)['exported']


def test_roi_save_rejected(tmp_path):
    p=project(tmp_path)
    box=Box(0,.1,.1,.8,.8,polygons=[[[.1,.1],[.8,.1],[.5,.8]]],roi=[.2,.2,.7,.7])
    with pytest.raises(ValueError,match='ROI'):p.labels.save('sample',[box])


def test_timestamp_sampling_and_cancel(tmp_path):
    import cv2
    from studio.worker import Worker
    from studio.video_sampling import extract
    from studio.review import import_video
    video=tmp_path/'test.avi'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(64,64))
    for i in range(12):writer.write(np.full((64,64,3),i*10,dtype=np.uint8))
    writer.release()
    task=dict(kind='extract',video=str(video),interval=.5,run=str(tmp_path/'run'))
    worker=Worker(task);save_json(worker.run/'task.json',task)
    result=extract(worker)
    assert result['count']==3
    manifest=read_json(worker.run/'frame_manifest.json')
    assert [o['frame'] for o in manifest['outputs']]==[0,5,10]
    p=project(tmp_path);names=import_video(p,worker.run)['names']
    assert len(names)==3
    manifest['state']='cancelled';save_json(worker.run/'frame_manifest.json',manifest)
    with pytest.raises(ValueError,match='完整'):import_video(p,worker.run)
    worker.task['interval']=0
    with pytest.raises(ValueError):extract(worker)


@pytest.mark.parametrize(('step','expected'), [(5,[0,5,10]),(10,[0,10]),(15,[0]),(20,[0]),(30,[0])])
def test_frame_step_sampling_presets(tmp_path, step, expected):
    import cv2
    from studio.worker import Worker
    from studio.video_sampling import extract
    video=tmp_path/'preset.avi'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(64,64))
    for i in range(12):writer.write(np.full((64,64,3),i*10,dtype=np.uint8))
    writer.release()
    task=dict(kind='extract',video=str(video),frame_step=step,run=str(tmp_path/f'run-{step}'))
    worker=Worker(task)
    result=extract(worker)
    manifest=read_json(worker.run/'frame_manifest.json')
    assert result['count']==len(expected)
    assert [item['frame'] for item in manifest['outputs']]==expected


def test_frame_step_sampling_rejects_non_preset(tmp_path):
    from studio.worker import Worker
    from studio.video_sampling import extract
    video=tmp_path/'unused.avi';video.write_bytes(b'video')
    worker=Worker(dict(kind='extract',video=str(video),frame_step=7,run=str(tmp_path/'invalid')))
    with pytest.raises(ValueError,match='只能是'):
        extract(worker)


def test_vfr_sampling_cancel_resume_and_bad_timestamps(tmp_path,monkeypatch):
    """Uneven presentation times, including several targets hitting one frame."""
    import cv2
    from studio.worker import Worker
    from studio.video_sampling import extract
    video=tmp_path/'vfr.mp4';video.write_bytes(b'fixture-content-fingerprint')
    times=[40,140,390,800,840,1200]
    class Capture:
        def __init__(self,*args):self.index=-1
        def isOpened(self):return True
        def get(self,key):return len(times) if key==cv2.CAP_PROP_FRAME_COUNT else times[self.index]
        def read(self):
            self.index+=1
            return (True,np.zeros((32,32,3),np.uint8)) if self.index<len(times) else (False,None)
        def release(self):pass
    monkeypatch.setattr(cv2,'VideoCapture',Capture)
    worker=Worker(dict(kind='extract',video=str(video),interval=.2,run=str(tmp_path/'vfr-run')))
    original=worker.check;calls=0
    def cancel():
        nonlocal calls
        calls+=1
        if calls==4:raise InterruptedError('cancel fixture')
    worker.check=cancel
    with pytest.raises(InterruptedError):extract(worker)
    assert read_json(worker.run/'frame_manifest.json')['state']=='cancelled'
    worker.check=original;result=extract(worker)
    manifest=read_json(worker.run/'frame_manifest.json')
    assert result['count']==5
    assert [o['frame'] for o in manifest['outputs']]==[0,2,3,4,5]
    assert len({o['sample_id'] for o in manifest['outputs']})==5
    assert len(list((worker.run/'video_images').glob('*.jpg')))==5
    # A duplicate timestamp must fail, rather than falling back to average FPS.
    times[2]=times[1]
    worker=Worker(dict(kind='extract',video=str(video),interval=.2,run=str(tmp_path/'bad-run')))
    with pytest.raises(ValueError,match='时间戳不可靠'):extract(worker)
    assert read_json(worker.run/'frame_manifest.json')['state']=='failed'
