from pathlib import Path
import cv2
import numpy as np
import pytest
from studio.domain import Project, read_json, save_json, mask_box
from studio.service import StudioService
from studio.contour_simplification import simplify_ring


def test_append_class_preserves_existing_ids(tmp_path):
    service=StudioService();service.project=Project(tmp_path/'project')
    try:
        service.project.labels.set_classes(['first','second'])
        result=service.dispatch('classes.ensure',{'name':' second '})
        assert result['class_id']==1 and not result['created']
        result=service.dispatch('classes.ensure',{'name':'third'})
        assert result['class_id']==2 and result['classes']==['first','second','third']
        for name in ('','  ','a\nb'):
            with pytest.raises(ValueError):service.dispatch('classes.ensure',{'name':name})
    finally:service.close()


def test_paused_source_requires_gpu_ack_and_token(tmp_path):
    service=StudioService();service.project=Project(tmp_path/'project')
    run=tmp_path/'run';run.mkdir()
    service.tasks.task={'kind':'tracking','run':str(run)}
    service.tasks._busy=True
    try:
        for state in ({},{'state':'paused','pause_token':'token'},
                      {'state':'paused','pause_token':'token','gpu_released':False}):
            save_json(run/'frame_manifest.json',state)
            with pytest.raises(ValueError):service.paused_source({'pause_token':'token'})
        state=dict(state='paused',pause_token='token',gpu_released=True,preview=str(run/'frame.jpg'))
        save_json(run/'frame_manifest.json',state)
        with pytest.raises(ValueError):service.paused_source({'pause_token':'stale'})
        assert service.paused_source({'pause_token':'token'})==run/'frame.jpg'
        save_json(run/'control.json',{'action':'commit'})
        with pytest.raises(ValueError):service.paused_source({'pause_token':'token'})
    finally:
        service.tasks._busy=False;service.close()


def test_finish_review_control_requires_the_current_pause_token(tmp_path):
    service=StudioService();service.project=Project(tmp_path/'项目 空格')
    run=tmp_path/'run';run.mkdir()
    service.tasks.task={'kind':'tracking','run':str(run)}
    service.tasks._busy=True
    save_json(run/'frame_manifest.json',dict(state='paused',pause_token='current',gpu_released=True,
                                             preview=str(run/'frame.jpg')))
    try:
        with pytest.raises(ValueError):
            service.dispatch('task.control',dict(project=str(service.project.root),control={
                'action':'finish_review','pause_token':'stale'}))
        result=service.dispatch('task.control',dict(project=str(service.project.root),control={
            'action':'finish_review','pause_token':'current','frame':12,'targets':[]}))
        assert result['accepted']
        assert read_json(run/'control.json')['action']=='finish_review'
    finally:
        service.tasks._busy=False;service.close()


def test_video_drafts_are_isolated_for_same_name_in_different_directories(tmp_path):
    service=StudioService();service.project=Project(tmp_path/'项目 空格')
    first=tmp_path/'摄像头 A'/'clip.mp4';second=tmp_path/'摄像头 B'/'clip.mp4'
    first.parent.mkdir();second.parent.mkdir();first.write_bytes(b'a');second.write_bytes(b'b')
    try:
        service.dispatch('video.draft.save',dict(project=str(service.project.root),video=str(first),
                         frame=3,boxes=[dict(cls=0,box=[.1,.1,.2,.2])]))
        service.dispatch('video.draft.save',dict(project=str(service.project.root),video=str(second),
                         frame=3,boxes=[dict(cls=1,box=[.2,.2,.3,.3])]))
        one=service.dispatch('video.draft.load',dict(project=str(service.project.root),video=str(first),frame=3))
        two=service.dispatch('video.draft.load',dict(project=str(service.project.root),video=str(second),frame=3))
        assert one['boxes'][0]['cls']==0 and two['boxes'][0]['cls']==1
    finally:service.close()


def test_simplification_preserves_thin_branch_and_hole():
    mask=np.zeros((180,220),np.uint8)
    cv2.ellipse(mask,(85,90),(55,65),0,0,360,1,-1)
    mask[88:92,85:200]=1
    cv2.circle(mask,(70,90),15,0,-1)
    box=mask_box(mask)
    assert box.holes and box.raw_polygons
    assert max(p[0] for ring in box.polygons for p in ring)>.89
    rebuilt=np.zeros_like(mask)
    cv2.fillPoly(rebuilt,[np.rint(np.asarray(r)*[220,180]).astype(np.int32) for r in box.polygons],1)
    cv2.fillPoly(rebuilt,[np.rint(np.asarray(r)*[220,180]).astype(np.int32) for r in box.holes],0)
    assert rebuilt[90,195] and not rebuilt[90,70]
    assert sum(map(len,box.polygons))<=sum(map(len,box.raw_polygons))


def test_circle_is_reduced_with_pixel_error_bound():
    mask=np.zeros((300,300),np.uint8);cv2.circle(mask,(150,150),110,1,-1)
    raw=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0][0].reshape(-1,2)
    result=np.asarray(simplify_ring(raw),np.float32)
    assert 3<=len(result)<len(raw)
    rebuilt=np.zeros_like(mask);cv2.fillPoly(rebuilt,[np.rint(result).astype(np.int32)],1)
    assert np.count_nonzero(rebuilt&mask)/np.count_nonzero(rebuilt|mask)>=.99


def test_keyframe_association_rejects_ambiguous_objects(tmp_path):
    from studio.tracking_backfill import SampleBackfill
    from studio.domain import Box
    backfill=SampleBackfill.__new__(SampleBackfill)
    backfill.project=Project(tmp_path/'project')
    backfill.samples={2:'frame.jpg'}
    ring=[[.1,.1],[.4,.1],[.4,.4]]
    box=Box(0,.1,.1,.4,.4,polygons=[ring])
    backfill.project.labels.save('frame',[box])
    targets={7:dict(cls=0,object_id='stable')}
    assert backfill.human_keyframes(targets,0)[2][7]['object_id']=='stable'
    with pytest.raises(ValueError):
        backfill.human_keyframes({**targets,8:dict(cls=0)},0)
    box.target_id=7;backfill.project.labels.save('frame',[box])
    assert 7 in backfill.human_keyframes({**targets,8:dict(cls=0)},0)[2]
