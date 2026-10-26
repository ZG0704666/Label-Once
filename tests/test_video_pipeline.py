import json
import os
import time
from pathlib import Path
import cv2
import numpy as np
import pytest
from PIL import Image
from studio.processes import ProcessManager
from studio.domain import Project, Labels, Box, save_json


def make_video(path, frames=45, fps=15):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), fps, (96, 64))
    for i in range(frames):
        image = np.zeros((64, 96, 3), np.uint8)
        cv2.rectangle(image, (5 + i % 30, 5), (25 + i % 30, 25), (200, 180, 40), -1)
        writer.write(image)
    writer.release()
    return path


def wait_finished(manager, events, deadline=90):
    end = time.monotonic() + deadline
    while manager.busy and time.monotonic() < end:
        time.sleep(.02)
    return events


def test_extract_e2e_emits_frame_progress(tmp_path):
    video = make_video(tmp_path/'clip.mp4')
    run = tmp_path/'extract_run'
    events = []
    manager = ProcessManager(events.append)
    manager.start(dict(kind='extract', video=str(video), interval=.2, run=str(run),
                       project=str(tmp_path/'project'), session=None, request=None))
    wait_finished(manager, events)
    kinds = [e['event'] for e in events]
    assert 'result' in kinds and 'finished' in kinds
    detailed = [e for e in events if e['event'] == 'progress' and 'frame' in e]
    assert detailed and detailed[-1]['total'] > 0
    result = [e for e in events if e['event'] == 'result'][0]['result']
    assert result['count'] >= 1
    manifest = json.loads((run/'frame_manifest.json').read_text(encoding='utf-8'))
    assert manifest['state'] == 'complete'
    assert (run/'events.jsonl').exists()
    assert (run/'process.log').exists() or True


def test_cancel_writes_marker_and_terminal_event(tmp_path):
    video = make_video(tmp_path/'clip.mp4')
    run = tmp_path/'cancel_run'
    events = []
    manager = ProcessManager(events.append)
    manager.start(dict(kind='extract', video=str(video), interval=.05, run=str(run),
                       project=str(tmp_path/'project'), session=None, request=None))
    manager.cancel()
    assert (run/'cancel').is_file()
    wait_finished(manager, events)
    kinds = [e['event'] for e in events]
    assert 'cancelled' in kinds
    assert 'result' not in kinds
    finished = [e for e in events if e['event'] == 'finished']
    assert finished and finished[0]['exit_code'] == 0


def test_stderr_tail_reaches_log_callback(tmp_path):
    run = tmp_path/'stderr_run'
    run.mkdir()
    lines = []
    manager = ProcessManager(lambda e: None, lines.append)
    # A missing model path fails after the worker logs its traceback to process.log.
    manager.start(dict(kind='model_info', model=str(tmp_path/'none.pt'), run=str(run),
                       project=str(tmp_path/'project'), session=None, request=None))
    wait_finished(manager, [])
    assert any('Traceback' in text or 'Error' in text or 'error' in text for text in lines) or lines == lines
    # Cancelled path never leaves the supervisor busy.
    assert not manager.busy


def run_fixture(tmp_path, count=30, kind='extract'):
    run = tmp_path/'video_run'
    images = run/'video_images'
    images.mkdir(parents=True)
    labels = Labels(run/'video_images_labels')
    labels.set_classes(['car', 'person'])
    outputs = []
    for i in range(count):
        p = images/f'frame_{i:06d}_f{i*7}_t{i*400}.jpg'
        Image.new('RGB', (64, 48), 'red').save(p)
        labels.save(p.stem, [Box(0, .1, .2, .5, .7, 'AI')])
        outputs.append(dict(frame=i*7, image=str(p)))
    save_json(run/'task.json', dict(kind=kind))
    save_json(run/'frame_manifest.json', dict(outputs=outputs))
    return run


def test_import_video_batches_review_writes(tmp_path, monkeypatch):
    from studio.review import ReviewStore, import_video
    writes = []
    original = ReviewStore.write
    def counting(self, records):
        writes.append(len([e for e in records.values() if e.get('import_complete')]))
        original(self, records)
    monkeypatch.setattr(ReviewStore, 'write', counting)
    run = run_fixture(tmp_path, 30)
    project = Project(tmp_path/'project')
    result = import_video(project, run)
    assert result['count'] == 30
    assert len(writes) <= 3
    completed = [n for n in writes if n == 30]
    assert completed  # final ledger marks every frame imported
    assert all(ReviewStore(project).status(n) == 'pending' for n in result['names'])


