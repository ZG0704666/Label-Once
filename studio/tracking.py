from __future__ import annotations

import math
import time
import copy
from dataclasses import asdict
from pathlib import Path

from .domain import Box, Labels, digest, mask_box, read_json, save_json
from .video_sampling import sampling_spec

QUALITY = dict(min_area_ratio=.45, max_area_ratio=1.8, min_iou=.02,
               max_center_distance_ratio=1.25, max_frame_area_ratio=.85)
# 同时跟踪的“活跃”目标上限。旧实现把终身 ID 编号也限制在 <32：目标消失后
# 再出现（或新类别加入）的长任务会提前耗尽编号。现在编号只增不减（不封顶），
# 仅同一时刻的活跃目标数受限；已结束的目标释放名额。
ACTIVE_LIMIT = 32


def quality_reason(old, new, config=QUALITY):
    if new is None:
        return '目标丢失'
    area = (new.x2-new.x1)*(new.y2-new.y1)
    previous = max(1e-9, (old.x2-old.x1)*(old.y2-old.y1))
    ratio = area/previous
    intersection = max(0, min(old.x2,new.x2)-max(old.x1,new.x1))*max(0,min(old.y2,new.y2)-max(old.y1,new.y1))
    iou = intersection/max(1e-9, previous+area-intersection)
    distance = math.hypot((new.x1+new.x2-old.x1-old.x2)/2, (new.y1+new.y2-old.y1-old.y2)/2)/max(math.sqrt(previous), 1e-9)
    if area > config['max_frame_area_ratio']:
        return '目标占画面过大'
    if not config['min_area_ratio'] <= ratio <= config['max_area_ratio']:
        return '面积突变'
    if iou < config['min_iou'] and distance > config['max_center_distance_ratio']:
        return '位置突变'
    return None


