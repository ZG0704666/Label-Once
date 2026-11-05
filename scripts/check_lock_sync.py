"""Fail if any pin in requirements.txt is missing from, or drifts from, requirements.lock.txt.

The lock file is the fully-resolved source of truth (regenerate it with
scripts/lock_environment.py). This guard keeps the two in sync so a bumped
direct dependency can't silently diverge from the pinned environment.

No third-party imports: CI installs only pytest/numpy/opencv/Pillow/PyYAML.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DIRECT = ROOT / 'requirements.txt'
LOCK = ROOT / 'requirements.lock.txt'


def normalize(name: str) -> str:
    """PEP 503 canonical name: case-insensitive, runs of -_. collapse to -."""
    return re.sub(r'[-_.]+', '-', name).strip().lower()


def parse_pins(path: Path) -> dict:
    """Return {canonical_name: (display_name, pinned_version)} for == pins."""
    pins = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.split('#')[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._+-]+)', line)
        if not match:
            continue
        name, version = match.group(1), match.group(2)
        pins[normalize(name)] = (name, version)
    return pins


def main() -> int:
    if not LOCK.exists():
        print(f'ERROR: {LOCK.name} not found; run scripts/lock_environment.py to generate it.')
        return 1
    direct = parse_pins(DIRECT)
    lock = parse_pins(LOCK)

    drift = []
    for key, (name, version) in sorted(direct.items()):
        if key not in lock:
            drift.append(f'{name}=={version} is not present in {LOCK.name}')
        elif lock[key][1] != version:
            drift.append(f'{name}: requirements.txt pins {version} but lock has {lock[key][1]}')

    if drift:
        print(f'ERROR: requirements.txt and {LOCK.name} are out of sync:')
        for item in drift:
            print(f'  - {item}')
        print('Fix: align the pins, or regenerate the lock via scripts/lock_environment.py.')
        return 1

    print(f'OK: all {len(direct)} direct pins in requirements.txt match {LOCK.name}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
