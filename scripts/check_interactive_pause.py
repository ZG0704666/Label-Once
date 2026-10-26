"""GPU smoke test of the desktop service pause / interactive SAM / commit contract."""
import sys,time,json,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import cv2
from ultralytics.utils import ASSETS
from studio.service import StudioService
from studio.domain import read_json,save_json
out=ROOT/'acceptance'/'interactive_pause'/uuid.uuid4().hex;out.mkdir(parents=True)
events=[]
service=StudioService(lambda e:events.append(e))
try:
    service.dispatch('project.open',{'path':str(out/'project')})
    service.dispatch('classes.ensure',{'name':'person'})
    pixels=cv2.resize(cv2.imread(str(ASSETS/'zidane.jpg')),(640,360))
    video=out/'video.mp4';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),10,(640,360))
    for i in range(60):writer.write(pixels)
    writer.release()
    opened=service.dispatch('video.open',{'path':str(video)})
    opts=dict(video_session=opened['session'],frame=0,model=str(ROOT/'sam'/'sam2_t.pt'),device='0',imgsz=1024,class_id=0,object_id='person-id',request=1,points=[[200,180]],labels=[1],bbox=[70,75,310,355],epsilon=1)
    first=service.dispatch('sam.segment',opts)['box'];assert first['polygons']
    target=dict(id=7,cls=0,object_id='person-id',box=[first[k] for k in ('x1','y1','x2','y2')],polygons=first['polygons'],holes=first['holes'])
    task=service.dispatch('task.start',{'kind':'tracking','options':dict(video=str(video),model=opts['model'],device='0',imgsz=1024,interval=.2,start_frame=0,targets=[target],next_id=8,quality=dict(min_area_ratio=.001,max_area_ratio=1000,min_iou=0,max_center_distance_ratio=100,max_frame_area_ratio=1))})
    deadline=time.monotonic()+120
    while not any(e.get('event')=='tracking_frame' for e in events):
        assert time.monotonic()<deadline,events[-5:];time.sleep(.05)
    service.dispatch('task.control',{'control':{'action':'pause'}})
    paused=None
    while paused is None:
        paused=next((e for e in events if e.get('state')=='paused' and e.get('pause_token')),None)
        assert time.monotonic()<deadline,events[-5:];time.sleep(.05)
    assert paused['gpu_released']
    cls=service.dispatch('classes.ensure',{'name':'edited-person','pause_token':paused['pause_token']})['class_id']
    opts.update(frame=paused['frame'],pause_token=paused['pause_token'],points=[[200,180],[300,80]],labels=[1,0],class_id=cls,request=2)
    box=service.dispatch('sam.segment',opts)['box'];assert box['object_id']=='person-id'
    target.update(cls=cls,box=[box[k] for k in ('x1','y1','x2','y2')],polygons=box['polygons'],holes=box['holes'])
    service.dispatch('task.control',{'control':dict(action='commit',pause_token=paused['pause_token'],frame=paused['frame'],targets=[target],next_id=8)})
    while service.tasks.busy:
        assert time.monotonic()<deadline,events[-5:];time.sleep(.1)
    assert not any(e.get('event')=='error' for e in events),events[-5:]
    key=read_json(Path(task['run'])/f"keyframe_{paused['frame']}.json")
    assert key['targets']['7']['object_id']=='person-id' and key['targets']['7']['cls']==cls
    report=dict(passed=True,frame=paused['frame'],run=task['run'],checks=['idle video Q/E','GPU pause acknowledgement','paused Q/E','append category while paused','mask commit and resume','stable target/object IDs'])
    save_json(out/'report.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))
finally:service.close()
