# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
hiddenimports = collect_submodules('ultralytics') + collect_submodules('openvino') + ['tensorrt', 'tensorrt_bindings', 'onnxruntime', 'onnxslim', 'torchvision', 'torch.distributed.run']
datas = collect_data_files('ultralytics') + [('assets/logo.png', 'assets')]
binaries = collect_dynamic_libs('tensorrt_libs')
a = Analysis(['launch.py'], pathex=['.'], hiddenimports=hiddenimports, datas=datas, binaries=binaries, runtime_hooks=['scripts/rth_torch.py'], excludes=['pytest','notebook','IPython','PySide6','PyQt6','tkinter','tensorflow','jax'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, exclude_binaries=True, name='YoloTrainStudio', console=False, debug=False, icon='assets/logo.ico')
coll = COLLECT(exe, a.binaries, a.datas, name='YoloTrainStudio')
