"""多数据集版本的智能整合引擎。

架构约束（与 docs/DATASET_MERGE.md 对应）
---------------------------------------
1. 类别表只追加：合并永远不能移动既有类别的 ID；新类名按首次出现顺序追加在末尾。
   首次确认过的映射写入 classes_alias.json，之后自动套用。
2. 版本不可变：产物永远是一个新的数据集版本；staging -> 校验 -> 原子改名；
   绝不写任何来源目录（本项目版本 / 其它 Label Once 项目 / 外部 YOLO 目录一律只读）。
3. 幂等可重放：外部来源扫描结果按内容指纹缓存在 sources.json；
   同一指纹直接复用哈希与解析结果，文件变动（大小/时间）会触发重新扫描。
4. 失败前置：冲突在落盘前全部裁定，阻断项（BLOCK）直接拒绝提交，
   警告项（WARN）继续但写入 merge manifest 供审计。
5. 泄漏前置：冻结基准集（golden）命中的样本与其同组近邻帧强制进 val，
   训练一侧永远见不到基准集内容；发布门禁在发布前还会兜底一次。
6. 统一重划：所有来源（外部目录/其它项目/本项目版本/本项目素材）原有的
   train/val/test 划分一律作废，整库按（训练/验证/测试比例 + 随机种子）按组重划；
   只有基准集黑名单固定项优先。外部目录里没有标签的图片作为空标注负样本收录。
"""
from __future__ import annotations

import csv
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from .dataset import FRAME_PATTERN
from .domain import IMAGE_EXTENSIONS, atomic_write, digest, natural_key, read_json, save_json, unique_id

PROJECT_KIND = 'project'          # 当前项目里已完成的素材
VERSION_KIND = 'version'          # 本项目的某个数据集版本
CROSS_KIND = 'cross_project'      # 其它 Label Once 项目
EXTERNAL_KIND = 'external_yolo'   # 外部 YOLO 目录（images/ + labels/，或扁平结构）
KINDS = (PROJECT_KIND, VERSION_KIND, CROSS_KIND, EXTERNAL_KIND)
SPLIT_DIRS = {'train': 'train', 'val': 'val', 'valid': 'val', 'validation': 'val', 'test': 'test'}


@dataclass
class Sample:
    source: str          # 来源展示键
    name: str            # 唯一文件名（落在划分目录平铺）
    image_path: str
    label_path: str
    image_sha256: str
    label_sha256: str
    classes: list        # 类别 ID（来源坐标系）
    group: str
    split: str | None    # 来源已声明的划分（可继承）
    segment: bool = False

    def to_dict(self):
        return dict(source=self.source, name=self.name, image_path=self.image_path,
                    label_path=self.label_path, image_sha256=self.image_sha256,
                    label_sha256=self.label_sha256, classes=list(self.classes),
                    group=self.group, split=self.split, segment=self.segment)

    @classmethod
    def from_dict(cls, data):
        return cls(data['source'], data['name'], data['image_path'], data['label_path'],
                   data['image_sha256'], data['label_sha256'], list(data.get('classes') or []),
                   data.get('group') or 'solo:' + data['name'],
                   data.get('split') if data.get('split') in ('train', 'val', 'test') else None,
                   bool(data.get('segment')))


# ---------------------------------------------------------------- 来源缓存与扫描

def _cache_file(store):
    return store.root / 'sources.json'


def _load_cache(store):
    data = read_json(_cache_file(store), {}) or {}
    return data if data.get('schema') == 1 else {'schema': 1, 'sources': {}}


def _cache_key(source):
    kind = source.get('kind')
    if kind == PROJECT_KIND:
        return ['project']
    if kind == VERSION_KIND:
        return ['version', str(source.get('version') or '')]
    if kind in (CROSS_KIND, EXTERNAL_KIND):
        return [kind, str(Path(source['path']).resolve())]
    raise ValueError(f'未知数据来源类型：{kind}，支持 {"、".join(KINDS)}')


def _display_key(key, version=None):
    kind = key[0]
    if kind == PROJECT_KIND:
        return 'project'
    if kind == VERSION_KIND:
        return f'version:{key[1]}'
    if kind == CROSS_KIND:
        return f'cross_project:{Path(key[1]).name}:{version}'
    return f'external_yolo:{Path(key[1]).name}'


