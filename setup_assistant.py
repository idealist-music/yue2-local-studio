"""Interactive Linux/WSL2 installer and read-only diagnostics (stdlib only)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

APP = Path(__file__).resolve().parent
YUE_URL = "https://github.com/multimodal-art-projection/YuE.git"
YUE_TAG = "yue2-v0.1.6"
SHEET_REPO = "m-a-p/SheetSage2"
SHEET_REV = "488abe28ef4db3dbb056da19cb49d80f4b14bc61"
MERT_REPO = "m-a-p/MERT-v2-FullSong"
MERT_REV = "d8ba1c745e733b3908ce6ad16ebeb17ac7600a42"
YUE_MODEL = ("m-a-p/YuE2-3B", "14fc6c6f146441b1dd6363fcb2e01e82a6914cb7")
YUE_VAE = ("m-a-p/YuE2-Vae", "9a94e1d0ea9f8087e98f77fa88df4a4068104d2a")
SYSTEM_ROOTS = tuple(Path(name) for name in ("/usr", "/etc", "/var", "/lib", "/lib64", "/bin", "/sbin", "/opt", "/boot"))


def protect_write_target(path):
    resolved = Path(path).expanduser().resolve()
    if resolved == Path("/") or any(resolved == root or resolved.is_relative_to(root) for root in SYSTEM_ROOTS):
        raise RuntimeError(f"System directory is not an installer destination: {resolved}")
    return resolved


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def python_probe(path):
    if not path or not Path(path).is_file():
        return None
    script = ("import importlib.metadata as m,json,sys\n"
              "names=('fastapi','uvicorn','anyio','yue2-infer','torch','torchaudio','transformers','huggingface-hub','safetensors','numpy','soundfile','scipy','mir_eval','pretty_midi','mido','setuptools')\n"
              "found={}\n"
              "for name in names:\n"
              " try: found[name]=m.version(name)\n"
              " except m.PackageNotFoundError: pass\n"
              "print(json.dumps({'python':list(sys.version_info[:3]),'packages':found}))\n")
    try:
        result = subprocess.run([str(path), "-B", "-c", script], capture_output=True, text=True,
                                timeout=15, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        return json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def weight_snapshot(path, *, merged=False):
    if not path or not Path(path).is_dir():
        return False
    root = Path(path)
    config = read_json(root / "config.json")
    single = root / "model.safetensors"
    index = read_json(root / "model.safetensors.index.json")
    shards = set(index.get("weight_map", {}).values()) if isinstance(index, dict) else set()
    weights = (single.is_file() and single.stat().st_size > 0) or bool(
        shards and all((root / shard).is_file() and (root / shard).stat().st_size > 0 for shard in shards))
    return bool(isinstance(config, dict) and weights and
                (not merged or config.get("weights_format") == "merged"))


def cached_snapshot(repo, revision):
    """Inspect an exact Hugging Face revision without downloading anything."""
    cache = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if not cache:
        cache = str(Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub")
    return Path(cache) / ("models--" + repo.replace("/", "--")) / "snapshots" / revision


def yue_model_ready(value, repo, revision):
    if value == repo:
        return weight_snapshot(cached_snapshot(repo, revision))
    return weight_snapshot(value)


def version_below(version, limit):
    match = re.match(r"^(\d+)\.(\d+)", version or "")
    return bool(match and tuple(map(int, match.groups())) < limit)


def matches_pin(installed, pin):
    return bool(installed and installed.split("+", 1)[0] == pin)


def pinned_requirements(path):
    """Read simple exact pins from the reviewed SheetSage2 requirements file."""
    pins = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)\s*$", line.strip())
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def sheet_package_for(model, app=APP):
    model = Path(model)
    candidates = ([model] if model.name == "SheetSage2" else []) + [model.parent / "SheetSage2", app / "models" / "SheetSage2"]
    return next((p for p in candidates if (p / "__init__.py").is_file() and
                 (p / "modeling_sheetsage2.py").is_file()), None)


def sheet_import_probe(python, package):
    if not python or package is None:
        return False, "Python or local SheetSage2 package missing"
    script = ("import inspect,sys\n"
              "sys.path.insert(0,sys.argv[1])\n"
              "from SheetSage2.modeling_sheetsage2 import SheetSage2Model\n"
              "assert 'melody_only' in inspect.signature(SheetSage2Model.transcribe).parameters\n"
              "print('SheetSage2Model import and melody_only OK')\n")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    try:
        run = subprocess.run([str(python), "-B", "-c", script, str(package.parent)],
                             capture_output=True, text=True, timeout=45, env=env)
        return run.returncode == 0, (run.stdout or run.stderr).strip()[-400:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def audio_runtime_probe(python):
    if not python:
        return False, "YuE Python is not configured"
    script = ("import numpy,soundfile as sf\n"
              "formats=sf.available_formats()\n"
              "print('libsndfile='+str(sf.__libsndfile_version__)+'; MP3='+str('MP3' in formats))\n")
    try:
        run = subprocess.run([str(python), "-B", "-c", script], capture_output=True, text=True,
                             timeout=20, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        return run.returncode == 0, (run.stdout or run.stderr).strip()[-300:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def gpu_probe():
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    try:
        run = subprocess.run([executable, "--query-gpu=name,memory.total,compute_cap", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10)
        if run.returncode == 0:
            return run.stdout.strip()[:300]
        run = subprocess.run([executable, "-L"], capture_output=True, text=True, timeout=10)
        return run.stdout.strip()[:300] if run.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def ffmpeg_probe(path=Path("/usr/bin/ffmpeg")):
    info = {"path": str(path), "on_path": shutil.which("ffmpeg"), "version": None,
            "libraries": None, "ok": False}
    if not path.is_file() or not os.access(path, os.X_OK):
        return info
    try:
        result = subprocess.run([str(path), "-version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            info["version"] = result.stdout.splitlines()[0]
        if shutil.which("ldd"):
            linked = subprocess.run(["ldd", str(path)], capture_output=True, text=True, timeout=10)
            info["libraries"] = "not found" not in linked.stdout and linked.returncode == 0
        info["ok"] = bool(info["version"] and re.search(r"ffmpeg version 6\.1(?:[.\-\s]|$)", info["version"]) and info["libraries"] is True)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return info


def report(app=APP, config_path=None):
    config_path = Path(config_path or app / "config.local.json")
    config = read_json(config_path) or {}
    app_python = app / ".venv" / "bin" / "python"
    app_probe = python_probe(app_python)
    app_packages = (app_probe or {}).get("packages", {})
    app_ok = bool(app_probe and app_probe["python"] >= [3, 10] and
                  app_packages.get("fastapi") == "0.115.6" and app_packages.get("uvicorn") == "0.34.0" and
                  version_below(app_packages.get("anyio"), (4, 10)))
    print("\n[Application / アプリ本体]")
    print(f"{'OK' if app_ok else 'MISSING'} app Python and HTTP packages: {app_python}")
    print(f"{'OK' if shutil.which('git') else 'MANUAL'} git for a new YuE clone: {shutil.which('git') or 'not found'}")

    yue_python = config.get("python")
    yue_probe = python_probe(yue_python)
    yue_version = (yue_probe or {}).get("packages", {}).get("yue2-infer")
    yue_root = Path(yue_python).parent.parent.parent if yue_python else None
    abc = Path(config.get("abc_tools")) if config.get("abc_tools") else (yue_root / "skills/yue2-music/scripts/abc_tools.py" if yue_root else None)
    model, vae = config.get("model"), config.get("vae")
    print("\n[Normal generation / 通常生成]")
    print(f"{'OK' if yue_version == '0.1.6' else 'MISSING'} yue2-infer 0.1.6: {yue_python or 'not configured'} ({yue_version or 'not found'})")
    if yue_probe:
        print(f"{'OK' if yue_probe['python'] >= [3, 10] else 'MISSING'} YuE Python >=3.10: {'.'.join(map(str, yue_probe['python']))}")
    print(f"{'OK' if abc and abc.is_file() else 'MISSING'} official abc_tools.py: {abc or 'not configured'}")
    model_ok = yue_model_ready(model, YUE_MODEL[0], config.get("revision") or YUE_MODEL[1])
    vae_ok = yue_model_ready(vae, YUE_VAE[0], config.get("vae_revision") or YUE_VAE[1])
    print(f"{'OK' if model_ok else 'MANUAL'} YuE2 model offline snapshot: {model or 'not configured'}")
    print(f"{'OK' if vae_ok else 'MANUAL'} YuE2 VAE offline snapshot: {vae or 'not configured'}")
    torch_ok, audio_ok = False, False
    if yue_probe:
        packages = yue_probe["packages"]
        torch_ok = matches_pin(packages.get("torch"), "2.10.0")
        print(f"{'OK' if torch_ok else 'MANUAL'} PyTorch 2.10.0: {packages.get('torch', 'missing')}")
        audio_ok, audio_detail = audio_runtime_probe(yue_python)
        print(f"{'OK' if audio_ok else 'MISSING'} NumPy/SoundFile/libsndfile for audio_probe.py: {audio_detail}")
    gpu = gpu_probe()
    print(f"{'OK' if gpu else 'MANUAL'} NVIDIA driver/GPU: {gpu or 'nvidia-smi unavailable'}")
    print("MANUAL BF16 support, CUDA wheel compatibility, and sufficient VRAM: use the commands in INSTALL.md")

    sheet_python, sheet_model = config.get("sheetsage_python"), config.get("sheetsage_model")
    sheet_probe = python_probe(sheet_python)
    package = sheet_package_for(sheet_model, app) if sheet_model else None
    import_ok, import_detail = sheet_import_probe(sheet_python, package) if sheet_probe else (False, "not configured")
    distinct = bool(sheet_python and yue_python and Path(sheet_python).parent.parent.resolve() != Path(yue_python).parent.parent.resolve())
    ffmpeg = ffmpeg_probe()
    cover_ffmpeg = ffmpeg_probe(Path(ffmpeg["on_path"])) if ffmpeg["on_path"] else ffmpeg
    print("\n[Cover + Motif / 追加機能]")
    print(f"{'OK' if sheet_probe and distinct else 'MISSING'} separate SheetSage2 Python: {sheet_python or 'not configured'}")
    if sheet_probe:
        print(f"{'OK' if sheet_probe['python'][:2] in ([3, 10], [3, 11]) else 'MISSING'} SheetSage2 Python 3.10/3.11: {'.'.join(map(str, sheet_probe['python']))}")
    print(f"{'OK' if package else 'MISSING'} local SheetSage2 source: {package or 'not found'}")
    print(f"{'OK' if import_ok else 'MISSING'} direct class import and melody_only: {import_detail}")
    print(f"{'OK' if weight_snapshot(sheet_model, merged=True) else 'MISSING'} offline merged SheetSage2 snapshot: {sheet_model or 'not configured'}")
    print("MANUAL SheetSage2/MERT access, license and downloaded revision: inspect official sources")
    print(f"{'OK' if cover_ffmpeg['ok'] else 'MISSING'} Cover audio FFmpeg 6.1 + shared libraries on PATH: {cover_ffmpeg['version'] or 'not executable'}")
    print(f"{'OK' if ffmpeg['ok'] else 'MISSING'} Motif /usr/bin/ffmpeg 6.1 + shared libraries: {ffmpeg['version'] or 'not executable'}; ldd={ffmpeg['libraries']}; PATH={ffmpeg['on_path']}")
    if not ffmpeg["ok"]:
        print("  Motif clipping cannot run. Cover transcription does not call this fixed path, but the official SheetSage2 audio stack may also require FFmpeg 6.1.")
    normal_ok = bool(app_ok and yue_version == "0.1.6" and yue_probe and yue_probe["python"] >= [3, 10] and
                     abc and abc.is_file() and model_ok and vae_ok and torch_ok and audio_ok)
    sheet_ok = bool(import_ok and distinct and sheet_probe and sheet_probe["python"][:2] in ([3, 10], [3, 11]) and
                    weight_snapshot(sheet_model, merged=True))
    result = {"app": app_ok, "normal": normal_ok,
              "cover": bool(normal_ok and sheet_ok and cover_ffmpeg["ok"]),
              "motif": bool(normal_ok and sheet_ok and ffmpeg["ok"])}
    print("\n[Stage summary / 段階別判定]")
    for key, label in (("app", "Application"), ("normal", "Normal generation"),
                       ("cover", "Cover audio transcription"), ("motif", "Motif")):
        print(f"{'OK' if result[key] else 'MISSING/MANUAL'} {label}")
    return result


class Installer:
    def __init__(self, app=APP, config_path=None, external=None):
        self.app = Path(app).resolve()
        self.config_path = Path(config_path or self.app / "config.local.json")
        self.config = read_json(self.config_path) or {}
        self.external = protect_write_target(external or Path.home() / "yue2-external")
        if self.external.is_relative_to(self.app):
            raise RuntimeError("External dependencies must be placed outside the application directory")
        self.proposals = {}

    def confirm(self, source, target, size, action):
        print(f"\nSource / 取得元: {source}\nDestination / 導入先: {target}\nApproximate space / 容量目安: {size}\nAction / 作業: {action}")
        try:
            answer = input("Proceed? / 実行しますか？ [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        return answer in ("y", "yes")

    def execute(self, command, *, cwd=None):
        subprocess.run(command, cwd=cwd, check=True)

    def venv(self, path, python, role):
        executable = path / "bin/python"
        if executable.is_file():
            print(f"Reuse existing {role} venv: {executable}")
            return executable
        protect_write_target(path)
        if path.exists() and not (path / "pyvenv.cfg").is_file():
            raise RuntimeError(f"Existing non-venv directory was not changed: {path}")
        if not shutil.which(python):
            raise RuntimeError(f"{python} is unavailable. Install Python/venv manually; see INSTALL.ja.md / INSTALL.md")
        action = "resume the incomplete" if path.exists() else "create a new"
        if not self.confirm("local Python interpreter", path, "typically <1 GiB before packages",
                            f"{action} {role} venv with {python} -m venv"):
            return None
        self.execute([python, "-m", "venv", str(path)])
        if not executable.is_file():
            raise RuntimeError(f"venv creation did not produce {executable}")
        return executable

    def app_stage(self):
        python = self.venv(self.app / ".venv", "python3", "app")
        if python is None:
            return None
        app_info = python_probe(python) or {}
        if app_info.get("python", [0, 0])[:2] < [3, 10]:
            raise RuntimeError("Application Python must be 3.10 or newer; existing venv was not changed")
        packages = app_info.get("packages", {})
        if (packages.get("fastapi") == "0.115.6" and packages.get("uvicorn") == "0.34.0" and
                version_below(packages.get("anyio"), (4, 10))):
            print("Reuse existing application packages")
            return python
        if self.confirm("requirements.txt / Python package index", python.parent.parent,
                        "usually <1 GiB", "install the pinned app packages; existing packages may change"):
            protect_write_target(python.parent.parent)
            self.execute([str(python), "-m", "pip", "install", "-r", str(self.app / "requirements.txt")])
        return python

    def download(self, hf, repo, revision, target, size):
        if weight_snapshot(target):
            print(f"Reuse existing snapshot: {target}")
            return True
        if not self.confirm(f"https://huggingface.co/{repo}/tree/{revision}", target, size,
                            "download the pinned model snapshot; existing partial files can resume"):
            return False
        protect_write_target(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.execute([str(hf), "download", repo, "--revision", revision, "--local-dir", str(target)])
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Download stopped ({exc.returncode}). Check access at https://huggingface.co/{repo}; "
                               f"run {hf} auth login interactively, then retry. Never place tokens in config or logs.") from exc
        if not weight_snapshot(target):
            raise RuntimeError(f"Snapshot incomplete: {target}; check access/free space and retry")
        return True

    def yue_stage(self, yue_dir=None):
        configured = self.config.get("python")
        default = Path(configured).parent.parent.parent if configured and Path(configured).is_file() else self.external / "YuE"
        root = Path(yue_dir or default).expanduser().resolve()
        if root.is_relative_to(self.app):
            raise RuntimeError("YuE must be installed outside the application directory")
        if not root.exists():
            if not shutil.which("git"):
                raise RuntimeError("git is missing; install it manually and retry")
            if not self.confirm(YUE_URL + " @ " + YUE_TAG, root, "source: tens of MiB; venv: many GiB",
                                "git clone the official YuE repository at the release tag"):
                return None
            protect_write_target(root)
            root.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="yue-clone-", dir=root.parent) as temporary:
                candidate = Path(temporary) / "YuE"
                self.execute(["git", "clone", "--depth", "1", "--branch", YUE_TAG, "--single-branch", YUE_URL, str(candidate)])
                if not (candidate / "pyproject.toml").is_file() or not (candidate / "skills/yue2-music/scripts/abc_tools.py").is_file():
                    raise RuntimeError("The cloned YuE repository lacks the required YuE2 files")
                if root.exists():
                    raise RuntimeError("YuE destination appeared during clone; it was not overwritten")
                os.rename(candidate, root)
        abc = root / "skills/yue2-music/scripts/abc_tools.py"
        if not (root / "pyproject.toml").is_file() or not abc.is_file():
            raise RuntimeError(f"Existing directory is not a usable YuE2 checkout: {root}")
        configured_path = Path(configured) if configured else None
        venv_dir = configured_path.parent.parent if configured_path and configured_path.is_file() and configured_path.is_relative_to(root) else root / "venv"
        version = "python3.12" if shutil.which("python3.12") else "python3"
        python = self.venv(venv_dir, version, "YuE2")
        if python is None:
            return None
        yue_info = python_probe(python) or {}
        if yue_info.get("python", [0, 0])[:2] < [3, 10]:
            raise RuntimeError("YuE2 Python must be 3.10 or newer; existing venv was not changed")
        installed = yue_info.get("packages", {}).get("yue2-infer")
        if installed and installed != "0.1.6":
            raise RuntimeError(f"Existing YuE2 environment is version {installed}; review it manually, no upgrade was attempted")
        if not installed:
            if not self.confirm(f"{root} (official pyproject.toml)", venv_dir,
                                "several GiB; PyTorch CUDA wheels are large", "python -m pip install . in the YuE2 venv"):
                return None
            protect_write_target(venv_dir)
            self.execute([str(python), "-m", "pip", "install", "."], cwd=root)
        self.proposals.update(python=str(python), abc_tools=str(abc))
        hf = python.parent / "hf"
        for repo, revision, folder, size, key in ((YUE_MODEL[0], YUE_MODEL[1], "YuE2-3B", "about 8-10 GiB", "model"),
                                                   (YUE_VAE[0], YUE_VAE[1], "YuE2-Vae", "about 0.6 GiB", "vae")):
            configured_model = self.config.get(key)
            if yue_model_ready(configured_model, repo, self.config.get("revision" if key == "model" else "vae_revision") or revision):
                print(f"Reuse configured {key} snapshot: {configured_model}")
                self.proposals[key] = configured_model
                continue
            if weight_snapshot(cached_snapshot(repo, revision)):
                print(f"Reuse official Hugging Face cache for {repo} @ {revision}")
                self.proposals[key] = repo
                continue
            target = self.external / folder
            if not hf.is_file() and not weight_snapshot(target):
                print(f"MANUAL: Hugging Face CLI is missing in {python.parent}; {key} download was skipped")
                continue
            if self.download(hf, repo, revision, target, size):
                self.proposals[key] = str(target)
        return python

    def sheet_stage(self, sheet_python="python3.11"):
        if not shutil.which(sheet_python) and shutil.which("python3.10"):
            sheet_python = "python3.10"
        configured = self.config.get("sheetsage_python")
        venv_dir = Path(configured).parent.parent if configured and Path(configured).is_file() else self.external / "sheetsage-venv"
        yue = self.proposals.get("python") or self.config.get("python")
        if yue and venv_dir.resolve() == Path(yue).parent.parent.resolve():
            raise RuntimeError("SheetSage2 and YuE2 must use separate venvs")
        python = self.venv(venv_dir, sheet_python, "SheetSage2")
        if python is None:
            return None
        sheet_info = python_probe(python) or {}
        if sheet_info.get("python", [0, 0])[:2] not in ([3, 10], [3, 11]):
            raise RuntimeError("SheetSage2 Python must be 3.10 or 3.11; existing venv was not changed")
        configured_model = self.config.get("sheetsage_model")
        if weight_snapshot(configured_model, merged=True):
            existing_package = sheet_package_for(configured_model, self.app)
            import_ok, detail = sheet_import_probe(python, existing_package)
            if import_ok:
                print(f"Reuse existing standalone SheetSage2 and local class: {configured_model}")
                self.proposals.update(sheetsage_python=str(python), sheetsage_model=str(configured_model))
                return python
            print(f"Existing SheetSage2 snapshot needs environment repair: {detail}")
        packages = (python_probe(python) or {}).get("packages", {})
        if not packages.get("huggingface-hub"):
            if not self.confirm("PyPI huggingface-hub==0.36.0", venv_dir, "<100 MiB",
                                "install the official model download CLI into the separate venv"):
                return None
            protect_write_target(venv_dir)
            self.execute([str(python), "-m", "pip", "install", "huggingface-hub==0.36.0"])
        hf = python.parent / "hf"
        if not hf.is_file():
            raise RuntimeError(f"Hugging Face CLI is unavailable: {hf}")
        source, mert = self.external / "SheetSage2", self.external / "MERT-v2-FullSong"
        if configured_model:
            sibling = Path(configured_model).parent
            if weight_snapshot(sibling / "SheetSage2"):
                source = sibling / "SheetSage2"
            if weight_snapshot(sibling / "MERT-v2-FullSong"):
                mert = sibling / "MERT-v2-FullSong"
        for repo, revision, target, size in ((SHEET_REPO, SHEET_REV, source, "about 0.25 GiB"),
                                              (MERT_REPO, MERT_REV, mert, "about 2.6 GiB")):
            if not self.download(hf, repo, revision, target, size):
                return None
        if not all((source / name).is_file() for name in ("__init__.py", "modeling_sheetsage2.py", "requirements.txt")):
            raise RuntimeError("SheetSage2 source package is missing required Python files")
        packages = (python_probe(python) or {}).get("packages", {})
        pins = pinned_requirements(source / "requirements.txt")
        if not all(pins.get(name) == version for name, version in (("torch", "2.8.0"), ("torchaudio", "2.8.0"),
                                                                    ("transformers", "4.45.2"), ("numpy", "1.24.3"))):
            raise RuntimeError("Unexpected SheetSage2 requirements; no package changes were made")
        mismatched = {name: (packages[name], version) for name, version in pins.items()
                      if name in packages and not matches_pin(packages[name], version)}
        if mismatched:
            raise RuntimeError(f"Existing SheetSage2 venv has different pinned packages: {mismatched}; review manually")
        if any(not matches_pin(packages.get(name), version) for name, version in pins.items()):
            if not self.confirm("https://download.pytorch.org/whl/cu126 and SheetSage2/requirements.txt", venv_dir,
                                "several GiB", "install missing torch/torchaudio 2.8.0 CUDA 12.6 and pinned SheetSage2 requirements"):
                return None
            protect_write_target(venv_dir)
            if not matches_pin(packages.get("torch"), "2.8.0") or not matches_pin(packages.get("torchaudio"), "2.8.0"):
                self.execute([str(python), "-m", "pip", "install", "torch==2.8.0", "torchaudio==2.8.0",
                              "--index-url", "https://download.pytorch.org/whl/cu126"])
            self.execute([str(python), "-m", "pip", "install", "-r", str(source / "requirements.txt")])
        import_ok, detail = sheet_import_probe(python, source)
        if not import_ok:
            raise RuntimeError(f"Direct SheetSage2Model import/melody_only check failed: {detail}")
        merged = Path(self.config.get("sheetsage_model") or self.external / "SheetSage2-standalone")
        if merged.exists() and not weight_snapshot(merged, merged=True):
            raise RuntimeError(f"Existing standalone directory is incomplete: {merged}; it was not changed")
        if not merged.exists():
            if not self.confirm(f"{source} + {mert}", merged, "about 3 GiB extra, plus substantial host RAM",
                                "merge MERT parent and SheetSage2 adapter using the local class; no transcription"):
                return None
            protect_write_target(merged)
            self.execute([str(python), "-B", str(self.app / "prepare_sheetsage.py"), str(source), str(mert), str(merged)])
        self.proposals.update(sheetsage_python=str(python), sheetsage_model=str(merged))
        return python

    def config_stage(self):
        print("\nSuggested config.local.json values / 設定候補:")
        print(json.dumps(self.proposals, ensure_ascii=False, indent=2))
        if self.config_path.exists():
            print(f"Existing config was not modified: {self.config_path}")
            return
        if not self.confirm("config.example.json and detected paths", self.config_path, "<2 KiB",
                            "create a local config; no credentials or tokens are stored"):
            return
        protect_write_target(self.config_path)
        config = read_json(self.app / "config.example.json")
        if not isinstance(config, dict):
            raise RuntimeError("config.example.json is invalid")
        config.update(self.proposals)
        self.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(self.config_path, 0o600)


def load_check(kind, app=APP, config_path=None):
    config = read_json(config_path or app / "config.local.json")
    if not isinstance(config, dict):
        raise RuntimeError("Create config.local.json before running a load check")
    print("This loads model weights but does not transcribe audio or generate music.")
    try:
        approved = input("Proceed with the large model load? / モデルを読み込みますか？ [y/N] ").strip().lower()
    except EOFError:
        approved = ""
    if approved not in ("y", "yes"):
        return
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1",
           "TRANSFORMERS_OFFLINE": "1", "PYTHONUNBUFFERED": "1"}
    if kind == "yue":
        runtime = {key: config.get(key) for key in ("python", "model", "vae", "device", "pipeline",
                                                    "revision", "vae_revision", "cache_dir")}
        process = subprocess.run([config["python"], "-B", "-u", str(app / "worker.py")],
                                 input=json.dumps({"type": "init", "job_id": None, "runtime": runtime}) + "\n",
                                 capture_output=True, text=True, cwd=app, env=env, timeout=360)
        events = [json.loads(line) for line in process.stdout.splitlines() if line.startswith("{")]
        if not any(event.get("type") == "ready" for event in events):
            raise RuntimeError("YuE2 worker load failed: " + process.stderr[-1000:])
        print("OK YuE2 worker reached ready; no generation was run")
    else:
        model = config.get("sheetsage_model")
        package = sheet_package_for(model, app) if model else None
        if not package:
            raise RuntimeError("Local SheetSage2 Python package not found")
        script = ("import inspect,sys\n"
                  "sys.path.insert(0,sys.argv[1])\n"
                  "from SheetSage2.modeling_sheetsage2 import SheetSage2Model\n"
                  "model=SheetSage2Model.from_pretrained(sys.argv[2],local_files_only=True).eval()\n"
                  "assert 'melody_only' in inspect.signature(model.transcribe).parameters\n"
                  "print('OK standalone model loaded with direct class and melody_only')\n")
        result = subprocess.run([config["sheetsage_python"], "-B", "-c", script,
                                 str(package.parent), str(model)], capture_output=True, text=True,
                                cwd=app, env=env, timeout=360)
        if result.returncode:
            raise RuntimeError("SheetSage2 standalone load failed: " + result.stderr[-1000:])
        print(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser(description="YuE2 Local Studio setup and diagnostics")
    parser.add_argument("--doctor", action="store_true", help="read-only diagnostics")
    parser.add_argument("--stage", choices=("app", "yue", "cover"), help="interactive setup stage")
    parser.add_argument("--external-dir", type=Path, help="external directory for source and models")
    parser.add_argument("--yue-dir", type=Path, help="reuse or clone the YuE directory")
    parser.add_argument("--config", type=Path, help="alternate local config path")
    parser.add_argument("--load-check", choices=("yue", "sheet"), help="optional large model load check")
    args = parser.parse_args()
    if args.doctor:
        report(APP, args.config)
        return 0
    if args.load_check:
        try:
            load_check(args.load_check, APP, args.config)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"Load check failed: {exc}", file=sys.stderr)
            return 2
        return 0
    stage = args.stage
    if not stage:
        print("1: app only / アプリのみ\n2: app + YuE2 / 通常生成まで\n3: app + YuE2 + SheetSage2 / Cover・Motifまで")
        try:
            stage = {"1": "app", "2": "yue", "3": "cover"}.get(input("Select / 選択 [1/2/3]: ").strip())
        except EOFError:
            stage = None
        if not stage:
            raise SystemExit("No stage selected")
    try:
        installer = Installer(config_path=args.config, external=args.external_dir)
        if installer.app_stage() is None:
            print("Application stage stopped by user choice")
            return 1
        if stage in ("yue", "cover"):
            if installer.yue_stage(args.yue_dir) is None:
                installer.config_stage()
                print("YuE2 stage stopped by user choice")
                return 1
        if stage == "cover":
            if installer.sheet_stage() is None:
                installer.config_stage()
                print("SheetSage2 stage stopped by user choice")
                return 1
        installer.config_stage()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"STOPPED / 停止: {exc}", file=sys.stderr)
        print("Existing environments and config were retained. Fix the issue and rerun the same stage.", file=sys.stderr)
        return 2
    report(APP, args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
