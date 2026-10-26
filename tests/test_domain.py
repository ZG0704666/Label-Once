import numpy as np
import pytest
from PIL import Image
from studio.domain import Box,Labels,Project,mask_box
from studio.dataset import DatasetStore


def project_fixture(path,n=12):
    project=Project(path);project.labels.set_classes(['目标','other'])
    for i in range(n):
        Image.new('RGB',(64,64),(i*10,30,80)).save(project.images/f'{i}.png')
        project.labels.save(str(i),[Box(i%2,.1,.2,.8,.9,'AI')])
    return project


def test_labels_roundtrip_and_zero_replacement(tmp_path):
    labels=Labels(tmp_path);labels.set_classes(['猫'])
    labels.save('图',[Box(0,.123456,.2,.9,.8,'AI')])
    result=labels.load('图')[0]
    assert result.x1==pytest.approx(.123456,abs=1e-6)
    assert result.origin=='AI'
    labels.save('图',[])
    assert labels.load('图')==[]
    assert (tmp_path/'图.txt').exists()


def test_legacy_and_reorder(tmp_path):
    labels=Labels(tmp_path/'labels');labels.set_classes(['a','b'])
    (labels.folder/'x.txt').write_text('1 0.5 0.5 0.2 0.2 #AI\n',encoding='utf-8')
    assert labels.load('x')[0].origin=='AI'
    backup=labels.reorder(['b','a'],{0:1,1:0})
    assert labels.load('x')[0].cls==0 and backup.exists()


def test_mask_inclusive_max():
    mask=np.zeros((10,20));mask[9,19]=1
    box=mask_box(mask)
    assert box.x2==1 and box.y2==1 and box.x1==.95 and box.y1==.9


def test_pair_rename_and_recovery(tmp_path):
    project=project_fixture(tmp_path)
    project.batch_rename('样本_',3)
    assert (project.images/'样本_000003.png').exists()
    assert project.labels.load('样本_000003')[0].cls==0
    dest=project.trash_image(project.images/'样本_000003.png')
    assert (dest/'样本_000003.txt').exists()


def test_dataset_determinism_incremental_and_snapshot(tmp_path):
    project=project_fixture(tmp_path/'project');store=DatasetStore(project)
    first=store.create();m1=store.manifest(first)
    second=store.create();m2=store.manifest(second)
    assert [(r['name'],r['split']) for r in m1['images']]==[(r['name'],r['split']) for r in m2['images']]
    assert len({r['name'] for r in m1['images']})==12
    assert {r['split'] for r in m1['images']}=={'train','val','test'}
    assert store.create(incremental=True)==second
    Image.new('RGB',(64,64)).save(project.images/'新增.png');project.labels.save('新增',[])
    third=store.create(incremental=True)
    old={r['name']:r['split'] for r in m2['images']}
    assert all(old.get(r['name'],r['split'])==r['split'] for r in store.manifest(third)['images'])
    Image.new('RGB',(64,64),'red').save(project.images/'0.png')
    with pytest.raises(ValueError,match='变化'):store.create(incremental=True)
    assert len(store.manifest(first)['images'])==12


def test_quality_empty_and_jumps():
    from studio.tracking import quality_reason
    old=Box(0,.1,.1,.3,.3)
    assert quality_reason(old,None)=='目标丢失'
    assert quality_reason(old,Box(0,.11,.1,.31,.3)) is None
    assert quality_reason(old,Box(0,.7,.7,.9,.9))=='位置突变'
