"""One cached SAM model/image, owned by the bridge GPU scheduler."""
from dataclasses import asdict
import math


class InteractiveSam:
    def __init__(self):
        self.predictor = None
        self.model_key = self.image_key = None

    def close(self):
        self.predictor = None
        self.model_key = self.image_key = None
        import gc
        gc.collect()
        import sys
        if 'torch' in sys.modules:
            sys.modules['torch'].cuda.empty_cache()

    def segment(self, path, options):
        import cv2
        import numpy as np
        from PIL import Image
        from ultralytics import SAM
        from .domain import mask_box
        key = (options['model'], options.get('device', 'cpu'), int(options.get('imgsz', 1024)))
        if key != self.model_key:
            self.close()
            model = SAM(key[0])
            self.predictor = model.task_map['segment']['predictor'](overrides=dict(model=key[0], device=key[1],
                imgsz=key[2], task='segment', mode='predict', verbose=False, save=False))
            self.predictor.setup_model(model=model.model, verbose=False)
            self.model_key = key
        image_key = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        if self.image_key != image_key:
            with Image.open(path) as raw:
                self.pixels = np.asarray(raw.convert('RGB'))[:, :, ::-1].copy()
            self.predictor.reset_image()
            self.predictor.set_image(self.pixels)
            self.image_key = image_key
        points = options.get('points', [])
        labels = options.get('labels', [])
        bbox = options.get('bbox')
        if len(points) != len(labels) or any(v not in (0, 1) for v in labels):
            raise ValueError('SAM 提示点与标签不匹配')
        if not bbox and not any(labels):
            raise ValueError('请先添加一个正点或框选目标')
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points):
            raise ValueError('SAM 提示坐标无效')
        prompts = dict(points=[points] if points else None, labels=[labels] if labels else None,
                       bboxes=[bbox] if bbox else None)
        self.predictor.set_prompts(prompts)
        result = self.predictor(source=self.pixels)[0]
        if result.masks is None or len(result.masks.data) == 0:
            raise ValueError('本次提示没有有效轮廓，保留最近结果')
        h, w = self.pixels.shape[:2]
        mask = cv2.resize(result.masks.data[0].cpu().numpy().astype('uint8'), (w, h), interpolation=cv2.INTER_NEAREST)
        roi = options.get('roi')
        if roi:
            a,b,c,d = roi
            if not (0 <= a < c <= w and 0 <= b < d <= h):
                raise ValueError('ROI 必须位于原图范围内')
            yy,xx = np.ogrid[:h,:w]
            mask *= ((xx >= a)&(xx <= c)&(yy >= b)&(yy <= d))
        box = mask_box(mask, options['class_id'], float(options.get('epsilon', 1)))
        if box is None or not box.polygons:
            raise ValueError('ROI 内没有有效轮廓，保留最近结果')
        box.object_id = options['object_id']
        box.roi = [v/s for v,s in zip(roi, (w,h,w,h))] if roi else None
        return dict(box=asdict(box), request=options['request'])
