"""Focused progressive workflow through only the released backend in a clean environment.

Arguments: release directory, 640x360 SAM fixture, 12-frame 10fps video, output directory.
"""
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

release, image, video, output = [Path(p).resolve() for p in sys.argv[1:5]]
output.mkdir(parents=True, exist_ok=True)
env = {k.upper(): v for k, v in os.environ.items()
       if not k.upper().startswith(('CONDA', 'PYTHON', 'LABELONCE', 'DOTNET'))}
env['PATH'] = str(Path(env['SYSTEMROOT'])/'System32')+';'+env['SYSTEMROOT']
env['APPDATA'] = str(output/'appdata')
rows = queue.Queue()
pending = []
counter = 0
report = dict(checks=[], pass_=False)

def record():
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

with tempfile.TemporaryDirectory(prefix='labelonce_progressive_') as temporary, \
        (output/'stderr.log').open('w', encoding='utf-8') as err:
    proc = subprocess.Popen([str(release/'backend/backend.exe'), '--bridge'], cwd=temporary,
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
        text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)

    def read():
        try:
            for line in proc.stdout:
                rows.put(json.loads(line))
        finally:
            rows.put({'closed': True})
    threading.Thread(target=read, daemon=True).start()

    def call(method, params):
        global counter
        counter += 1
        proc.stdin.write(json.dumps(dict(version=1, id=counter, method=method, params=params))+'\n')
        proc.stdin.flush()
        deadline = time.monotonic()+180
        while time.monotonic() < deadline:
            row = rows.get(timeout=max(.1, deadline-time.monotonic()))
            if row.get('closed'):
                raise RuntimeError('Released backend disconnected')
            if row.get('id') == counter:
                assert 'error' not in row, row
                return row['result']
            if 'event' in row:
                pending.append(row['event'])
        raise TimeoutError(method)

    def task(kind, options, correction=None):
        pending.clear()
        spec = call('task.start', dict(kind=kind, options=options))
        result = None
        paused = committed = False
        deadline = time.monotonic()+300
        while time.monotonic() < deadline:
            row = {'event': pending.pop(0)} if pending else rows.get(timeout=max(.1, deadline-time.monotonic()))
            assert not row.get('closed'), row
            e = row.get('event', {})
            if correction and e.get('event') == 'progress' and '帧 3/' in e.get('text', '') and not paused:
                call('task.control', dict(control=dict(action='pause')))
                paused = True
            if correction and e.get('event') == 'tracking_state' and e.get('state') == 'paused':
                report['corrected_frame'] = e['frame']
                call('task.control', dict(control=dict(action='commit', pause_token=e.get('pause_token'), frame=e['frame'], next_id=8,
                    targets=[dict(id=7, **correction)])))
                committed = True
            assert e.get('event') != 'error', e
            if e.get('event') == 'result':
                result = e['result']
            if e.get('event') == 'finished':
                assert result is not None, e
                if correction:
                    assert paused and committed
                return result, spec
        raise TimeoutError(kind)

    try:
        project = output/'中文 空格标注项目'
        hello = call('hello', {})
        model = next(p for p in hello['sam_models'] if Path(p).name == 'sam2_t.pt')
        call('project.open', dict(path=str(project)))
        call('classes.save', dict(names=['person']))
        fixture = output/'inputs'/image.name
        fixture.parent.mkdir(exist_ok=True)
        shutil.copy2(image, fixture)
        imported = call('images.import', dict(paths=[str(fixture)]))
        name = imported['names'][0]
        options = dict(name=name, model=model, device='0', imgsz=1024, class_id=0,
            object_id='frozen-stable', epsilon=1, request=1, points=[[200,180]], labels=[1],
            bbox=[70,75,310,355], roi=[70,75,310,355])
        first = call('sam.segment', options)['box']
        options.update(points=[[200,180],[300,80]], labels=[1,0], request=2)
        second = call('sam.segment', options)['box']
        assert first['object_id'] == second['object_id'] == 'frozen-stable'
        assert second['polygons']
        assert all(70-1e-6 <= x*640 <= 310+1e-6 and 75-1e-6 <= y*360 <= 355+1e-6
                   for ring in second['polygons'] for x,y in ring)
        saved = call('annotation.save', dict(name=name, boxes=[second], expected_revision=0, confirm=True))
        loaded = call('annotation.load', dict(name=name))
        assert saved['revision'] == loaded['revision']
        exported, _ = task('segment_dataset', dict(split_components=True, fill_holes=True))
        assert exported['exported'], exported
        report['checks'].append('frozen JSONL multi-point SAM + ROI + same object + save/load + segmentation export')
        extracted, spec = task('extract', dict(video=str(video), interval=.2))
        imported, _ = task('import_video', dict(source_run=spec['run']))
        assert len(imported['names']) == 6, imported
        target = dict(cls=0, box=[.15,.25,.4,.85], polygons=[[[.15,.25],[.4,.25],[.4,.85],[.15,.85]]], holes=None)
        tracked, track = task('tracking', dict(video=str(video), sample_run=spec['run'],
            model=model, device='0', imgsz=1024, interval=.2, start_frame=0,
            targets=[dict(id=7, **target)], quality=dict(min_area_ratio=.001, max_area_ratio=1000,
            min_iou=0, max_center_distance_ratio=100, max_frame_area_ratio=1)), correction=target)
        assert not tracked['conflicts'], tracked
        frame = report['corrected_frame']
        keyframe = json.loads((Path(track['run'])/f'keyframe_{frame}.json').read_text(encoding='utf-8'))
        assert keyframe['targets']['7']['polygons'] == target['polygons'], keyframe
        if frame % 2 == 0:
            corrected = call('annotation.load', dict(name=imported['names'][frame//2]))['boxes'][0]
            assert corrected['target_id'] == 7 and corrected['origin'] == '人工' and corrected['polygons']
        reopened = call('project.open', dict(path=str(project)))
        assert len(reopened['images']) == 7, reopened
        report.update(segmentation=exported, tracking=tracked, pass_=True)
        report['checks'].append('frozen extract/import -> continuous SAM2 -> existing-image backfill -> pause polygon correction/resume; 7 images total')
        record()
        print('PASS: frozen progressive SAM, segmentation and sampled-video correction', flush=True)
    except BaseException as exc:
        report['error'] = repr(exc)
        record()
        raise
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
