# Qt is intentionally excluded from the production backend.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
hiddenimports = collect_submodules('ultralytics') + collect_submodules('openvino') + ['tensorrt', 'tensorrt_bindings', 'onnxruntime', 'onnxslim', 'torchvision', 'torch.distributed.run', 'studio.bridge', 'studio.worker']
a = Analysis(['backend_launch.py'], pathex=['.'], hiddenimports=hiddenimports,
    datas=collect_data_files('ultralytics'), binaries=collect_dynamic_libs('tensorrt_libs'),
    runtime_hooks=['scripts/rth_torch.py'], excludes=['pytest','notebook','IPython','PySide6','PyQt6','PyQt5','tkinter','tensorflow','jax'])
pyz = PYZ(a.pure)
# Force the modern VS2022 CRT from System32 into the bundle. PyInstaller otherwise
# picks the stale conda-env-root copies (msvcp140 14.16 / vcruntime140_1 14.27),
# which fail to load torch's c10.dll (WinError 1114).
import os as _os
_CRT_NAMES = {'msvcp140.dll', 'msvcp140_1.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'}
_system32 = _os.path.join(_os.environ.get('WINDIR', r'C:\Windows'), 'System32')
a.binaries = [(n, p, t) for (n, p, t) in a.binaries
              if _os.path.basename(n).lower() not in _CRT_NAMES]
for _n in sorted(_CRT_NAMES):
    _src = _os.path.join(_system32, _n)
    if _os.path.isfile(_src):
        a.binaries.append((_n, _src, 'BINARY'))
# Console subsystem preserves stdin/stdout; WPF uses CREATE_NO_WINDOW + redirected pipes.
exe = EXE(pyz, a.scripts, exclude_binaries=True, name='backend', console=True, debug=False)
coll = COLLECT(exe, a.binaries, a.datas, name='backend')
