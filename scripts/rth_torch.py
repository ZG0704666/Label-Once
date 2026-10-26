"""Load the native ML runtime before Qt's bundled runtime hook."""
import os
import sys
import json

if '--worker' in sys.argv:
    with open(sys.argv[sys.argv.index('--worker') + 1], encoding='utf-8') as f:
        task = json.load(f)
    if task.get('kind') == 'export':
        if task.get('format') == 'onnx':
            os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
        if task.get('format') == 'engine':
            os.environ['NVIDIA_TF32_OVERRIDE'] = '0'
            # TensorRT loads builder kernels lazily through native LoadLibrary.
            # Python's DLL directory handles alone do not cover those lookups.
            # Restrict the search path addition to this frozen export worker.
            runtime = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
            native = [os.path.join(runtime, 'tensorrt_libs'), os.path.join(runtime, 'torch', 'lib')]
            os.environ['PATH'] = os.pathsep.join([p for p in native if os.path.isdir(p)] + [os.environ.get('PATH', '')])

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')
import torch
