"""Pin installed distributions needed by the application, without conda build URLs."""
import importlib.metadata as md
import re
from pathlib import Path
from packaging.requirements import Requirement

roots=['PyQt5','ultralytics','numpy','opencv-python','matplotlib','PyYAML','Pillow','requests','tqdm','psutil','torch','torchvision','onnx','onnxruntime','onnxslim','openvino','tensorrt-cu12','PyInstaller','pytest']
pending=list(roots);seen={};missing=set()
while pending:
    name=pending.pop();key=re.sub('[-_.]+','-',name).lower()
    if key in seen or key in missing:continue
    try:dist=md.distribution(name)
    except md.PackageNotFoundError:missing.add(key);continue
    seen[key]=(dist.metadata['Name'],dist.version)
    for value in dist.requires or []:
        req=Requirement(value)
        if not req.marker or req.marker.evaluate({'extra':''}):pending.append(req.name)
text='# Python 3.10 x64; install CUDA Torch wheels from the cu128 index first.\n'
text+='\n'.join(f'{name}=={version}' for _,(name,version) in sorted(seen.items()))+'\n'
(Path(__file__).resolve().parents[1]/'requirements.lock.txt').write_text(text,encoding='utf-8')
print('Pinned',len(seen),'distributions; unavailable metadata:',sorted(missing))
