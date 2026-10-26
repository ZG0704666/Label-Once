"""发布门禁：在冻结基准集上评估模型，类别顺序、模型类别表、精度与泄漏四项都必须通过。

设计要点
--------
1. 基准集只读。Ultralytics 扫描标签目录时会写 <labels>.cache，直接指向基准集会污染冻结资产；
   这里把标签复制到临时目录、图片用目录联接挂载，评估产物也一并落到临时目录。
2. 类别顺序必须逐项相等。训练用数据集的 names 与基准集的 names 顺序不同，per-class AP50
   就会张冠李戴，门禁形同虚设；这里直接判定失败并打印两边的对照。
3. 基线模型的类别表必须是基准集类别表的前缀。新增类别是允许的，但只要顺序或内容变了，
   旧模型的输出索引就对不上，逐类跌幅毫无意义。
4. 与上一版模型逐类对比 AP50 跌幅，而不是只看一个总分。
5. 基准集图片不得出现在训练集里，否则门禁量的是被训练过的数据。
6. 量化模型（ONNX/INT8）可一并送检，与浮点模型的掉点也受同一上限约束。

用法
----
python scripts/check_release_gate.py \
    --project "F:/Aries AI/项目" \
    --model "F:/Aries AI/项目/Model/train_xxx.pt" \
    --golden "F:/Aries AI/Aries Glass/golden/v1.1.0/dataset.yaml" \
    --baseline "F:/Aries AI/项目/Model/train_previous.pt" \
    --quantized "F:/Aries AI/项目/Model/best_int8.onnx"

退出码 0 = 通过，1 = 未通过，可直接接入 CI。
训练页的「发布门禁」按钮走同一逻辑：worker.gate -> run_gate(...) -> Model/release_gate.json。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

# Windows 控制台默认是遗留代码页，渲染不了通过/失败标记。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp'}


def load_dataset_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding='utf-8-sig')) or {}


def names_of(data: dict) -> list[str]:
    names = data.get('names')
    if names is None:
        raise ValueError('dataset.yaml 缺少 names 字段')
    if isinstance(names, dict):
        return [str(value) for _, value in sorted(names.items(), key=lambda item: int(item[0]))]
    return [str(value) for value in names]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def image_hashes(folder: Path) -> dict[str, list[str]]:
    """Map each distinct image content to the file names that carry it."""
    hashes: dict[str, list[str]] = {}
    if not folder.is_dir():
        return hashes
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in IMAGE_SUFFIXES:
            hashes.setdefault(digest(path), []).append(path.name)
    return hashes


def materialize_images(source: Path, target: Path) -> None:
    """Copy an image folder into the scratch area.

    A junction or symlink is not enough: Ultralytics resolves the image path with
    Path.resolve(), which on Windows follows a junction back to the real folder, and the label
    cache would then be written next to the frozen golden labels. Real copies keep the golden set
    untouched; hard links are used when both live on the same volume.
    """
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        destination = target / path.name
        if destination.exists():
            continue  # train and val often point at the same folder
        try:
            os.link(path, destination)
        except OSError:
            shutil.copy2(path, destination)


def stage_dataset(golden_yaml: Path, target: Path) -> Path:
    """Mirror the golden dataset into a scratch directory so nothing is written back to it."""
    data = load_dataset_yaml(golden_yaml)
    root = Path(str(data.get('path', golden_yaml.parent))).resolve()
    names = names_of(data)
    specs = {}
    for key in ('train', 'val'):
        spec = str(data.get(key, key))
        specs[key] = spec
        image_source = root / spec
        label_source = root / spec.replace('images', 'labels', 1)
        if not image_source.is_dir():
            continue
        materialize_images(image_source, target / spec)
        label_target = target / spec.replace('images', 'labels', 1)
        label_target.mkdir(parents=True, exist_ok=True)
        if label_source.is_dir():
            for label in label_source.glob('*.txt'):
                shutil.copy2(label, label_target / label.name)
    staged = dict(path=str(target), train=specs['train'], val=specs['val'],
                  nc=len(names), names={index: name for index, name in enumerate(names)})
    staged_yaml = target / 'dataset.yaml'
    staged_yaml.write_text(yaml.safe_dump(staged, allow_unicode=True, sort_keys=False), encoding='utf-8')
    return staged_yaml


def label_formats(label_dir: Path) -> tuple[int, int]:
    """Count detect-style and segment-style label files in the golden set."""
    detect = segment = 0
    if not label_dir.is_dir():
        return detect, segment
    for path in label_dir.glob('*.txt'):
        fields = 0
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.strip():
                fields = len(line.split())
                break
        if fields == 5:
            detect += 1
        elif fields > 5:
            segment += 1
    return detect, segment


def model_names(model_path: Path) -> list[str]:
    from ultralytics import YOLO
    model = YOLO(str(model_path))
    names = getattr(model.model, 'names', {}) or {}
    if isinstance(names, dict):
        return [str(value) for _, value in sorted(names.items(), key=lambda item: int(item[0]))]
    return [str(value) for value in names]


def evaluate(model_path: Path, staged_yaml: Path, scratch: Path):
    from ultralytics import YOLO
    result = YOLO(str(model_path)).val(data=str(staged_yaml), conf=.25, verbose=False,
                                       project=str(scratch / 'runs'), name='val', exist_ok=True)
    return [float(value) for value in result.box.ap50], float(result.box.map50)


def resolve_train_split(dataset_yaml: Path) -> Path:
    data = load_dataset_yaml(dataset_yaml)
    root = Path(str(data.get('path', dataset_yaml.parent))).resolve()
    return root / str(data.get('train', 'images/train'))


def run_gate(project: Path, model: Path, golden: Path, baseline: Path | None = None,
             quantized: Path | None = None, dataset_version: str | None = None,
             map50_min: float = .50, ap50_drop_max: float = .03, quant_drop_max: float = .02,
             strict_labels: bool = False, report_dir: Path | None = None,
             log=print, check=lambda: None) -> dict:
    """Run every gate check and return the summary (also written to Model/release_gate.json)."""
    project = Path(project)
    model, golden = Path(model), Path(golden)
    if not project.is_dir():
        raise ValueError(f'项目目录不存在: {project}')
    if not model.is_file():
        raise ValueError(f'模型不存在: {model}')
    if not golden.is_file():
        raise ValueError(f'基准集 dataset.yaml 不存在: {golden}')

    golden_data = load_dataset_yaml(golden)
    golden_names = names_of(golden_data)
    golden_root = Path(str(golden_data.get('path', golden.parent))).resolve()
    report_dir = Path(report_dir).resolve() if report_dir else project / 'Model'
    report_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    warnings = []

    # 训练用数据集的类别表
    dataset_yaml = None
    version = dataset_version
    if not version:
        active = project / (project.name + '_dataset') / 'active.json'
        if active.is_file():
            version = json.loads(active.read_text(encoding='utf-8-sig')).get('version')
    if version:
        candidate = project / (project.name + '_dataset') / 'versions' / version / 'dataset.yaml'
        if candidate.is_file():
            dataset_yaml = candidate
    if dataset_yaml is None:
        candidate = project / (project.name + '_dataset') / 'dataset.yaml'
        if candidate.is_file():
            dataset_yaml = candidate
    if dataset_yaml is None:
        raise ValueError('找不到训练用数据集的 dataset.yaml，无法核对类别顺序')
    train_names = names_of(load_dataset_yaml(dataset_yaml))

    with tempfile.TemporaryDirectory(prefix='labelonce_gate_') as scratch_name:
        scratch = Path(scratch_name)
        staged_yaml = stage_dataset(golden, scratch / 'golden')
        check()

        log('[1/5] 类别顺序核对')
        log(f'  训练集 ({dataset_yaml.name}): {train_names}')
        log(f'  基准集: {golden_names}')
        if train_names != golden_names:
            log('  ❌ 类别顺序不一致，逐类 AP50 会张冠李戴，门禁无效')
            for index, name in enumerate(golden_names):
                actual = train_names[index] if index < len(train_names) else '<缺失>'
                log(f'      基准集 #{index} = {name!r}，训练集 #{index} = {actual!r}')
            failures.append('类别顺序与基准集不一致')
        else:
            log(f'  ✅ 顺序一致（{len(golden_names)} 类）')
        check()

        log('[2/5] 基准集标签格式')
        detect, segment = label_formats(golden_root / 'labels' / 'val')
        if segment:
            message = f'基准集混用了检测框标签（{detect} 个）与分割多边形标签（{segment} 个），Ultralytics 会丢弃多边形'
            log(f'  ⚠ {message}')
            if strict_labels:
                failures.append(message)
            else:
                warnings.append(message)
        else:
            log(f'  ✅ 全部为检测框标签（{detect} 个）')
        check()

        log('[3/5] 泄漏检查')
        golden_images = image_hashes(golden_root / str(golden_data.get('val', 'images/val')))
        train_split = resolve_train_split(dataset_yaml)
        train_images = image_hashes(train_split)
        overlap = sorted(set(golden_images) & set(train_images))
        golden_count = sum(len(value) for value in golden_images.values())
        train_count = sum(len(value) for value in train_images.values())
        if overlap:
            log(f'  ❌ 基准集有 {len(overlap)} 张图片出现在训练集里：')
            for value in overlap[:10]:
                for name in golden_images[value]:
                    log(f'      {name}')
            failures.append(f'基准集与训练集重叠 {len(overlap)} 张')
        else:
            log(f'  ✅ 基准集 {golden_count} 张与训练集 {train_count} 张无重叠')
        check()

        log('[4/5] 评估新模型')
        candidate_names = model_names(model)
        if candidate_names != golden_names:
            log(f'  ❌ 模型类别表与基准集不一致：模型 {candidate_names}')
            failures.append('模型类别表与基准集不一致')
        check()
        new_ap50, new_map50 = evaluate(model, staged_yaml, scratch)
        old_ap50 = None
        if baseline and Path(baseline).is_file():
            baseline = Path(baseline)
            log(f'  评估基线模型: {baseline.name}')
            old_names = model_names(baseline)
            if old_names != golden_names[:len(old_names)]:
                log(f'  ❌ 基线模型类别表 {old_names}')
                log(f'     不是基准集类别表 {golden_names[:len(old_names)]} 的前缀，逐类跌幅没有意义')
                failures.append('基线模型类别表与基准集不兼容，逐类比较无效')
            else:
                check()
                old_ap50, _ = evaluate(baseline, staged_yaml, scratch)
        else:
            log('  ⚠ 未提供基线模型，跳过逐类跌幅比较')
        check()

        rows = []
        for index, name in enumerate(golden_names):
            current = new_ap50[index] if index < len(new_ap50) else 0.0
            if old_ap50 is None:
                rows.append(dict(cls=name, old_ap50=None, new_ap50=current, drop=None, passed=True))
                continue
            if index >= len(old_ap50):
                rows.append(dict(cls=name, old_ap50=None, new_ap50=current, drop=None, passed=True,
                                 note='新增类别'))
                continue
            previous = old_ap50[index]
            drop = previous - current
            rows.append(dict(cls=name, old_ap50=previous, new_ap50=current, drop=drop,
                             passed=drop <= ap50_drop_max))
        log(f'\n  {"类别":<24}{"旧AP50":>10}{"新AP50":>10}{"跌幅":>10}  门禁')
        log('  ' + '-' * 62)
        for row in rows:
            old_text = 'N/A' if row['old_ap50'] is None else f"{row['old_ap50']:.4f}"
            drop_text = 'N/A' if row['drop'] is None else f"{row['drop']:+.4f}"
            note = f"  ({row['note']})" if row.get('note') else ''
            log(f"  {row['cls']:<24}{old_text:>10}{row['new_ap50']:>10.4f}{drop_text:>10}  "
                f"{'✅' if row['passed'] else '❌'}{note}")
        log(f'\n  整体 mAP50: {new_map50:.4f}（下限 {map50_min}）')
        if new_map50 < map50_min:
            failures.append(f'整体 mAP50 {new_map50:.4f} 低于下限 {map50_min}')
        for row in rows:
            if not row['passed']:
                failures.append(f"{row['cls']} AP50 跌幅 {row['drop']:+.4f} 超过 {ap50_drop_max}")
        check()

        quant_rows = []
        if quantized and Path(quantized).is_file():
            quantized = Path(quantized)
            log(f'[5/5] 评估量化模型: {quantized.name}')
            try:
                quant_ap50, quant_map50 = evaluate(quantized, staged_yaml, scratch)
            except Exception as error:  # 量化模型可能因算子不支持而无法用 ultralytics 加载
                log(f'  ⚠ 量化模型无法直接评估: {error}')
                warnings.append(f'量化模型未评估: {error}')
            else:
                for index, name in enumerate(golden_names):
                    current = quant_ap50[index] if index < len(quant_ap50) else 0.0
                    reference = new_ap50[index] if index < len(new_ap50) else 0.0
                    drop = reference - current
                    quant_rows.append(dict(cls=name, fp32_ap50=reference, int8_ap50=current,
                                           drop=drop, passed=drop <= quant_drop_max))
                    if drop > quant_drop_max:
                        failures.append(f'{name} 量化掉点 {drop:+.4f} 超过 {quant_drop_max}')
                log(f'  量化 mAP50: {quant_map50:.4f}')
        else:
            log('[5/5] 未提供量化模型，跳过量化掉点检查')

    import hashlib
    hasher = hashlib.sha256()
    with model.open('rb') as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b''):
            hasher.update(chunk)
    model_hash = hasher.hexdigest()
    model_stat = model.stat()
    summary = dict(golden=str(golden), model=str(model), model_sha256=model_hash,
                   model_size=model_stat.st_size, model_mtime_ns=model_stat.st_mtime_ns,
                   dataset_version=version or '', baseline=str(baseline or ''),
                   quantized=str(quantized or ''), dataset=str(dataset_yaml),
                   class_aligned=train_names == golden_names, map50=new_map50,
                   map50_min=map50_min, ap50_drop_max=ap50_drop_max,
                   quant_drop_max=quant_drop_max, leakage=len(overlap),
                   passed=not failures, failures=failures, warnings=warnings,
                   per_class=rows, per_class_quantized=quant_rows,
                   report=str(report_dir / 'release_gate.json'))
    (report_dir / 'release_gate.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    with (report_dir / 'release_gate.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=['cls', 'old_ap50', 'new_ap50', 'drop', 'passed'],
                                extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description='Label Once 发布门禁')
    parser.add_argument('--project', required=True, type=Path, help='Label Once 项目目录')
    parser.add_argument('--model', required=True, type=Path, help='待发布的模型权重')
    parser.add_argument('--golden', required=True, type=Path, help='冻结基准集的 dataset.yaml')
    parser.add_argument('--baseline', type=Path, help='上一版模型权重，用于逐类对比')
    parser.add_argument('--quantized', type=Path, help='量化模型（ONNX/INT8），与浮点模型一并送检')
    parser.add_argument('--dataset-version', help='用于取类别表的数据集版本，默认取当前激活版本')
    parser.add_argument('--map50-min', type=float, default=.50, help='整体 mAP50 下限')
    parser.add_argument('--ap50-drop-max', type=float, default=.03, help='逐类 AP50 跌幅上限')
    parser.add_argument('--quant-drop-max', type=float, default=.02, help='量化掉点上限')
    parser.add_argument('--strict-labels', action='store_true', help='基准集标签格式混用时也判失败')
    parser.add_argument('--report', type=Path, help='报告输出目录，默认写到项目的 Model 目录')
    args = parser.parse_args()

    print('=' * 64)
    print('  Label Once 发布门禁')
    print('=' * 64)
    try:
        summary = run_gate(project=args.project.resolve(), model=args.model, golden=args.golden,
                           baseline=args.baseline, quantized=args.quantized,
                           dataset_version=args.dataset_version, map50_min=args.map50_min,
                           ap50_drop_max=args.ap50_drop_max, quant_drop_max=args.quant_drop_max,
                           strict_labels=args.strict_labels, report_dir=args.report)
    except (ValueError, FileNotFoundError) as error:
        print(f'❌ {error}')
        print('=' * 64)
        return 1
    for warning in summary['warnings']:
        print(f'  ⚠ {warning}')
    if summary['passed']:
        print('  ✅ 门禁通过，可以发布')
    else:
        print('  ❌ 门禁未通过，禁止发布：')
        for reason in summary['failures']:
            print(f'     - {reason}')
    print(f'  报告 → {summary["report"]}')
    print('=' * 64)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
