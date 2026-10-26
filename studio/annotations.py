"""Versioned pixel geometry with atomic canonical commit and repairable projections."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import uuid

from .domain import atomic_write, read_json, save_json


class AnnotationConflict(ValueError):
    pass


def fingerprint(labels, stem):
    h = hashlib.sha256()
    for ext in ('.txt', '.mark', '.segments.json', '.annotation.json'):
        path = labels.folder / (stem + ext)
        h.update(ext.encode())
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()


class AnnotationStore:
    def __init__(self, labels):
        self.labels = labels

    def path(self, stem):
        return self.labels.folder / (stem + '.annotation.json')

    def size(self, stem):
        from PIL import Image
        folder = self.labels.folder.parent / self.labels.folder.name.removesuffix('_labels')
        for image in folder.glob(stem + '.*'):
            try:
                with Image.open(image) as im:
                    return im.size
            except (OSError, ValueError):
                continue
        return (1, 1)

    def project(self, stem, doc, retire=True):
        # The journal remains until ALL compatibility files are durably replaced.
        for ext, text in doc['projections'].items():
            atomic_write(self.labels.folder / (stem + ext), text)
        journal = self.labels.folder / (stem + '.sync.json')
        if retire:
            journal.unlink(missing_ok=True)
        else:
            save_json(journal, dict(revision=doc['revision'], repaired=True))

    def read(self, stem):
        doc = read_json(self.path(stem))
        if doc is None:
            return None
        if doc.get('schema') != 2:
            raise ValueError('不支持的标注文档版本')
        journal = self.labels.folder / (stem + '.sync.json')
        if journal.exists():
            pending = read_json(journal)
            if pending['revision'] == doc['revision']:
                if not pending.get('repaired'):
                    self.project(stem, doc, retire=False)
            else:
                # Canonical replacement failed; projections still belong to the old commit.
                journal.unlink()
        for ext, text in doc['projections'].items():
            path = self.labels.folder / (stem + ext)
            if not path.exists() or path.read_text(encoding='utf-8-sig') != text:
                raise AnnotationConflict(f'{stem}{ext} 已被外部修改，请保留编辑并解决标签冲突')
        return doc

    def boxes(self, doc):
        from .domain import Box
        w, h = doc['size']
        result = []
        for obj in doc['objects']:
            data = dict(obj)
            data.pop('geometry_revision', None)
            for key, scale in (('x1', w), ('x2', w), ('y1', h), ('y2', h)):
                data[key] /= scale
            for key in ('polygons', 'raw_polygons', 'holes'):
                if data.get(key):
                    data[key] = [[[x/w, y/h] for x, y in ring] for ring in data[key]]
            if data.get('roi'):
                data['roi'] = [v/s for v, s in zip(data['roi'], (w, h, w, h))]
            result.append(Box(**data))
        return result

    def save(self, stem, boxes, expected_revision=None):
        journal = read_json(self.labels.folder / (stem + '.sync.json'), {})
        old = self.read(stem)
        revision = old['revision'] if old else 0
        if expected_revision is not None and expected_revision != revision:
            # A projection failure can commit the canonical revision without acknowledging
            # it to the caller. Only that journal permits retrying the interrupted write.
            if journal.get('revision') != revision or expected_revision != revision - 1:
                raise AnnotationConflict('标注版本已变化，请重新打开或解决冲突；未覆盖已有数据')
        w, h = self.size(stem)
        objects = []
        old_objects = {o['object_id']: o for o in old['objects']} if old else {}
        for box in boxes:
            box.object_id = box.object_id or uuid.uuid4().hex
            obj = asdict(box)
            obj['object_id'] = box.object_id
            for key, scale in (('x1', w), ('x2', w), ('y1', h), ('y2', h)):
                obj[key] *= scale
            for key in ('polygons', 'raw_polygons', 'holes'):
                if obj.get(key):
                    obj[key] = [[[x*w, y*h] for x, y in ring] for ring in obj[key]]
            if obj.get('roi'):
                obj['roi'] = [v*s for v, s in zip(obj['roi'], (w, h, w, h))]
                a, b, c, d = obj['roi']
                if any(not (a-1e-7 <= x <= c+1e-7 and b-1e-7 <= y <= d+1e-7)
                       for ring in obj.get('polygons') or [] for x, y in ring):
                    raise ValueError('轮廓超出当前对象 ROI，请修正后保存')
            previous = old_objects.get(obj['object_id'], {})
            same = {k:v for k,v in previous.items() if k != 'geometry_revision'} == obj
            obj['geometry_revision'] = previous['geometry_revision'] if same else revision + 1
            objects.append(obj)
        if old and objects == old['objects']:
            (self.labels.folder / (stem + '.sync.json')).unlink(missing_ok=True)
            return old
        lines = [f'{b.cls} {(b.x1+b.x2)/2:.12f} {(b.y1+b.y2)/2:.12f} {b.x2-b.x1:.12f} {b.y2-b.y1:.12f}' for b in boxes]
        txt = '\n'.join(lines) + ('\n' if lines else '')
        sidecar = dict(schema=2, label_sha256=hashlib.sha256(txt.encode()).hexdigest(), polygons=[b.polygons for b in boxes])
        projections = {'.txt': txt, '.mark': '\n'.join(b.origin for b in boxes) + ('\n' if boxes else ''),
                       '.segments.json': json.dumps(sidecar, ensure_ascii=False, indent=2, allow_nan=False)}
        doc = dict(schema=2, image_id=old['image_id'] if old else uuid.uuid4().hex, size=[w, h],
                   revision=revision+1, objects=objects, projections=projections)
        save_json(self.labels.folder / (stem + '.sync.json'), dict(revision=revision+1))
        save_json(self.path(stem), doc)
        self.project(stem, doc)
        return doc
