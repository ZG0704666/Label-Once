import os
import sys
from pathlib import Path
from .domain import read_json, save_json

APP_ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
CONFIG_ROOT = Path(os.environ.get('APPDATA', str(Path.home()))) / 'YoloTrainStudio'
CONFIG_ROOT.mkdir(parents=True, exist_ok=True)


def settings():
    return read_json(CONFIG_ROOT/'settings.json', {'brand': 'YoloTrain Studio', 'recent': [], 'sam_imgsz': 1024})


def bundled_logo():
    candidates = [
        APP_ROOT/'assets'/'logo.png',
        Path(__file__).resolve().parent.parent/'assets'/'logo.png',
    ]
    return next((path for path in candidates if path.exists()), candidates[-1])


def save_settings(data):
    save_json(CONFIG_ROOT/'settings.json', data)


def model_paths(sam=False):
    folder = 'sam' if sam else 'models'
    roots = [APP_ROOT/folder, APP_ROOT.parent/folder]
    return sorted({str(p.resolve()) for root in roots if root.exists() for p in root.glob('*.pt')})


# The optimizer is pinned instead of 'auto'. Ultralytics' 'auto' silently ignores lr0/momentum
# and swaps to MuSGD once the iteration count passes 10000, which made the learning-rate field
# in the UI a no-op and made the optimizer depend on dataset size. momentum=.9 is the AdamW
# beta1 convention (the old .937 was calibrated for SGD).
ADVANCED = dict(optimizer='AdamW', momentum=.9, weight_decay=.0005, warmup_epochs=3.,
                warmup_momentum=.8, lrf=.01, box=7.5, cls=.5, dfl=1.5, freeze=0, max_det=300,
                workers=0, patience=100, save_period=-1, amp=True, rect=False, seed=42,
                cache=False, fraction=1., perspective=0., shear=0., close_mosaic=10,
                nbs=64, cos_lr=False)
AUGMENTS = dict(fliplr=.5, scale=.5, mosaic=1., hsv_h=.015, hsv_s=.7, hsv_v=.4,
                flipud=0., degrees=0., mixup=0., translate=.1)


def augmentation_values(flags):
    """Map stored augmentation switches onto the Ultralytics augmentation knobs.

    The Qt app stores one 'hsv' switch while AUGMENTS keeps hsv_h/hsv_s/hsv_v apart, so a
    plain `if key in AUGMENTS` filter dropped the colour switch on every preset round-trip.
    """
    values = {}
    for key, enabled in (flags or {}).items():
        keys = ('hsv_h', 'hsv_s', 'hsv_v') if key == 'hsv' else (key,)
        for name in keys:
            if name in AUGMENTS:
                values[name] = AUGMENTS[name] if enabled else 0
    return values
