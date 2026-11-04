"""GPU acceptance: lifetime-ID decoupling beyond 32, loss grading, object swap to a new class.

Scenario (user case #5): person A vanishes mid-video; later a car appears in the same
region while person B keeps tracking. The run must (P1) commit corrections with
next_id=40 without hitting the legacy 32 lifetime-ID cap, (P2) grade A's loss with a
3-frame grace before pausing, (P3) release A's active slot at commit and add the car
as target 40 while paused.
"""
import json, os, sys, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
os.environ['YOLO_AUTOINSTALL'] = 'False'
import cv2
import numpy as np
import torch
from studio.domain import Project, read_json, save_json
from studio.worker import Worker
import studio.worker as worker_module

LEFT = dict(x1=80, y1=80, x2=280, y2=330)    # person A frames 0-11 / car frames 20-39
RIGHT = dict(x1=360, y1=80, x2=570, y2=330)  # person B, constant
CAR = dict(x1=80, y1=150, x2=260, y2=320)

def norm(r, w=640, h=360):
    return [r['x1']/w, r['y1']/h, r['x2']/w, r['y2']/h]

def main():
    assert torch.cuda.is_available(), 'GPU acceptance requires CUDA'
    out = ROOT/'acceptance'/'multi_target_gpu'/uuid.uuid4().hex; out.mkdir(parents=True)
    p = Project(out/'project'); p.labels.set_classes(['person', 'car'])
    video = out/'video.mp4'; writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 10, (640, 360))
    pixels = np.empty((360, 640, 3), np.uint8)
    for frame in range(40):
        draw(pixels, frame); writer.write(pixels)
    writer.release()
    task = dict(kind='tracking', run=str(out/'tracking'), project=str(p.root), video=str(video), model=str(ROOT/'sam'/'sam2_t.pt'),
                device='0', imgsz=1024, interval=.2, classes=['person', 'car'], session='gpu-multi', start_frame=0,
                targets=[dict(id=7, cls=0, object_id='person-a', box=norm(LEFT)),
                         dict(id=8, cls=0, object_id='person-b', box=norm(RIGHT))],
                quality=dict(min_area_ratio=.001, max_area_ratio=1000, min_iou=0,
                             max_center_distance_ratio=100, max_frame_area_ratio=1, loss_grace_frames=3))
    tracking_run = out/'tracking'; tracking_run.mkdir(parents=True)
    save_json(tracking_run/'task.json', task)
    events = []
    emit_orig = worker_module.emit
    stage = dict(name='idle')

    def save_control(command):
        save_json(tracking_run/'control.json', command)

    def emit(kind, **payload):
        events.append(dict(event=kind, **payload))
        text = payload.get('text', '')
        if kind == 'progress' and '帧 10/' in text and stage['name'] == 'idle':
            save_control(dict(action='pause')); stage['name'] = 'await-pause-1'
        elif kind == 'progress' and '帧 22/' in text and stage['name'] == 'running-2':
            save_control(dict(action='pause')); stage['name'] = 'await-pause-3'
        elif kind == 'tracking_state' and payload.get('state') == 'paused' and not payload.get('failures'):
            frame = payload['frame']; token = payload.get('pause_token')
            if stage['name'] == 'await-pause-1':
                assert frame == 9, f'首段暂停应在帧 9，实际 {frame}'
                save_control(dict(action='commit', pause_token=token, frame=frame, next_id=40,
                    targets=[dict(id=7, cls=0, object_id='person-a', box=norm(LEFT)),
                             dict(id=8, cls=0, object_id='person-b', box=norm(RIGHT))]))
                stage['name'] = 'running-1'
            elif stage['name'] == 'await-pause-3':
                assert frame == 21, f'第三段暂停应在帧 21，实际 {frame}'
                save_control(dict(action='add', cls=1, box=norm(CAR)))
                stage['name'] = 'added-3'
            elif stage['name'] == 'added-3':
                save_control(dict(action='resume'))
                stage['name'] = 'running-3'
        elif kind == 'tracking_state' and payload.get('state') == 'paused' and payload.get('failures'):
            frame = payload['frame']
            if stage['name'] == 'running-1':
                assert 15 <= frame <= 18, f'丢失分级应在帧 15-18 暂停，实际 {frame}'
                assert '目标丢失' in ''.join(payload['failures'].values()), payload
                save_control(dict(action='commit', pause_token=payload['pause_token'], frame=frame, next_id=40,
                    targets=[dict(id=8, cls=0, object_id='person-b', box=norm(RIGHT))]))
                stage['name'] = 'running-2'
    worker_module.emit = emit
    try:
        result = Worker(task).execute()
    finally:
        worker_module.emit = emit_orig

    assert result['conflicts'] == [], result['conflicts']
    assert not any(e['event'] == 'error' for e in events), [e for e in events if e['event'] == 'error']
    assert not any('32' in e.get('message', '') for e in events if e['event'] == 'log'), [e for e in events if e['event'] == 'log']
    grace = [e for e in events if e['event'] == 'log' and '目标 7 连续丢失' in e.get('message', '')]
    assert len(grace) == 3, [e['message'] for e in grace]          # 帧 12/13/14 宽期，帧 15 分级暂停
    manifest = read_json(tracking_run/'frame_manifest.json')
    assert manifest['next_id'] == 41, manifest['next_id']           # commit(40) + add → 41；终身 ID 不受 32 限制
    failures = [e for e in manifest['events'] if e.get('action') == 'quality_failure']
    assert len(failures) == 1 and '目标丢失（连续' in ''.join(failures[0]['failures'].values()), failures
    segments = manifest['segments']
    assert len(segments) >= 3 and not any(len(s['targets']) > 32 for s in segments), '活跃目标从未超过 32'
    boxes = {o['frame']: {int(k): v for k, v in o['boxes'].items()} for o in manifest['outputs']}
    frames = sorted(boxes)
    assert len(frames) == 20 and frames[0] == 0 and frames[-1] == 38, frames   # stride 2 → 20 张
    for f in [0, 2, 4, 6, 8, 10]:
        assert 7 in boxes[f] and boxes[f][7]['target_id'] == 7 and boxes[f][7]['cls'] == 0, boxes[f]
    for f in [12, 14, 16, 18]:
        assert 7 not in boxes[f] and 40 not in boxes[f], (f, boxes[f])         # A 已消失、车未出现
    late = [f for f in frames if f >= 20]
    hits = [f for f in late if 40 in boxes[f]]
    assert len(hits) >= 7, (late, {f: list(boxes[f]) for f in late})
    assert all(boxes[f][40]['cls'] == 1 and 0 <= boxes[f][40]['x1'] / 640 and boxes[f][40]['x2'] / 640 <= .5 for f in hits)
    assert all(40 not in boxes[f] for f in frames if f < 20)
    assert all(8 in boxes[f] for f in frames)                                  # B 全程稳定

    # 重放幂等：不产生新输出，不制造冲突
    before = {o['frame']: o['boxes'] for o in manifest['outputs']}
    again = Worker(task).execute()
    after_manifest = read_json(tracking_run/'frame_manifest.json')
    assert again['conflicts'] == [] and again['count'] == result['count']
    assert before == {o['frame']: o['boxes'] for o in after_manifest['outputs']}

    report = dict(pass_=True, root=str(out), device=torch.cuda.get_device_name(0), next_id=manifest['next_id'],
                  checks=['next_id=40 commit 超越终身 32 上限', '丢失分级：连续丢失宽限 3 帧',
                          '分级暂停后提交只保留 B（A 名额释放）', '暂停中 add 目标 40（新类别 car，晚期出现）',
                          '全程 target/object_id 稳定，活跃 ≤32', '重放幂等'])
    save_json(out/'report.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))

def draw(pixels, frame):
    pixels[:] = 255
    if frame < 12:
        cv2.rectangle(pixels, (LEFT['x1'], LEFT['y1']), (LEFT['x2'], LEFT['y2']), (200, 110, 50), -1)
    if frame >= 20:
        cv2.rectangle(pixels, (CAR['x1'], CAR['y1']), (CAR['x2'], CAR['y2']), (40, 220, 60), -1)
    cv2.rectangle(pixels, (RIGHT['x1'], RIGHT['y1']), (RIGHT['x2'], RIGHT['y2']), (60, 110, 200), -1)

if __name__ == '__main__':
    main()
