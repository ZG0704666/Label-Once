"""Isolate TensorRT packaging diagnostics; never overwrites the original task evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

release, original, output = [Path(p).resolve() for p in sys.argv[1:4]]
output.mkdir(parents=True, exist_ok=True)
task = json.loads(original.read_text(encoding='utf-8'))
task['run'] = str(output)
task_path = output/'task.json'
task_path.write_text(json.dumps(task, ensure_ascii=False), encoding='utf-8')
env = {k.upper(): v for k, v in os.environ.items()
       if not k.upper().startswith(('CONDA', 'PYTHON', 'LABELONCE', 'DOTNET'))}
native = [] if '--default-path' in sys.argv[4:] else [str(release/'backend/_internal/tensorrt_libs'),
    str(release/'backend/_internal/torch/lib')]
env['PATH'] = ';'.join(native+[str(Path(env['SYSTEMROOT'])/'System32'), env['SYSTEMROOT']])
with tempfile.TemporaryDirectory(prefix='labelonce_engine_probe_') as directory, \
        (output/'console.log').open('w', encoding='utf-8') as log:
    completed = subprocess.run([str(release/'backend/backend.exe'), '--worker', str(task_path)],
        cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300,
        creationflags=subprocess.CREATE_NO_WINDOW)
report = dict(exit_code=completed.returncode, pass_=completed.returncode == 0,
    path=env['PATH'], result=json.loads((output/'result.json').read_text(encoding='utf-8'))
    if (output/'result.json').exists() else None)
(output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
raise SystemExit(0 if report['pass_'] else 1)
