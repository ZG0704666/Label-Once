"""Tests for the release gate: class alignment, baseline compatibility, leakage, label formats."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

GATE_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'check_release_gate.py'


def load_gate():
    spec = importlib.util.spec_from_file_location('check_release_gate', GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_gate()


def write_dataset(root: Path, names, images=('a.jpg', 'b.jpg'), labels=None, split='val',
                 color=(200, 210, 220), train_spec=None):
    (root / 'images' / split).mkdir(parents=True, exist_ok=True)
    (root / 'labels' / split).mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(images):
        # Distinct content per file so that content hashes are meaningful.
        Image.new('RGB', (32, 32), (color[0], color[1], color[2] + index)).save(root / 'images' / split / name)
        body = labels[index] if labels else f'0 0.5 0.5 0.2 0.2\n'
        (root / 'labels' / split / f'{Path(name).stem}.txt').write_text(body, encoding='utf-8')
    data = dict(path=str(root), train=train_spec or f'images/{split}', val=f'images/{split}',
                nc=len(names), names={index: name for index, name in enumerate(names)})
    (root / 'dataset.yaml').write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                                       encoding='utf-8')
    return root / 'dataset.yaml'


def make_project(tmp_path, names, golden_images=('a.jpg', 'b.jpg')):
    project = tmp_path / '项目'
    (project / 'Model').mkdir(parents=True)
    version = project / '项目_dataset' / 'versions' / 'v1'
    version.mkdir(parents=True)
    write_dataset(version, names, images=golden_images, color=(10, 20, 30), train_spec='images/train')
    (version / 'images' / 'train').mkdir(parents=True, exist_ok=True)
    (version / 'labels' / 'train').mkdir(parents=True, exist_ok=True)
    (project / '项目_dataset' / 'active.json').write_text(
        json.dumps({'version': 'v1'}), encoding='utf-8')
    return project


def run_gate(monkeypatch, argv, ap50=None, map50=.8, names=None, baseline_names=None):
    monkeypatch.setattr(sys, 'argv', ['check_release_gate.py'] + argv)
    calls = {}

    def fake_evaluate(model_path, staged_yaml, scratch):
        calls.setdefault('evaluated', []).append(Path(model_path).name)
        values = ap50 if ap50 is not None else [.9] * 10
        if 'old' in Path(model_path).name and baseline_names is not None:
            # A baseline with fewer classes reports fewer per-class values.
            return values[:len(baseline_names)], map50
        return values, map50

    def fake_model_names(model_path):
        if 'old' in Path(model_path).name:
            return baseline_names if baseline_names is not None else names
        return names

    monkeypatch.setattr(gate, 'evaluate', fake_evaluate)
    monkeypatch.setattr(gate, 'model_names', fake_model_names)
    return gate.main(), calls


def test_names_of_accepts_dict_and_list(tmp_path):
    path = tmp_path / 'd.yaml'
    path.write_text(yaml.safe_dump(dict(names={0: 'b', 1: 'a'})), encoding='utf-8')
    assert gate.names_of(gate.load_dataset_yaml(path)) == ['b', 'a']
    path.write_text(yaml.safe_dump(dict(names=['x', 'y'])), encoding='utf-8')
    assert gate.names_of(gate.load_dataset_yaml(path)) == ['x', 'y']


def test_label_formats_separates_boxes_from_polygons(tmp_path):
    root = tmp_path / 'labels' / 'val'
    root.mkdir(parents=True)
    (root / 'box.txt').write_text('0 0.5 0.5 0.2 0.2\n', encoding='utf-8')
    (root / 'poly.txt').write_text('1 0.1 0.1 0.9 0.1 0.9 0.9\n', encoding='utf-8')
    detect, segment = gate.label_formats(root)
    assert (detect, segment) == (1, 1)


def test_gate_passes_when_alignment_holds_and_no_leak(tmp_path, monkeypatch):
    names = ['目标甲', '目标乙']
    project = make_project(tmp_path, names)
    golden = write_dataset(tmp_path / 'golden', names)
    model = project / 'Model' / 'new.pt'
    model.write_bytes(b'fake')
    code, _ = run_gate(monkeypatch, ['--project', str(project), '--model', str(model),
                                     '--golden', str(golden)],
                       ap50=[.9, .8], map50=.85, names=names)
    assert code == 0


def test_gate_blocks_when_the_class_order_differs(tmp_path, monkeypatch):
    project = make_project(tmp_path, ['目标甲', '目标乙'])
    golden = write_dataset(tmp_path / 'golden', ['目标乙', '目标甲'])
    model = project / 'Model' / 'new.pt'
    model.write_bytes(b'fake')
    code, _ = run_gate(monkeypatch, ['--project', str(project), '--model', str(model),
                                     '--golden', str(golden)],
                       ap50=[.9, .8], map50=.85, names=['目标甲', '目标乙'])
    assert code == 1
    report = json.loads((project / 'Model' / 'release_gate.json').read_text(encoding='utf-8'))
    assert not report['class_aligned']
    assert any('类别顺序' in reason for reason in report['failures'])


def test_gate_blocks_when_the_baseline_class_table_is_incompatible(tmp_path, monkeypatch):
    names = ['a', 'b']
    project = make_project(tmp_path, names)
    golden = write_dataset(tmp_path / 'golden', names)
    model = project / 'Model' / 'new.pt'
    model.write_bytes(b'fake')
    baseline = project / 'Model' / 'old.pt'
    baseline.write_bytes(b'fake')
    code, _ = run_gate(monkeypatch, ['--project', str(project), '--model', str(model),
                                     '--golden', str(golden), '--baseline', str(baseline)],
                       ap50=[.9, .8], map50=.85, names=names,
                       baseline_names=['b', 'a'])
    assert code == 1
    report = json.loads((project / 'Model' / 'release_gate.json').read_text(encoding='utf-8'))
    assert any('基线模型类别表' in reason for reason in report['failures'])


def test_gate_accepts_a_baseline_that_is_a_prefix_of_the_golden_classes(tmp_path, monkeypatch):
    names = ['a', 'b', 'c']
    project = make_project(tmp_path, names)
    golden = write_dataset(tmp_path / 'golden', names)
    model = project / 'Model' / 'new.pt'
    model.write_bytes(b'fake')
    baseline = project / 'Model' / 'old.pt'
    baseline.write_bytes(b'fake')
    code, calls = run_gate(monkeypatch, ['--project', str(project), '--model', str(model),
                                         '--golden', str(golden), '--baseline', str(baseline)],
                           ap50=[.9, .8, .7], map50=.85, names=names, baseline_names=['a', 'b'])
    assert code == 0
    assert 'old.pt' in calls['evaluated']
    report = json.loads((project / 'Model' / 'release_gate.json').read_text(encoding='utf-8'))
    added = [row for row in report['per_class'] if row.get('note') == '新增类别']
    assert [row['cls'] for row in added] == ['c']


def test_gate_blocks_when_the_golden_images_appear_in_the_training_split(tmp_path, monkeypatch):
    names = ['a']
    project = make_project(tmp_path, names)
    golden = write_dataset(tmp_path / 'golden', names)
    version = project / '项目_dataset' / 'versions' / 'v1'
    # The very same bytes as a golden image, but filed under the training split.
    shutil.copy2(tmp_path / 'golden' / 'images' / 'val' / 'a.jpg',
                 version / 'images' / 'train' / 'a.jpg')
    model = project / 'Model' / 'new.pt'
    model.write_bytes(b'fake')
    code, _ = run_gate(monkeypatch, ['--project', str(project), '--model', str(model),
                                     '--golden', str(golden)],
                       ap50=[.9], map50=.85, names=names)
    assert code == 1
    report = json.loads((project / 'Model' / 'release_gate.json').read_text(encoding='utf-8'))
    assert report['leakage'] >= 1


def test_gate_blocks_when_the_overall_map50_is_below_the_floor(tmp_path, monkeypatch):
    names = ['a']
    project = make_project(tmp_path, names)
    golden = write_dataset(tmp_path / 'golden', names)
    model = project / 'Model' / 'new.pt'
    model.write_bytes(b'fake')
    code, _ = run_gate(monkeypatch, ['--project', str(project), '--model', str(model),
                                     '--golden', str(golden)],
                       ap50=[.2], map50=.2, names=names)
    assert code == 1
    report = json.loads((project / 'Model' / 'release_gate.json').read_text(encoding='utf-8'))
    assert any('mAP50' in reason for reason in report['failures'])


def test_gate_warns_when_the_baseline_is_missing(tmp_path, monkeypatch):
    names = ['a']
    project = make_project(tmp_path, names)
    golden = write_dataset(tmp_path / 'golden', names)
    model = project / 'Model' / 'new.pt'
    model.write_bytes(b'fake')
    code, _ = run_gate(monkeypatch, ['--project', str(project), '--model', str(model),
                                     '--golden', str(golden)],
                       ap50=[.9], map50=.85, names=names)
    assert code == 0
    report = json.loads((project / 'Model' / 'release_gate.json').read_text(encoding='utf-8'))
    assert all(row['old_ap50'] is None for row in report['per_class'])
