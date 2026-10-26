"""Exercise the delivered EXE without a global Python search path."""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT/'dist/YoloTrainStudio/YoloTrainStudio.exe'
OUT = ROOT/'acceptance/frozen'
OUT.mkdir(exist_ok=True)
session = OUT/datetime.now().strftime('%Y%m%d_%H%M%S')
session.mkdir()
env = dict(os.environ)
for key in list(env):
    if key.upper().startswith(('PYTHON', 'CONDA')):
        env.pop(key)
system_root = env.get('SystemRoot', r'C:\Windows')
env['PATH'] = os.pathsep.join([system_root+'\\System32', system_root])
env['YOLO_AUTOINSTALL'] = 'False'
results = {}
model = str(ROOT/'models/yolov8n.pt')
common = dict(model=model, project=str(ROOT/'acceptance/验证项目'))
tasks = [(f'predict_{device}', dict(kind='predict', source=str(ROOT/'acceptance/验证项目/Main/测试_00.jpg'), mode='image', device=device)) for device in ('cpu', '0')]
tasks += [(f'export_{fmt}', dict(kind='export', format=fmt, params=dict(imgsz=64, batch=1, quantize=32, device='0' if fmt=='engine' else 'cpu'))) for fmt in ('onnx','torchscript','openvino','engine')]
for name, task in tasks:
    run = session/name
    run.mkdir(exist_ok=True)
    task.update(common, run=str(run))
    path = run/'task.json'
    path.write_text(json.dumps(task, ensure_ascii=False), encoding='utf-8')
    process = subprocess.run([str(EXE), '--worker', str(path)], env=env, timeout=240)
    events = [json.loads(line) for line in (run/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    results[name] = dict(exit_code=process.returncode, terminal=events[-1])
    (OUT/'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(name, process.returncode, events[-1]['event'], flush=True)
    if process.returncode or events[-1]['event'] != 'result':
        sys.exit(1)
