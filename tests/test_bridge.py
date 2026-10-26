import io
import json
import sys
import subprocess
import time
from pathlib import Path
from PIL import Image
import pytest
from studio.service import StudioService
from studio.domain import read_json, save_json


@pytest.fixture
def service(tmp_path, monkeypatch):
    from studio import config, service as module
    monkeypatch.setattr(config, 'CONFIG_ROOT', tmp_path/'config')
    monkeypatch.setattr(module, 'CONFIG_ROOT', tmp_path/'config')
    s=StudioService()
    s.dispatch('project.open', {'path':str(tmp_path/'中文 空格项目')})
    s.dispatch('classes.save', {'names':['目标']})
    yield s
    s.close()


def test_raw_exif_save_confirm_and_compatibility(service,tmp_path):
    source=tmp_path/'竖拍.jpg'
    exif=Image.Exif();exif[274]=6
    Image.new('RGB',(200,100),'red').save(source,exif=exif)
    result=service.dispatch('images.import',{'paths':[str(source)]})
    name=result['names'][0]
    image=service.dispatch('annotation.load',{'name':name})
    assert (image['width'],image['height'],image['orientation'])==(200,100,6)
    with Image.open(image['path']) as raw:
        assert raw.size==(200,100) and not raw.getexif().get(274)
    box=dict(cls=0,x1=.1,y1=.2,x2=.5,y2=.7,polygons=[[[.1,.2],[.5,.2],[.5,.7]]])
    service.dispatch('annotation.save',{'name':name,'boxes':[box],'confirm':True})
    assert service.snapshot()['images'][0]['status']=='confirmed'
    loaded=service.project.labels.load(Path(name).stem)[0]
    assert loaded.polygons==box['polygons']
    box['x2']=.6
    service.dispatch('annotation.save',{'name':name,'boxes':[box]})
    assert service.snapshot()['images'][0]['status']=='pending'


def test_failed_save_never_confirms(service,monkeypatch):
    Image.new('RGB',(20,30)).save(service.project.images/'a.png')
    def fail(*args):raise OSError('模拟磁盘写入失败')
    monkeypatch.setattr(service.project.labels,'save',fail)
    with pytest.raises(OSError):service.dispatch('annotation.save',{'name':'a.png','boxes':[],'confirm':True})
    assert service.snapshot()['images'][0]['status']=='legacy'


def test_stale_project_and_unsafe_name(service):
    with pytest.raises(ValueError):service.dispatch('annotation.load',{'name':'../x.jpg'})
    with pytest.raises(ValueError):service.dispatch('images.trash',{'project':'other-project','names':[]})


def test_protocol_utf8_errors_and_no_qt(tmp_path):
    messages=[{'version':1,'id':'中文','method':'hello','params':{}},
              {'version':99,'id':'bad','method':'hello','params':{}},
              {'version':1,'id':'missing','method':'does-not-exist','params':{}}]
    proc=subprocess.run([sys.executable,'-X','utf8','-m','studio.bridge'],input=''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in messages),text=True,encoding='utf-8',capture_output=True,timeout=30)
    assert proc.returncode==0,proc.stderr
    rows=[json.loads(x) for x in proc.stdout.splitlines()]
    assert rows[0]['id']=='中文' and rows[0]['result']['protocol']==1
    assert rows[1]['error']['code']=='ValueError' and rows[2]['error']
    code="import studio.bridge,sys;assert not any(x.startswith(('PyQt','PySide')) for x in sys.modules)"
    subprocess.run([sys.executable,'-c',code],check=True,timeout=30)


def test_headless_worker_error_cancel_and_single_task(service):
    from studio.processes import ProcessManager
    events=[];manager=ProcessManager(events.append)
    task=dict(kind='inspect_images',project=str(service.project.root),run=str(service.project.new_run('inspect_images')))
    manager.start(task)
    with pytest.raises(RuntimeError):manager.start(task)
    manager.thread.join(30)
    assert not manager.busy and any(e['event']=='result' for e in events)
    assert read_json(Path(task['run'])/'result.json')=={'bad':[]}
    broken=dict(task,kind='nonexistent',run=str(service.project.new_run('broken')))
    manager.start(broken);manager.thread.join(30)
    assert any(e['event']=='error' for e in events)


def test_invalid_classes_preserve_labels_and_legacy_preset(service):
    service.project.labels.save('sample', [])
    before=(service.project.labels.folder/'sample.txt').read_bytes()
    with pytest.raises(ValueError):service.dispatch('classes.save',{'names':['duplicate','duplicate']})
    assert service.project.labels.classes==['目标']
    assert (service.project.labels.folder/'sample.txt').read_bytes()==before
    save_json(service.project.config/'train_preset.json',dict(epochs=3,batch=2,lr=.002,imgsz=320,augmentation={'mosaic':False},advanced={'params':{'patience':7}}))
    result=service.dispatch('preset.get',{})
    assert result['epochs']==3 and result['lr0']==.002 and result['mosaic']==0 and result['patience']==7


def test_supervisor_force_stop_and_broken_event(service,monkeypatch):
    import studio.processes as module
    real_popen=subprocess.Popen
    def sleeper(*args,**kwargs):
        return real_popen([sys.executable,'-c','import time;time.sleep(60)'],**kwargs)
    monkeypatch.setattr(module.subprocess,'Popen',sleeper)
    events=[];manager=module.ProcessManager(events.append)
    task=dict(kind='inspect_images',project=str(service.project.root),run=str(service.project.new_run('cancel')))
    # Restore Popen before taskkill uses subprocess.run internally.
    manager.start(task);monkeypatch.setattr(module.subprocess,'Popen',real_popen)
    manager.cancel(True);manager.thread.join(15)
    assert not manager.busy and manager.process.poll() is not None
    assert events[-1]['event']=='finished'
    monkeypatch.setattr(module.subprocess,'Popen',sleeper)
    task['run']=str(service.project.new_run('bad_events'))
    manager.start(task);monkeypatch.setattr(module.subprocess,'Popen',real_popen)
    phase2=len(events)
    (Path(task['run'])/'events.jsonl').write_text('broken json\n',encoding='utf-8')
    import time as _time;_time.sleep(0.5)
    # 新语义：坏行只跳过并记账，监督线程不崩、busy 不误清、无 error 误报（第一阶段强杀的 error 不计入）。
    assert manager.busy and manager.process.poll() is None
    assert not any(e.get('event')=='error' for e in events[phase2:] if isinstance(e,dict))
    assert any((isinstance(e,str) and '无法解析' in e)
               or (isinstance(e,dict) and e.get('event')=='log' and '无法解析' in str(e.get('data')))
               for e in events[phase2:])
    manager.cancel(True);manager.thread.join(15)
    assert not manager.busy and manager.process.poll() is not None
    assert events[-1]['event']=='finished'
