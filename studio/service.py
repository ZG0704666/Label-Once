"""Application operations shared by the native desktop bridge, without importing Qt."""
from __future__ import annotations
from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile
import uuid
from .domain import Box, Project, IMAGE_EXTENSIONS, read_json, save_json
from .config import settings, save_settings, CONFIG_ROOT, model_paths, ADVANCED, AUGMENTS, augmentation_values
from .processes import ProcessManager


class StudioService:
    def __init__(self, emit=lambda event: None):
        self.project = None
        self.tasks = ProcessManager(emit)
        self.video = None
        from .interactive_sam import InteractiveSam
        self.sam = InteractiveSam()
        self.preview = tempfile.TemporaryDirectory(prefix='labelonce_')
        self._raster = None

    def require(self, params, idle=False):
        if self.project is None:
            raise ValueError('请先打开或新建项目')
        if params.get('project') and Path(params['project']).resolve() != self.project.root:
            raise ValueError('请求所属项目已改变，未执行过期操作')
        if idle and self.tasks.busy:
            raise RuntimeError('请先等待当前任务完成或停止')
        return self.project

    def paused_source(self, params):
        task=self.tasks.task or {}
        if not self.tasks.busy or task.get('kind') != 'tracking':
            raise ValueError('没有已暂停的跟踪任务')
        run=Path(task['run'])
        state=read_json(run/'frame_manifest.json', {})
        if (state.get('state') != 'paused' or not state.get('gpu_released') or
            not params.get('pause_token') or params['pause_token'] != state.get('pause_token') or
            (run/'control.json').exists()):
            raise ValueError('请等待跟踪确认暂停并释放模型')
        return Path(state['preview'])

    def image(self, name):
        if Path(name).name != name:
            raise ValueError('无效的项目图片名称')
        path = self.project.images/name
        if not path.is_file():
            raise ValueError('图片不存在')
        return path

    def _resume_training(self, project, task):
        """Resolve a resume target to its run directory and checkpoint, inheriting the original run.

        Resuming continues the interrupted run in place, so the artifacts, the experiment record
        and the training curve all stay in the directory the user already knows.
        """
        path = Path(task['resume']).expanduser()
        if path.is_dir():
            found = sorted(path.rglob('weights/last.pt'))
            if not found:
                raise ValueError('该运行目录中没有 last.pt 检查点，无法续训')
            path = found[-1]
        if path.name != 'last.pt' or not path.is_file():
            raise ValueError('续训需要 last.pt 检查点')
        run = path.parent.parent.parent
        if not run.resolve().is_relative_to(project.runs.resolve()):
            raise ValueError('只能续训当前项目的训练运行')
        original = read_json(run/'task.json', {})
        task['run'] = str(run)
        task['resume'] = str(path)
        if not task.get('dataset_version'):
            task['dataset_version'] = original.get('dataset_version')
        return task

    def snapshot(self):
        from .review import ReviewStore
        from .dataset import DatasetStore
        p = self.project
        review = ReviewStore(p)
        records = review.records()
        dataset = DatasetStore(p)
        experiments = p.models/'experiments.jsonl'
        gate = read_json(p.models/'release_gate.json', {}) or {}
        gate_model = Path(gate.get('model') or '')
        gate_stat = gate_model.stat() if gate_model.is_file() else None
        gate['stale'] = bool(gate and (
            gate.get('dataset_version', '') != (dataset.active() or '') or gate_stat is None or
            gate.get('model_size') != gate_stat.st_size or gate.get('model_mtime_ns') != gate_stat.st_mtime_ns))
        return dict(project=str(p.root), classes=p.labels.classes, stats=p.stats(),
            images=[dict(name=i.name, path=str(i), status=review.status(i.name, records),
                         batch=records.get(i.name, {}).get('batch'), metadata=records.get(i.name, {})) for i in p.image_paths()],
            versions=dataset.list_versions(), active_version=dataset.active(), release_gate=gate,
            models=sorted(set(model_paths()+[str(x) for x in p.models.glob('*.pt')])),
            sam_models=model_paths(True), workspace=read_json(p.config/'workspace.json', {}),
            experiments=[json.loads(line) for line in experiments.read_text(encoding='utf-8').splitlines() if line.strip()] if experiments.exists() else [])

    def dispatch(self, method, params):
        if method == 'hello':
            return dict(protocol=1, capabilities=['review.batch', 'review.pending', 'review.reject', 'progress.frame_counts', 'task.control.supersedes'],
                        settings=settings(), preferences=read_json(CONFIG_ROOT/'wpf.json', {}),
                        models=model_paths(), sam_models=model_paths(True), advanced=ADVANCED, augments=AUGMENTS)
        if method == 'settings.save':
            current = settings()
            current.update(params.get('settings', {}))
            if int(current.get('sam_imgsz', 1024)) % 32:
                raise ValueError('SAM 输入尺寸须为 32 的倍数')
            save_settings(current)
            if 'preferences' in params:
                save_json(CONFIG_ROOT/'wpf.json', params['preferences'])
            return current
        if method == 'project.open':
            if self.tasks.busy:
                raise RuntimeError('请先停止当前任务')
            p = Project(params['path'])
            p.assert_unique_stems()
            self.project = p
            cfg = settings()
            cfg['recent'] = [str(p.root)]+[r for r in cfg.get('recent', []) if r != str(p.root)][:9]
            save_settings(cfg)
            return self.snapshot()
        if method == 'task.cancel':
            return self.tasks.cancel(params.get('force', False))
        if method == 'task.status':
            return dict(busy=self.tasks.busy, task=self.tasks.task)
        p = self.require(params)
        if method == 'project.snapshot':
            return self.snapshot()
        if method == 'workspace.save':
            save_json(p.config/'workspace.json', params['state'])
            return {'saved': True}
        if method == 'images.import':
            self.require(params, True)
            from .imports import import_images
            paths = []
            for value in params['paths']:
                source = Path(value)
                paths.extend(sorted(str(x) for x in source.rglob('*') if x.is_file() and x.suffix.lower() in IMAGE_EXTENSIONS) if source.is_dir() else [value])
            report=dict(duplicates=0,failures=[])
            names=import_images(p, paths, report)
            return dict(names=names, report=report, snapshot=self.snapshot())
        if method == 'images.transfer':
            self.require(params, True)
            from .imports import import_images
            destination = Project(params['destination'])
            if destination.root == p.root:
                raise ValueError('目标项目不能是当前项目')
            names = params['names']
            imported = import_images(destination, [str(self.image(n)) for n in names])
            if params.get('move'):
                for name in names:
                    p.trash_image(self.image(name))
            return dict(names=imported)
        if method == 'images.rename':
            self.require(params, True)
            if params.get('preview', False):
                return [[a.name, b.name] for a,b in p.rename_preview(params['prefix'], params.get('start', 1))]
            p.batch_rename(params['prefix'], params.get('start', 1))
            return self.snapshot()
        if method == 'images.trash':
            self.require(params, True)
            return {'folders': [str(p.trash_image(self.image(n))) for n in params['names']]}
        if method == 'sam.segment':
            if self.tasks.busy:
                path=self.paused_source(params)
            elif params.get('video_session'):
                if not self.video or params['video_session'] != self.video['session']:
                    raise ValueError('视频会话已改变')
                path=Path(self._video_frame(params['frame'])['path'])
            else:
                path=self.image(params['name'])
            return self.sam.segment(path, params)
        if method == 'sam.release':
            self.sam.close()
            return dict(released=True)
        if method == 'annotation.simplify':
            self.require(params, True)
            import cv2
            import numpy as np
            from PIL import Image
            epsilon = float(params['epsilon'])
            if not math.isfinite(epsilon) or epsilon <= 0:
                raise ValueError('轮廓误差必须为正数')
            with Image.open(self.image(params['name'])) as image:
                w,h = image.size
            boxes = [Box(**b) for b in params['boxes']]
            for b in boxes:
                if not b.raw_polygons:
                    continue
                simplified=[]
                for ring in b.raw_polygons:
                    contour=np.asarray(ring,dtype=np.float32)*[w,h]
                    from .contour_simplification import simplify_ring
                    reduced=simplify_ring(contour,epsilon)
                    simplified.append([[float(x/w),float(y/h)] for x,y in reduced] if len(reduced)>=3 else ring)
                b.polygons=simplified
            return dict(boxes=[asdict(b) for b in boxes])
        if method == 'annotation.load':
            from PIL import Image
            path = self.image(params['name'])
            with Image.open(path) as im:
                width, height = im.size
                orientation = int(im.getexif().get(274, 1))
                # WPF receives a raw raster without EXIF auto-rotation (WebP supported too).
                raster = Path(self.preview.name)/(uuid.uuid4().hex+'.png')
                im.convert('RGB').save(raster)
                if self._raster is not None and self._raster.is_file():
                    # 上一次打开的栅格已不再使用，防临时目录随打开次数无限膨胀
                    try:self._raster.unlink()
                    except OSError:pass
                self._raster = raster
            return dict(name=path.name, path=str(raster), source=str(path), width=width, height=height,
                        orientation=orientation, boxes=[asdict(b) for b in p.labels.load(path.stem)],
                        revision=read_json(p.labels.folder/(path.stem+'.annotation.json'), {}).get('revision', 0),
                        metadata=__import__('studio.review', fromlist=['ReviewStore']).ReviewStore(p).records().get(path.name, {}))
        if method == 'annotation.save':
            self.require(params, True)
            path = self.image(params['name'])
            boxes = [Box(**b) for b in params['boxes']]
            for b in boxes:
                if not isinstance(b.cls, int) or b.cls < 0 or b.cls >= len(p.labels.classes):
                    raise ValueError('标注类别无效')
                if not all(math.isfinite(v) for v in (b.x1,b.y1,b.x2,b.y2)):
                    raise ValueError('标注坐标无效')
                if b.polygons and any(not all(math.isfinite(v) and 0 <= v <= 1 for v in xy) or len(xy)!=2 for poly in b.polygons for xy in poly):
                    raise ValueError('轮廓坐标无效')
            doc = p.labels.save(path.stem, boxes, params.get('expected_revision'))
            if params.get('confirm'):
                from .review import ReviewStore
                ReviewStore(p).confirm([path.name])
            return dict(saved=True, name=path.name, revision=doc['revision'])
        if method == 'review.pending':
            self.require(params, True)
            items = []
            for name in params.get('names', []):
                image = self.image(name)
                label = p.labels.folder/(image.stem+'.txt')
                missing = not label.is_file()
                boxes = [] if missing else p.labels.load(image.stem)
                items.append(dict(name=name, missing=missing,
                                  empty=not missing and not boxes,
                                  unknown=any(b.cls >= len(p.labels.classes) for b in boxes)))
            return dict(items=items)
        if method == 'review.reject':
            self.require(params, True)
            from .review import ReviewStore
            names = params['names']
            for n in names:
                self.image(n)
            ReviewStore(p).reject(names, params.get('reason', ''))
            return {'rejected': names}
        if method == 'review.confirm':
            self.require(params, True)
            from .review import ReviewStore
            names = params['names']
            for n in names:
                self.image(n)
            ReviewStore(p).confirm(names)
            return {'confirmed': names}
        if method == 'classes.ensure':
            if self.tasks.busy and (self.tasks.task or {}).get('kind') != 'tracking':
                raise RuntimeError('后台任务运行中，请等待完成或停止后再修改类别')
            if self.tasks.busy:self.paused_source(params)
            name = params.get('name')
            if not isinstance(name, str) or not name.strip() or '\n' in name or '\r' in name:
                raise ValueError('类别名称不能为空或包含换行')
            name = name.strip()
            names = p.labels.classes
            created = name not in names
            if created:
                names.append(name)
                p.labels.set_classes(names)
            return dict(class_id=names.index(name), name=name, created=created, classes=names)
        if method == 'classes.save':
            self.require(params, True)
            names = params['names']
            if not names or any(not isinstance(n, str) or not n.strip() or '\n' in n or '\r' in n for n in names) or len(set(names)) != len(names):
                raise ValueError('类别名称不能为空、重复或包含换行')
            old = p.labels.classes
            mapping = params.get('mapping')
            if mapping is None:
                mapping = {i:names.index(n) for i,n in enumerate(old) if n in names}
                free_old = [i for i in range(len(old)) if i not in mapping]
                free_new = [i for i in range(len(names)) if i not in mapping.values()]
                mapping.update(zip(free_old, free_new))
            mapping = {int(k):int(v) for k,v in mapping.items()}
            if any(k < 0 or k >= len(old) or v < 0 or v >= len(names) for k,v in mapping.items()):
                raise ValueError('类别映射超出范围')
            backup = p.labels.reorder(names, mapping)
            return dict(classes=names, backup=str(backup))
        if method == 'dataset.activate':
            self.require(params, True)
            from .dataset import DatasetStore
            DatasetStore(p).activate(params['version'])
            return self.snapshot()
        if method == 'dataset.merge.preview':
            self.require(params, True)
            from .dataset import DatasetStore
            from .merge import preview
            return preview(DatasetStore(p), params.get('spec', {}))
        if method == 'dataset.sources':
            self.require(params, True)
            from .dataset import DatasetStore
            from .merge import list_sources
            return list_sources(DatasetStore(p), forget=params.get('forget'))
        if method == 'dataset.merge.external_versions':
            self.require(params)
            root = Path(params['external'])
            base = root / (root.name + '_dataset')
            versions = []
            if (base / 'versions').is_dir():
                versions = sorted(q.name for q in (base / 'versions').iterdir()
                                  if (q / 'dataset_manifest.json').is_file())
            active = (read_json(base / 'active.json', {}) or {}).get('version')
            return dict(project=str(root), active=active, versions=versions)
        if method == 'preset.get':
            values = dict(ADVANCED, **AUGMENTS, epochs=50,batch=16,lr0=.001,imgsz=640,device='0')
            old = read_json(p.config/'train_preset.json', read_json(p.config/'train.json', {}))
            values.update(read_json(p.models/'advanced_train_params.json', {}).get('params', {}))
            values.update(old.get('advanced', {}).get('params', {}))
            for key in ('epochs','batch','lr0','imgsz','device'):
                if key in old: values[key] = old[key]
            if 'lr' in old: values['lr0'] = old['lr']
            values.update(augmentation_values(old.get('augmentation', {})))
            values.update(read_json(p.config/'wpf_train_preset.json', {}))
            return values
        if method == 'preset.save':
            save_json(p.config/'wpf_train_preset.json', params['params'])
            return {'saved': True}
        if method in ('video.draft.save', 'video.draft.load'):
            import hashlib
            token=hashlib.sha256(str(Path(params['video']).resolve()).casefold().encode()).hexdigest()
            path=p.config/'video_drafts'/(token+'.json')
            state=read_json(path, dict(schema=1,video=params['video'],frames={}))
            if method.endswith('save'):
                state['frames'][str(params['frame'])]=params['boxes']
                save_json(path,state)
                return dict(saved=True)
            return dict(boxes=state['frames'].get(str(params['frame']), []))
        if method == 'video.open':
            self.require(params, True)
            import cv2
            if self.video:
                self.video['capture'].release()
            capture = cv2.VideoCapture(params['path'])
            if not capture.isOpened():
                raise ValueError('视频无法读取')
            self.video = dict(capture=capture,path=params['path'],session=uuid.uuid4().hex,
                              total=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),fps=capture.get(cv2.CAP_PROP_FPS))
            # 换会话时清理旧会话遗留的预览帧：长时间拖动逐帧会让临时目录涨到 GB 级
            for stale in Path(self.preview.name).glob('*.jpg'):
                if not stale.name.startswith(self.video['session']):
                    try:stale.unlink()
                    except OSError:pass
            return self._video_frame(0)
        if method == 'video.frame':
            if not self.video or params['session'] != self.video['session']:
                raise ValueError('视频会话已改变')
            return self._video_frame(params['frame'])
        if method == 'task.control':
            if params['control'].get('action') in ('commit','resume','finish_review'):
                self.paused_source(params['control'])
                self.sam.close()
            return self.tasks.control(params['control'])
        if method == 'task.restore':
            self.require(params, True)
            self.sam.close()
            task = read_json(Path(params['run'])/'task.json', {})
            if task.get('kind') not in ('tracking', 'extract') or Path(task['project']).resolve() != p.root:
                raise ValueError('请选择当前项目的跟踪或抽帧任务目录')
            task.update(run=params['run'], session=uuid.uuid4().hex)
            return self.tasks.start(task)
        if method == 'tracking.candidate':
            run = Path(params['run'])
            task = read_json(run/'task.json', {})
            if Path(task.get('project', '')).resolve() != p.root:
                raise ValueError('候选不属于当前项目')
            candidate = read_json(run/'backfill_conflicts.json', {}).get(params['name'])
            if candidate is None:
                raise ValueError('当前图片没有冲突候选')
            return candidate
        if method == 'task.start':
            self.require(params, True)
            from .dataset import DatasetStore
            self.sam.close()
            kind = params['kind']
            if kind not in {'prelabel','model_info','sam','train','predict','evaluate','export','extract','import_video','inspect_images','dataset','tracking','segment_dataset','dataset_merge','gate'}:
                raise ValueError('未知任务类型')
            task = dict(params.get('options', {}),kind=kind,project=str(p.root))
            if kind == 'train' and task.get('resume'):
                task = self._resume_training(p, task)
            else:
                task['run'] = str(p.new_run(kind))
            if kind in ('train','evaluate'):
                store = DatasetStore(p)
                task['dataset'] = str(store.yaml_path(task.get('dataset_version')))
                task['dataset_version'] = task.get('dataset_version') or store.active()
            if kind == 'prelabel':
                if any(int(v) < -1 or int(v) >= len(p.labels.classes) for v in task.get('mapping', {}).values()):
                    raise ValueError('AI 类别映射超出范围')
                task['labels'] = str(p.labels.folder)
                task['images'] = [str(self.image(n)) for n in task.pop('names')]
            if kind == 'sam':
                task['image'] = str(self.image(task.pop('name')))
            if kind == 'tracking':
                if task.get('sample_run'):
                    from .review import ReviewStore
                    from .annotations import fingerprint
                    task['sample_versions']={name:fingerprint(p.labels,Path(name).stem) for name,entry in ReviewStore(p).records().items() if entry.get('run')==task['sample_run']}
                task.update(classes=p.labels.classes, session=uuid.uuid4().hex)
            if kind == 'export' and task.get('params', {}).get('quantize') == 8:
                task['params']['data'] = str(DatasetStore(p).yaml_path())
            return self.tasks.start(task)
        raise ValueError(f'未知接口：{method}')

    def _video_frame(self, frame):
        import cv2
        v = self.video
        frame = max(0, min(v['total']-1, int(frame)))
        v['capture'].set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, image = v['capture'].read()
        if not ok:
            raise ValueError(f'无法读取第 {frame+1} 帧')
        path = Path(self.preview.name)/f'{v["session"]}_{frame}.jpg'
        cv2.imencode('.jpg', image)[1].tofile(path)
        return dict(path=str(path),source=v['path'],frame=frame,total=v['total'],fps=v['fps'],
                    width=image.shape[1],height=image.shape[0],orientation=1,session=v['session'])

    def close(self):
        self.tasks.close()
        self.sam.close()
        if self.video:
            self.video['capture'].release()
        self.preview.cleanup()
