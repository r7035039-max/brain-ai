"""Discover local GGUF files and run one llama.cpp model at a time."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
DEFAULT_PORT = 8080
LOOPBACK = urllib.request.build_opener(urllib.request.ProxyHandler({}))
REQUEST_TIMEOUT = max(60, int(os.environ.get("BRAIN_AI_REQUEST_TIMEOUT", "3600")))


class ModelUnavailable(RuntimeError):
    """The requested model or the local server could not be started."""


@dataclass(frozen=True)
class Weight:
    repo: str
    filename: str
    sha256: str
    min_bytes: int = 1_000_000_000

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.filename}"


@dataclass(frozen=True)
class Model:
    alias: str
    weights: Weight
    context: int
    projector: Weight | None = None


MODELS = {
    "chat": Model(
        "Qwen3-4B",
        Weight("ggml-org/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf",
               "ab27b9bfa375a178d6cba48f3ad892b94b7739659dcc7aae8058ce0ffed6b328"),
        8192,
    ),
    "coder": Model(
        "Qwen2.5-Coder-7B-Instruct",
        Weight("Qwen/Qwen2.5-Coder-7B-Instruct-GGUF", "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
               "509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c"),
        8192,
    ),
    "vision": Model(
        "Qwen3-VL-4B-Instruct",
        Weight("Qwen/Qwen3-VL-4B-Instruct-GGUF", "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
               "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a"),
        4096,
        Weight("Qwen/Qwen3-VL-4B-Instruct-GGUF", "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
               "30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d",
               min_bytes=100_000_000),
    ),
}
PATH_VARS = {
    "chat": "BRAIN_AI_CHAT_MODEL",
    "coder": "BRAIN_AI_CODER_MODEL",
    "vision": "BRAIN_AI_VISION_MODEL",
}


def _as_path(value: str) -> Path:
    path = Path(os.path.expandvars(value.strip().strip('"'))).expanduser()
    return path if path.is_absolute() else ROOT / path


def find_server() -> Path | None:
    if override := os.environ.get("BRAIN_AI_LLAMA_SERVER"):
        candidate = _as_path(override)
        if candidate.is_file():
            return candidate
    names = ("llama-server.exe", "llama-server", "llama.exe", "llama")
    for name in names:
        if found := shutil.which(name):
            return Path(found).resolve()
    for folder in (ROOT, ROOT / "llama.cpp", ROOT / "bin", ROOT / "llama.cpp/build/bin"):
        for name in names:
            if (folder / name).is_file():
                return (folder / name).resolve()
    if local := os.environ.get("LOCALAPPDATA"):
        packages = Path(local) / "Microsoft/WinGet/Packages"
        for folder in sorted(packages.glob("ggml.llamacpp*"), reverse=True):
            for name in names:
                for candidate in folder.rglob(name):
                    if candidate.is_file():
                        return candidate.resolve()
    return None


def _valid_gguf(path: Path, minimum: int) -> bool:
    try:
        if path.stat().st_size < minimum:
            return False
        with path.open("rb") as file:
            return file.read(4) == b"GGUF"
    except OSError:
        return False


def _known_weights(role: str, weight: Weight, *, projector: bool = False) -> Path | None:
    override = os.environ.get("BRAIN_AI_VISION_PROJECTOR" if projector else PATH_VARS[role])
    candidates = [_as_path(override)] if override else []
    if role == "chat":
        if legacy_path := os.environ.get("BRAIN_AI_MODEL"):
            candidates.append(_as_path(legacy_path))
        try:
            candidates.append(_as_path((ROOT / "model_path.txt").read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeError):
            pass

    home = Path.home()
    names = [weight.filename]
    if role == "coder":
        names.append("qwen2.5-coder-7b-instruct-q4_k_m-00001-of-00002.gguf")
    folders = [ROOT / "models", ROOT / "llama.cpp/models", ROOT / "ckpt",
               ROOT / "data", home / "Downloads", ROOT]
    candidates.extend(folder / name for folder in folders for name in names)
    candidates.extend(path for name in names for path in (ROOT / "models").rglob(name))

    hf_caches = [home / ".cache/huggingface/hub"]
    for key in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if value := os.environ.get(key):
            hf_caches.insert(0, _as_path(value))
    if value := os.environ.get("HF_HOME"):
        hf_caches.insert(0, _as_path(value) / "hub")
    repos = [weight.repo]
    if role == "chat":
        repos.append("Qwen/Qwen3-4B-GGUF")
    for cache in hf_caches:
        for repo in repos:
            snapshots = cache / ("models--" + repo.replace("/", "--")) / "snapshots"
            for name in names:
                candidates.extend(snapshots.glob(f"*/{name}"))

    llama_caches = [home / ".cache/llama.cpp"]
    if value := os.environ.get("LOCALAPPDATA"):
        llama_caches.append(Path(value) / "llama.cpp")
    if value := os.environ.get("LLAMA_CACHE"):
        llama_caches.insert(0, _as_path(value))
    for cache in llama_caches:
        for name in names:
            candidates.extend(cache.glob(f"*{name}"))

    for candidate in candidates:
        if not _valid_gguf(candidate, weight.min_bytes):
            continue
        shard = re.search(r"-(\d{5})-of-(\d{5})\.gguf$", candidate.name, re.I)
        if shard:
            if shard[1] != "00001":
                continue
            prefix = candidate.name[:shard.start()]
            if not all(_valid_gguf(candidate.with_name(
                f"{prefix}-{number:05d}-of-{shard[2]}.gguf"
            ), 1) for number in range(2, int(shard[2]) + 1)):
                continue
        # Preserve shard filenames if this is a symlink into the HF cache.
        return candidate.absolute()
    return None


def model_paths(role: str) -> tuple[Path | None, Path | None]:
    spec = MODELS[role]
    path = _known_weights(role, spec.weights)
    projector = _known_weights(role, spec.projector, projector=True) if spec.projector else None
    return path, projector


def download_models(roles: list[str]) -> None:
    """Download the official model files once, with resume and SHA-256 checking."""
    curl = shutil.which("curl.exe") or shutil.which("curl")
    for role in dict.fromkeys(roles):
        spec = MODELS[role]
        path, projector = model_paths(role)
        files = [(path, spec.weights)]
        if spec.projector:
            files.append((projector, spec.projector))
        for existing, weight in files:
            if existing:
                print(f"Found {existing}")
                continue
            if not curl:
                raise ModelUnavailable(f"curl is required to download {weight.filename}. Download it to models/ from {weight.url}")
            directory = ROOT / "models"
            directory.mkdir(exist_ok=True)
            destination = directory / weight.filename
            partial = destination.with_suffix(".gguf.part")
            print(f"Downloading {weight.filename}", flush=True)
            result = subprocess.run([
                curl, "--fail", "--location", "--continue-at", "-", "--retry", "2",
                "--connect-timeout", "20", "--speed-limit", "1024", "--speed-time", "120",
                "--progress-bar", "--output", str(partial), weight.url,
            ])
            if _valid_gguf(partial, weight.min_bytes):
                print(f"Checking SHA-256 for {weight.filename}", flush=True)
                with partial.open("rb") as file:
                    digest = hashlib.file_digest(file, "sha256").hexdigest()
                if digest == weight.sha256:
                    partial.replace(destination)
                    continue
            if result.returncode:
                raise ModelUnavailable(f"Download interrupted for {weight.filename}. Run the same command to resume.")
            # curl finished, so keep an invalid file from being resumed next time.
            partial.unlink(missing_ok=True)
            raise ModelUnavailable(f"Checksum failed for {weight.filename}. Run the download again.")


def _preferred_port() -> int:
    value = os.environ.get("BRAIN_AI_PORT", str(DEFAULT_PORT))
    try:
        port = int(value)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise ModelUnavailable("Set BRAIN_AI_PORT to a number from 1 to 65535.")
    return port


def _chat_gpu_layers() -> int:
    value = os.environ.get("BRAIN_AI_CHAT_GPU_LAYERS", "0")
    try:
        layers = int(value)
    except ValueError as error:
        raise ModelUnavailable("Set BRAIN_AI_CHAT_GPU_LAYERS to a nonnegative integer.") from error
    if layers < 0:
        raise ModelUnavailable("Set BRAIN_AI_CHAT_GPU_LAYERS to a nonnegative integer.")
    return layers


def _available_port(preferred: int) -> int:
    # Ask the OS to pick a free port if the preferred one cannot be bound.
    for port in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind((HOST, port))
                return probe.getsockname()[1]
        except OSError as error:
            if port == 0:
                raise ModelUnavailable(f"Could not find a free local port: {error}") from error


def _server_ids(port: int) -> tuple[str, ...]:
    try:
        with LOOPBACK.open(f"http://{HOST}:{port}/v1/models", timeout=1) as response:
            rows = json.load(response)["data"]
        return tuple(row["id"] for row in rows
                     if isinstance(row, dict) and isinstance(row.get("id"), str))
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


class ModelRuntime:
    def __init__(self) -> None:
        self._requests = threading.Lock()
        self._process_lock = threading.Lock()
        self._closed = threading.Event()
        self._process: subprocess.Popen | None = None
        self._role: str | None = None
        self._port: int | None = None
        self._chat_gpu_failed = False
        self._metric_lock = threading.Lock()
        self._metrics = {'role': None, 'model': None, 'state': 'idle', 'task': 'Ready',
                         'request_started': None, 'last_elapsed': None, 'completion_tokens': 0,
                         'tokens_per_second': None, 'last_error': None}

    def _metric(self, **values):
        with self._metric_lock:
            self._metrics.update(values)

    def report_task(self, text):
        self._metric(task=str(text)[:250])

    def metrics(self):
        with self._metric_lock:
            values = dict(self._metrics)
        with self._process_lock:
            process = self._process
            values['process_pid'] = process.pid if process is not None and process.poll() is None else None
        values['elapsed'] = (time.monotonic() - values['request_started']
                             if values['request_started'] else values['last_elapsed'])
        return values

    def interrupt(self):
        """Stop an owned request/server; future requests can load a model again."""
        with self._process_lock:
            owned = self._process is not None
        if owned: self._stop_owned()
        return owned

    def _stop_owned(self) -> None:
        with self._process_lock:
            if self._process is not None:
                _stop(self._process)
                self._process = None
            self._role = None
            self._port = None

    def unload(self) -> None:
        with self._requests:
            self._stop_owned()

    def close(self) -> None:
        self._closed.set()
        self._stop_owned()

    def status(self) -> str:
        try:
            port = self._port or _preferred_port()
        except ModelUnavailable as error:
            return str(error)
        ids = _server_ids(port)
        return f"{', '.join(ids)} at {HOST}:{port}" if ids else "No model loaded"

    def activate(self, role: str, progress) -> None:
        with self._requests:
            self._ensure(role, progress)

    def _ensure(self, role: str, progress) -> tuple[str, int]:
        if self._closed.is_set():
            raise ModelUnavailable("Brain AI is closing.")
        spec = MODELS[role]
        preferred = _preferred_port()
        with self._process_lock:
            process, active_role, active_port = self._process, self._role, self._port
        running = process is not None and process.poll() is None
        if running and active_role == role and active_port is not None:
            return spec.alias, active_port
        gpu_layers = _chat_gpu_layers() if role == "chat" and not self._chat_gpu_failed else 0

        # Keep support for a chat server the user started at the preferred port.
        if role == "chat" and not gpu_layers and (not running or active_port != preferred):
            ids = _server_ids(preferred)
            if ids:
                self._stop_owned()
                return ids[0], preferred

        model, projector = model_paths(role)
        if model is None or (spec.projector and projector is None):
            raise ModelUnavailable(f"{spec.alias} files are missing. Run: python main.py --download-models {role}")
        exe = find_server()
        if not exe:
            raise ModelUnavailable("llama-server was not found. Install llama.cpp or set BRAIN_AI_LLAMA_SERVER to its path.")

        self._stop_owned()
        if gpu_layers:
            try:
                return self._start_model(role, spec, model, projector, exe, preferred, gpu_layers, progress)
            except ModelUnavailable:
                if self._closed.is_set():
                    raise
                self._chat_gpu_failed = True
                progress("Qwen3 could not start on Vulkan. Using CPU for this session.")
        return self._start_model(role, spec, model, projector, exe, preferred, 0, progress)

    def _start_model(self, role: str, spec: Model, model: Path, projector: Path | None,
                     exe: Path, preferred: int, gpu_layers: int, progress) -> tuple[str, int]:
        port = _available_port(preferred)
        if port != preferred:
            progress(f"Port {preferred} is unavailable. Using {HOST}:{port}.")
        device = "Vulkan0" if gpu_layers else "none"
        target = f"Vulkan ({gpu_layers} GPU layers)" if gpu_layers else "CPU"
        progress(f"Loading {spec.alias} on {target} at {HOST}:{port} ...")

        command = [str(exe)]
        if exe.name.lower() in {"llama", "llama.exe"}:
            command.append("serve")
        command.extend([
            "-m", str(model), "--alias", spec.alias, "--host", HOST, "--port", str(port),
            "-c", str(spec.context), "-np", "1", "--cache-ram", "0",
            "--device", device, "-ngl", str(gpu_layers), "--no-op-offload", "--no-kv-offload",
        ])
        if gpu_layers:
            command.extend(["-b", "128", "-ub", "64"])
        if projector:
            command.extend(["--mmproj", str(projector), "--no-mmproj-offload"])
        env = os.environ.copy()
        env["PATH"] = str(exe.parent) + os.pathsep + env.get("PATH", "")
        env.pop("LLAMA_ARG_DEVICE", None)
        if not gpu_layers:
            env["GGML_VK_VISIBLE_DEVICES"] = ""
        suffix = "_vulkan" if gpu_layers else ""
        log_path = ROOT / f"llama_server_{role}{suffix}.log"
        with self._process_lock, log_path.open("w", encoding="utf-8") as log:
            if self._closed.is_set():
                raise ModelUnavailable("Brain AI is closing.")
            print(f"Command: {command!r}", file=log, flush=True)
            try:
                process = subprocess.Popen(
                    command, cwd=exe.parent, env=env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as error:
                raise ModelUnavailable(f"Could not launch {exe.name}: {error}") from error
            self._process = process
            self._port = port
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline and not self._closed.is_set():
                if process.poll() is not None:
                    break
                if spec.alias in _server_ids(port) and process.poll() is None:
                    with self._process_lock:
                        if self._closed.is_set():
                            break
                        self._role = role
                    progress(f"{spec.alias} ready on {target} at {HOST}:{port}")
                    return spec.alias, port
                self._closed.wait(0.5)
        except BaseException:
            self._stop_owned()
            raise
        self._stop_owned()
        raise ModelUnavailable(f"{spec.alias} could not start at {HOST}:{port}. See {log_path.name}.")

    def complete(self, role: str, messages: list[dict], *, max_tokens: int,
                 temperature: float = 0.2, progress=None, require_complete: bool = False,
                 json_output: bool = False) -> str:
        with self._requests:
            self._metric(role=role, model=MODELS[role].alias, state='loading', last_error=None,
                         request_started=time.monotonic())
            try:
                model, port = self._ensure(role, progress or (lambda _: None))
            except Exception as error:
                self._metric(state='idle', request_started=None, last_error=str(error))
                raise
            started = time.monotonic()
            self._metric(state='generating', model=model, request_started=started)
            payload = {
                "model": model, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "stream": False,
            }
            if json_output:
                payload["response_format"] = {"type": "json_object"}
            request = urllib.request.Request(
                f"http://{HOST}:{port}/v1/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with LOOPBACK.open(request, timeout=REQUEST_TIMEOUT) as response:
                    result = json.load(response)
            except urllib.error.HTTPError as error:
                detail = error.read(1500).decode("utf-8", errors="replace")
                self._metric(state='idle', request_started=None, last_error=detail, last_elapsed=time.monotonic()-started)
                raise RuntimeError(f"{model} HTTP {error.code}: {detail}") from error
            except (OSError, ValueError) as error:
                self._metric(state='idle', request_started=None, last_error=str(error), last_elapsed=time.monotonic()-started)
                raise ModelUnavailable(f"{model} request failed: {error}") from error
            elapsed = max(.001, time.monotonic() - started)
            tokens = result.get('usage', {}).get('completion_tokens', 0)
            timings = result.get('timings', {})
            speed = timings.get('predicted_per_second') or (tokens / elapsed if tokens else None)
            self._metric(state='idle', request_started=None, last_elapsed=elapsed,
                         completion_tokens=tokens, tokens_per_second=speed)
            choice = result["choices"][0]
            content = choice["message"].get("content") or ""
            answer = re.sub(r"<think>[\s\S]*?(?:</think>|\Z)", "", content).strip()
            if not answer or ((require_complete or json_output) and choice.get("finish_reason") == "length"):
                self._metric(last_error='Empty or truncated response')
                raise ValueError(f"{model} returned an empty or truncated answer.")
            return answer


runtime = ModelRuntime()
