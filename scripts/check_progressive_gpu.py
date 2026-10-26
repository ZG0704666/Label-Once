"""Real GPU acceptance for JSONL SAM and sampled-video polygon correction."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['YOLO_AUTOINSTALL'] = 'False'
import cv2
import numpy as np
import torch
from ultralytics.utils import ASSETS
from studio.domain import Project, Box, read_json, save_json
from studio.annotations import fingerprint
from studio.review import ReviewStore, import_video
from studio.segmentation import export_segmentation
from studio.worker import Worker
from studio.tracking import Sam2Backend
import studio.worker as worker_module


def main():
    assert torch.cuda.is_available(), 'GPU acceptance requires CUDA'
    out = ROOT/'acceptance'/'progressive_gpu'/uuid.uuid4().hex
    out.mkdir(parents=True)
    p = Project(out/'project');p.labels.set_classes(['person'])
    pixels = cv2.resize(cv2.imread(str(ASSETS/'zidane.jpg')), (640,360))
    image = p.images/'input.jpg';cv2.imencode('.jpg', pixels)[1].tofile(image)
    model = str(ROOT/'sam'/'sam2_t.pt')
    report = dict(device=torch.cuda.get_device_name(0), root=str(out), checks=[])
    # Use the actual JSONL boundary, including stdout isolation and cached requests.
    with (out/'bridge-stderr.log').open('w', encoding='utf-8') as err:
        proc = subprocess.Popen([sys.executable,'-m','studio.bridge'],cwd=ROOT,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=err,text=True,encoding='utf-8')
        counter = 0
        def call(method, params):
            nonlocal counter
            counter += 1
            proc.stdin.write(json.dumps(dict(version=1,id=counter,method=method,params=params))+'\n');proc.stdin.flush()
            response = json.loads(proc.stdout.readline())
            assert response['id']==counter, response
            assert 'error' not in response, response
            return response['result']
        try:
            call('project.open',dict(path=str(p.root)))
            options=dict(project=str(p.root),name=image.name,model=model,device='0',imgsz=1024,
                class_id=0,object_id='gpu-same-object',epsilon=1,request=1,
                points=[[200,180]],labels=[1],bbox=[70,75,310,355],roi=[70,75,310,355])
            first=call('sam.segment', options)['box']
            options.update(points=[[200,180],[300,80]],labels=[1,0],request=2)
            second=call('sam.segment', options)['box']
            assert first['object_id']==second['object_id']=='gpu-same-object'
            assert second['polygons']
            assert all(70-1e-6<=x*640<=310+1e-6 and 75-1e-6<=y*360<=355+1e-6 for r in second['polygons'] for x,y in r)
            saved=call('annotation.save',dict(project=str(p.root),name=image.name,boxes=[second],expected_revision=0,confirm=True))
            loaded=call('annotation.load',dict(project=str(p.root),name=image.name))
            assert saved['revision']==loaded['revision'] and loaded['boxes'][0]['object_id']==second['object_id']
            report['checks'].append('JSONL multi-positive/negative + bbox + hard ROI + same object + save/load')
        finally:
            proc.stdin.close();proc.wait(timeout=60)
    exported=export_segmentation(p,split_components=True,fill_holes=True)
    assert exported['exported'];report['checks'].append('reviewed SAM polygon segmentation export')
    video=out/'source.mp4';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),10,(640,360))
    for _ in range(12):writer.write(pixels)
    writer.release()
    extract_task=dict(kind='extract',video=str(video),interval=.2,run=str(out/'extract'))
    worker=Worker(extract_task);save_json(worker.run/'task.json',extract_task)
    result=worker.execute();names=import_video(p,worker.run)['names'];assert len(names)==6
    manifest=read_json(worker.run/'frame_manifest.json')
    assert [o['frame'] for o in manifest['outputs']]==[0,2,4,6,8,10]
    ring=[[.15,.25],[.4,.25],[.4,.85],[.15,.85]]
    target=dict(cls=0,box=[.15,.25,.4,.85],polygons=[ring],holes=None)
    backend=Sam2Backend(model,'0',1024)
    backend.start_segment(str(video),0,{7:dict(target,pixels=[96,90,256,306])})
    idx,_,masks=backend.next_frame();assert idx==0 and set(masks)=={7}
    expected=np.zeros((360,640),np.uint8);cv2.fillPoly(expected,[np.rint(np.array(ring)*[640,360]).astype('int32')],1)
    actual=cv2.resize((masks[7]>0).astype('uint8'),(640,360),interpolation=cv2.INTER_NEAREST)
    iou=np.logical_and(expected,actual).sum()/np.logical_or(expected,actual).sum()
    assert iou>.95, f'Mask prompt did not preserve polygon: IoU={iou}'
    backend.correct_current(str(video),2,{7:dict(target,pixels=[96,90,256,306])})
    idx,_,masks=backend.next_frame();assert idx==2 and set(masks)=={7};backend.close()
    report.update(mask_prompt_iou=float(iou));report['checks'].append('real SAM2 polygon mask init/correction with stable target 7')
    from studio.domain import Box
    for name in names[1:5]:
        p.labels.save(Path(name).stem,[Box(0,.15,.25,.4,.85,'人工',polygons=[ring],target_id=7)])
    tracking_run=out/'tracking' 
    task=dict(kind='tracking',run=str(tracking_run),project=str(p.root),video=str(video),sample_run=str(worker.run),
        model=model,device='0',imgsz=1024,interval=.2,classes=['person'],session='gpu-acceptance',start_frame=0,
        sample_versions={n:fingerprint(p.labels,Path(n).stem) for n in names},
        targets=[dict(id=7,**target)],quality=dict(min_area_ratio=.001,max_area_ratio=1000,min_iou=0,
        max_center_distance_ratio=100,max_frame_area_ratio=1))
    tracking_worker=Worker(task);save_json(tracking_run/'task.json',task)
    old_emit=worker_module.emit; paused=False;corrected=False
    def emit(kind, **payload):
        nonlocal paused,corrected
        if kind=='progress' and '帧 3/' in payload.get('text','') and not paused:
            save_json(tracking_run/'control.json',dict(action='pause'));paused=True
        if kind=='tracking_state' and payload.get('state')=='paused' and not corrected:
            frame=payload['frame'];assert frame==2
            save_json(tracking_run/'control.json',dict(action='commit',frame=frame,next_id=8,targets=[dict(id=7,**target)]));corrected=True
    worker_module.emit=emit
    try:
        result=tracking_worker.execute()
    finally:
        worker_module.emit=old_emit
    assert paused and corrected and all((tracking_run/f'keyframe_{f}.json').is_file() for f in [2,4,6,8])
    report['checks'].append('five annotated frames: initial mask plus four automatic human keyframe corrections')
    assert result['conflicts']==[], result['conflicts']
    assert len(p.image_paths())==7 and not list((tracking_run/'video_images').glob('*.jpg'))
    for name in names:
        boxes=p.labels.load(Path(name).stem);assert boxes and boxes[0].target_id==7
        assert boxes[0].polygons
    corrected_name=names[1];assert p.labels.load(Path(corrected_name).stem)[0].origin=='人工'
    report['checks'].append('timestamp extract/import -> continuous tracking -> existing-image backfill -> pause polygon commit -> resume; no duplicate images')
    before={n:fingerprint(p.labels,Path(n).stem) for n in names}
    worker_module.emit=lambda *args,**kwargs:None
    try:
        again=Worker(task).execute()
    finally:
        worker_module.emit=old_emit
    assert before=={n:fingerprint(p.labels,Path(n).stem) for n in names}
    report['checks'].append('completed tracking replay preserves saved annotations')
    report.update(pass_=True,tracking=result,replay=again)
    save_json(out/'report.json',report);save_json(out.parent/'latest.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
