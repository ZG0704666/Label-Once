"""Real GPU/worker workflow acceptance. Uses generated fixtures, never user data."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import json
import time
from PIL import Image, ImageDraw
from studio.service import StudioService
from studio.domain import save_json

source=Path(__file__).resolve().parents[2]
root=source/'acceptance'/'wpf'
root.mkdir(parents=True,exist_ok=True)
events=[]
service=StudioService(events.append)
report={}

def task(kind,options,timeout=300):
    start=time.time();events.clear()
    spec=service.dispatch('task.start',dict(kind=kind,options=options))
    service.tasks.thread.join(timeout)
    if service.tasks.busy:
        service.tasks.cancel(True)
        raise TimeoutError(kind)
    errors=[e for e in events if e['event']=='error']
    results=[e['result'] for e in events if e['event']=='result']
    report[kind+('_'+options.get('format','') if kind=='export' else '')]=dict(seconds=time.time()-start,run=spec['run'],errors=errors,result=results[-1] if results else None)
    save_json(root/'backend-report.json',report)
    if errors:raise RuntimeError(errors[0]['message'])
    return results[-1],spec

try:
    service.dispatch('project.open',{'path':str(root/'中文 空格验证项目')})
    service.dispatch('classes.save',{'names':['object']})
    fixtures=root/'fixtures';fixtures.mkdir(exist_ok=True)
    for i,(w,h) in enumerate([(640,360),(360,640),(512,512),(1800,240),(200,100),(640,360),(640,360),(640,360),(640,360),(640,360),(640,360),(640,360)]):
        path=fixtures/f'fixture_{i:02}.jpg'
        if not path.exists():
            image=Image.new('RGB',(w,h),'#193442');draw=ImageDraw.Draw(image)
            draw.rectangle((w*.2,h*.2,w*.7,h*.8),fill='#F1AE58',outline='white',width=3)
            draw.text((10,10),f'{w} x {h} / RAW PIXELS',fill='white')
            exif=Image.Exif()
            if i==4:exif[274]=6
            image.save(path,exif=exif)
    service.dispatch('images.import',{'paths':[str(fixtures)]})
    for p in service.project.image_paths():
        service.dispatch('annotation.save',{'name':p.name,'boxes':[dict(cls=0,x1=.2,y1=.2,x2=.7,y2=.8)],'confirm':True})
    save_json(service.project.config/'workspace.json',dict(schema=1,image='fixture_01.jpg'))
    dataset,_=task('dataset',dict(ratios=[.7,.2,.1],seed=42))
    training,_=task('train',dict(model=str(source/'models/yolo11n.pt'),params=dict(epochs=1,batch=2,imgsz=64,device='0',workers=0,amp=False,plots=True,mosaic=0,close_mosaic=0),dataset_version=dataset['version']),600)
    model=training['best']
    task('predict',dict(model=model,source=str(fixtures/'fixture_00.jpg'),mode='image',device='0'))
    task('evaluate',dict(model=model,dataset_version=dataset['version'],device='0'))
    for fmt in ('onnx','openvino','torchscript','engine'):
        try:task('export',dict(model=model,format=fmt,params=dict(imgsz=64,batch=1,quantize=32,device='0' if fmt=='engine' else 'cpu')),600)
        except Exception as exc:print(fmt,exc,flush=True)
    task('sam',dict(model=str(source/'sam/sam2_t.pt'),name='fixture_04.jpg',class_id=0,device='0',imgsz=256,point=[80,50],request='acceptance-exif'))
    import cv2
    import numpy as np
    for name,size in [('landscape',(320,180)),('portrait',(180,320))]:
        path=fixtures/(name+'.mp4');writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),10,size)
        for i in range(12):
            frame=np.zeros((size[1],size[0],3),dtype=np.uint8);cv2.rectangle(frame,(int(size[0]*.2)+i, int(size[1]*.2)),(int(size[0]*.7)+i,int(size[1]*.8)),(60,180,230),-1);writer.write(frame)
        writer.release()
        preview=service.dispatch('video.open',{'path':str(path)})
        assert (preview['width'],preview['height'])==size
        assert service.dispatch('video.frame',{'session':preview['session'],'frame':5})['frame']==5
        result,extract=task('extract',dict(video=str(path),interval=.3))
        task('import_video',dict(source_run=extract['run']))
    events.clear()
    tracking=service.dispatch('task.start',dict(kind='tracking',options=dict(video=str(fixtures/'portrait.mp4'),interval=.2,model=str(source/'sam/sam2_t.pt'),device='0',imgsz=256,targets=[dict(id=0,cls=0,box=[.2,.2,.7,.8])],next_id=1)))
    deadline=time.time()+120
    paused=None
    run_dir=Path(tracking['run'])
    while time.time()<deadline and service.tasks.busy:
        paused=next((e for e in reversed(events) if e['event']=='tracking_state' and e['state']=='paused'),None)
        if paused:break
        if not (run_dir/'control.json').exists() and any(e['event']=='tracking_state' and e['state']=='tracking' for e in events):
            service.tasks.control(dict(action='pause'))
        time.sleep(.05)
    if paused:
        service.tasks.control(dict(action='commit',frame=paused['frame'],targets=[dict(id=int(k),**v) for k,v in paused['targets'].items()],next_id=1))
    service.tasks.thread.join(120)
    if service.tasks.busy:service.tasks.cancel(True)
    report['tracking']=dict(run=tracking['run'],pause_confirmed=paused is not None,events=events.copy())
    if not any(e['event']=='error' for e in events):
        events.clear();service.dispatch('task.restore',{'run':tracking['run']});service.tasks.thread.join(120)
        if service.tasks.busy:service.tasks.cancel(True)
        report['tracking_restore']=events.copy()
    save_json(root/'backend-report.json',report)
finally:
    service.close()
print(json.dumps({k:{'errors':v.get('errors',[])} if isinstance(v,dict) else 'recorded' for k,v in report.items()},ensure_ascii=False),flush=True)
