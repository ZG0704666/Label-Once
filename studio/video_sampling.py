"""Timestamp-based sequential extraction. A completed manifest is the import boundary."""
import math
from pathlib import Path
from .domain import digest, save_json, read_json


def extract(worker):
    import cv2
    video = Path(worker.task['video']).resolve()
    frame_step = worker.task.get('frame_step')
    legacy_interval = float(worker.task.get('interval', .5)) if frame_step is None else None
    if frame_step is not None:
        raw_step = frame_step
        try:
            frame_step = int(raw_step)
            integral = float(raw_step) == frame_step
        except (TypeError, ValueError, OverflowError):
            integral = False
        if not integral or frame_step not in (5, 10, 15, 20, 30):
            raise ValueError('帧间隔只能是 5、10、15、20 或 30 帧')
    elif not math.isfinite(legacy_interval) or legacy_interval <= 0:
        raise ValueError('抽帧间隔必须是有限正数')
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError('视频无法读取')
    dest = worker.run/'video_images'
    dest.mkdir(exist_ok=True)
    fingerprint = digest(video)
    manifest = dict(schema=2, state='analyzing', video=str(video), video_sha256=fingerprint,
                    outputs=[], decoded_frames=0)
    manifest.update(frame_step=frame_step) if frame_step is not None else manifest.update(interval=legacy_interval)
    old = read_json(worker.run/'frame_manifest.json', {})
    plan_matches = (old.get('frame_step') == frame_step if frame_step is not None
                    else old.get('frame_step') is None and old.get('interval') == legacy_interval)
    if old and (old.get('video_sha256') != fingerprint or not plan_matches):
        cap.release()
        raise ValueError('视频或抽帧计划已改变，不能恢复此输出')
    total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    first = previous = None
    target = 0
    index = 0
    try:
        save_json(worker.run/'frame_manifest.json', manifest)
        while True:
            worker.check()
            ok, frame = cap.read()
            if not ok:
                break
            timestamp = cap.get(cv2.CAP_PROP_POS_MSEC)/1000
            if not math.isfinite(timestamp) or timestamp < 0 or (previous is not None and timestamp <= previous):
                raise ValueError(f'第 {index} 帧时间戳不可靠，无法准确抽帧')
            if first is None:
                first = timestamp
            previous = timestamp
            relative = timestamp-first
            due = index % frame_step == 0 if frame_step is not None else relative+1e-9 >= target*legacy_interval
            if due:
                count = len(manifest['outputs'])
                path = dest/f'frame_{count:06d}_f{index}_t{round(relative*1000)}.jpg'
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                if not ok:
                    raise ValueError(f'第 {index} 帧编码失败')
                encoded.tofile(path)
                manifest['outputs'].append(dict(image=str(path), frame=index, timestamp=relative,
                    sample_id=f'{fingerprint}:{index}', width=frame.shape[1], height=frame.shape[0]))
                if frame_step is None:
                    target = math.floor((relative+1e-9)/legacy_interval)+1
            index += 1
            manifest['decoded_frames'] = index
            if index % 10 == 0:
                worker.progress(min(.99, index/total), f'正在按时间索引抽帧 · 已生成 {len(manifest["outputs"])} 张（分析中）',
                                frame=index, total=total, exported=len(manifest['outputs']))
        if not index:
            raise ValueError('视频没有可解码帧')
        manifest.update(state='complete', count=len(manifest['outputs']))
        save_json(worker.run/'frame_manifest.json', manifest)
        worker.progress(1, f'抽帧完成 · 校准数量 {len(manifest["outputs"])} 张')
        return dict(folder=str(dest), count=len(manifest['outputs']), manifest=str(worker.run/'frame_manifest.json'))
    except BaseException as exc:
        manifest['state'] = 'cancelled' if isinstance(exc, InterruptedError) else 'failed'
        save_json(worker.run/'frame_manifest.json', manifest)
        raise
    finally:
        cap.release()
