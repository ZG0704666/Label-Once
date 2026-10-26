from __future__ import annotations

import random
import re
import shutil
from collections import Counter
from pathlib import Path

import yaml

from .domain import Project, atomic_write, digest, read_json, save_json, unique_id

# Video frames carry the source video in their name, e.g. video_4620b2c7db04_frame_000003_f9_t900.jpg
FRAME_PATTERN = re.compile(r'^(.*)_frame_\d+_f\d+_t\d+$')


def sample_group(name, review_records=None):
    """Module-level twin of DatasetStore.group_key for callers without a store instance."""
    batch = (review_records or {}).get(name, {}).get('batch')
    if batch:
        return f'batch:{batch}'
    match = FRAME_PATTERN.match(Path(name).stem)
    if match:
        return f'video:{match.group(1)}'
    return f'solo:{name}'


class DatasetStore:
    def __init__(self, project: Project):
        self.project = project
        self.root = project.root / (project.root.name + '_dataset')
        self.versions = self.root / 'versions'
        self.versions.mkdir(parents=True, exist_ok=True)

    def list_versions(self):
        return sorted(p.name for p in self.versions.iterdir() if (p/'dataset_manifest.json').exists())

    def active(self):
        return read_json(self.root / 'active.json', {}).get('version')

    def manifest(self, version=None):
        version = version or self.active()
        if not version or Path(version).name != version:
            raise ValueError('请先创建数据集版本')
        return read_json(self.versions / version / 'dataset_manifest.json')

    def activate(self, version):
        self.manifest(version)
        src = self.versions / version / 'dataset.yaml'
        # The single YAML file is the authoritative atomic active pointer for external tools.
        atomic_write(self.root / 'dataset.yaml', src.read_text(encoding='utf-8'))
        save_json(self.root / 'active.json', {'version': version})

    def yaml_path(self, version=None):
        version = version or self.active()
        self.manifest(version)
        return self.versions / version / 'dataset.yaml'

    def group_key(self, name, review_records=None):
        """Identify the capture batch a sample belongs to.

        Frames of one video and one import batch are near-duplicates of each other, so they have to
        land in the same split; splitting them leaks the validation set into training.
        """
        return sample_group(name, review_records)

    def _fill_empty_splits(self, splits, ratios, counts, class_counts, groups, all_groups,
                           assignments, pinned):
        """Move a whole group into an empty requested split when the group granularity allows it."""
        for i, target_split in enumerate(splits):
            if not ratios[i] or counts[target_split]:
                continue
            donors = [j for j, s in enumerate(splits) if counts[s] > 1]
            if not donors:
                break
            donor = max(donors, key=lambda j: counts[splits[j]])
            movable = [g for g, members in all_groups.items()
                       if g in groups and g not in pinned
                       and all(assignments[r['name']] == splits[donor] for r in members)]
            if not movable:
                break
            key = min(movable, key=lambda g: (len(all_groups[g]), g))
            for r in groups[key]:
                assignments[r['name']] = target_split
                counts[splits[donor]] -= 1
                counts[target_split] += 1
                class_counts[splits[donor]].subtract(r['classes'])
                class_counts[target_split].update(r['classes'])
            pinned[key] = target_split

    def _plan_splits(self, records, ratios, seed, assignments):
        """Shared split planner for build and merge: groups travel intact, class balance guides placement.

        records carry {name, classes, group}; assignments holds already-decided name->split pins
        (inherited splits or the golden blacklist). Returns the group table, the final assignments,
        per-split counts, the split names and groups spanning more than one split.
        """
        splits = ('train', 'val', 'test')
        n = len(records)
        targets = [int(n*r) for r in ratios]
        for i in sorted(range(3), key=lambda i: (-(n*ratios[i]-targets[i]), i))[:n-sum(targets)]:
            targets[i] += 1
        # Keep nonzero requested splits usable on tiny validation datasets.
        for i in range(3):
            if n >= sum(r > 0 for r in ratios) and ratios[i] and targets[i] == 0:
                donor = max(range(3), key=lambda j: targets[j])
                targets[donor] -= 1
                targets[i] += 1
        total_class = Counter(c for r in records for c in r['classes'])
        counts = Counter(assignments.values())
        class_counts = {s: Counter() for s in splits}
        for r in records:
            if r['name'] in assignments:
                class_counts[assignments[r['name']]].update(r['classes'])
        # Samples captured together (one video, one import batch) share a group and must share a
        # split; a per-image split leaks near-duplicates into the validation set.
        all_groups = {}
        for r in records:
            all_groups.setdefault(r['group'], []).append(r)
        groups = {}
        for r in records:
            if r['name'] not in assignments:
                groups.setdefault(r['group'], []).append(r)
        settled = {g: Counter(assignments[r['name']] for r in members if r['name'] in assignments)
                   for g, members in all_groups.items()}
        pinned = {g: counter.most_common(1)[0][0] for g, counter in settled.items() if counter}
        keys = list(groups)
        random.Random(seed).shuffle(keys)
        position = {g: i for i, g in enumerate(keys)}
        order = sorted(keys, key=lambda g: (-len(groups[g]), position[g]))
        for key in order:
            members = groups[key]
            if key in pinned:
                target = pinned[key]
            else:
                eligible = [i for i, s in enumerate(splits) if ratios[i] and counts[s] < targets[i]]
                if not eligible:
                    eligible = [i for i in range(3) if ratios[i]]
                def score(i):
                    s = splits[i]
                    classes = {c for r in members for c in r['classes']}
                    deficit = sum((total_class[c]*ratios[i]-class_counts[s][c])/max(total_class[c], 1) for c in classes)
                    return (deficit/max(len(members), 1), (targets[i]-counts[s])/max(targets[i], 1), -i)
                target = splits[max(eligible, key=score)]
            for r in members:
                assignments[r['name']] = target
                counts[target] += 1
                class_counts[target].update(r['classes'])
        self._fill_empty_splits(splits, ratios, counts, class_counts, groups, all_groups, assignments, pinned)
        # A group that inherited members in two splits from an earlier version cannot be repaired
        # without rebuilding, so report it instead of silently shipping a leaky split.
        leaked = sorted(g for g, members in all_groups.items()
                        if len({assignments[r['name']] for r in members}) > 1)
        return all_groups, assignments, counts, splits, leaked

    def create(self, ratios=(.7, .2, .1), seed=42, incremental=False):
        if len(ratios) != 3 or any(r < 0 for r in ratios) or abs(sum(ratios)-1) > 1e-6:
            raise ValueError('训练/验证/测试比例必须非负且总和为 1')
        self.project.assert_unique_stems()
        names = self.project.labels.classes
        if not names:
            raise ValueError('项目尚无类别')
        from .review import ReviewStore
        review = ReviewStore(self.project); review_records = review.records(); excluded = 0
        records = []
        for p in self.project.image_paths():
            if review.status(p.name, review_records) in ("pending", "rejected"):
                excluded += 1
                continue
            label = self.project.labels.folder / (p.stem+'.txt')
            if not label.exists():
                continue  # Missing is not a reviewed negative image.
            boxes = self.project.labels.load(p.stem)
            if any(b.cls >= len(names) for b in boxes):
                raise ValueError(f'{p.name} 包含不存在的类别')
            records.append({'name': p.name, 'sha256': digest(p), 'label_sha256': digest(label),
                            'classes': sorted({b.cls for b in boxes}),
                            'group': self.group_key(p.name, review_records)})
        if not records:
            raise ValueError('没有已审核的图片标签（允许空 TXT 负样本）')
        prior = self.manifest() if incremental and self.active() else None
        assignments = {}
        if prior:
            if prior['names'] != names or prior['ratios'] != list(ratios):
                raise ValueError('增量更新必须保持类别及比例；请使用重新平衡')
            current = {r['name']: r for r in records}
            for old in prior['images']:
                new = current.get(old['name'])
                if not new or new['sha256'] != old['sha256'] or new['label_sha256'] != old['label_sha256']:
                    raise ValueError(f'旧样本丢失或变化：{old["name"]}；请重新平衡')
                assignments[old['name']] = old['split']
            if len(assignments) == len(records):
                return prior['version']
        all_groups, assignments, counts, splits, leaked = self._plan_splits(records, ratios, seed, assignments)
        if leaked and not prior:
            raise ValueError('分组划分出现跨集合分组，请检查导入批次设置')
        version = unique_id()
        folder = self.versions / version
        staging = self.versions / ('.'+version)
        staging.mkdir()
        try:
            for s in splits:
                (staging/'images'/s).mkdir(parents=True)
                (staging/'labels'/s).mkdir(parents=True)
            for r in records:
                r['split'] = assignments[r['name']]
                src = self.project.images/r['name']
                shutil.copy2(src, staging/'images'/r['split']/src.name)
                shutil.copy2(self.project.labels.folder/(src.stem+'.txt'), staging/'labels'/r['split']/(src.stem+'.txt'))
            manifest = dict(schema_version=1, version=version, parent=prior['version'] if prior else None,
                            names=names, ratios=list(ratios), seed=seed, images=records, excluded_pending=excluded,
                            groups={g: dict(split=assignments[members[0]['name']], count=len(members),
                                            classes=sorted({c for m in members for c in m['classes']}))
                                    for g, members in all_groups.items()},
                            leaked_groups=leaked)
            save_json(staging/'dataset_manifest.json', manifest)
            config = dict(path=str(folder), train='images/train', val='images/val', test='images/test', names=dict(enumerate(names)))
            atomic_write(staging/'dataset.yaml', yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
            staging.rename(folder)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self.activate(version)
        note = f'，跨集合分组 {len(leaked)} 个（请重新划分）' if leaked else ''
        empty = [s for i, s in enumerate(splits) if ratios[i] and not counts[s]]
        if empty:
            note += f'，空集合 {"、".join(empty)}（分组过少，无法满足比例）'
        self.project.log(f'创建数据集版本 {version}，{dict(counts)}，排除待复审 {excluded} 张{note}')
        return version