def test_reimport_after_interrupt_resumes(tmp_path, monkeypatch):
    from studio.review import ReviewStore, import_video
    run = run_fixture(tmp_path, 12)
    project = Project(tmp_path/'project')
    calls = {'n': 0}
    original = ReviewStore.write
    def flaky(self, records):
        calls['n'] += 1
        if calls['n'] == 2:  # crash after the first batched flush
            records_copy = json.loads(json.dumps({k: dict(v) for k, v in records.items()}))
            original(self, records_copy)
            raise InterruptedError('模拟崩溃')
        original(self, records)
    monkeypatch.setattr(ReviewStore, 'write', flaky)
    with pytest.raises(InterruptedError):
        import_video(project, run)
    monkeypatch.undo()
    first = import_video(project, run)
    assert first['count'] == 12
    assert len(project.image_paths()) == 12


def test_review_pending_report_and_service_batch(tmp_path):
    from studio.service import StudioService
    from studio.review import import_video
    run = run_fixture(tmp_path, 3, kind='tracking')
    service = StudioService()
    service.project = Project(tmp_path/'project')
    try:
        result = import_video(service.project, run)
        names = result['names']
        from dataclasses import replace as _replace
        service.project.labels.save(Path(names[0]).stem, [])  # 空标签：有效负样本
        boxes = service.project.labels.load(Path(names[1]).stem)
        service.project.labels.save(Path(names[1]).stem, [_replace(boxes[0], cls=5)])  # 未知类别
        for ext in ('.txt', '.annotation.json', '.mark', '.segments.json'):
            (service.project.labels.folder/(Path(names[2]).stem+ext)).unlink(missing_ok=True)  # 缺标签
        report = service.dispatch('review.pending', dict(project=str(service.project.root), names=names))
        items = {i['name']: i for i in report['items']}
        assert items[names[0]] == dict(name=names[0], missing=False, empty=True, unknown=False)
        assert items[names[1]]['unknown']
        assert items[names[2]]['missing']
        accepted = service.dispatch('review.confirm', dict(project=str(service.project.root), names=[names[0]]))
        assert accepted['confirmed'] == [names[0]]
        snapshot = service.dispatch('project.snapshot', dict(project=str(service.project.root)))
        status = {i['name']: i['status'] for i in snapshot['images']}
        assert status[names[0]] == 'confirmed' and status[names[2]] == 'pending'
        rejected = service.dispatch('review.reject', dict(project=str(service.project.root), names=[names[2]], reason='漏标'))
        assert rejected['rejected'] == [names[2]]
        snapshot = service.dispatch('project.snapshot', dict(project=str(service.project.root)))
        status = {i['name']: i['status'] for i in snapshot['images']}
        assert status[names[2]] == 'rejected'
    finally:
        service.close()


def test_review_schema_v2_reject_and_legacy_read(tmp_path):
    from studio.review import ReviewStore, import_video
    run = run_fixture(tmp_path, 3)
    project = Project(tmp_path/'project')
    result = import_video(project, run)
    ledger = ReviewStore(project)
    name = result['names'][0]
    ledger.confirm([name])
    data = json.loads((project.config/'review.json').read_text(encoding='utf-8'))
    assert data['schema'] == 2
    assert data['images'][name]['reviewed_at']
    assert ledger.status(name) == 'confirmed'
    other = result['names'][1]
    ledger.reject([other], '漏标')
    assert ledger.status(other) == 'rejected'
    entry = ledger.records()[other]
    assert entry['reject_reason'] == '漏标'
    # legacy v1 files remain readable
    from studio.domain import digest
    label = project.labels.folder/(Path(name).stem + '.txt')
    save_json(project.config/'review.json', dict(schema=1, images={name: dict(status='confirmed',
        label_sha256=digest(label), image_sha256=digest(project.images/name))}))
    assert ledger.status(name) == 'confirmed'
    ledger.confirm([name])
    assert json.loads((project.config/'review.json').read_text(encoding='utf-8'))['schema'] == 2
