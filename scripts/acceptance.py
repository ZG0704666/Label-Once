"""Real CPU/GPU integration checks; writes evidence under acceptance/."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['YOLO_AUTOINSTALL']='False'
os.environ['NVIDIA_TF32_OVERRIDE']='0'
from PIL import Image,ImageDraw
from studio.domain import Box,Project,save_json
from studio.dataset import DatasetStore
from studio.worker import Worker

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'acceptance'
OUT.mkdir(exist_ok=True)
MODEL=str(ROOT/'models'/'yolov8n.pt')


def prepare():
    p=Project(OUT/'验证项目');p.labels.set_classes(['square','circle'])
    for i in range(12):
        im=Image.new('RGB',(96,96),(20+i*3,30,40));d=ImageDraw.Draw(im)
        d.rectangle((16,16,48,48),fill='orange');d.ellipse((52,52,84,84),fill='cyan')
        im.save(p.images/f'测试_{i:02d}.jpg')
        p.labels.save(f'测试_{i:02d}',[Box(0,16/96,16/96,49/96,49/96),Box(1,52/96,52/96,85/96,85/96)])
    store=DatasetStore(p);store.create()
    return p,store


def run(task):
    result=Worker(task).execute();save_json(Path(task['run'])/'result.json',result);return result


def main():
    p,store=prepare();results={}
    saved=OUT/'integration.json'
    if saved.exists():results=json.loads(saved.read_text(encoding='utf-8'))
    for device in ['cpu','0']:
        if 'train_'+device in results:continue
        path=p.new_run('train_'+device)
        results['train_'+device]=run(dict(kind='train',run=str(path),project=str(p.root),model=MODEL,dataset=str(store.yaml_path()),dataset_version=store.active(),
            params=dict(epochs=1,batch=2,imgsz=64,device=device,workers=0,amp=False,plots=True,seed=42,mosaic=0,fliplr=0,scale=0,translate=0)))
        save_json(saved,results)
    for device in ['cpu','0']:
        if 'predict_'+device in results:continue
        results['predict_'+device]=run(dict(kind='predict',run=str(p.new_run('predict_'+device)),project=str(p.root),model=MODEL,source=str(p.image_paths()[0]),mode='image',device=device))
    results['evaluate']=run(dict(kind='evaluate',run=str(p.new_run('evaluate')),project=str(p.root),model=results['train_0']['best'],dataset=str(store.yaml_path()),device='0'))
    save_json(saved,results)
    for fmt in ['torchscript','onnx','openvino','engine']:
        if 'export_'+fmt in results:continue
        params=dict(imgsz=64,batch=1,quantize=32,device='0' if fmt=='engine' else 'cpu')
        if fmt=='onnx':params.update(opset=18,simplify=True,dynamic=False)
        results['export_'+fmt]=run(dict(kind='export',run=str(p.new_run('export_'+fmt)),project=str(p.root),model=MODEL,format=fmt,params=params))
        save_json(OUT/'integration.json',results)
    import numpy as np
    import torch
    import onnx
    import onnxruntime as ort
    import openvino as ov
    from ultralytics import YOLO
    model=YOLO(MODEL).model.eval().float()
    x=torch.rand(1,3,64,64,generator=torch.Generator().manual_seed(42))
    with torch.no_grad():expected=model(x)[0].numpy()
    with open(results['export_torchscript']['output'],'rb') as f:
        script=torch.jit.load(f).eval()
    with torch.no_grad():actual=script(x)
    if isinstance(actual,(tuple,list)):actual=actual[0]
    comparisons={}
    def compare(name,actual,atol=1e-3):
        np.testing.assert_allclose(actual,expected,rtol=1e-3,atol=atol)
        comparisons[name]=dict(max_abs_error=float(np.abs(actual-expected).max()),shape=list(actual.shape),passed=True,atol=atol)
    compare('torchscript',actual.numpy())
    onnx_path=results['export_onnx']['output'];onnx.checker.check_model(onnx.load(onnx_path))
    sess=ort.InferenceSession(onnx_path,providers=['CPUExecutionProvider']);compare('onnx',sess.run(None,{sess.get_inputs()[0].name:x.numpy()})[0])
    xml=next(Path(results['export_openvino']['output']).glob('*.xml'));compiled=ov.Core().compile_model(str(xml),'CPU',{'INFERENCE_PRECISION_HINT':'f32'})
    compare('openvino',compiled(x.numpy())[compiled.output(0)])
    # Use the same exported tensor convention through Ultralytics' engine runtime.
    from ultralytics.nn.autobackend import AutoBackend
    backend=AutoBackend(results['export_engine']['output'],device=torch.device('cuda:0'))
    with torch.no_grad():trt=backend(x.cuda())
    if isinstance(trt,(tuple,list)):trt=trt[0]
    compare('tensorrt',trt.cpu().numpy())
    save_json(OUT/'numerical_comparison.json',comparisons)
    print(json.dumps(comparisons,indent=2))


if __name__=='__main__':main()
