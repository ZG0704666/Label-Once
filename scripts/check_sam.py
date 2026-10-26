import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['YOLO_AUTOINSTALL']='False'
import cv2
import numpy as np
from ultralytics.utils import ASSETS
from studio.domain import save_json,unique_id
from studio.worker import Worker
from studio.tracking import Sam2Backend
root=Path(__file__).resolve().parents[1];out=root/'acceptance'/'sam';out.mkdir(exist_ok=True)
image=cv2.imread(str(ASSETS/'zidane.jpg'));image=cv2.resize(image,(640,360));cv2.imencode('.jpg',image)[1].tofile(out/'input.jpg')
video=out/'pair.mp4';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),10,(640,360))
for i in range(12):writer.write(image)
writer.release()
model=str(root/'sam'/'sam2_t.pt')
result=Worker(dict(kind='sam',run=str(out/'image_task'),model=model,image=str(out/'input.jpg'),bbox=[70,75,550,355],class_id=0,request='check',device='0',imgsz=1024)).execute()
assert result['boxes'];save_json(out/'sam_result.json',result)
backend=Sam2Backend(model,'0',1024)
targets={2:dict(pixels=[70,75,300,355]),7:dict(pixels=[365,15,580,355])}
backend.start_segment(str(video),0,targets)
frames=[]
for i in range(4):
    idx,im,masks=backend.next_frame();assert idx==i;assert set(masks)=={2,7};frames.append(dict(frame=idx,ids=list(masks)))
backend.correct_current(str(video),3,targets)
idx,im,masks=backend.next_frame();assert idx==3 and set(masks)=={2,7}
backend.correct_current(str(video),4,{7:targets[7],12:targets[2]})
idx,im,masks=backend.next_frame();assert idx==4 and set(masks)=={7,12}
backend.close();save_json(out/'backend_results.json',dict(frames=frames,correct=True,add_end=True))
task=dict(kind='tracking',run=str(out/('tracking_'+unique_id())),video=str(video),model=model,device='0',imgsz=1024,interval=.2,classes=['person'],targets=[dict(id=0,cls=0,box=[70/640,75/360,300/640,355/360]),dict(id=1,cls=0,box=[365/640,15/360,580/640,355/360])],quality=dict(min_area_ratio=.01,max_area_ratio=100,min_iou=0,max_center_distance_ratio=100,max_frame_area_ratio=1.))
worker=Worker(task);result=worker.execute();assert result['count']==6
manifest=Path(result['manifest']);import json
before=json.loads(manifest.read_text(encoding='utf-8'))
again=Worker(task).execute();after=json.loads(manifest.read_text(encoding='utf-8'));assert before['outputs']==after['outputs']
assert before['segments']==after['segments']
save_json(out/'integration.json',dict(image_sam=True,tracking=result,resume_no_duplicates=True))
print('SAM/SAM2 checks passed')
