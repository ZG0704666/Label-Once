"""Regression tests for the training path: group-aware splits, preset round-trip, optimizer wiring."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from studio.config import ADVANCED, AUGMENTS, augmentation_values
from studio.dataset import DatasetStore
from studio.domain import Box, Project
from studio.service import StudioService
from studio.worker import Worker


def video_project(path, videos=('video_aaa', 'video_bbb', 'video_ccc'), frames=6):
    """A project whose samples come from several videos, so frames of one video are near-duplicates."""
    project = Project(path)
    project.labels.set_classes(['目标'])
    for video in videos:
        for index in range(frames):
            name = f'{video}_frame_{index:06d}_f{index}_t0.jpg'
            Image.new('RGB', (64, 64), (index * 10, 30, 80)).save(project.images / name)
            project.labels.save(Path(name).stem, [Box(0, .1, .2, .8, .9, 'AI')])
    return project


def group_splits(manifest):
    splits = {}
    for record in manifest['images']:
        splits.setdefault(record['group'], set()).add(record['split'])
    return splits


def test_video_frames_never_straddle_splits(tmp_path):
    project = video_project(tmp_path / '项目')
    store = DatasetStore(project)
    version = store.create(ratios=(.7, .2, .1), seed=7)
    manifest = store.manifest(version)
    splits = group_splits(manifest)
    assert len(splits) == 3, '三个视频应形成三个分组'
    for group, assigned in splits.items():
        assert len(assigned) == 1, f'分组 {group} 被拆到了多个集合：{assigned}'
    assert manifest['leaked_groups'] == []
    assert set(manifest['groups']) == set(splits)


def test_group_split_is_deterministic(tmp_path):
    project = video_project(tmp_path / '项目')
    store = DatasetStore(project)
    first = store.manifest(store.create(ratios=(.7, .2, .1), seed=11))
    second = store.manifest(store.create(ratios=(.7, .2, .1), seed=11))
    assert [(r['name'], r['split']) for r in first['images']] == [(r['name'], r['split']) for r in second['images']]


def test_import_batch_stays_in_one_split(tmp_path):
    project = Project(tmp_path / '项目')
    project.labels.set_classes(['目标'])
    for index in range(10):
        Image.new('RGB', (32, 32)).save(project.images / f'{index}.png')
        project.labels.save(str(index), [Box(0, .1, .2, .8, .9, 'AI')])
    from studio.review import ReviewStore
    review = ReviewStore(project)
    records = review.records()
    for index in range(10):
        records[f'{index}.png'] = {'batch': 'images_one_session'}
    review.write(records)
    review.confirm([f'{index}.png' for index in range(10)])
    dataset = DatasetStore(project)
    manifest = dataset.manifest(dataset.create(ratios=(.7, .2, .1), seed=5))
    splits = group_splits(manifest)
    assert len(splits) == 1, '同一次导入的图片必须整体落在同一个集合'
    assert manifest['leaked_groups'] == []


def test_augmentation_values_expands_the_legacy_colour_switch():
    assert augmentation_values({'mosaic': False}) == {'mosaic': 0}
    assert augmentation_values({'hsv': False}) == {'hsv_h': 0, 'hsv_s': 0, 'hsv_v': 0}
    assert augmentation_values({'hsv': True}) == {'hsv_h': AUGMENTS['hsv_h'],
                                                 'hsv_s': AUGMENTS['hsv_s'],
                                                 'hsv_v': AUGMENTS['hsv_v']}
    assert augmentation_values({'unknown': True}) == {}


def test_legacy_colour_switch_survives_the_preset_round_trip(tmp_path):
    service = StudioService()
    try:
        service.dispatch('project.open', {'path': str(tmp_path / '中文 空格项目')})
        service.dispatch('classes.save', {'names': ['目标']})
        service.project.config.mkdir(parents=True, exist_ok=True)
        (service.project.config / 'train_preset.json').write_text(json.dumps(
            dict(epochs=3, batch=2, lr=.002, imgsz=320,
                 augmentation={'mosaic': False, 'hsv': False},
                 advanced={'params': {'patience': 7}}), ensure_ascii=False), encoding='utf-8')
        values = service.dispatch('preset.get', {})
        assert values['mosaic'] == 0
        assert values['hsv_h'] == 0 and values['hsv_s'] == 0 and values['hsv_v'] == 0
        assert values['patience'] == 7 and values['epochs'] == 3 and values['lr0'] == .002
    finally:
        service.close()


def test_optimizer_is_pinned_instead_of_auto():
    assert ADVANCED['optimizer'] == 'AdamW', 'auto 会在大数据集上静默切换优化器并忽略学习率'
    assert 'nbs' in ADVANCED, '名义 batch size 会影响梯度累积与迭代次数估算'


class FakeYOLO:
    """Stands in for ultralytics.YOLO and records what the worker passes to train()."""

    captured = None
    instances = []

    def __init__(self, path):
        self.path = path
        self.trainer = None
        FakeYOLO.instances.append(self)

    def add_callback(self, event, callback):
        pass

    def train(self, **params):
        FakeYOLO.captured = params
        save_dir = Path(params.get('project', '.')) / 'train'
        (save_dir / 'weights').mkdir(parents=True, exist_ok=True)
        (save_dir / 'weights' / 'best.pt').write_bytes(b'fake')
        self.trainer = SimpleNamespace(save_dir=save_dir, metrics={'metrics/mAP50(B)': .5},
                                        epochs=1, epoch=0)


def install_fake_ultralytics(monkeypatch):
    """Replace ultralytics without importing it, so the suite runs without torch."""
    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=FakeYOLO))
    FakeYOLO.captured = None


def test_training_parameters_reach_model_train(tmp_path, monkeypatch):
    install_fake_ultralytics(monkeypatch)
    project = video_project(tmp_path / '项目')
    store = DatasetStore(project)
    version = store.create(ratios=(.7, .2, .1), seed=1)
    task = dict(kind='train', project=str(project.root), run=str(project.new_run('train')),
                model='yolo11n.pt', dataset=str(store.yaml_path(version)),
                dataset_version=version,
                params=dict(ADVANCED, **{k: AUGMENTS[k] for k in AUGMENTS},
                            epochs=2, batch=2, lr0=.001, imgsz=64, device='cpu'))
    Worker(task).train()
    captured = FakeYOLO.captured
    assert captured['optimizer'] == 'AdamW'
    assert captured['lr0'] == .001
    assert captured['mosaic'] == AUGMENTS['mosaic']
    assert captured['hsv_h'] == AUGMENTS['hsv_h']
    assert captured['fliplr'] == AUGMENTS['fliplr']
    assert captured['data'] == task['dataset']
    assert captured['epochs'] == 2 and captured['batch'] == 2


def test_resume_uses_the_checkpoint_and_keeps_the_original_dataset(tmp_path, monkeypatch):
    install_fake_ultralytics(monkeypatch)
    project = video_project(tmp_path / '项目')
    store = DatasetStore(project)
    version = store.create(ratios=(.7, .2, .1), seed=1)
    run = project.new_run('train')
    checkpoint = run / 'train' / 'weights' / 'last.pt'
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(b'fake')
    task = dict(kind='train', project=str(project.root), run=str(run), model='yolo11n.pt',
                dataset=str(store.yaml_path(version)), dataset_version=version,
                resume=str(checkpoint), params=dict(epochs=2, batch=2))
    Worker(task).train()
    captured = FakeYOLO.captured
    assert captured['resume'] is True
    assert captured['data'] == task['dataset']
    assert 'project' not in captured, '续训必须沿用检查点里的输出目录，否则产物会散落在别处'


def test_resume_rejects_a_checkpoint_outside_the_project(tmp_path):
    service = StudioService()
    try:
        service.dispatch('project.open', {'path': str(tmp_path / '中文 空格项目')})
        outside = tmp_path / 'other' / 'train' / 'weights' / 'last.pt'
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(b'fake')
        with pytest.raises(ValueError, match='只能续训当前项目'):
            service.dispatch('task.start', {'kind': 'train', 'options': {'resume': str(outside)}})
    finally:
        service.close()