class Sam2Backend:
    def __init__(self, model, device='cpu', imgsz=1024):
        import ultralytics
        if ultralytics.__version__ != '8.4.161':
            raise RuntimeError('SAM2 跟踪需要固定的 ultralytics==8.4.161')
        self.path, self.device, self.imgsz = model, device, imgsz
        self.model = self.predictor = self.stream = None

    def start_segment(self, video, frame, targets):
        import cv2
        from ultralytics.data.loaders import LoadImagesAndVideos, SourceTypes
        from ultralytics.models.sam import SAM2VideoPredictor
        class Loader(LoadImagesAndVideos):
            def _new_video(loader, path):
                super()._new_video(path)
                loader.cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
                loader.frames = max(0, loader.frames-frame)
        class Predictor(SAM2VideoPredictor):
            def add_new_prompts(predictor, *args, **kwargs):
                # 8.4.161 prepares N,H,W masks; SAM2 track_step requires N,1,H,W.
                masks = kwargs.get('masks')
                if masks is not None and masks.ndim == 3:
                    kwargs['masks'] = masks[:, None]
                return super().add_new_prompts(*args, **kwargs)

            def inference(predictor, *args, **kwargs):
                result = super().inference(*args, **kwargs)
                state = predictor.inference_state
                index = predictor.dataset.frame
                out = state['output_dict']
                current = out['cond_frame_outputs'].get(index, out['non_cond_frame_outputs'].get(index))
                masks = current['pred_masks'].flatten(0,1)
                valid = (masks > predictor.model.mask_threshold).sum((1,2)) > 0
                predictor.valid_object_indices = valid.nonzero().flatten().cpu().tolist()
                return result
        self.close()
        loader = Loader(video, batch=1, vid_stride=1)
        loader.source_type = SourceTypes()
        self.predictor = Predictor(overrides=dict(model=self.path, device=self.device, imgsz=self.imgsz,
                                                 task='segment', mode='predict', verbose=False, save=False))
        if self.model is not None:
            self.predictor.setup_model(model=self.model, verbose=False)
        self.ids = list(targets)
        if any(targets[i].get('polygons') for i in self.ids):
            width, height = int(loader.cap.get(3)), int(loader.cap.get(4))
            self.stream = self.predictor(source=loader, masks=self.rasterize_targets(targets, width, height), stream=True)
        else:
            self.stream = self.predictor(source=loader, bboxes=[targets[i]['pixels'] for i in self.ids], stream=True)
        self.start = frame

    def rasterize_targets(self, targets, width, height):
        """把目标几何（多边形优先，否则外接框）栅格化为掩码，按 self.ids 顺序排列。"""
        import cv2
        import numpy as np
        masks=[]
        for i in self.ids:
            t=targets[i]
            mask=np.zeros((height,width),dtype=np.uint8)
            if t.get('polygons'):
                # 用 shift=5（×32 定点）保留亚像素坐标，避免 rint 取整产生的半像素边界偏移，
                # 否则 prompt mask 的舍入误差会被 SAM2 当成提示进一步放大成整体位置漂移。
                contours=[np.rint(np.asarray(r,dtype=np.float64)*[width*32,height*32]).astype(np.int32) for r in t['polygons']]
                cv2.fillPoly(mask,contours,1,shift=5)
                if t.get('holes'):
                    cv2.fillPoly(mask,[np.rint(np.asarray(r,dtype=np.float64)*[width*32,height*32]).astype(np.int32) for r in t['holes']],0,shift=5)
            else:
                a,b,c,d=map(round,t['pixels']);mask[b:d,a:c]=1
            masks.append(mask)
        return np.stack(masks)

    def next_frame(self):
        result = next(self.stream)
        self.model = self.predictor.model
        indices = self.predictor.valid_object_indices
        masks = result.masks.data.cpu().numpy() if result.masks is not None else []
        if len(indices) != len(masks):
            raise RuntimeError('SAM2 mask 和持久目标映射数量不一致')
        return self.start+self.predictor.dataset.frame-1, result.orig_img, {self.ids[i]: m for i,m in zip(indices,masks)}

    def correct_current(self, video, frame, targets):
        """暂停后恢复跟踪。优先会话内纠偏：预测器仍驻留且目标集合未增删时，
        直接在当前帧注入修正 mask（add_new_prompts）并重编码记忆
        （propagate_in_video_preflight），保留此前的 SAM2 时序记忆。
        目标集合变化或预测器已释放时回退完整重启（重建加载器与预测器）。"""
        predictor = self.predictor
        if predictor is None or self.stream is None or set(targets) != set(self.ids) or frame-self.start < 0:
            return self.start_segment(video, frame, targets)
        try:
            dataset = predictor.dataset
            width, height = int(dataset.cap.get(3)), int(dataset.cap.get(4))
            masks = self.rasterize_targets(targets, width, height)
            _, _, prepared = predictor._prepare_prompts((self.imgsz,)*2, (height, width), masks=masks)
            # SAM2 的状态帧号按“已消费帧数”计数（从 1 开始，等于 dataset.frame）：
            # 暂停发生在消费完 frame 之后，因此状态索引 = frame-start+1。
            index = frame-self.start+1
            assert index == predictor.dataset.frame, '会话内纠偏帧索引失配'
            for obj_id in range(len(self.ids)):
                predictor.add_new_prompts(obj_id=obj_id, masks=prepared[obj_id:obj_id+1], frame_idx=index)
            predictor.propagate_in_video_preflight()
            self.model = predictor.model
        except Exception:
            # 会话内纠偏失败（状态损坏/尺寸异常）时回退完整重启，保证正确性优先。
            self.start_segment(video, frame, targets)

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        if self.predictor is not None:
            dataset = getattr(self.predictor, 'dataset', None)
            if dataset is not None and getattr(dataset, 'cap', None) is not None:
                dataset.cap.release()

    def release_gpu(self):
        self.close()
        self.model = self.predictor = self.stream = None
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def run_tracking(worker):
    import cv2
    import ultralytics
    task, run = worker.task, worker.run
    from .worker import emit as send
    def emit(kind, **payload):
        send(kind, session=task.get('session'), run=str(run), next_id=manifest.get('next_id', 0), **payload)
    video = Path(task['video'])
    cap = cv2.VideoCapture(str(video))
    fps, total = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(3)), int(cap.get(4))
    cap.release()
    if fps <= 0 or total <= 0:
        raise ValueError('视频参数无效')
    # SAM2 默认按 imgsz（常为 1024）推理，1080p/4K 视频会被下采样再上采样，
    # 轮廓边界天生带数像素偏移（表现为框“漂在物体旁边、没精准贴合”）。
    # 这里把推理尺寸对齐到视频原生短边（64 的倍数、上限 2048），消除该误差源。
    short_side = max(1, min(w, h))
    task['imgsz'] = min(2048, max(task.get('imgsz', 1024), -(-short_side // 64) * 64))
    fingerprint = dict(path=str(video.resolve()), size=video.stat().st_size, sha256=digest(video))
    model_fingerprint = digest(task['model'])
    frame_step, legacy_interval = sampling_spec(task)
    manifest_path = run/'frame_manifest.json'
    manifest = read_json(manifest_path)
    if manifest:
        if manifest.get('schema_version') != 1 or manifest.get('backend_version') != ultralytics.__version__ or manifest.get('imgsz') != task['imgsz']:
            raise ValueError('跟踪记录版本或输入尺寸不匹配，无法恢复')
        saved_step = manifest.get('frame_step')
        saved_interval = manifest.get('interval')
        plan_matches = saved_step == frame_step if frame_step is not None else saved_step is None and saved_interval == legacy_interval
        if manifest['video'] != fingerprint or not plan_matches or manifest['model_sha256'] != model_fingerprint:
            raise ValueError('源视频、模型或采样间隔发生变化，无法恢复')
        segment = manifest['segments'][-1]
        start, targets = segment['start_frame'], {int(k):copy.deepcopy(v) for k,v in segment['targets'].items()}
        checkpoint = manifest['checkpoint']
    else:
        targets = {int(t['id']):dict(cls=t['cls'], box=t['box'], polygons=t.get('polygons'), holes=t.get('holes'),object_id=t.get('object_id')) for t in task['targets']}
        if not targets or len(targets) > ACTIVE_LIMIT or any(i < 0 for i in targets):
            raise ValueError(f'请初始化 1–{ACTIVE_LIMIT} 个目标（同一时刻活跃目标数上限，新目标自动分配新编号）')
        start = int(task.get("start_frame",0))
        if not 0<=start<total:raise ValueError("起始帧超出视频范围")
        checkpoint = start-1
        manifest = dict(schema_version=1, video=fingerprint, fps=fps, width=w, height=h,
                        model=task['model'], model_sha256=model_fingerprint, backend='ultralytics-sam2',
                        backend_version=ultralytics.__version__, imgsz=task['imgsz'],
                        checkpoint=-1, state='tracking', next_id=max(task.get('next_id', 0),max(targets)+1), events=[], segments=[], outputs=[])
        manifest.update(frame_step=frame_step) if frame_step is not None else manifest.update(interval=legacy_interval)
        manifest['segments'].append(dict(start_frame=start, targets=copy.deepcopy(targets)))
    images = run/'video_images'
    images.mkdir(exist_ok=True)
    labels = Labels(run/'video_images_labels')
    labels.set_classes(task['classes'])
    written = {out['frame'] for out in manifest['outputs']}
    # 强杀可能落在“输出已写盘但尚未登记进 manifest”的窗口；这些文件可再次生成，
    # 恢复时清理，否则同名输出会永久卡死续跑（以前会一律拒绝覆盖）。
    registered = {Path(out['image']).stem for out in manifest['outputs']}
    for stale in images.glob('frame_*.jpg'):
        if stale.stem in registered:
            continue
        stale.unlink(missing_ok=True)
        (labels.folder/(stale.stem+'.txt')).unlink(missing_ok=True)
        (labels.folder/(stale.stem+'.annotation.json')).unlink(missing_ok=True)
    from .tracking_backfill import SampleBackfill
    backfill=SampleBackfill(task,run) if task.get('sample_run') else None
    sample_plan=read_json(Path(task['sample_run'])/'frame_manifest.json', {}) if backfill else {}
    if backfill and (sample_plan.get('state') != 'complete' or sample_plan.get('video_sha256') != fingerprint['sha256']):
        raise ValueError('抽帧清单未完成或原视频内容已改变，拒绝跟踪回填')
    sample_frames={o['frame'] for o in sample_plan.get('outputs', [])}
    keyframe_path=run/'planned_keyframes.json'
    skipped_keyframes={}
    if keyframe_path.exists():
        human_keyframes={int(f):{int(i):t for i,t in ts.items()} for f,ts in read_json(keyframe_path,{}).items()}
    else:
        human_keyframes, skipped_keyframes = backfill.human_keyframes(targets,start) if backfill else ({}, {})
        save_json(keyframe_path,human_keyframes)
    for frame in list(human_keyframes):
        committed=read_json(run/f'keyframe_{frame}.json',{})
        if committed.get('targets'):
            human_keyframes[frame]={int(i):t for i,t in committed['targets'].items()}
    if skipped_keyframes:
        mapping = {frame:('；'.join(reasons)) for frame,reasons in sorted(skipped_keyframes.items())}
        if task.get('quality',{}).get('strict_keyframes'):
            raise ValueError(f'关键帧无法安全关联（strict_keyframes）：{mapping}')
        for frame, reasons in sorted(skipped_keyframes.items()):
            emit('log', message=f'关键帧 {frame} 已跳过：{"；".join(reasons)}。跟踪会继续，请留意丢失目标，可暂停修正。')
    applied_keyframes=set()
    # A committed human keyframe is authoritative. Replaying that same decoded
    # frame must not manufacture a conflict against the correction we just saved.
    manual_frames={int(path.stem.removeprefix('keyframe_')) for path in run.glob('keyframe_*.json')}
    quality = {**QUALITY, **task.get('quality',{})}
    loss_grace = max(0, int(quality.get('loss_grace_frames', 3)))  # 目标丢失的连续帧宽限；0=立即暂停
    reanchor_every = max(0, int(quality.get('reanchor_frames', 150)))  # 定期重锚间隔；0=关闭。SAM2 时序记忆会累积陈旧帧使 mask 滑离物体，周期性重编码当前 mask 可阻止漂移
    control_path = run/'control.json'
    control_path.unlink(missing_ok=True)
    backend = Sam2Backend(task['model'],task.get('device','cpu'),task['imgsz'])
    def prepared():
        return {i:{**v, 'pixels':[v['box'][0]*w,v['box'][1]*h,v['box'][2]*w,v['box'][3]*h]} for i,v in targets.items()}
    import uuid
    for target_id,target in targets.items():
        if not target.get('object_id'):target['object_id']=uuid.uuid5(uuid.NAMESPACE_URL,f'{run}:target:{target_id}').hex
    if targets:backend.start_segment(str(video), start, prepared())
    paused, frame_index, last_preview = not bool(targets), start, -1
    emit('tracking_state',state='paused' if paused else 'tracking',targets=targets,frame=frame_index)
    finish_requested = False
    loss_counter = {}  # target_id -> 连续丢失帧数（失败分级宽限用）
    pause_idle = time.monotonic()
    def preview_current():
        # Read the exact paused frame; a throttled earlier preview is not editable.
        capture=cv2.VideoCapture(str(video));capture.set(cv2.CAP_PROP_POS_FRAMES,frame_index)
        ok,picture=capture.read();capture.release()
        if not ok:raise ValueError('无法读取暂停帧')
        preview=run/f'preview_pause_{frame_index}.jpg'
        cv2.imencode('.jpg',picture)[1].tofile(preview)
        emit('tracking_frame',frame=frame_index,path=str(preview),boxes={i:asdict(Box(t['cls'],*t['box'],'AI',polygons=t.get('polygons'),holes=t.get('holes'),target_id=i,object_id=t.get('object_id'))) for i,t in targets.items()})
    def acknowledge_pause(failures=None):
        import uuid
        nonlocal pause_idle
        gpu = bool(task.get('gpu_keep_alive', True)) and bool(targets)
        if not gpu:
            backend.release_gpu()  # 暂停释放 GPU（可用 gpu_keep_alive=false 强制，或空闲超时自动释放）
        preview_current()
        manifest.update(state='paused', pause_token=uuid.uuid4().hex, gpu_released=not gpu,
                        pause_frame=frame_index, preview=str(run/f'preview_pause_{frame_index}.jpg'))
        save_json(manifest_path,manifest)
        emit('tracking_state',state='paused',targets=targets,frame=frame_index,
             pause_token=manifest['pause_token'],gpu_released=not gpu,
             **({'failures':failures} if failures else {}))
        pause_idle = time.monotonic()
    if paused:acknowledge_pause()
    try:
        while True:
            worker.check()
            command = read_json(control_path)
            if command:
                control_path.unlink(missing_ok=True)
                action = command['action']
                if action == 'pause':
                    paused = True
                elif action == 'resume':
                    if targets:
                        backend.correct_current(str(video),frame_index,prepared())
                        loss_counter.clear()
                    paused = False
                elif action in ('correct','add','end','seek','commit','finish_review'):
                    if not paused:
                        raise ValueError('请暂停后编辑目标')
                    if action in ('commit','finish_review'):
                        if not command.get('pause_token') or command['pause_token'] != manifest.get('pause_token'):raise ValueError('暂停会话已变化')
                        current_classes=Labels(Path(task['project'])/'Main_labels').classes
                        if current_classes[:len(task['classes'])]!=task['classes']:raise ValueError('类别映射已变化')
                        task['classes']=current_classes
                        save_json(run/'task.json',task)
                        labels.set_classes(current_classes)
                        if command.get('frame') != frame_index:raise ValueError('纠偏帧已变化，请重新暂停')
                        incoming={int(t['id']):dict(cls=t['cls'],box=t['box'],polygons=t.get('polygons'),holes=t.get('holes'),object_id=t.get('object_id')) for t in command['targets']}
                        if len(incoming)!=len(command['targets']) or len(incoming)>ACTIVE_LIMIT:raise ValueError('目标 ID 重复，或同时跟踪目标超过 32')
                        for i,t in incoming.items():
                            b=t['box']
                            if not (i>=0 and 0<=t['cls']<len(task['classes']) and len(b)==4 and all(math.isfinite(v) for v in b) and 0<=b[0]<b[2]<=1 and 0<=b[1]<b[3]<=1):raise ValueError('目标数据无效')
                            if i not in targets and i<manifest['next_id']:raise ValueError('不能复用已结束目标 ID')
                        next_id=max(manifest['next_id'],int(command.get('next_id',0)),max(incoming,default=-1)+1)
                        targets=incoming;manifest['next_id']=next_id
                        corrections=[Box(t['cls'],*t['box'],'人工',polygons=t.get('polygons'),holes=t.get('holes'),target_id=i,object_id=t.get('object_id')) for i,t in targets.items()]
                        save_json(run/f'keyframe_{frame_index}.json',dict(frame=frame_index,targets=targets))
                        manual_frames.add(frame_index)
                        for output in manifest['outputs']:
                            if output['frame']==frame_index:
                                labels.save(Path(output['image']).stem,corrections)
                                output['boxes']={i:asdict(b) for i,b in zip(targets,corrections)}
                        if backfill:backfill.update(frame_index,corrections,manual=True)
                    elif action == 'add':
                        target_id = manifest['next_id']
                        if len(targets) >= ACTIVE_LIMIT:
                            raise ValueError(f'同时跟踪目标已达 {ACTIVE_LIMIT} 个上限；可结束旧目标释放名额')
                        manifest['next_id'] += 1
                        targets[target_id] = dict(cls=command['cls'],box=command['box'])
                    elif action == 'correct':
                        targets[int(command['id'])]['box'] = command['box']
                    elif action == 'end':
                        targets.pop(int(command['id']),None)
                    else:
                        if targets or not frame_index <= command['frame'] < total:
                            raise ValueError('仅无活动目标时允许向前定位')
                        frame_index = command['frame']
                    manifest['events'].append({**command, 'frame':frame_index})
                    manifest['segments'].append(dict(start_frame=frame_index,targets=copy.deepcopy(targets)))
                    checkpoint = frame_index-1
                    manifest.update(checkpoint=checkpoint,targets=targets,state='paused')
                    save_json(manifest_path,manifest)
                    if targets:
                        try:
                            backend.correct_current(str(video),frame_index,prepared())
                        except Exception as exc:
                            emit('log',message='恢复失败，修正已保存，可重试：'+str(exc))
                            paused=True
                            acknowledge_pause()
                            continue
                        loss_counter.clear()
                    checkpoint = frame_index-1
                    if action in ('commit','finish_review'):paused=not bool(targets)
                    if action=='finish_review':finish_requested=True
                    if paused:preview_current()
                manifest.update(targets=targets,checkpoint=checkpoint,state='paused' if paused else 'tracking')
                save_json(manifest_path,manifest)
                if paused:acknowledge_pause()
                else:
                    manifest.update(pause_token=None,gpu_released=False)
                    save_json(manifest_path,manifest)
                    emit('tracking_state',state='tracking',targets=targets,frame=frame_index)
            if finish_requested:
                break
            if not targets:
                manifest.update(state='completed',checkpoint=frame_index,targets={})
                save_json(manifest_path,manifest)
                break
            if paused:
                keep_seconds = max(1.0, float(task.get('gpu_keep_alive_seconds', 300)))
                if backend.predictor is not None and time.monotonic()-pause_idle >= keep_seconds:
                    backend.release_gpu()  # 释放 SAM2 与显存；恢复时自动回退完整重启
                    manifest['gpu_released'] = True
                    save_json(manifest_path,manifest)
                    emit('tracking_state',state='paused',targets=targets,frame=frame_index,
                         pause_token=manifest.get('pause_token'),gpu_released=True)
                    pause_idle = time.monotonic()
                time.sleep(.05)
                continue
            try:
                frame_index, image, masks = backend.next_frame()
            except StopIteration:
                break
            if frame_index in human_keyframes and frame_index not in applied_keyframes:
                corrections=copy.deepcopy(human_keyframes[frame_index])
                for target_id,t in corrections.items(): t["object_id"]=targets[target_id].get("object_id")
                targets.update(corrections)
                try:
                    backend.correct_current(str(video),frame_index,prepared())
                except Exception as exc:
                    # 人工修正已写回 targets/keyframe；单次会话内纠正失败不中断跟踪，保持继续（必要时后台自动回退完整重启）。
                    emit('log',message=f'人工关键帧 {frame_index} 已保存，但会话内纠正失败，继续跟踪：{exc}')
                loss_counter.clear()
                applied_keyframes.add(frame_index)
                manual_frames.add(frame_index)
                save_json(run/f'keyframe_{frame_index}.json',dict(frame=frame_index,targets=targets))
                manifest['segments'].append(dict(start_frame=frame_index,targets=copy.deepcopy(targets)))
                save_json(manifest_path,manifest)
                emit('log',message=f'应用人工关键帧 {frame_index}')
                continue
            boxes, failures = {}, {}
            for target_id,t in targets.items():
                box = mask_box(masks[target_id],t['cls']) if target_id in masks else None
                old = Box(t['cls'],*t['box'])
                reason = quality_reason(old,box,quality) if frame_index != backend.start else ('目标丢失' if box is None else None)
                if reason:
                    failures[target_id] = reason
                if box:
                    box.target_id=target_id
                    box.object_id=t.get("object_id")
                    boxes[target_id] = box
                    loss_counter[target_id] = 0
            if frame_index <= checkpoint:
                for target_id, box in boxes.items():
                    targets[target_id].update(box=[box.x1,box.y1,box.x2,box.y2],polygons=box.polygons,holes=box.holes)
                continue  # deterministic memory replay: never export or pause
            if frame_index-last_preview >= max(1,int(fps/5)):
                preview = run/f'preview_{frame_index}.jpg'
                cv2.imencode('.jpg',image)[1].tofile(preview)
                emit('tracking_frame',frame=frame_index,path=str(preview),boxes={i:asdict(b) for i,b in boxes.items()},targets=targets)
                last_preview = frame_index
            if failures:
                # 失败分级：单目标丢失按“连续帧宽限”缓期（遮挡/闪回不再立刻全场暂停）；
                # 面积/位置突变等几何异常没有缓期语义，前后帧都已错，立即交给用户。
                pending_failures = {}
                for target_id, reason in failures.items():
                    if reason == '目标丢失' and loss_grace > 0:
                        loss_counter[target_id] = loss_counter.get(target_id,0)+1
                        if loss_counter[target_id] <= loss_grace:
                            emit('log',message=f'目标 {target_id} 连续丢失 {loss_counter[target_id]}/{loss_grace} 帧，缓期观察；若持续出现则暂停')
                            continue
                        pending_failures[target_id] = f'目标丢失（连续 {loss_counter[target_id]} 帧）'
                    else:
                        pending_failures[target_id] = reason
                if pending_failures:
                    paused = True
                    manifest['state'] = 'paused'
                    manifest['events'].append(dict(frame=frame_index,action='quality_failure',failures=pending_failures))
                    save_json(manifest_path,manifest)
                    acknowledge_pause(pending_failures)
                    continue
                # 宽限期内：按缺该目标继续（下方正常导出流程自然缺少此框）
            for target_id,box in boxes.items():
                targets[target_id].update(box=[box.x1,box.y1,box.x2,box.y2],polygons=box.polygons,holes=box.holes)
            # 定期重锚：把当前帧 mask 重新作为提示注入并重编码 SAM2 时序记忆，
            # 防止记忆库陈旧帧累积导致轮廓逐渐滑离物体（整体位置漂移）。
            if reanchor_every and frame_index > backend.start and frame_index > checkpoint and (frame_index-backend.start) % reanchor_every == 0:
                try:
                    backend.correct_current(str(video),frame_index,prepared())
                    emit('log',message=f'第 {frame_index} 帧已重新锚定目标记忆，抑制轮廓漂移')
                except Exception as exc:
                    emit('log',message=f'第 {frame_index} 帧重锚失败（继续跟踪）：{exc}')
            stride = frame_step if frame_step is not None else max(1,round(legacy_interval*fps))
            if backfill and frame_index in sample_frames and frame_index not in manual_frames:
                backfill.update(frame_index,list(boxes.values()))
            if not backfill and frame_index % stride == 0 and frame_index not in written:
                name = f'frame_{len(written):06d}_f{frame_index}_t{round(frame_index/fps*1000)}'
                path = images/(name+'.jpg')
                if path.exists():
                    raise ValueError(f'检测到未登记输出 {path.name}，拒绝覆盖；请重启跟踪任务以自动清理')
                cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,95])[1].tofile(path)
                try:
                    labels.save(name,list(boxes.values()))
                except Exception:
                    path.unlink(missing_ok=True)
                    raise
                manifest['outputs'].append(dict(frame=frame_index,timestamp_ms=round(frame_index/fps*1000),image=str(path),
                                                boxes={i:asdict(b) for i,b in boxes.items()}))
                written.add(frame_index)
            manifest.update(checkpoint=frame_index,state='tracking',targets=targets)
            save_json(manifest_path,manifest)
            worker.progress((frame_index+1)/total,f'帧 {frame_index+1}/{total}，导出 {len(written)} 张',
                            frame=frame_index+1,total=total,exported=len(written))
    except InterruptedError:
        manifest['state'] = 'cancelled'
        raise
    except Exception:
        manifest['state'] = 'failed'
        raise
    finally:
        backend.close()
        manifest['state'] = 'cancelled' if worker.cancelled() else manifest['state']
        save_json(manifest_path,manifest)
    manifest['state'] = 'completed'
    save_json(manifest_path,manifest)
    return {'images':str(images),'labels':str(labels.folder),'manifest':str(manifest_path),'count':len(written),
            'conflicts':list(read_json(run/'backfill_conflicts.json', {}).keys())}
