import json
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.domain import Project,save_json
from studio.dataset import DatasetStore

root=Path(__file__).resolve().parents[1]
project=Project(root/'acceptance/验证项目');store=DatasetStore(project)
run=project.new_run('cancel_acceptance')
task=dict(kind='train',run=str(run),project=str(project.root),model=str(root/'models/yolov8n.pt'),dataset=str(store.yaml_path()),dataset_version=store.active(),params=dict(epochs=50,batch=2,imgsz=64,device='cpu',workers=0,amp=False,plots=False))
save_json(run/'task.json',task)
command=[str(root/'dist/YoloTrainStudio/YoloTrainStudio.exe'),'--worker'] if '--frozen' in sys.argv else [sys.executable,'-m','studio.worker']
with (run/'process.log').open('w',encoding='utf-8') as log:
    process=subprocess.Popen(command+[str(run/'task.json')],stdout=log,stderr=log)
    deadline=time.monotonic()+120
    requested=False
    while process.poll() is None and time.monotonic()<deadline:
        events=run/'events.jsonl'
        if events.exists() and '"event": "epoch"' in events.read_text(encoding='utf-8'):
            (run/'cancel').write_text('cancel');requested=True
        time.sleep(.05)
    if process.poll() is None:process.kill();raise RuntimeError('训练未按期停止')
assert requested
record=json.loads((run/'result.json').read_text(encoding='utf-8'))
assert record['status']=='cancelled' and Path(record['best']).exists()
epochs=sum('"event": "epoch"' in line for line in (run/'events.jsonl').read_text(encoding='utf-8').splitlines())
assert epochs<50
save_json(root/'acceptance/cancel.json',dict(frozen='--frozen' in sys.argv,run=str(run),epochs=epochs,status=record['status'],best=record['best']))
print('Cancellation passed',epochs,flush=True)