def _scan_source(store, source):
    """Harvest one source. External dirs reuse cached hashes while the fingerprint holds."""
    key = _cache_key(source)
    kind = key[0]
    if kind == PROJECT_KIND:
        samples, names = _scan_project(store)
        return dict(key='project', kind=kind, path=str(store.project.root), version=None,
                    names=names, samples=samples, skipped=0)
    if kind == VERSION_KIND:
        folder = store.versions / key[1] if key[1] else None
        if not folder or not (folder / 'dataset_manifest.json').exists():
            raise ValueError(f'本项目没有数据集版本：{key[1] or "<未指定>"}')
        samples, names = _scan_version(store, f'version:{folder.name}', folder)
        return dict(key=f'version:{folder.name}', kind=kind, path=str(folder), version=folder.name,
                    names=names, samples=samples, skipped=0)
    if kind == CROSS_KIND:
        folder = _external_version_folder(Path(key[1]), source.get('version'))
        samples, names = _scan_version(store, _display_key(key, folder.name), folder)
        return dict(key=_display_key(key, folder.name), kind=kind, path=str(folder), version=folder.name,
                    names=names, samples=samples, skipped=0)
    root = Path(key[1])
    if not root.is_dir():
        raise ValueError(f'外部 YOLO 目录不存在：{root}')
    display = _display_key(key)
    fingerprint = _external_fingerprint(root)
    cache = _load_cache(store)
    entry = cache['sources'].get(str(key))
    if entry and entry.get('fingerprint') == fingerprint:
        return dict(key=display, kind=kind, path=str(root), version=None,
                    names=list(entry.get('names') or []),
                    samples=[Sample.from_dict(s) for s in entry.get('samples') or []],
                    skipped=int(entry.get('skipped') or 0))
    samples, names, skipped = _scan_external(display, root)
    cache['sources'][str(key)] = dict(kind=kind, path=str(root), version=None, names=names,
        fingerprint=fingerprint, skipped=skipped, samples=[s.to_dict() for s in samples])
    save_json(_cache_file(store), cache)
    return dict(key=display, kind=kind, path=str(root), version=None,
                names=names, samples=samples, skipped=skipped)


def _external_version_folder(root, version):
    base = root / (root.name + '_dataset')
    version = version or (read_json(base / 'active.json', {}) or {}).get('version')
    if not version:
        raise ValueError(f'其它项目 {root.name} 尚无激活的数据集版本，请先在该项目里创建')
    folder = base / 'versions' / version
    if not (folder / 'dataset_manifest.json').exists():
        raise ValueError(f'其它项目 {root.name} 没有数据集版本 {version}')
    return folder


def _scan_project(store):
    """当前项目已完成素材（收录规则与训练建库一致：排除待复审/已驳回，缺标签跳过）。"""
    project = store.project
    from .review import ReviewStore
    review = ReviewStore(project)
    records = review.records()
    names = list(project.labels.classes)
    samples = []
    for p in project.image_paths():
        if review.status(p.name, records) in ('pending', 'rejected'):
            continue
        label = project.labels.folder / (p.stem + '.txt')
        if not label.exists():
            continue
        boxes = project.labels.load(p.stem)
        if any(b.cls >= len(names) for b in boxes):
            raise ValueError(f'{p.name} 包含不存在的类别，请先修正标注')
        samples.append(Sample('project', p.name, str(p), str(label), digest(p), digest(label),
                              sorted({b.cls for b in boxes}), store.group_key(p.name, records), None))
    return samples, names


