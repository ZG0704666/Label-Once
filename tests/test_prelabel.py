import sys
from types import SimpleNamespace
from studio.domain import Labels,Box
from studio.worker import Worker


def test_zero_detection_replace_clears_old_labels(tmp_path,monkeypatch):
    class EmptyTensor:
        def cpu(self):return self
        def tolist(self):return []
    result=SimpleNamespace(boxes=SimpleNamespace(xyxyn=EmptyTensor(),cls=EmptyTensor(),conf=EmptyTensor()))
    class Model:
        def __init__(self,*args):pass
        def predict(self,*args,**kwargs):return [result]
    monkeypatch.setitem(sys.modules,'ultralytics',SimpleNamespace(YOLO=Model))
    labels=Labels(tmp_path/'labels');labels.set_classes(['target'])
    labels.save('image',[Box(0,.1,.1,.7,.7)])
    task=dict(kind='prelabel',run=str(tmp_path/'run'),labels=str(labels.folder),model='fixture',images=[str(tmp_path/'image.png')],mapping={'0':0},replace=True)
    Worker(task).execute()
    assert labels.load('image')==[]
    assert (labels.folder/'image.txt').read_text()==''
    assert (labels.folder/'image.mark').read_text()==''
