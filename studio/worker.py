"""JSONL worker protocol. Heavy imports remain outside the GUI process."""
from __future__ import annotations

import contextlib
import csv
import json
import os
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path

from .domain import Box, IMAGE_EXTENSIONS, Labels, Project, atomic_write, mask_box, read_json, save_json


EVENT_PATH = None


def _write_stdout(text):
    stream = sys.__stdout__
    if stream is None:
        return
    buffer = getattr(stream, 'buffer', None)
    if buffer is not None:
        buffer.write(text.encode('utf-8'))
        buffer.flush()
    else:
        stream.write(text)
        stream.flush()


def emit(kind, **payload):
    line = json.dumps(dict(event=kind, **payload), ensure_ascii=False, default=str, allow_nan=False) + '\n'
    _write_stdout(line)
    if EVENT_PATH is not None:
        with EVENT_PATH.open('a', encoding='utf-8') as f:
            f.write(line)


class Worker:
    def __init__(self, task):
        self.task = task
        self.run = Path(task['run'])
        self.run.mkdir(parents=True, exist_ok=True)
        self.cancel_file = self.run/'cancel'

    def cancelled(self):
        return self.cancel_file.exists()

    def check(self):
        if self.cancelled():
            raise InterruptedError('用户已停止任务')

    def progress(self, value, text='', **extra):
        emit('progress', value=float(value), text=text, **extra)

    def execute(self):
        os.environ['YOLO_AUTOINSTALL'] = 'False'
        kind = self.task['kind']
        if kind == 'export' and self.task['format'] == 'onnx':
            os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
        return getattr(self, kind)()

    def prelabel(self):
        from ultralytics import YOLO
        model = YOLO(self.task['model'])
        labels = Labels(self.task['labels'])
        mapping = {int(k): int(v) for k, v in self.task['mapping'].items() if int(v) >= 0}
        paths = self.task['images']
        for i, p in enumerate(paths):
            self.check()
            result = model.predict(p, conf=self.task.get('conf', .5), iou=self.task.get('iou', .45),
                                   device=self.task.get('device', 'cpu'), verbose=False)[0]
            boxes = [] if self.task.get('replace') else labels.load(Path(p).stem)
            for coords, cls, conf in zip(result.boxes.xyxyn.cpu().tolist(), result.boxes.cls.cpu().tolist(), result.boxes.conf.cpu().tolist()):
                if int(cls) in mapping:
                    boxes.append(Box(mapping[int(cls)], *coords, 'AI', float(conf)))
            labels.save(Path(p).stem, boxes)
            self.progress((i+1)/len(paths), Path(p).name)
        return {'count': len(paths)}

    def model_info(self):
        from ultralytics import YOLO
        return {'names': YOLO(self.task['model']).names}

    def sam(self):
        from ultralytics import SAM
        from PIL import Image
        width, height = Image.open(self.task['image']).size
        kwargs = dict(device=self.task.get('device', 'cpu'), imgsz=self.task.get('imgsz', 1024), verbose=False)
        if 'point' in self.task:
            kwargs.update(points=[self.task['point']], labels=[1])
        else:
            kwargs['bboxes'] = [self.task['bbox']]
        # Prompts and stored labels use raw pixels. Passing a path lets some image
        # loaders apply EXIF rotation, so explicitly supply the unrotated BGR array.
        import numpy as np
        with Image.open(self.task['image']) as raw:
            pixels = np.asarray(raw.convert('RGB'))[:, :, ::-1].copy()
        result = SAM(self.task['model'])(pixels, **kwargs)[0]
        boxes = []
        if result.masks is not None:
            for m in result.masks.data.cpu().numpy()[:1]:
                box = mask_box(m, self.task['class_id'])
                if box:
                    boxes.append(asdict(box))
        return {'boxes': boxes, 'request': self.task['request'], 'image': self.task['image']}

    def train(self):
        from ultralytics import YOLO
        import shutil
        requested = dict(self.task['params'])
        resume = self.task.get('resume')
        if resume:
            # Ultralytics restores every argument from the checkpoint, so only the dataset may be
            # overridden here; anything else would silently continue against a different setup.
            model = YOLO(str(resume))
            params = dict(data=self.task['dataset'], resume=True)
        else:
            model = YOLO(self.task['model'])
            params = dict(requested)
            params.update(data=self.task['dataset'], project=str(self.run), name='train', exist_ok=False, plots=True)
        start = time.time()
        def epoch(trainer):
            metrics = {k: float(v) for k, v in trainer.metrics.items()}
            emit('epoch', epoch=trainer.epoch+1, metrics=metrics)
            self.progress((trainer.epoch+1)/trainer.epochs, f'第 {trainer.epoch+1}/{trainer.epochs} 轮')
            if self.cancelled():
                trainer.stop = True
        def batch(trainer):
            if self.cancelled():
                trainer.stop = True
        model.add_callback('on_fit_epoch_end', epoch)
        model.add_callback('on_train_batch_end', batch)
        model.train(**params)
        trainer = model.trainer
        best = Path(trainer.save_dir)/'weights'/'best.pt'
        project = Project(self.task['project'])
        copied = project.models/(self.run.name+'.pt')
        if best.exists():
            shutil.copy2(best, copied)
        metrics = {k: float(v) for k, v in trainer.metrics.items()}
        audit = dict(params) if not resume else dict(requested, resume=str(resume), data=params['data'])
        record = dict(schema_version=1, experiment_id=self.run.name, timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'),
                      params=audit, metrics=metrics, dataset=self.task['dataset'], dataset_version=self.task.get('dataset_version'),
                      output=str(trainer.save_dir), best=str(copied) if copied.exists() else None,
                      duration=time.time()-start, status='cancelled' if self.cancelled() else 'completed')
        with (project.models/'experiments.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str)+'\n')
        project.log(f'训练 {record["status"]} {self.run.name}')
        if self.cancelled():
            # 用户已停止：把“已停止”如实上抛，由监督层按 cancelled 收尾
            # （以前会走 result 事件，把停止伪装成“任务完成”）。
            raise InterruptedError('训练已停止，输出与实验记录已保留')
        return record

    def predict(self):
        from ultralytics import YOLO
        import cv2
        import numpy as np
        model = YOLO(self.task['model'])
        source = Path(self.task['source'])
        mode = self.task['mode']
        kwargs = dict(conf=self.task.get('conf', .25), iou=self.task.get('iou', .45),
                      device=self.task.get('device', 'cpu'), verbose=False)
        rows, errors = [], []
        labels = Labels(self.run/'labels')
        labels.set_classes([model.names[i] for i in range(len(model.names))])
        def process(image, name):
            self.check()
            result = model.predict(image, **kwargs)[0]
            boxes = []
            for coords, cls, score in zip(result.boxes.xyxyn.cpu().tolist(), result.boxes.cls.cpu().tolist(), result.boxes.conf.cpu().tolist()):
                box = Box(int(cls), *coords, 'AI', float(score))
                boxes.append(box)
                rows.append(dict(image=name, name=model.names[int(cls)], **asdict(box), latency_ms=sum(result.speed.values())))
            labels.save(Path(name).stem, boxes)
            return result.plot()
        if mode == 'video':
            cap = cv2.VideoCapture(str(source))
            if not cap.isOpened():
                raise ValueError('无法打开视频')
            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            w, h = int(cap.get(3)), int(cap.get(4))
            total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            output = self.run/(source.stem+'_result.mp4')
            writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
            if not writer.isOpened():
                cap.release()
                raise RuntimeError('无法创建 MP4 编码器')
            i = 0
            try:
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    writer.write(process(frame, f'frame_{i:08d}.jpg'))
                    i += 1
                    self.progress(i/total, f'帧 {i}', frame=i, total=total)
            finally:
                cap.release()
                writer.release()
            outputs = [str(output)]
        else:
            paths = [source] if mode == 'image' else sorted(p for p in source.rglob('*') if p.suffix.lower() in IMAGE_EXTENSIONS)
            outputs = []
            for i, p in enumerate(paths):
                self.check()
                try:
                    image = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if image is None:
                        raise ValueError('图片损坏')
                    name = f'{i:06d}_{p.stem}.jpg'
                    plotted = process(image, name)
                    out = self.run/name
                    cv2.imencode('.jpg', plotted)[1].tofile(out)
                    outputs.append(str(out))
                except InterruptedError:
                    raise
                except Exception as exc:
                    errors.append({'image': str(p), 'error': str(exc)})
                self.progress((i+1)/max(1, len(paths)), p.name)
        save_json(self.run/'detections.json', rows)
        if rows:
            with (self.run/'detections.csv').open('w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
        if not outputs:
            raise ValueError(f'无有效输入：{errors}')
        return {'outputs': outputs, 'detections': rows, 'errors': errors}

    def evaluate(self):
        from ultralytics import YOLO
        model = YOLO(self.task['model'])
        def batch(validator):
            self.check()
        model.add_callback('on_val_batch_end', batch)
        results = model.val(data=self.task['dataset'], split='test', conf=self.task.get('conf', .25),
                            iou=self.task.get('iou', .45), device=self.task.get('device', 'cpu'),
                            project=str(self.run), name='evaluation', plots=True, save_txt=True, save_conf=True)
        per_class = []
        for i, cls in enumerate(results.box.ap_class_index):
            p, r, m50, m = results.box.class_result(i)
            per_class.append(dict(class_id=int(cls), name=results.names[int(cls)], precision=float(p), recall=float(r), map50=float(m50), map=float(m)))
        return {'metrics': {k: float(v) for k, v in results.results_dict.items()}, 'per_class': per_class, 'output': str(results.save_dir)}

    def export(self):
        import importlib.util
        import shutil
        import tempfile
        from ultralytics import YOLO
        fmt = self.task['format']
        required = {'onnx': 'onnx', 'openvino': 'openvino', 'engine': 'tensorrt', 'torchscript': 'torch'}[fmt]
        if importlib.util.find_spec(required) is None:
            raise RuntimeError(f'缺少 {required}，请运行 scripts/install.ps1 -Exports')
        params = dict(self.task.get('params', {}))
        if params.get('quantize') == 8 and not params.get('data'):
            raise ValueError('INT8 导出必须指定项目校准数据集')
        # Ultralytics writes beside its input model: isolate that side effect per task.
        src = Path(self.task['model'])
        if fmt == 'onnx':
            params.update(device='cpu')
        elif fmt == 'engine':
            params.setdefault('device', 0)
            if params.get('quantize',32)==32:
                os.environ['NVIDIA_TF32_OVERRIDE']='0'
        with tempfile.TemporaryDirectory(prefix='yts_export_') as temporary:
            target = Path(temporary)/'model.pt'
            shutil.copy2(src, target)
            result = Path(YOLO(str(target)).export(format=fmt, **params))
            destination = self.run/result.name
            if result.is_dir():
                shutil.copytree(result,destination)
            else:
                shutil.copy2(result,destination)
        return {'output': str(destination), 'format': fmt}

    def extract(self):
        from .video_sampling import extract
        return extract(self)

    def segment_dataset(self):
        from .segmentation import export_segmentation
        return export_segmentation(Project(self.task['project']), self.task.get('split_components', False),
                                   self.task.get('fill_holes', False), self.check)

    def import_video(self):
        from .review import import_video
        return import_video(Project(self.task['project']), self.task['source_run'], self.check, self.progress)

    def inspect_images(self):
        from PIL import Image
        project = Project(self.task['project'])
        bad = []
        paths = project.image_paths()
        for i, p in enumerate(paths):
            self.check()
            try:
                with Image.open(p) as im:
                    im.load()
                    if min(im.size) < self.task.get('min_size', 0):
                        bad.append({'path': str(p), 'reason': f'尺寸 {im.size}'})
            except Exception as exc:
                bad.append({'path': str(p), 'reason': str(exc)})
            self.progress((i+1)/max(1, len(paths)), p.name)
        return {'bad': bad}

    def dataset(self):
        from .dataset import DatasetStore
        store = DatasetStore(Project(self.task['project']))
        version = store.create(tuple(self.task.get('ratios', [.7,.2,.1])), self.task.get('seed', 42), self.task.get('incremental', False))
        return {'version': version, 'dataset': str(store.yaml_path(version))}

    def dataset_merge(self):
        """Integrate several dataset sources into a fresh version (see studio/merge.py)."""
        from .dataset import DatasetStore
        from .merge import merge
        store = DatasetStore(Project(self.task['project']))
        keys = ('sources', 'ratios', 'seed', 'resolutions', 'accept_new_classes',
                'dedup', 'keep_segment', 'blacklist')
        # 黑名单（路径或 SHA256）原样传递，由 merge._normalize_spec 统一解析。
        spec = {key: self.task[key] for key in keys if key in self.task}
        return merge(store, spec, progress=self.progress, check=self.check)

    def gate(self):
        """Run the release gate script against a frozen golden set inside this worker."""
        import importlib.util
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'check_release_gate.py'
        module = importlib.util.module_from_spec(importlib.util.spec_from_file_location('check_release_gate', script))
        module.__loader__.exec_module(module)
        path = lambda key: Path(self.task[key]) if self.task.get(key) else None
        stage = [0]
        def log(text):
            stage[0] += 1
            self.progress(min(.98, stage[0]/40), str(text))
            self.check()
        return module.run_gate(project=Path(self.task['project']), model=path('model'), golden=path('golden'),
                               baseline=path('baseline'), quantized=path('quantized'),
                               dataset_version=self.task.get('dataset_version'),
                               map50_min=float(self.task.get('map50_min', .5)),
                               ap50_drop_max=float(self.task.get('ap50_drop_max', .03)),
                               quant_drop_max=float(self.task.get('quant_drop_max', .02)),
                               strict_labels=bool(self.task.get('strict_labels', False)),
                               report_dir=Path(self.task['project'])/'Model',
                               log=log, check=self.check)


    def tracking(self):
        from .tracking import run_tracking
        return run_tracking(self)


def main(task_path):
    global EVENT_PATH
    task = read_json(task_path)
    worker = Worker(task)
    EVENT_PATH = worker.run/'events.jsonl'
    EVENT_PATH.write_text('', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = (worker.run/'process.log').open('a', encoding='utf-8', buffering=1)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = worker.execute()
        save_json(worker.run/'result.json', result)
        emit('result', result=result)
    except InterruptedError as exc:
        emit('cancelled', message=str(exc))
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit('error', message=str(exc), traceback=traceback.format_exc())
        return 1
    return 0


if __name__ == '__main__':
    # Tracking imports studio.worker.emit; share this module's event sink when
    # launched with -m, rather than importing a second unconfigured instance.
    sys.modules['studio.worker'] = sys.modules[__name__]
    raise SystemExit(main(sys.argv[1]))
