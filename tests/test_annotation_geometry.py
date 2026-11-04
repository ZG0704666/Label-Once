import numpy as np
import pytest
from studio.domain import Labels, mask_box
from studio.annotations import AnnotationConflict


def test_contour_persistence_and_conflict(tmp_path):
    mask=np.zeros((100,100),dtype=np.uint8)
    mask[10:80,10:25]=1;mask[65:80,10:80]=1
    box=mask_box(mask)
    assert box.polygons and len(box.polygons[0])>4
    labels=Labels(tmp_path/'labels');labels.set_classes(['object']);labels.save('a',[box])
    loaded=labels.load('a')[0];assert loaded.polygons==box.polygons
    labels.reorder(['renamed'],{0:0});assert labels.load('a')[0].polygons==box.polygons
    # 外部 TXT 被改动后，旧轮廓必须失效并提示冲突，而不是静默使用过期几何。
    (labels.folder/'a.txt').write_text('0 .5 .5 .2 .2\n')
    with pytest.raises(AnnotationConflict):labels.load('a')
