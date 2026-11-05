"""Drive only the packaged JSONL backend from a clean directory/environment."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

release=Path(sys.argv[1]).resolve()
fixtures=Path(sys.argv[2]).resolve()
output=Path(sys.argv[3]).resolve();output.mkdir(parents=True,exist_ok=True)
env={k.upper():v for k,v in os.environ.items() if not k.upper().startswith(('CONDA','PYTHON','LABELONCE','DOTNET'))}
env['PATH']=str(Path(env['SYSTEMROOT'])/'System32')+';'+env['SYSTEMROOT']
env['APPDATA']=str(output/'appdata')
continuation='--continue-after-exports' in sys.argv[4:]
rows=queue.Queue();report=json.loads((output/'frozen-report.json').read_text(encoding='utf-8')) if continuation else {};request=0
log=(output/'backend-stderr.log').open('w',encoding='utf-8')
temporary=tempfile.TemporaryDirectory(prefix='labelonce_frozen_')
proc=subprocess.Popen([str(release/'backend/backend.exe'),'--bridge'],cwd=temporary.name,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
def read():
    try:
        for line in proc.stdout:rows.put(json.loads(line))
    except Exception as exc:rows.put({'reader_error':str(exc)})
    finally:rows.put({'closed':True})
threading.Thread(target=read,daemon=True).start()
def record():
    (output/'frozen-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def call(method,params=None):
    global request
    request+=1
    proc.stdin.write(json.dumps(dict(version=1,id=str(request),method=method,params=params or {}),ensure_ascii=False)+'\n');proc.stdin.flush()
    while True:
        row=rows.get(timeout=60)
        if 'closed' in row or 'reader_error' in row:raise RuntimeError(row)
        if row.get('id')==str(request):
            if 'error' in row:raise RuntimeError(row['error'])
            return row['result']
        # No long-running operation is active during plain RPC calls except control.
        if 'event' in row:deferred.append(row['event'])
deferred=[]
def task(kind,options,pause=False,restore=None):
    deferred.clear();start=time.monotonic()
    spec=call('task.restore',dict(run=restore)) if restore else call('task.start',dict(kind=kind,options=options))
    events=[];result=None;paused=False
    if pause:call('task.control',dict(control={'action':'pause'}))
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        e=deferred.pop(0) if deferred else rows.get(timeout=600).get('event')
        if not e:raise RuntimeError('后台连接退出或非事件响应')
        events.append(e)
        if e['event']=='tracking_state' and e['state']=='paused' and pause:
            paused=True
            call('task.control',dict(control=dict(action='commit',pause_token=e.get('pause_token'),frame=e['frame'],targets=[dict(id=int(k),**v) for k,v in e['targets'].items()],next_id=e['next_id'])))
            pause=False
        elif e['event']=='tracking_state' and e['state']=='tracking' and pause:
            call('task.control',dict(control={'action':'pause'}))
        if e['event']=='result':result=e['result']
        if e['event']=='finished':break
    else:raise TimeoutError(kind)
    errors=[e for e in events if e['event']=='error']
    name=kind+('_'+options.get('format','') if kind=='export' else '')+('_restore' if restore else '')
    report[name]=dict(seconds=time.monotonic()-start,run=spec['run'],errors=errors,result=result,pause_confirmed=paused,events=events if kind=='tracking' else [],exit_code=events[-1].get('exit_code'))
    record()
    if errors or result is None:raise RuntimeError(errors or '没有成功结果')
    return result,spec
try:
    hello=call('hello');report['environment']=dict(cwd=temporary.name,path=env['PATH'],models=hello['models'],sam_models=hello['sam_models'])
    assert hello['models'] and all(str(release) in p for p in hello['models'])
    project=output/'中文 空格成品项目'
    call('project.open',{'path':str(project)})
    call('classes.save',{'names':['object']})
    inputs=output/'inputs';inputs.mkdir(exist_ok=True)
    for p in fixtures.iterdir():
        if p.suffix in ('.jpg','.mp4'):shutil.copy2(p,inputs/p.name)
    imported=call('images.import',{'paths':[str(inputs)]})
    if not continuation:
        # Confirm every project image (the acceptance project may already exist on rerun).
        for i in call('project.snapshot')['images']:call('annotation.save',dict(name=i['name'],boxes=[dict(cls=0,x1=.2,y1=.2,x2=.7,y2=.8)],confirm=True))
    image=call('annotation.load',{'name':'fixture_04.jpg'});assert image['orientation']==6
    if not continuation:
        dataset,_=task('dataset',dict(ratios=[.7,.2,.1],seed=42))
        model=next(p for p in hello['models'] if Path(p).name=='yolo11n.pt')
        training,_=task('train',dict(model=model,params=dict(epochs=1,batch=2,imgsz=64,device='0',workers=0,amp=False,plots=True,mosaic=0,close_mosaic=0),dataset_version=dataset['version']))
        best=training['best']
        task('predict',dict(model=best,source=str(inputs/'fixture_00.jpg'),mode='image',device='0'))
        task('evaluate',dict(model=best,dataset_version=dataset['version'],device='0'))
        for fmt in ('onnx','openvino','torchscript','engine'):task('export',dict(model=best,format=fmt,params=dict(imgsz=64,batch=1,quantize=32,device='0' if fmt=='engine' else 'cpu')))
    sam=next(p for p in hello['sam_models'] if Path(p).name=='sam2_t.pt')
    task('sam',dict(model=sam,name='fixture_04.jpg',class_id=0,device='0',imgsz=256,point=[80,50],request='frozen-exif'))
    for name,size in [('landscape',(320,180)),('portrait',(180,320))]:
        v=call('video.open',dict(path=str(inputs/(name+'.mp4'))));assert (v['width'],v['height'])==size
        call('video.frame',dict(session=v['session'],frame=5))
        _,extract=task('extract',dict(video=str(inputs/(name+'.mp4')),interval=.3))
        task('import_video',dict(source_run=extract['run']))
    _,tracking=task('tracking',dict(video=str(inputs/'portrait.mp4'),interval=.2,model=sam,device='0',imgsz=256,targets=[dict(id=0,cls=0,box=[.2,.2,.7,.8])],next_id=1),pause=True)
    assert report['tracking']['pause_confirmed']
    task('tracking',{},restore=tracking['run'])
    # Reopen an existing project with the same disk formats.
    reopened=call('project.open',dict(path=str(project)));assert reopened['images']
    report['annotation_workflow_pass']=True
    report['pass']=not any(v.get('errors') for v in report.values() if isinstance(v,dict))
    record();print('PASS: frozen annotation/video GPU workflow; all recorded tasks pass='+str(report['pass']),flush=True)
finally:
    proc.stdin.close()
    try:proc.wait(timeout=15)
    except subprocess.TimeoutExpired:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
    log.close();temporary.cleanup()
