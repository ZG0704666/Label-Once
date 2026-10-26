"""Explicitly reviewed YOLO segmentation exports, separate from detection versions."""
import math
import random
import shutil
from pathlib import Path

import yaml
from .dataset import sample_group
from .domain import atomic_write, save_json, unique_id, digest
from .review import ReviewStore
from .annotations import fingerprint


def export_segmentation(project, split_components=False, fill_holes=False, check=lambda: None):
    review = ReviewStore(project)
    ledger = review.records()
    samples, issues = [], []
    for image in project.image_paths():
        check()
        if review.status(image.name, ledger) != 'confirmed':
            continue
        boxes = project.labels.load(image.stem)
        lines = []
        for b in boxes:
            reason = None
            if not b.polygons:
                reason = '只有检测框，缺少真实轮廓'
            elif b.holes and not fill_holes:
                reason = '含孔洞，需要明确选择填孔'
            elif len(b.polygons) > 1 and not split_components:
                reason = '多连通区域，需要明确选择拆分实例'
            elif b.cls < 0 or b.cls >= len(project.labels.classes):
                reason = '类别无效'
            else:
                for ring in b.polygons:
                    if len(ring) < 3 or any(len(p) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in p) for p in ring):
                        reason = '轮廓顶点无效'
                        break
                    area = abs(sum(a[0]*c[1]-c[0]*a[1] for a,c in zip(ring, ring[1:]+ring[:1])))
                    if area <= 1e-15:
                        reason = '轮廓面积为零'
                        break
                    if b.roi and any(not (b.roi[0]-1e-10 <= x <= b.roi[2]+1e-10 and b.roi[1]-1e-10 <= y <= b.roi[3]+1e-10) for x,y in ring):
                        reason = '轮廓超出 ROI'
                        break
                    lines.append(str(b.cls)+' '+' '.join(f'{v:.12f}' for xy in ring for v in xy))
            if reason:
                issues.append(dict(name=image.name, object_id=b.object_id, reason=reason))
        samples.append((image, lines))
    if issues:
        return dict(exported=False, issues=issues)
    if not samples:
        raise ValueError('没有已复核图片；空图片也需要明确确认无目标')
    version = unique_id()
    root = project.root / 'segmentation_dataset' / 'versions'
    root.mkdir(parents=True, exist_ok=True)
    folder, staging = root/version, root/('.'+version)
    # 分组打散：同视频/同导入批次的帧是近邻重复，必须整组落在同一 split，
    # 否则验证集会泄漏进训练（与 dataset._plan_splits 的组保证一致）。
    groups = {}
    for image, lines in samples:
        groups.setdefault(sample_group(image.name, ledger), []).append((image, lines))
    keys = list(groups)
    random.Random(42).shuffle(keys)
    validation = max(1, round(len(samples)*.2)) if len(samples) > 1 else 0
    val_keys, train_keys, filled = [], [], 0
    for key in keys:
        if filled < validation:
            val_keys.append(key); filled += len(groups[key])
        else:
            train_keys.append(key)
    if not train_keys and len(keys) > 1 and val_keys:
        moved = max(val_keys, key=lambda g: len(groups[g]))
        val_keys.remove(moved); train_keys.append(moved)
    order, split_of = [], {}
    for key in val_keys:
        for image, lines in groups[key]:
            order.append((image, lines)); split_of[image.name] = 'val'
    for key in train_keys:
        for image, lines in groups[key]:
            order.append((image, lines)); split_of[image.name] = 'train'
    has_val = bool(val_keys)
    records = []
    try:
        for split in ('train', 'val'):
            (staging/'images'/split).mkdir(parents=True)
            (staging/'labels'/split).mkdir(parents=True)
        for index, (image, lines) in enumerate(order):
            check()
            split = split_of[image.name]
            shutil.copy2(image, staging/'images'/split/image.name)
            atomic_write(staging/'labels'/split/(image.stem+'.txt'), '\n'.join(lines)+ ('\n' if lines else ''))
            records.append(dict(name=image.name, split=split, image_sha256=digest(image),
                                geometry_sha256=fingerprint(project.labels, image.stem), instances=len(lines)))
        names = project.labels.classes
        atomic_write(staging/'classes.txt', '\n'.join(names)+'\n')
        config = dict(path=str(folder), train='images/train', val='images/val' if has_val else 'images/train', names=dict(enumerate(names)))
        atomic_write(staging/'dataset.yaml', yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
        save_json(staging/'dataset_manifest.json', dict(schema=1, task='segment', version=version, images=records,
                  split_components=split_components, fill_holes=fill_holes, names=names))
        staging.rename(folder)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return dict(exported=True, folder=str(folder), count=len(records), issues=[])
