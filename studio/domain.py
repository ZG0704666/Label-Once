from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}


def natural_key(value):
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r'(\d+)', str(value))]


def atomic_write(path: Path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_json(path, value):
    atomic_write(Path(path), json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def unique_id():
    return datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]


@dataclass
class Box:
    cls: int
    x1: float
    y1: float
    x2: float
    y2: float
    origin: str = '人工'
    score: float | None = None
    polygons: list | None = None
    object_id: str | None = None
    target_id: int = -1
    roi: list | None = None
    raw_polygons: list | None = None
    holes: list | None = None

    def clipped(self):
        a, b = sorted((max(0., min(1., self.x1)), max(0., min(1., self.x2))))
        c, d = sorted((max(0., min(1., self.y1)), max(0., min(1., self.y2))))
        return Box(self.cls, a, c, b, d, self.origin, self.score, self.polygons,
                   self.object_id, self.target_id, self.roi, self.raw_polygons, self.holes)


class Labels:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    @property
    def classes(self):
        p = self.folder / 'classes.txt'
        return p.read_text(encoding='utf-8-sig').splitlines() if p.exists() else []

    def set_classes(self, names):
        if any(not n.strip() for n in names) or len(set(names)) != len(names):
            raise ValueError('类别名称不能为空或重复')
        atomic_write(self.folder / 'classes.txt', '\n'.join(names) + ('\n' if names else ''))

    def load(self, stem):
        from .annotations import AnnotationStore
        store = AnnotationStore(self)
        doc = store.read(stem)
        if doc is not None:
            return store.boxes(doc)
        p = self.folder / (stem + '.txt')
        if not p.exists():
            return []
        marks = self.folder / (stem + '.mark')
        origins = marks.read_text(encoding='utf-8-sig').splitlines() if marks.exists() else []
        result = []
        for i, line in enumerate(p.read_text(encoding='utf-8-sig').splitlines()):
            if not line.strip():
                continue
            values = line.split('#')[0].split()
            if len(values) != 5:
                raise ValueError(f'{p.name}:{i + 1} 不是 YOLO 矩形标签')
            cls, cx, cy, w, h = map(float, values)
            import math
            if not all(math.isfinite(v) for v in (cls, cx, cy, w, h)) or cls < 0 or cls != int(cls) or w <= 0 or h <= 0:
                raise ValueError(f'{p.name}:{i + 1} 标签数值无效')
            origin = origins[i] if i < len(origins) else ('AI' if '#AI' in line else '人工')
            stable_id = uuid.uuid5(uuid.NAMESPACE_URL, str(p.resolve()) + ':' + str(i)).hex
            result.append(Box(int(cls), cx-w/2, cy-h/2, cx+w/2, cy+h/2, origin, object_id=stable_id).clipped())
        outline = read_json(self.folder/(stem+'.segments.json'), {})
        if outline.get('label_sha256') == digest(p):
            for box, polygons in zip(result, outline.get('polygons', [])):
                box.polygons = polygons
        return result

    def save(self, stem, boxes, expected_revision=None):
        from .annotations import AnnotationStore
        clean = [b.clipped() for b in boxes]
        clean = [b for b in clean if b.x2 > b.x1 and b.y2 > b.y1]
        return AnnotationStore(self).save(stem, clean, expected_revision)

    def reorder(self, names, old_to_new):
        staged = {}
        for p in self.folder.glob('*.txt'):
            if p.name == 'classes.txt':
                continue
            boxes = self.load(p.stem)
            from dataclasses import replace
            staged[p.stem] = [replace(b, cls=old_to_new[b.cls]) for b in boxes if b.cls in old_to_new]
        # Complete validation before changing any labels; preserve a recoverable copy.
        backup = self.folder.parent / ('labels_backup_' + unique_id())
        shutil.copytree(self.folder, backup)
        for stem, boxes in staged.items():
            self.save(stem, boxes)
        self.set_classes(names)
        return backup


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.images = self.root / 'Main'
        self.labels = Labels(self.root / 'Main_labels')
        self.models = self.root / 'Model'
        self.config = self.root / 'Config'
        self.runs = self.root / 'runs'
        for p in (self.images, self.models, self.config, self.runs):
            p.mkdir(parents=True, exist_ok=True)

    def image_paths(self):
        return sorted((p for p in self.images.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS), key=natural_key)

    def assert_unique_stems(self):
        stems = [p.stem.casefold() for p in self.image_paths()]
        if len(stems) != len(set(stems)):
            raise ValueError('同名不同扩展名图片会共用标签，请先消除重名')

    def log(self, text):
        p = self.root / 'activity.log'
        with p.open('a', encoding='utf-8') as f:
            f.write(f'{datetime.now().isoformat(timespec="seconds")} {text}\n')

    def stats(self):
        paths = self.image_paths()
        counts = {n: 0 for n in self.labels.classes}
        annotated = empty = invalid = 0
        for p in paths:
            try:
                boxes = self.labels.load(p.stem)
                annotated += bool(boxes)
                empty += not boxes and (self.labels.folder / (p.stem+'.txt')).exists()
                for b in boxes:
                    name = self.labels.classes[b.cls] if b.cls < len(self.labels.classes) else f'class_{b.cls}'
                    counts[name] = counts.get(name, 0) + 1
            except ValueError:
                invalid += 1
        return dict(total=len(paths), annotated=annotated, empty=empty, invalid=invalid, pending=len(paths)-annotated-empty, classes=counts)

    def new_run(self, kind):
        path = self.runs / (kind + '_' + unique_id())
        path.mkdir(parents=True)
        return path

    def import_images(self, paths):
        self.assert_unique_stems()
        existing = {p.stem.casefold() for p in self.image_paths()}
        added = []
        for source in map(Path, paths):
            if source.suffix.lower() not in IMAGE_EXTENSIONS or source.stem.casefold() in existing:
                continue
            shutil.copy2(source, self.images / source.name)
            existing.add(source.stem.casefold())
            added.append(source.name)
        self.log(f'导入 {len(added)} 张图片')
        return added

    def rename_preview(self, prefix, start=1):
        if not prefix or re.search(r'[<>:"/\\|?*]', prefix):
            raise ValueError('文件名前缀无效')
        return [(p, self.images / f'{prefix}{i:06d}{p.suffix.lower()}') for i, p in enumerate(self.image_paths(), start)]

    def batch_rename(self, prefix, start=1):
        self.assert_unique_stems()
        preview = self.rename_preview(prefix, start)
        moves = []
        for old, new in preview:
            moves.append((old, new))
            for ext in ('.txt', '.mark', '.segments.json', '.annotation.json', '.sync.json'):
                src = self.labels.folder / (old.stem+ext)
                if src.exists():
                    moves.append((src, self.labels.folder / (new.stem+ext)))
        sources = {a for a, _ in moves}
        if any(b.exists() and b not in sources for _, b in moves):
            raise ValueError('目标名称已存在，未重命名')
        staged = []
        try:
            for a, b in moves:
                tmp = a.with_name('.rename_' + uuid.uuid4().hex)
                a.rename(tmp)
                staged.append((a, tmp, b))
            for a, tmp, b in staged:
                tmp.rename(b)
        except Exception:
            # Move completed destinations back through their staging names before rollback.
            for a, tmp, b in staged:
                if not tmp.exists() and b.exists():
                    b.rename(tmp)
            for a, tmp, b in staged:
                if tmp.exists():
                    tmp.rename(a)
            raise
        from .review import ReviewStore
        ReviewStore(self).rename({a.name:b.name for a,b in preview})
        self.log(f'成对重命名 {len(preview)} 张图片')

    def trash_image(self, image):
        image = Path(image).resolve()
        if image.parent != self.images:
            raise ValueError('只能移除当前项目图片')
        dest = self.root / '.trash' / unique_id()
        dest.mkdir(parents=True)
        for p in [image, self.labels.folder/(image.stem+'.txt'), self.labels.folder/(image.stem+'.mark'), self.labels.folder/(image.stem+'.segments.json'), self.labels.folder/(image.stem+'.annotation.json'), self.labels.folder/(image.stem+'.sync.json')]:
            if p.exists():
                shutil.move(str(p), dest / p.name)
        return dest


def mask_box(mask, cls=0, epsilon=1.):
    import numpy as np
    import cv2
    from .contour_simplification import simplify_ring
    y, x = np.where(np.asarray(mask) > 0)
    if not len(x):
        return None
    h, w = mask.shape[-2:]
    contours, hierarchy = cv2.findContours((np.asarray(mask)>0).astype('uint8'), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    polygons, raw, holes = [], [], []
    for i, contour in enumerate(contours):
        if len(contour)<3:
            continue
        original = [[float(px/w),float(py/h)] for px,py in contour.reshape(-1,2)]
        simplified = [[float(px/w),float(py/h)] for px,py in simplify_ring(contour.reshape(-1,2), epsilon)]
        if len(simplified)<3:
            simplified=original
        if hierarchy[0][i][3] >= 0:
            holes.append(original)
        else:
            raw.append(original)
            polygons.append(simplified)
    # An exterior reduction must not cut through an unchanged hole.
    if holes:
        for i,ring in enumerate(polygons):
            poly=np.asarray(ring,dtype=np.float32)
            original=np.asarray(raw[i],dtype=np.float32)
            for hole in holes:
                if cv2.pointPolygonTest(original,tuple(hole[0]),False)>=0 and any(cv2.pointPolygonTest(poly,tuple(point),False)<=0 for point in hole):
                    polygons[i]=raw[i]
                    break
    return Box(cls, float(x.min()/w), float(y.min()/h), float((x.max()+1)/w), float((y.max()+1)/h),
               'AI', polygons=polygons, raw_polygons=raw, holes=holes or None)
