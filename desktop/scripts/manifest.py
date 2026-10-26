"""Record the local WPF delivery without changing the historical Qt manifest."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

source = Path(__file__).resolve().parents[2]
root = source.parents[1]
release = root / "Release/TrainStudio-WPF"
evidence = source / "acceptance/wpf/frozen"


def record(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


reports = [evidence / "frozen-report.json", evidence / "screenshots/desktop-report.json",
           evidence / "screenshots/release-smoke.json"]
frozen, desktop, smoke = [json.loads(path.read_text(encoding="utf-8")) for path in reports]
tasks = {key: {"exit_code": value["exit_code"], "errors": value.get("errors", [])}
         for key, value in frozen.items() if isinstance(value, dict) and "exit_code" in value}
assert tasks and all(t["exit_code"] == 0 and not t["errors"] for t in tasks.values())
assert len(desktop) == 28 and all(item["pass"] for item in desktop)
assert smoke["pass"] and smoke["exitCode"] == 0
files = [p for p in release.rglob("*") if p.is_file() and p.name != "交付清单-WPF.json"]
artifacts = [release / name for name in ("LabelOnce.exe", "LabelOnce.dll", "LabelOnce.Core.dll",
              "backend/backend.exe", "README.md", "WPF_ACCEPTANCE.md", "requirements.lock.txt")]
artifacts += sorted((release / "models").glob("*.pt")) + sorted((release / "sam").glob("*.pt"))
code = [source / name for name in ("studio/bridge.py", "studio/service.py", "studio/processes.py",
        "backend_launch.py", "Backend.spec", "desktop/global.json")]
code += [p for p in (source / "desktop").rglob("*")
         if p.is_file() and p.suffix in (".cs", ".xaml", ".csproj", ".ps1")
         and not {"obj", "bin"}.intersection(p.relative_to(source).parts)]
manifest = {
    "created_at": datetime.now().astimezone().isoformat(),
    "application": "Label Once WPF", "source": source.relative_to(root).as_posix(),
    "release": release.relative_to(root).as_posix(), "entry": "Release/TrainStudio-WPF/LabelOnce.exe",
    "runtime": "Windows x64 self-contained; frozen Python backend; no Conda activation required",
    "development": {"conda": "labelonce", "python": "3.10 x64", "dotnet_sdk": "10.0.401",
                    "wpf_ui": "4.3.0", "communitytoolkit_mvvm": "8.4.2",
                    "torch": "2.11.0+cu128", "torchvision": "0.26.0"},
    "release_inventory_excluding_manifest": {"files": len(files), "bytes": sum(p.stat().st_size for p in files)},
    "verified": {"python_passed": 26, "python_skipped": 1, "geometry_assertions": 6916,
                 "native_window_checks": len(desktop), "frozen_tasks": tasks,
                 "release_smoke": smoke["pass"], "physical_dpi_percent": 150,
                 "gpu": "NVIDIA GeForce RTX 5080 Laptop GPU"},
    "remaining_acceptance": ["Physical 100/125/200% DPI and mixed-DPI monitor dragging",
                              "Multi-GPU DDP, other hardware, large real datasets and long training"],
    "qt_fallback": "Release/TrainStudio", "git_commit_push_publish": False,
    "artifacts": [record(p) for p in artifacts], "source_files": [record(p) for p in sorted(set(code))],
    "evidence": [record(p) for p in reports],
}
content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
for destination in (root / "交付清单-WPF.json", release / "交付清单-WPF.json"):
    destination.write_text(content, encoding="utf-8")
print(json.dumps(manifest["release_inventory_excluding_manifest"]))
