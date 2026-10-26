"""Project review ledger and lossless, repeatable video result import."""
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import hashlib
import re
import shutil

from .domain import Labels, digest, read_json, save_json
from .annotations import fingerprint

REVIEW_SCHEMA = 2
WRITE_INTERVAL = 25


class ReviewStore:
    def __init__(self, project):
        self.project = project
        self.path = project.config / 'review.json'

    def records(self):
        return read_json(self.path, {'schema': REVIEW_SCHEMA, 'images': {}})['images']

    def write(self, records):
        save_json(self.path, {'schema': REVIEW_SCHEMA, 'images': records})

    def status(self, name, records=None):
        entry = (self.records() if records is None else records).get(name)
        if entry is None:
            return 'legacy'
        if entry.get('status') == 'rejected':
            return 'rejected'
        label = self.project.labels.folder / (Path(name).stem + '.txt')
        image = self.project.images / name
        if (entry.get('status') == 'confirmed' and label.is_file() and image.is_file()
                and entry.get('label_sha256') == digest(label)
                and entry.get('image_sha256') == digest(image)
                and entry.get('geometry_sha256', fingerprint(self.project.labels, Path(name).stem)) == fingerprint(self.project.labels, Path(name).stem)):
            return 'confirmed'
        return 'pending'

    def confirm(self, names):
        records = self.records()
        # Validate the whole selection before marking any sample as accepted.
        for name in names:
            from PIL import Image
            with Image.open(self.project.images/name) as image:image.verify()
            path = self.project.labels.folder / (Path(name).stem + '.txt')
            if not path.is_file():
                raise ValueError(f'{name} 缺少标签，请先标注或明确保存空标注')
            boxes = self.project.labels.load(Path(name).stem)
            if any(b.cls >= len(self.project.labels.classes) for b in boxes):
                raise ValueError(f'{name} 包含未知类别')
            records.setdefault(name, {}).update(status='confirmed', label_sha256=digest(path),
                                                image_sha256=digest(self.project.images/name),
                                                geometry_sha256=fingerprint(self.project.labels, Path(name).stem),
                                                reviewer='local', reviewed_at=datetime.now().isoformat(timespec='seconds'),
                                                reject_reason=None)
        self.write(records)

    def reject(self, names, reason=''):
        records = self.records()
        for name in names:
            image = self.project.images/name
            if not image.is_file():
                raise ValueError(f'{name} 不存在')
            label = self.project.labels.folder / (Path(name).stem + '.txt')
            records.setdefault(name, {}).update(status='rejected',
                                                label_sha256=digest(label) if label.is_file() else None,
                                                image_sha256=digest(image),
                                                geometry_sha256=fingerprint(self.project.labels, Path(name).stem),
                                                reject_reason=reason or '需重新标注', reviewer='local',
                                                reviewed_at=datetime.now().isoformat(timespec='seconds'))
        self.write(records)

    def rename(self, mapping):
        records = self.records()
        self.write({mapping.get(name, name): entry for name, entry in records.items()})


def import_video(project, run, check=lambda: None, progress=lambda *args, **extra: None):
    """Import a run, matching classes by name, never overwriting reviewed work."""
    from PIL import Image
    run = Path(run).resolve()
    task = read_json(run/'task.json', {})
    if task.get('kind') not in ('tracking', 'extract'):
        raise ValueError('请选择视频追踪或抽帧任务目录')
    manual = task['kind'] == 'extract'
    folder = run/'video_images'
    if not folder.is_dir():
        raise ValueError('任务没有已导出的图片')
    labels_folder = run/'video_images_labels'
    if not manual and not (labels_folder/'classes.txt').is_file():
        raise ValueError('缺少 video_images_labels/classes.txt')
    labels = Labels(labels_folder)
    classes = list(project.labels.classes)
    source_classes = labels.classes
    entries = []
    manifest = read_json(run/'frame_manifest.json', {})
    if manual and manifest.get('schema', 0) >= 2 and manifest.get('state') != 'complete':
        raise ValueError('抽帧清单尚未完整提交，不能导入取消或失败的输出')
    registered = {Path(o['image']).name for o in manifest.get('outputs', [])}
    metadata = {Path(o['image']).name: o for o in manifest.get('outputs', [])}
    for image in sorted(folder.glob('*.jpg')):
        check()
        if (not manual or manifest) and image.name not in registered:
            raise ValueError(f'{image.name} 不在导出记录中，拒绝导入未完成的帧')
        with Image.open(image) as im:
            im.verify()
        if not manual and not (labels_folder/(image.stem+'.txt')).is_file():
            raise ValueError(f'{image.name} 缺少同名 TXT 标签')
        boxes = [] if manual else labels.load(image.stem)
        if any(b.cls >= len(source_classes) for b in boxes):
            raise ValueError(f'{image.name} 包含未知类别')
        for b in boxes:
            if source_classes[b.cls] not in classes:
                classes.append(source_classes[b.cls])
        entries.append((image, [replace(b, cls=classes.index(source_classes[b.cls])) for b in boxes]))
    if not entries:
        raise ValueError('没有可导入的已输出帧')
    ledger = ReviewStore(project)
    records = ledger.records()
    token = hashlib.sha256(str(run).casefold().encode()).hexdigest()[:12]
    batch = f'video_{token}'
    imported = []
    project.labels.set_classes(classes)
    plan = []
    for image, boxes in entries:
        source = str(image)
        existing = next((name for name, e in records.items() if e.get('source') == source and e.get('batch') == batch), None)
        if existing and records[existing].get('import_complete'):
            if not (project.images/existing).is_file() or not (project.labels.folder/(Path(existing).stem+'.txt')).is_file():
                raise ValueError(f'已导入样本 {existing} 缺失图片或标签，请检查项目；不会覆盖人工修改')
            imported.append(existing)
            continue
        name = existing or f'{batch}_{image.name}'
        destination = project.images/name
        if not existing and (destination.exists() or (project.labels.folder/(Path(name).stem+'.txt')).exists()):
            raise ValueError(f'目标文件冲突：{name}，未覆盖')
        frame = re.search(r'_f(\d+)_', image.stem)
        records[name] = dict(batch=batch, source=source, run=str(run), frame=int(frame[1]) if frame else len(plan),
                             status='pending', import_complete=False)
        plan.append((image, boxes, name))
    # Register every planned frame first, then flush completion marks in batches;
    # a crash between writes is still resumable through 'import_complete'.
    if plan:
        ledger.write(records)
    for i, (image, boxes, name) in enumerate(plan):
        check()
        destination = project.images/name
        staging = destination.with_suffix('.importing')
        shutil.copy2(image, staging)
        staging.replace(destination)
        project.labels.save(Path(name).stem, boxes)
        records[name].update(import_complete=True, video=manifest.get('video'), video_sha256=manifest.get('video_sha256'),
                             sample_id=metadata.get(image.name, {}).get('sample_id'), timestamp=metadata.get(image.name, {}).get('timestamp'))
        if (i+1) % WRITE_INTERVAL == 0 or i+1 == len(plan):
            ledger.write(records)
        imported.append(name)
        progress((i+1)/len(entries), f'导入 {i+1}/{len(entries)}', frame=i+1, total=len(entries))
    project.log(f'视频结果导入 {batch}：{len(imported)} 张，待复审')
    return dict(batch=batch, names=imported, count=len(imported))