def _scan_version(store, display, folder):
    manifest = read_json(folder / 'dataset_manifest.json')
    if not manifest:
        raise ValueError(f'{folder} 缺少 dataset_manifest.json，不是有效的数据集版本')
    names = list(manifest.get('names') or [])
    missing, samples = [], []
    for entry in manifest.get('images', []):
        split = entry.get('split')
        name = entry['name']
        image = folder / 'images' / str(split) / name if split else folder / 'images' / name
        label = (folder / 'labels' / str(split) / (Path(name).stem + '.txt') if split
                 else folder / 'labels' / (Path(name).stem + '.txt'))
        if not image.is_file() or not label.is_file():
            missing.append(name)
            continue
        samples.append(Sample(display, name, str(image), str(label),
                              entry.get('sha256') or digest(image), entry.get('label_sha256') or digest(label),
                              list(entry.get('classes') or []),
                              entry.get('group') or store.group_key(name, {}),
                              split if split in ('train', 'val', 'test') else None))
    if missing:
        preview = '、'.join(missing[:5]) + ('…' if len(missing) > 5 else '')
        raise ValueError(f'{display} 有 {len(missing)} 张样本缺少图片或标签：{preview}；请检查该版本是否被移动过')
    return samples, names


def _external_fingerprint(root):
    """目录内容指纹：路径 + 大小 + mtime，避免预览阶段重复做全量哈希。"""
    h = hashlib.sha256()
    roots = [root / 'images' if (root / 'images').is_dir() else root]
    if (root / 'labels').is_dir():
        roots.append(root / 'labels')
    seen = set()
    for base in roots:
        for p in base.rglob('*'):
            if not p.is_file() or p.resolve() in seen:
                continue
            seen.add(p.resolve())
            stat = p.stat()
            h.update(f'{p.name}|{stat.st_size}|{stat.st_mtime_ns}\n'.encode())
    return h.hexdigest()


