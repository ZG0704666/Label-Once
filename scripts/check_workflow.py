"""Exercise atomic paused-frame edits through the real SAM2 backend."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.domain import save_json,read_json,unique_id,Project
from studio.worker import Worker
import studio.worker as protocol
from studio.review import import_video,ReviewStore
root=Path(__file__).resolve().parents[1];out=root/'acceptance'/'workflow';out.mkdir(exist_ok=True)
run=out/('tracking_'+unique_id())
task=dict(kind='tracking',session='workflow',run=str(run),video=str(root/'acceptance/sam/pair.mp4'),model=str(root/'sam/sam2_t.pt'),device='0',imgsz=1024,interval=.2,classes=['person'],targets=[dict(id=0,cls=0,box=[70/640,75/360,300/640,355/360]),dict(id=1,cls=0,box=[365/640,15/360,580/640,355/360])],quality=dict(min_area_ratio=.01,max_area_ratio=100,min_iou=0,max_center_distance_ratio=100,max_frame_area_ratio=1.))
run.mkdir();save_json(run/'task.json',task)
events=[];sent=False;committed=False
original=protocol.emit

def emit(kind,**event):
 global sent,committed
 events.append(dict(event=kind,**event))
 if kind=='tracking_frame' and not sent:
  save_json(run/'control.json',dict(action='pause'));sent=True
 elif kind=='tracking_state' and event.get('state')=='paused' and not committed:
  assert events[-2]['event']=='tracking_frame' and events[-2]['frame']==event['frame']
  targets=[dict(id=1,**event['targets'][1]),dict(id=2,cls=0,box=[70/640,75/360,300/640,355/360])]
  save_json(run/'control.json',dict(action='commit',frame=event['frame'],targets=targets,next_id=3));committed=True
protocol.emit=emit
result=Worker(task).execute();assert committed
before=read_json(run/'frame_manifest.json');assert before['next_id']==3
assert set(map(int,before['segments'][-1]['targets']))=={1,2}
Worker(task).execute();after=read_json(run/'frame_manifest.json');assert before['outputs']==after['outputs']
protocol.emit=original
project=Project(out/'复审验证项目');project.labels.set_classes(['other','person'])
imported=import_video(project,run);assert imported['count']>0
assert all(project.labels.load(Path(n).stem) for n in imported['names'])
ReviewStore(project).confirm(imported['names'])
manual_run=out/('extract_'+unique_id());manual=dict(kind='extract',run=str(manual_run),video=task['video'],interval=.2)
manual_run.mkdir();save_json(manual_run/'task.json',manual);Worker(manual).execute()
extracted=import_video(project,manual_run);assert extracted['count']==6
assert all(ReviewStore(project).status(n)=='pending' for n in extracted['names'])
save_json(out/'integration.json',dict(tracking=result,paused_commit=True,ids=[1,2],resume_no_duplicates=True,imported=imported,manual=extracted))
print('Workflow integration passed')
