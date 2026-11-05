# AGENTS.md — Label Once

Windows-local AI annotation + training platform: a .NET 10 WPF desktop client (`desktop/`) talking to a Python 3.10 backend (`studio/`) over a JSONL stdin/stdout bridge. Docs live in `docs/` (Chinese); `docs/12-testing.md` and `docs/11-build-release-ci.md` are the highest-value references.

## Commands

```powershell
# Python unit/integration tests (NO torch/ultralytics needed)
python -m pytest -q                                   # single file: python -m pytest tests/test_bridge.py -q
python -m pytest -q --cov --cov-report=term-missing   # what CI runs (coverage ratchet, see below)

# Lint / types (CI: python-lint job)
ruff check .                          # config in pyproject.toml [tool.ruff]
python -m mypy studio --no-site-packages

# Lock sync — run FIRST when touching dependencies
python scripts/checks/check_lock_sync.py

# .NET
dotnet restore desktop/LabelOnce.sln
dotnet build desktop/LabelOnce.sln -c Release
dotnet test desktop/LabelOnce.Core.Tests/LabelOnce.Core.Tests.csproj -c Release   # xUnit, headless

# Full app / release build
./desktop/scripts/build.ps1           # PyInstaller backend + WPF publish -> Release/TrainStudio-WPF
./desktop/scripts/start.ps1           # compile + launch WPF
./scripts/install.ps1                 # full env (Python deps + .NET SDK + model weights)
```

Required order when changing dependencies: edit `requirements.txt` -> regenerate lock (`scripts/lock_environment.py`) -> `check_lock_sync.py`. CI fails if the direct pins and `requirements.lock.txt` disagree.

## Test environment constraints (easy to get wrong)

- **Python tests must NOT import real `ultralytics`/`torch`/`PyQt5`.** They use `sys.modules` stubs (`FakeYOLO` via `monkeypatch.setitem`). Importing the real packages triggers `WinError 1114` loading `c10.dll` on Windows — the whole point of the current test design. Keep heavy imports lazy (inside functions) in `studio/`.
- Minimal test deps only: `pytest numpy opencv-python Pillow PyYAML pytest-cov`. Do not re-add ultralytics to CI.
- Coverage is a **ratchet, not a target**: `[tool.coverage.report] fail_under = 62`. `tracking.py`/`worker.py`/`interactive_sam.py` are intentionally uncovered here (GPU paths covered by `scripts/check_*.py` acceptance scripts instead).
- `LabelOnce.Desktop.Tests` is a **manual WPF acceptance harness** (moves the real mouse, sends keys, needs a live backend + visible desktop). It is NOT runnable in CI and not part of `dotnet test`. Only `LabelOnce.Core.Tests` runs headless.

## Lint / style gotchas

- `ruff` and `ruff format` are configured but **formatting is deliberately NOT enforced** — enabling `ruff format` would reformat the whole compact, one-line-heavy tree. Don't run a formatter pass casually.
- The ignore list is intentional: `E501` (long lines OK), `RUF001/002/003` (CJK characters in comments/strings are first-class here), `I001` (manual import order), `BLE001` (broad `except` used deliberately in `bridge.py`/`processes.py`). Don't "fix" these.
- Quote style is single (`inline-quotes = "single"`).
- `mypy` is a lenient baseline (`check_untyped_defs = false`, `--no-site-packages`). Don't tighten without a dedicated annotation pass.

## Architecture notes

- `backend/backend_launch.py` is the single frozen headless entry. Modes: `--bridge` (JSONL bridge, default), `--worker <id>`, or run a module/script. It anchors the repo root onto `sys.path` because `studio/` lives at the root, not under `backend/`.
- `studio/` is the entire Python backend: `bridge.py` (JSONL v1 protocol), `worker.py` (task orchestration), `domain.py`, `dataset.py`, `merge.py`, `tracking.py`, `segmentation.py`, `interactive_sam.py`. `studio` is the only packaged lib (`[tool.setuptools.packages.find]`).
- `desktop/LabelOnce.Desktop` = WPF UI; `desktop/LabelOnce.Core` = pure logic (viewport/annotation geometry, the headless-testable part).
- Docs on the wire protocol: `docs/09-bridge-protocol.md`. Protocol changes need a `tests/test_bridge.py` assertion (request/response/error frame).

## Release / packaging

- Shippable release = `Release/TrainStudio-WPF/` containing `LabelOnce.exe` + `backend/backend.exe` + `models/` + `sam/` weights. Copy the **whole folder**; never ship the EXE alone.
- CI (`package-windows` job) only publishes a **WPF-only smoke artifact**. The full release (backend.exe + weights) requires a local `desktop/scripts/build.ps1` run on a machine with the full conda env — CI installs no ML runtime.
- `Backend.spec` force-collects the System32 VS2022 CRT (msvcp140/vcruntime140) to avoid the torch `c10.dll` `WinError 1114` in the frozen backend. `scripts/rth_torch.py` fixes torch DLL search paths. Don't remove these.
- GitHub Releases trigger on `v*.*.*` tags only, gated on all test/lint jobs.

## Repo hygiene

- Never commit: `models/`, `sam/`, `train/` weights; `Release/`, `build/`, `dist/`, `bin/`, `obj/`; local annotation sidecars (`*.annotation.json`, `*.segments.json`, `*.mark`); caches. All covered by `.gitignore`.
- `scripts/check_*.py` and `scripts/acceptance/` need real models/GPU/video — pre-release manual acceptance, not CI.
- Target: Python `>=3.10,<3.11`, .NET SDK `10.0.x` (pinned in `desktop/global.json`). Windows-only.