def _scan_external(display, root):
    images_root = root / 'images' if (root / 'images').is_dir() else root
    labels_root = root / 'labels' if (root / 'labels').is_dir() else images_root
    names = _external_names(root)
    samples, skipped = [], []
    for image in sorted((p for p in images_root.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
                        key=natural_key):
        rel = image.relative_to(images_root)
        split = SPLIT_DIRS.get(rel.parts[0].lower()) if len(rel.parts) > 1 else None
        label = labels_root.joinpath(*rel.with_suffix('.txt').parts)
        if not label.is_file():
            label = image.with_suffix('.txt')
        match = FRAME_PATTERN.match(image.stem)
        group = f'video:{match.group(1)}' if match else f'solo:{image.name}'
        if not label.is_file():
            # 没有标签的图片作为空标注负样本收录（背景样本）。
            samples.append(Sample(display, image.name, str(image), '', digest(image),
                                  hashlib.sha256(b'').hexdigest(), [], group, split, False))
            continue
        ids, segment = _read_label(label, display, names)
        samples.append(Sample(display, image.name, str(image), str(label),
                              digest(image), digest(label), ids, group, split, segment))
    return samples, names, skipped


def _external_names(root):
    for candidate in (root / 'dataset.yaml', root / 'data.yaml'):
        if candidate.is_file():
            data = yaml.safe_load(candidate.read_text(encoding='utf-8-sig')) or {}
            raw = data.get('names')
            if isinstance(raw, dict):
                return [str(v) for _, v in sorted(raw.items(), key=lambda i: int(i[0]))]
            if isinstance(raw, list) and raw:
                return [str(v) for v in raw]
            break
    for candidate in (root / 'classes.txt', root / 'images' / 'classes.txt', root / 'labels' / 'classes.txt',
                      root / 'images' / 'train' / 'classes.txt'):
        if candidate.is_file():
            values = [line.strip() for line in candidate.read_text(encoding='utf-8-sig').splitlines()
                      if line.strip()]
            if values:
                return values
    return []


def _read_label(path, display, names):
    """解析 YOLO 标签 id；>5 字段视为多边形行保留（segment=True）。"""
    ids, segment = [], False
    for index, line in enumerate(path.read_text(encoding='utf-8-sig', errors='replace').splitlines()):
        code = line.split('#', 1)[0].split()
        if not code:
            continue
        if len(code) < 5:
            raise ValueError(f'{display}:{path.name} 第 {index+1} 行字段不足 5 个，标签损坏')
        try:
            cls = int(code[0])
        except ValueError as exc:
            raise ValueError(f'{display}:{path.name} 第 {index+1} 行类别不是整数') from exc
        if names and cls >= len(names):
            raise ValueError(f'{display}:{path.name} 第 {index+1} 行类别 ID {cls} '
                             f'超出其类别表（{len(names)} 类）')
        if len(code) > 5:
            segment = True
        ids.append(cls)
    return sorted(set(ids)), segment


# ---------------------------------------------------------------- 类别对齐（只追加）

def _align(store, scanned, spec, blocks):
    """按名字映射来源类别；既有 ID 永不位移，新类按首次出现顺序追加在末尾。"""
    base = list(store.project.labels.classes)
    saved = read_json(store.root / 'classes_alias.json', {}) or {}
    alias = {str(k).casefold(): str(v) for k, v in saved.items()}
    resolutions = {str(k): str(v) for k, v in (spec.get('resolutions') or {}).items()}
    buckets = {}
    for src in scanned:
        for name in src['names']:
            buckets.setdefault(name.casefold(), set()).add(name)
    ambiguous = {fold: sorted(values) for fold, values in buckets.items() if len(values) > 1}
    final, index = list(base), {name: i for i, name in enumerate(base)}
    rows, remaps = [], {}
    for src in scanned:
        mapping = {}
        for cls_id, name in enumerate(src['names']):
            canon, status = None, None
            if name in index:
                canon, status = name, 'exact'
            elif name in resolutions:
                canon, status = resolutions[name], 'resolution'
            elif name.casefold() not in ambiguous and alias.get(name.casefold()) in index:
                canon, status = alias[name.casefold()], 'alias'
            elif name.casefold() not in ambiguous:
                canon = next((n for n in final if n.casefold() == name.casefold()), None)
                status = 'alias' if canon else 'new'
            if canon is None:
                if name.casefold() in ambiguous:
                    blocks.append(dict(code='CLASS_UNRESOLVED',
                                       message=f'类别「{name}」（来源 {src["key"]}）存在多种大小写变体 '
                                               f'（{"、".join(ambiguous[name.casefold()])}），'
                                               f'请在 resolutions 里显式指定目标类别'))
                canon, status = name, 'new'
            if canon not in index:
                final.append(canon)
                index[canon] = len(final) - 1
            mapping[cls_id] = index[canon]
            rows.append(dict(source=src['key'], name=name, target=index[canon], canon=canon, status=status))
        remaps[src['key']] = mapping
    new_names = final[len(base):]
    if new_names and not spec.get('accept_new_classes'):
        blocks.append(dict(code='NEW_CLASSES',
                           message=f'整合将新增 {len(new_names)} 个类别：{"、".join(new_names)}；'
                                   f'它们将追加到项目类别表末尾，请预览确认'))
    return final, new_names, rows, remaps


# ---------------------------------------------------------------- 去重与冲突

def _dedupe(scanned, policy, blocks, warnings):
    """以图片 SHA256 为权威键去重；同名不同内容阻断，同图不同标签按策略取舍并告警。"""
    entries, by_content = {}, {}
    counts = {src['key']: dict(total=0, contributed=0, deduped=0) for src in scanned}
    duplicates, clashes = 0, []
    for src in scanned:
        stats = counts[src['key']]
        for sample in src['samples']:
            stats['total'] += 1
            existing = entries.get(sample.name)
            if existing is not None:
                if existing.image_sha256 == sample.image_sha256 and existing.label_sha256 == sample.label_sha256:
                    duplicates += 1
                    stats['deduped'] += 1
                    continue
                blocks.append(dict(code='STEM_CLASH',
                                   message=f'文件名 {sample.name} 在 {existing.source} 与 {src["key"]} 中'
                                           f'内容不同，落盘会互相覆盖，请先重命名其中一方'))
                continue
            other = by_content.get(sample.image_sha256)
            if other is not None:
                # 同内容同标签＝同一张图换了名字：必须作为重复跳过，否则两份拷贝
                # 会分别归入 train/val（验证集泄漏），且 total 被虚增。
                if entries[other].label_sha256 == sample.label_sha256:
                    duplicates += 1
                    stats['deduped'] += 1
                    continue
                clashes.append(dict(kept=other, dropped=sample.name,
                                    keeper=entries[other].source, challenger=src['key']))
                if policy == 'last':
                    del entries[other]
                else:
                    stats['deduped'] += 1
                    continue
            entries[sample.name] = sample
            by_content[sample.image_sha256] = sample.name
            stats['contributed'] += 1
    if clashes:
        detail = '；'.join(f'{c["keeper"]}·{c["kept"]} ↔ {c["challenger"]}·{c["dropped"]}' for c in clashes[:5])
        warnings.append(dict(code='HASH_DUP_CONTENT_CLASH',
                             message=f'{len(clashes)} 组图片内容相同但标签不同'
                                     f'（按{"后加入" if policy == "last" else "先登记"}来源保留）：{detail}'))
    return entries, dict(counts=counts, duplicates=duplicates, content_clashes=clashes)


# ---------------------------------------------------------------- 划分与冻结集

def _apply_blacklist(entries, blacklist, warnings):
    """golden 命中样本连同其同组近邻帧固定进 val；训练侧永远见不到基准集内容。"""
    hits = {name for name, sample in entries.items() if sample.image_sha256 in blacklist}
    if not hits:
        return {}, dict(hits=0, pinned_samples=0, blacklist_size=len(blacklist))
    groups = {entries[name].group for name in hits}
    assignments = {name: 'val' for name, sample in entries.items() if sample.group in groups}
    if len(assignments) > len(hits):
        warnings.append(dict(code='GOLDEN_GROUP',
                             message=f'基准集命中 {len(hits)} 张，同组近邻帧一并固定进 val，共 {len(assignments)} 张'))
    else:
        warnings.append(dict(code='GOLDEN_PIN',
                             message=f'基准集命中 {len(hits)} 张，已固定进 val'))
    return assignments, dict(hits=len(hits), pinned_samples=len(assignments), blacklist_size=len(blacklist))


# ----------------------------------------------------------------总体规划

def _normalize_spec(spec):
    norm = dict(spec or {})
    ratios = norm.get('ratios') or (.7, .2, .1)
    try:
        ratios = tuple(float(v) for v in ratios)
    except (TypeError, ValueError) as exc:
        raise ValueError('划分比例必须是数值') from exc
    if len(ratios) != 3 or any(r < 0 for r in ratios) or abs(sum(ratios)-1) > 1e-6:
        raise ValueError('训练/验证/测试比例必须非负且总和为 1')
    if ratios[0] + ratios[1] <= 0:
        raise ValueError('训练集与验证集比例不能同时为 0')
    norm['ratios'] = ratios
    norm['seed'] = int(norm.get('seed', 42))
    dedup = str(norm.get('dedup') or 'last')
    if dedup not in ('first', 'last'):
        raise ValueError('同名冲突处理只支持 first / last')
    norm['dedup'] = dedup
    norm['keep_segment'] = bool(norm.get('keep_segment', True))
    norm['accept_new_classes'] = bool(norm.get('accept_new_classes', False))
    norm['sources'] = norm.get('sources') or []
    if not norm['sources']:
        raise ValueError('请至少选择一个数据来源')
    # 黑名单统一在这里解析：既走路径（golden 目录 / manifest.csv / dataset.yaml / 单图），
    # 也接受直接给出 SHA256；预览与提交使用同一套解析，保证预览的固定数与提交一致。
    items = norm.get('blacklist')
    if items:
        if isinstance(items, (str, Path)):
            items = [items]
        digests = set()
        for item in items:
            text = str(item).strip().lower()
            if len(text) == 64 and all(c in '0123456789abcdef' for c in text):
                digests.add(text)
            else:
                digests.update(load_blacklist(item))
        norm['blacklist'] = sorted(digests)
    else:
        norm['blacklist'] = []
    return norm


def _plan(store, spec, progress, check):
    """完整计划：扫描 -> 类对齐 -> 去重 -> 黑名单 -> 划分；预览与提交共用这一条路径。"""
    blocks, warnings = [], []
    scanned = []
    total_sources = len(spec['sources'])
    for i, source in enumerate(spec['sources']):
        check()
        progress(0.02 + 0.18*i/total_sources, f'扫描来源 {i+1}/{total_sources}')
        scanned.append(_scan_source(store, source))
    if not sum(len(src['samples']) for src in scanned):
        raise ValueError('所选来源没有任何可整合的样本')

    progress(0.24, '类别对齐（按名映射，只追加）')
    names, new_names, class_rows, remaps = _align(store, scanned, spec, blocks)
    for src in scanned:
        if src['samples'] and not src['names']:
            blocks.append(dict(code='CLASS_TABLE_MISSING',
                               message=f'来源 {src["key"]} 有样本但缺少类别表，'
                                       f'外部目录请提供 dataset.yaml(names) 或 classes.txt'))
        mapping = remaps[src['key']]
        for sample in src['samples']:
            if any(cls < 0 or cls >= len(mapping) for cls in sample.classes):
                blocks.append(dict(code='ID_OUT_OF_RANGE',
                                   message=f'{src["key"]} 的 {sample.name} 类别 ID 超出其类别表'))
                break

    progress(0.30, '内容去重（SHA256）')
    entries, dedupe = _dedupe(scanned, spec['dedup'], blocks, warnings)
    if not entries:
        raise ValueError('来源之间没有不重复的可用样本')

    blacklist = {str(v).lower() for v in (spec.get('blacklist') or [])}
    pinned, pin_report = _apply_blacklist(entries, blacklist, warnings)

    progress(0.36, '分组划分（同组同集合）')
    records, sample_of = [], {}
    for name, sample in entries.items():
        mapping = remaps[sample.source]
        records.append(dict(name=name, sha256=sample.image_sha256, label_sha256=sample.label_sha256,
                            classes=sorted({mapping[c] for c in sample.classes}), group=sample.group,
                            source=sample.source))
        sample_of[name] = sample
    # 统一重划：所有来源原有 train/val/test 划分一律作废，整库按
    # （训练/验证/测试比例 + 随机种子）按组重划；只有基准集黑名单固定项优先。
    assignments = dict(pinned)
    all_groups, assignments, counts, splits, leaked = store._plan_splits(
        records, spec['ratios'], spec['seed'], assignments)
    if leaked:
        warnings.append(dict(code='CROSS_SPLIT_GROUP',
                             message=f'{len(leaked)} 个分组因在验证集固定后被重复分配而出现冲突：{", ".join(leaked[:5])}'))
    empty = [s for i, s in enumerate(splits) if spec['ratios'][i] and not counts[s]]
    if empty:
        warnings.append(dict(code='EMPTY_SPLIT',
                             message=f'空集合 {"、".join(empty)}（分组过少，无法满足比例）'))

    per_source = []
    for src in scanned:
        stats = dedupe['counts'][src['key']]
        per_source.append(dict(source=src['key'], kind=src['kind'], path=src['path'], version=src['version'],
                               names=src['names'], samples=stats['total'], contributed=stats['contributed'],
                               deduped=stats['deduped'],
                               empty_labels=sum(1 for s in src['samples'] if not s.label_path),
                               by_split={s: sum(1 for r in records
                                                if r['source'] == src['key'] and assignments[r['name']] == s)
                                         for s in splits},
                               skipped=src.get('skipped') or 0))
    report = dict(total=len(records), names=names, new_classes=new_names, class_rows=class_rows,
                  dedupe=dict(duplicates=dedupe['duplicates'],
                              content_clashes=dedupe['content_clashes'][:20],
                              content_clash_count=len(dedupe['content_clashes'])),
                  blacklist=pin_report, conflicts=dict(blocks=blocks, warnings=warnings),
                  estimate=dict(total=len(records), by_split=dict(counts)), per_source=per_source)
    return dict(spec=spec, scanned=scanned, entries=entries, sample_of=sample_of, records=records,
                names=names, new_names=new_names, class_rows=class_rows, remaps=remaps,
                assignments=assignments, all_groups=all_groups, splits=splits, leaked=leaked,
                report=report)


def preview(store, spec):
    """Dry-run：与提交同一条计划路径，但不写入任何版本。"""
    return _plan(store, _normalize_spec(spec), lambda *a, **k: None, lambda: None)['report']


def merge(store, spec, progress=None, check=None):
    """把多个来源整合为新的不可变数据集版本，成功后自动激活。"""
    progress = progress or (lambda *a, **k: None)
    check = check or (lambda: None)
    store.project.assert_unique_stems()
    plan = _plan(store, _normalize_spec(spec), progress, check)
    blocks = plan['report']['conflicts']['blocks']
    if blocks:
        raise ValueError('整合被阻断，请先解决以下问题：\n' + '\n'.join(
            f'[{b["code"]}] {b["message"]}' for b in blocks))
    spec, records, entries = plan['spec'], plan['records'], plan['entries']
    names, new_names = plan['names'], plan['new_names']
    progress(0.40, f'样本 {len(records)}，类别 {len(names)}（新增 {len(new_names)} 个）')
    # 新类必须先落进项目类别表（只追加），这样预览里确认的表就是实际训练的表。
    if new_names:
        classes = list(store.project.labels.classes)
        classes.extend(n for n in new_names if n not in classes)
        store.project.labels.set_classes(classes)
        store.project.log(f'整合新增类别 {len(new_names)} 个（追加在末尾）：{"、".join(new_names)}')
    version = unique_id()
    folder = store.versions / version
    staging = store.versions / ('.' + version)
    staging.mkdir()
    try:
        for s in plan['splits']:
            (staging/'images'/s).mkdir(parents=True)
            (staging/'labels'/s).mkdir(parents=True)
        total = len(records)
        for i, record in enumerate(records):
            check()
            split = plan['assignments'][record['name']]
            sample = plan['sample_of'][record['name']]
            record['split'] = split
            shutil.copy2(sample.image_path, staging/'images'/split/sample.name)
            _write_label(sample.label_path, staging/'labels'/split/(Path(record['name']).stem + '.txt'),
                         plan['remaps'][sample.source], spec['keep_segment'])
            if i % 20 == 0:
                progress(0.40 + 0.48*i/max(total, 1), f'写出 {i+1}/{total}')
        progress(0.92, '写入清单')
        manifest = dict(schema_version=1, version=version, parent=None,
                        names=names, ratios=list(spec['ratios']), seed=spec['seed'],
                        images=records, excluded_pending=0,
                        groups={g: dict(split=plan['assignments'][members[0]['name']], count=len(members),
                                        classes=sorted({c for m in members for c in m['classes']}))
                                for g, members in plan['all_groups'].items()},
                        leaked_groups=plan['leaked'],
                        merges=plan['report']['per_source'],
                        dedupe=dict(duplicates=plan['report']['dedupe']['duplicates'],
                                    content_clashes=plan['report']['dedupe']['content_clash_count']),
                        blacklist=plan['report']['blacklist'])
        save_json(staging/'dataset_manifest.json', manifest)
        config = dict(path=str(folder), train='images/train', val='images/val', test='images/test',
                      names=dict(enumerate(names)))
        atomic_write(staging/'dataset.yaml', yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
        staging.rename(folder)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    store.activate(version)
    _save_alias(store, plan)
    counts = {s: sum(1 for r in records if r['split'] == s) for s in plan['splits']}
    note = f'，共 {len(records)} 张，类别 {len(names)}（新增 {len(new_names)}）' if new_names \
        else f'，共 {len(records)} 张，类别 {len(names)}'
    if plan['report']['dedupe']['duplicates']:
        note += f'，去重 {plan["report"]["dedupe"]["duplicates"]} 张'
    store.project.log(f'整合数据集版本 {version}：来源 {len(spec["sources"])} 个{note}，分布 {counts}')
    progress(1, '整合完成')
    return dict(version=version, dataset=str(folder/'dataset.yaml'), total=len(records),
                by_split=counts, new_classes=new_names,
                duplicates=plan['report']['dedupe']['duplicates'],
                content_clashes=plan['report']['dedupe']['content_clashes'][:20],
                class_rows=plan['class_rows'], per_source=plan['report']['per_source'])


def _write_label(label_path, target, remap, keep_segment):
    """复制并重映射一个标签的类别 ID；恒等映射直接按字节复制；空路径写空标注。"""
    label_path = Path(label_path) if label_path else None
    if label_path is None:
        target.write_text('', encoding='utf-8')
        return
    text = label_path.read_text(encoding='utf-8-sig', errors='replace')
    if not remap or all(int(k) == int(v) for k, v in remap.items()):
        target.write_text(text, encoding='utf-8')
        return
    out = []
    for line in text.splitlines():
        code = line.split('#', 1)
        tokens = code[0].split()
        if not tokens:
            continue
        if len(tokens) < 5:
            raise ValueError(f'标签 {label_path.name} 存在损坏行，请先修复来源数据')
        if len(tokens) > 5 and not keep_segment:
            continue  # 用户选择不保留多边形行时，该文件只会包含检测框行
        cls = int(tokens[0])
        if cls not in remap:
            raise ValueError(f'标签 {label_path.name} 类别 ID {cls} 无法映射，请检查来源类别表')
        tokens[0] = str(remap[cls])
        out.append(' '.join(tokens) + (' #' + code[1] if len(code) > 1 else ''))
    target.write_text('\n'.join(out) + ('\n' if out else ''), encoding='utf-8')


def _save_alias(store, plan):
    """把用户显式指定或依赖别名机制得到的映射持久化，下次同类来源自动套用。"""
    alias = read_json(store.root / 'classes_alias.json', {}) or {}
    changes = False
    for row in plan['class_rows']:
        if row['status'] == 'exact':
            continue
        key = row['name'].casefold()
        if alias.get(key) != row['canon']:
            alias[key] = row['canon']
            changes = True
    if changes:
        save_json(store.root / 'classes_alias.json', alias)


# ---------------------------------------------------------------- 冻结基准集黑名单

_GOLDEN_COLUMNS = ('sha256', 'image_sha256', 'hash')


def load_blacklist(path):
    """从冻结基准集收集图片 SHA256：manifest.csv、golden dataset.yaml 或纯图片目录。"""
    path = Path(path)
    hashes: set[str] = set()
    if path.is_dir():
        for candidate in (path / 'manifest.csv', path.parent / 'manifest.csv'):
            if candidate.is_file():
                _absorb_csv(candidate, hashes)
                break
        for folder in (path / 'images' / 'val', path / 'images', path / 'val'):
            if folder.is_dir():
                _absorb_folder(folder, hashes)
                break
        return sorted(hashes)
    if path.suffix.lower() == '.csv':
        _absorb_csv(path, hashes)
        return sorted(hashes)
    if path.suffix.lower() in ('.yaml', '.yml'):
        data = yaml.safe_load(path.read_text(encoding='utf-8-sig')) or {}
        root = Path(str(data.get('path') or path.parent)).resolve()
        for key in ('val', 'train'):
            # val 和 train 都是冻结基准内容：训练集不得学习它们，全部吸收并固定进 val。
            spec = str(data.get(key) or '')
            if not spec:
                continue
            folder = Path(spec)
            folder = folder if folder.is_absolute() else root / folder
            if folder.is_dir():
                _absorb_folder(folder, hashes)
            elif any(ch in str(spec) for ch in '*?['):
                for match in root.glob(str(spec)):
                    if match.is_dir():
                        _absorb_folder(match, hashes)
        return sorted(hashes)
    if path.is_file():
        hashes.add(digest(path))
    return sorted(hashes)


def _absorb_csv(path, hashes):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            for column in _GOLDEN_COLUMNS:
                value = (row.get(column) or '').strip().lower()
                if value:
                    hashes.add(value)
                    break


def _absorb_folder(folder, hashes):
    for p in folder.rglob('*'):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            hashes.add(digest(p))


# ---------------------------------------------------------------- 登记列表

def list_sources(store, forget=None):
    cache = _load_cache(store)
    if forget:
        cache['sources'].pop(forget, None)
        save_json(_cache_file(store), cache)
    entries = [dict(key=str(key), kind=entry.get('kind'), path=entry.get('path'),
                    version=entry.get('version'), names=entry.get('names'),
                    samples=len(entry.get('samples') or []))
               for key, entry in cache['sources'].items()]
    return dict(sources=entries, alias=read_json(store.root / 'classes_alias.json', {}) or {},
                active=store.active(), versions=store.list_versions())
