import hashlib
import json
from pathlib import Path

import pytest
import yaml
from studio.domain import Project, atomic_write, digest
from studio.dataset import DatasetStore
from studio.merge import preview, merge, list_sources


def make_project(path, classes=('cat', 'dog')):
    project = Project(path)
    project.labels.set_classes(list(classes))
    return project


def add_project_sample(project, stem, blob, cls_ids=(), label_text=None):
    (project.images / f'{stem}.png').write_bytes(blob)
    text = label_text
    if text is None:
        text = '\n'.join(f'{c} .1 .2 .8 .9' for c in cls_ids) + '\n'
    (project.labels.folder / f'{stem}.txt').write_text(text, encoding='utf-8')


def add_ext_sample(root, split, stem, blob, lines):
    images = root / 'images' / split if split else root / 'images'
    labels = root / 'labels' / split if split else root / 'labels'
    images.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    (images / f'{stem}.png').write_bytes(blob)
    (labels / f'{stem}.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def set_ext_names(root, names):
    atomic_write(root / 'dataset.yaml',
                 yaml.safe_dump({'names': dict(enumerate(names))}, allow_unicode=True))


def read_manifest(folder):
    return json.loads((folder / 'dataset_manifest.json').read_text(encoding='utf-8'))


def split_of(manifest, name):
    return next(r['split'] for r in manifest['images'] if r['name'] == name)


def test_preview_blocks_new_classes_until_accepted(tmp_path):
    project = make_project(tmp_path / 'proj')
    root = tmp_path / 'ext'
    add_ext_sample(root, 'train', 'x1', b'img-a', ['0 .5 .5 .2 .2'])
    set_ext_names(root, ['dog', 'rabbit'])
    spec = dict(sources=[dict(kind='project'), dict(kind='external_yolo', path=str(root))])
    report = preview(DatasetStore(project), spec)
    codes = {b['code'] for b in report['conflicts']['blocks']}
    assert codes == {'NEW_CLASSES'} and report['new_classes'] == ['rabbit']
    spec['accept_new_classes'] = True
    report = preview(DatasetStore(project), spec)
    assert not report['conflicts']['blocks'] and report['new_classes'] == ['rabbit']


def test_merge_external_remaps_ids_and_appends_classes(tmp_path):
    project = make_project(tmp_path / 'proj')
    add_project_sample(project, 'p1', b'p1-blob', cls_ids=(1,))
    root = tmp_path / 'ext'
    add_ext_sample(root, 'train', 'x1', b'x1-blob', ['0 .5 .5 .2 .2'])  # dog -> id 0
    add_ext_sample(root, 'val', 'x2', b'x2-blob', ['1 .5 .5 .2 .2'])    # rabbit -> id 1
    set_ext_names(root, ['dog', 'rabbit'])
    store = DatasetStore(project)
    result = merge(store, dict(sources=[dict(kind='project'),
                                        dict(kind='external_yolo', path=str(root))],
                               accept_new_classes=True))
    assert result['new_classes'] == ['rabbit']
    assert project.labels.classes == ['cat', 'dog', 'rabbit']
    folder = store.versions / result['version']
    assert (folder / 'dataset.yaml').is_file() and store.active() == result['version']
    manifest = read_manifest(folder)
    by_split = {row['name']: row['split'] for row in manifest['images']}
    # 重划语义：外部样本存放在哪一档由比例与种子决定，不再继承来源目录；此处只断言重映射结果。
    x1 = (folder / 'labels' / by_split['x1.png'] / 'x1.txt').read_text(encoding='utf-8').splitlines()
    x2 = (folder / 'labels' / by_split['x2.png'] / 'x2.txt').read_text(encoding='utf-8').splitlines()
    assert x1[0].split()[0] == '1' and x2[0].split()[0] == '2'
    manifest = read_manifest(folder)
    assert manifest['names'] == ['cat', 'dog', 'rabbit']
    assert any(m['kind'] == 'external_yolo' for m in manifest['merges'])


def test_all_sources_resplit_and_declared_splits_are_discarded(tmp_path):
    """统一重划：所有来源（含声明过 test 的外部目录）原有划分作废，按比例+种子重分。"""
    project = make_project(tmp_path / 'proj')
    for i in range(12):
        add_project_sample(project, f'local{i:02d}', f'local-{i}'.encode(), cls_ids=(0,))
    external = tmp_path / 'external'
    set_ext_names(external, ['cat', 'dog'])
    add_ext_sample(external, 'test', 'heldout', b'external-test', ['0 .1 .1 .2 .2'])
    add_ext_sample(external, None, 'unassigned', b'external-unassigned', ['1 .1 .1 .2 .2'])
    store = DatasetStore(project)
    spec = dict(sources=[dict(kind='project'), dict(kind='external_yolo', path=str(external))],
                ratios=[.7, .2, .1], accept_new_classes=True)
    report = preview(store, spec)
    result = merge(store, spec)
    manifest = read_manifest(store.versions / result['version'])
    by_split = {row['name']: row['split'] for row in manifest['images']}
    assert set(result['by_split']) == {'train', 'val', 'test'}
    assert sum(result['by_split'].values()) == 14
    assert all(split in ('train', 'val', 'test') for split in by_split.values())
    assert report['estimate']['by_split'] == result['by_split']
    for row in manifest['images']:
        split = row['split']
        assert (store.versions / result['version'] / 'images' / split / row['name']).is_file()
        assert (store.versions / result['version'] / 'labels' / split / (Path(row['name']).stem + '.txt')).is_file()


def test_merge_requires_nonzero_train_or_validation_ratio(tmp_path):
    project = make_project(tmp_path / 'proj')
    add_project_sample(project, 'local', b'local', cls_ids=(0,))
    with pytest.raises(ValueError, match='训练集与验证集比例'):
        preview(DatasetStore(project), dict(sources=[dict(kind='project')], ratios=[0, 0, 1]))


def test_missing_external_label_included_as_negative_sample(tmp_path):
    """无标签图片收录为空标注负样本；预览与提交一致展示。"""
    project = make_project(tmp_path / 'proj')
    add_project_sample(project, 'p1', b'p1-blob', cls_ids=(0,))
    root = tmp_path / 'ext'
    add_ext_sample(root, 'train', 'x1', b'x1-blob', ['0 .5 .5 .2 .2'])
    set_ext_names(root, ['dog'])
    (root / 'images' / 'train' / 'bg.png').write_bytes(b'negative-blob-no-label')
    store = DatasetStore(project)
    spec = dict(sources=[dict(kind='project'), dict(kind='external_yolo', path=str(root))],
                accept_new_classes=True)
    report = preview(store, spec)
    ext = next(s for s in report['per_source'] if s['kind'] == 'external_yolo')
    assert ext['samples'] == 2 and ext['empty_labels'] == 1 and not ext.get('skipped')
    result = merge(store, spec)
    folder = store.versions / result['version']
    rows = read_manifest(folder)['images']
    bg = next(r for r in rows if r['name'] == 'bg.png')
    assert bg['classes'] == [] and bg['label_sha256'] == hashlib.sha256(b'').hexdigest()
    bg_label = folder / 'labels' / bg['split'] / 'bg.txt'
    assert bg_label.is_file() and bg_label.read_text(encoding='utf-8') == ''
    assert result['total'] == 3


def test_blacklist_accepts_yaml_path_in_preview(tmp_path):
    """黑名单统一在 merge 模块解析：路径在预览阶段同样命中（与提交一致）。"""
    project = make_project(tmp_path / 'proj')
    for i in range(3):
        add_project_sample(project, f'ok{i}', f'ok-{i}'.encode(), cls_ids=(0,))
    store = DatasetStore(project)
    version = store.create((.7, .2, .1), 42)
    spec = dict(sources=[dict(kind='version', version=version)],
                blacklist=[str(store.versions / version / 'dataset.yaml')])
    report = preview(store, spec)
    assert report['blacklist']['hits'] == 2  # yaml 的 train+val 两个目录都被吸收


def test_stem_clash_blocks_merge(tmp_path):
    project = make_project(tmp_path / 'proj')
    add_project_sample(project, 'dup', b'content-a', cls_ids=(0,))
    root = tmp_path / 'ext'
    add_ext_sample(root, 'train', 'dup', b'content-b totally different', ['1 .5 .5 .2 .2'])
    set_ext_names(root, ['dog', 'rabbit'])
    store = DatasetStore(project)
    with pytest.raises(ValueError) as exc:
        merge(store, dict(sources=[dict(kind='project'),
                                   dict(kind='external_yolo', path=str(root))],
                          accept_new_classes=True))
    assert '[STEM_CLASH]' in str(exc.value)
    assert not list((store.root / 'versions').glob('[!.]*'))


def test_content_dedupe_across_sources(tmp_path):
    project = make_project(tmp_path / 'proj')
    add_project_sample(project, 'same', b'identical-bytes', label_text='0 .5 .5 .2 .2\n')
    root = tmp_path / 'ext'
    add_ext_sample(root, 'train', 'same', b'identical-bytes', ['0 .5 .5 .2 .2'])
    set_ext_names(root, ['cat'])
    store = DatasetStore(project)
    result = merge(store, dict(sources=[dict(kind='project'),
                                        dict(kind='external_yolo', path=str(root))]))
    assert result['duplicates'] == 1 and result['total'] == 1
    ext = [s for s in list_sources(store)['sources'] if s['kind'] == 'external_yolo']
    assert ext and ext[0]['samples'] == 1


def test_blacklist_pins_golden_group_to_val(tmp_path):
    project = make_project(tmp_path / 'proj')
    add_project_sample(project, 'batch1_frame_000001_f1_t90', b'frame-1', cls_ids=(0,))
    add_project_sample(project, 'batch1_frame_000002_f1_t90', b'frame-2', cls_ids=(0,))
    add_project_sample(project, 'batch2_frame_000001_f1_t90', b'frame-3', cls_ids=(0,))
    store = DatasetStore(project)
    version = store.create((.7, .2, .1), 42)
    manifest = read_manifest(store.versions / version)
    target = next(r for r in manifest['images'] if r['name'] == 'batch1_frame_000001_f1_t90.png')
    spec = dict(sources=[dict(kind='version', version=version)], blacklist=[target['sha256']])
    report = preview(store, spec)
    assert report['blacklist']['hits'] == 1 and report['blacklist']['pinned_samples'] == 2
    assert any(w['code'] == 'GOLDEN_GROUP' for w in report['conflicts']['warnings'])
    result = merge(store, spec)
    merged = read_manifest(store.versions / result['version'])
    assert split_of(merged, 'batch1_frame_000001_f1_t90.png') == 'val'
    assert split_of(merged, 'batch1_frame_000002_f1_t90.png') == 'val'


def test_case_conflict_requires_hard_resolution(tmp_path):
    project = make_project(tmp_path / 'proj')
    first, second = tmp_path / 'e1', tmp_path / 'e2'
    add_ext_sample(first, 'train', 'a', b'a-bytes', ['0 .5 .5 .2 .2'])
    set_ext_names(first, ['Dog'])
    add_ext_sample(second, 'train', 'b', b'b-bytes', ['0 .5 .5 .2 .2'])
    set_ext_names(second, ['dog'])
    store = DatasetStore(project)
    spec = dict(sources=[dict(kind='external_yolo', path=str(first)),
                         dict(kind='external_yolo', path=str(second))])
    codes = {b['code'] for b in preview(store, spec)['conflicts']['blocks']}
    assert 'CLASS_UNRESOLVED' in codes
    spec['resolutions'] = {'Dog': 'dog'}
    result = merge(store, spec)
    assert result['new_classes'] == [] and project.labels.classes == ['cat', 'dog']
    folder = store.versions / result['version']
    ids = sorted({line.split()[0] for p in folder.rglob('labels/*/a.txt')
                  for line in p.read_text(encoding='utf-8').splitlines() if line.strip()})
    assert ids == ['1']  # 两个来源的 Dog/dog 均映射到既有 dog=id1


def test_keep_segment_toggle(tmp_path):
    project = make_project(tmp_path / 'proj')
    row = '0 .1 .1 .2 .2 .01 .01 .02 .02 .03 .03 .04 .04 .0 .0'
    root = tmp_path / 'ext'
    add_ext_sample(root, 'train', 'seg', b'seg-blob', ['0 .5 .5 .2 .2', row])
    set_ext_names(root, ['dog'])
    store = DatasetStore(project)
    result = merge(store, dict(sources=[dict(kind='external_yolo', path=str(root))],
                               keep_segment=False))
    text = (store.versions / result['version'] / 'labels' / 'train' / 'seg.txt').read_text(encoding='utf-8')
    assert len(text.splitlines()) == 1 and text.startswith('1 ')

    add_ext_sample(tmp_path / 'ext2', 'train', 's2', b's2-blob', [row])
    set_ext_names(tmp_path / 'ext2', ['dog'])
    result2 = merge(store, dict(sources=[dict(kind='external_yolo', path=str(tmp_path / 'ext2'))],
                                keep_segment=True))
    kept = (store.versions / result2['version'] / 'labels' / 'train' / 's2.txt').read_text(encoding='utf-8')
    assert len(kept.splitlines()) == 1 and kept.split()[0] == '1' and len(kept.split()) > 13


def test_cross_project_version_is_read_only_source(tmp_path):
    host = make_project(tmp_path / 'host')
    add_project_sample(host, 'h1', b'host-blob', cls_ids=(0,))
    other = make_project(tmp_path / 'guest')
    add_project_sample(other, 'g1', b'guest-blob', cls_ids=(1,))
    guest_version = DatasetStore(other).create((.7, .2, .1), 42)
    before = sorted(str(p) for p in (tmp_path / 'guest').rglob('*'))
    store = DatasetStore(host)
    result = merge(store, dict(sources=[dict(kind='cross_project', path=str(other.root))]))
    assert result['total'] == 1
    folder = store.versions / result['version']
    guest_src = tmp_path / 'guest' / 'guest_dataset' / 'versions' / guest_version / 'labels'
    guest_file = next(p for p in guest_src.rglob('g1.txt'))
    copied = next(folder.rglob('labels/*/g1.txt'))
    assert digest(copied) == digest(guest_file)
    assert sorted(str(p) for p in (tmp_path / 'guest').rglob('*')) == before  # guest 目录零触碰


def test_pending_and_rejected_are_excluded(tmp_path):
    project = make_project(tmp_path / 'proj')
    add_project_sample(project, 'ok', b'ok-bytes', cls_ids=(0,))
    add_project_sample(project, 'nope', b'nope-bytes', cls_ids=(0,))
    from studio.review import ReviewStore
    ReviewStore(project).reject(['nope.png'], '测试驳回')
    report = preview(DatasetStore(project), dict(sources=[dict(kind='project')]))
    assert report['estimate']['total'] == 1
    assert report['per_source'][0]['samples'] == 1


def test_alias_memory_reuses_prev_resolutions(tmp_path):
    project = make_project(tmp_path / 'proj')
    root = tmp_path / 'ext'
    add_ext_sample(root, 'train', 'b1', b'b1-blob', ['0 .5 .5 .2 .2'])
    set_ext_names(root, ['bunny'])
    store = DatasetStore(project)
    merge(store, dict(sources=[dict(kind='external_yolo', path=str(root))],
                      accept_new_classes=True, resolutions={'bunny': 'rabbit'}))
    assert project.labels.classes == ['cat', 'dog', 'rabbit']
    alias = json.loads((store.root / 'classes_alias.json').read_text(encoding='utf-8'))
    assert alias.get('bunny') == 'rabbit'
    root2 = tmp_path / 'ext2'
    add_ext_sample(root2, 'train', 'b2', b'b2-blob', ['0 .5 .5 .2 .2'])
    set_ext_names(root2, ['bunny'])
    report = preview(store, dict(sources=[dict(kind='external_yolo', path=str(root2))]))
    row = next(r for r in report['class_rows'] if r['name'] == 'bunny')
    assert row['status'] == 'alias' and report['new_classes'] == []


def test_content_identical_with_same_label_deduped_across_names(tmp_path):
    project = make_project(tmp_path / "proj")
    root = tmp_path / "ext"
    add_ext_sample(root, "train", "a1", b"same-blob", ["0 .5 .5 .2 .2"])
    add_ext_sample(root, "train", "b2", b"same-blob", ["0 .5 .5 .2 .2"])  # 同内容同标签、不同文件名
    add_ext_sample(root, "train", "c3", b"other-blob", ["0 .5 .5 .2 .2"])
    set_ext_names(root, ["dog"])
    store = DatasetStore(project)
    spec = dict(sources=[dict(kind="external_yolo", path=str(root))])
    report = preview(store, spec)
    assert report["dedupe"]["duplicates"] == 1 and not report["conflicts"]["blocks"]
    result = merge(store, spec)
    assert result["duplicates"] == 1 and result["total"] == 2
