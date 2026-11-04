"""Map continuous tracking to existing sampled images, guarding human geometry."""
from dataclasses import replace
from pathlib import Path
from .domain import Project, read_json, save_json
from .annotations import fingerprint
from .review import ReviewStore


class SampleBackfill:
    def __init__(self, task, run):
        self.project = Project(task['project'])
        self.run = run
        records = ReviewStore(self.project).records()
        self.samples = {entry['frame']: name for name,entry in records.items()
                        if entry.get('run') == task.get('sample_run') and entry.get('import_complete')}
        self.expected = read_json(run/'backfill_versions.json', dict(task.get('sample_versions', {})))

    def update(self, frame, boxes, manual=False):
        if frame not in self.samples:
            return False
        name = self.samples[frame]
        stem = Path(name).stem
        labels = self.project.labels
        current_hash = fingerprint(labels, stem)
        reviewed = ReviewStore(self.project).status(name) == 'confirmed'
        existing = labels.load(stem)
        # Only candidate outputs from THIS task can be replaced after the first fill.
        protected = reviewed or self.expected.get(name) != current_hash or (not manual and any(b.origin != 'AI' for b in existing))
        if protected:
            from dataclasses import asdict
            path = self.run/'backfill_conflicts.json'
            conflicts = read_json(path, {})
            conflicts[name] = dict(frame=frame, reason='人工修改、已复核或版本冲突', boxes=[asdict(b) for b in boxes])
            save_json(path, conflicts)
            return False
        import uuid
        sample_id = ReviewStore(self.project).records()[name].get('sample_id', name)
        boxes = [replace(b, object_id=uuid.uuid5(uuid.NAMESPACE_URL, f'{sample_id}:target:{b.target_id}').hex) for b in boxes]
        labels.save(stem, boxes)
        self.expected[name] = fingerprint(labels, stem)
        save_json(self.run/'backfill_versions.json', self.expected)
        return True

    def human_keyframes(self, targets, start):
        """Associate human masks only through IDs or unique class instances.

        软失败：无法安全关联的目标不抛异常，而是记录原因并跳过——跟踪继续，
        由失败分级在真正出问题时把现场交给用户。strict_keyframes 的调用方
        在 run_tracking 中根据返回的 skipped 再决定是否中止。
        """
        frames = {}
        skipped = {}
        for frame, name in sorted(self.samples.items()):
            if frame <= start: continue
            human = [b for b in self.project.labels.load(Path(name).stem) if b.origin != 'AI' and b.polygons]
            mapped = {}
            reasons = []
            for box in human:
                candidates = [i for i,t in targets.items() if t['cls'] == box.cls]
                if box.target_id in candidates: target_id = box.target_id
                elif len(candidates)==1 and sum(b.cls==box.cls for b in human)==1: target_id = candidates[0]
                elif not candidates:
                    reasons.append(f'目标 {box.cls} 在跟踪会话中不存在对应 ID')
                    continue
                else:
                    reasons.append(f'目标 {box.cls} 有多个同类别候选，无法安全关联')
                    continue
                if target_id in mapped:
                    reasons.append(f'目标 {box.cls} 的 ID {target_id} 重复映射，忽略后到者')
                    continue
                mapped[target_id] = dict(cls=box.cls, box=[box.x1,box.y1,box.x2,box.y2], polygons=box.polygons, holes=box.holes, object_id=targets[target_id].get('object_id'))
            if mapped: frames[frame] = mapped
            if reasons: skipped[frame] = reasons
        return frames, skipped
