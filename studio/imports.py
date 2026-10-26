"""Validated image/YOLO import with named category mapping and review registration."""
from pathlib import Path
from dataclasses import replace
import hashlib
import shutil
from PIL import Image
from .domain import Labels,digest
from .review import ReviewStore


def import_images(project,paths,report=None):
    from .domain import IMAGE_EXTENSIONS,unique_id
    entries=[];classes=list(project.labels.classes);review=ReviewStore(project);records=review.records()
    seen_sources=set()
    for p in map(Path,paths):
        source_path=str(p.resolve())
        if source_path in seen_sources:
            if report is not None:report['duplicates']+=1
            continue
        seen_sources.add(source_path)
        try:
            if not p.is_file() or p.suffix.lower() not in IMAGE_EXTENSIONS:
                raise ValueError('不是支持的图片文件')
            with Image.open(p) as image:image.verify()
            previous=next((n for n,e in records.items() if e.get('source')==source_path),None)
            if previous:
                if records[previous].get('source_sha256')!=digest(p):raise ValueError('来源文件已改变，请使用新文件名导入')
                if not (project.images/previous).is_file():raise ValueError('已导入图片已移动或回收；请恢复后重试')
                if report is not None:report['duplicates']+=1
                continue
            candidates=[p.parent.parent/'Main_labels',Path(str(p.parent)+'_labels'),p.parent/'labels',p.parent]
            folder=next((f for f in candidates if (f/(p.stem+'.txt')).is_file()),None)
            boxes=None
            if folder:
                source=Labels(folder);boxes=source.load(p.stem);names=source.classes
                if any(b.cls<0 or b.cls>=len(names) for b in boxes):raise ValueError('标签缺少有效类别表 classes.txt')
                for b in boxes:
                    if names[b.cls] not in classes:classes.append(names[b.cls])
                boxes=[replace(b,cls=classes.index(names[b.cls])) for b in boxes]
        except (OSError,ValueError) as exc:
            if report is None:raise
            report['failures'].append(dict(path=str(p),reason=str(exc)))
            continue
        entries.append((p,boxes,previous))
    added=[];project.labels.set_classes(classes);batch='images_'+unique_id();stems={p.stem.casefold() for p in project.image_paths()}
    for p,boxes,previous in entries:
        if previous:continue
        name=p.name
        if p.stem.casefold() in stems:
            token=hashlib.sha256(str(p.resolve()).encode()).hexdigest()[:10];name=f'{p.stem}_{token}{p.suffix}'
        if Path(name).stem.casefold() in stems:raise ValueError(f'{name} 目标冲突，未覆盖')
        shutil.copy2(p,project.images/name);stems.add(Path(name).stem.casefold());added.append(name)
        if boxes is not None:project.labels.save(Path(name).stem,boxes)
        records[name]=dict(status='pending',batch=batch,source=str(p.resolve()),source_sha256=digest(p))
        review.write(records)
    project.log(f'导入 {len(added)} 张图片，待完成');return added
