"""Static project checks and game metadata; never executes generated source."""
from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import json
import os
import re
import shlex
import sys
import time
import uuid
from pathlib import Path, PurePosixPath

# Import names and PyPI distribution names are not always the same.
DISTRIBUTIONS = {
    "pygame": ("pygame", "pygame-ce"), "ursina": ("ursina",),
    "pil": ("Pillow",), "cv2": ("opencv-python", "opencv-python-headless"),
    "yaml": ("PyYAML",), "dotenv": ("python-dotenv",),
    "panda3d": ("panda3d", "ursina"), "direct": ("panda3d", "ursina"),
    "numpy": ("numpy",), "matplotlib": ("matplotlib",),
    "pandas": ("pandas",), "requests": ("requests",),
    "pyglet": ("pyglet",), "pymunk": ("pymunk",), "arcade": ("arcade",),
    "moderngl": ("moderngl",), "opengl": ("PyOpenGL",),
    "psutil": ("psutil",), "pydantic": ("pydantic",),
    "customtkinter": ("customtkinter",), "pyautogui": ("PyAutoGUI",),
    "sklearn": ("scikit-learn",), "bs4": ("beautifulsoup4",),
}


def normalized(name):
    return re.sub(r"[-_.]+", "_", name).casefold()


def clean_requirements(text):
    """Keep pip entries; turn accidental prose into comments instead of packages.

    Prefer the standard packaging parser, or pip's bundled copy. Leave pip's
    option, URL, local-path and continued entries intact rather than trying to
    reinterpret its complete requirements-file grammar.
    """
    try:
        from packaging.requirements import Requirement, InvalidRequirement
    except ImportError:
        try:
            from pip._vendor.packaging.requirements import Requirement, InvalidRequirement
        except ImportError:
            Requirement = None
            InvalidRequirement = ValueError
    lines = []
    continuation = False
    for line in text.lstrip('\ufeff').splitlines():
        stripped = line.strip()
        if re.fullmatch(r'(?:`{3,}|~{3,})\s*[\w.+-]*', stripped):
            continue
        pip_special = (continuation or not stripped or stripped.startswith(('#', '-', '.', '/', '\\'))
                       or bool(re.match(r'(?:[a-zA-Z]:[\\/]|(?:https?|file|git\+\w+|hg\+\w+|svn\+\w+)://)', stripped))
                       or stripped.endswith(('\\', '.whl', '.tar.gz', '.zip')))
        continuation = stripped.endswith('\\')
        if pip_special:
            lines.append(line)
            continue
        candidate = re.split(r'\s+#', stripped, maxsplit=1)[0]
        candidate = re.split(r'\s+--hash(?:=|\s)', candidate, maxsplit=1)[0]
        try:
            if Requirement is not None:
                Requirement(candidate)
            elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[\w.,-]+\])?'
                                 r'(?:\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[\w.*+!,-]+)*'
                                 r'(?:\s*;\s*.+)?', candidate):
                raise ValueError('Not a dependency specification')
        except InvalidRequirement:
            lines.append('# Brain AI: non-requirement text: ' + line)
        else:
            lines.append(line)
    return '\n'.join(lines).rstrip() + '\n' if lines else ''


def clean_requirements_file(path):
    """Back up the original, then atomically repair dependency-file formatting."""
    path = Path(path)
    original = path.read_text(encoding='utf-8-sig')
    cleaned = clean_requirements(original)
    if original == cleaned:
        return False
    backup = path.with_name(path.name + '.before-cleaning')
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    temporary = path.with_name(path.name + '.cleaning.tmp')
    temporary.write_text(cleaned, encoding='utf-8')
    temporary.replace(path)
    return True


def declared_packages(text):
    result = {}
    for line in clean_requirements(text).splitlines():
        match = re.match(r"\s*([a-zA-Z][a-zA-Z0-9_.-]*)(?=\s|[<>=!~;\[@]|$)", line)
        if match:
            result[normalized(match[1])] = match[1]
    return result


def _module_names(paths):
    names = set()
    for filename in paths:
        path = PurePosixPath(str(filename).replace("\\", "/"))
        if path.suffix.lower() != ".py":
            continue
        parts = path.with_suffix("").parts
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        names.update(".".join(parts[:end]) for end in range(1, len(parts) + 1))
    return names


def _imports(tree, optional=False):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node, optional
        elif isinstance(node, ast.Try):
            guarded = any(
                isinstance(t, ast.Name) and t.id in {"ImportError", "ModuleNotFoundError"}
                for handler in node.handlers if handler.type is not None
                for t in ast.walk(handler.type)
            )
            for child in node.body:
                wrapper = ast.Module(body=[child], type_ignores=[])
                yield from _imports(wrapper, optional or guarded)
            for child in [*node.handlers, *node.orelse, *node.finalbody]:
                yield from _imports(ast.Module(body=[child], type_ignores=[]), optional)
        elif isinstance(node, ast.If) and (
            isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
            or isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING"
        ):
            for child in node.body:
                yield from _imports(ast.Module(body=[child], type_ignores=[]), True)
            for child in node.orelse:
                yield from _imports(ast.Module(body=[child], type_ignores=[]), optional)
        else:
            yield from _imports(node, optional)


def analyze_imports(completed, planned_paths=()):
    """Separate broken planned/local imports from environment dependencies.

    No generated module is imported. Unknown external names need human review;
    they are never blindly converted into pip install commands.
    """
    sources = {name: value for name, value in completed.items() if name.lower().endswith(".py")}
    actual = _module_names(sources)
    planned = actual | _module_names(planned_paths)
    local_roots = {name.split(".")[0] for name in planned}
    declared = declared_packages(completed.get("requirements.txt", ""))
    excluded = {Path(__file__).resolve().parent, Path.cwd().resolve()}
    search_paths = [p for p in sys.path if p and Path(p).resolve() not in excluded]
    availability = {}
    errors, warnings, missing, packages, unknown, undeclared = {}, [], set(), set(), set(), set()
    suggestions = set()
    for filename, source in sources.items():
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            errors.setdefault(filename, []).append(str(error))
            continue
        parent = list(PurePosixPath(filename).parent.parts)
        for node, optional in _imports(tree):
            relative = isinstance(node, ast.ImportFrom) and node.level > 0
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif relative:
                if len(parent) < node.level:
                    errors.setdefault(filename, []).append(f"line {node.lineno}: relative import outside its package")
                    continue
                parts = parent[:len(parent) - node.level + 1]
                modules = [".".join(parts + ([node.module] if node.module else []))]
                if node.module is None:
                    # `from . import helper` can also import exports of __init__.
                    init = "/".join(parts + ["__init__.py"])
                    exports = set()
                    if init in sources:
                        try:
                            for child in ast.walk(ast.parse(sources[init])):
                                if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                                    exports.add(child.name)
                                elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                                    exports.add(child.id)
                                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                                    exports.update(a.asname or a.name.split(".")[-1] for a in child.names)
                        except SyntaxError:
                            pass
                    modules += [".".join(parts + [a.name]) for a in node.names
                                if a.name != "*" and a.name not in exports]
            else:
                modules = [node.module or ""]
            for module in modules:
                root = module.split(".")[0]
                if relative or root in local_roots:
                    if module not in actual:
                        errors.setdefault(filename, []).append(
                            f"line {node.lineno}: local module {module!r} is missing; create/fix the project file"
                        )
                    continue
                if root in sys.stdlib_module_names or root in sys.builtin_module_names:
                    continue
                if optional:
                    continue
                aliases = DISTRIBUTIONS.get(root.casefold(), (root,))
                matched = next((declared[normalized(a)] for a in aliases if normalized(a) in declared), None)
                if root not in availability:
                    try:
                        availability[root] = importlib.machinery.PathFinder.find_spec(root, search_paths) is not None
                    except (ImportError, ValueError, OSError):
                        availability[root] = False
                if not matched:
                    undeclared.add(root)
                    if root.casefold() in DISTRIBUTIONS:
                        suggestions.add(aliases[0])
                if not availability[root]:
                    missing.add(root)
                    if matched or root.casefold() in DISTRIBUTIONS:
                        packages.add(matched or aliases[0])
                    else:
                        unknown.add(root)
    if missing:
        warnings.append("Packages needed in this Python environment: " + ", ".join(sorted(missing)))
    if undeclared:
        warnings.append("Check requirements.txt for these imports: " + ", ".join(sorted(undeclared)))
    if unknown:
        warnings.append("Unclassified imports (check local files or package names): " + ", ".join(sorted(unknown)))
    return {"local_errors": errors, "dependency_warnings": warnings,
            "missing_modules": sorted(missing), "missing_packages": sorted(packages),
            "unclassified_modules": sorted(unknown), "suggested_requirements": sorted(suggestions)}


def read_project_sources(folder):
    folder = Path(folder).resolve()
    sources = {}
    ignored = {".venv", "venv", "node_modules", "test_runs", "__pycache__", ".git",
               ".brain_history", ".brain_changes", "exports", "dist"}
    for parent, directories, files in os.walk(folder, followlinks=False):
        directories[:] = [name for name in directories if name not in ignored
                          and not name.startswith("brain_ai_backup")]
        for name in files:
            if (not name.lower().endswith(('.py', '.json', '.html', '.css', '.js', '.toml'))
                    or name.startswith('.') or name in {'game.json', 'build_report.json', 'dependency_report.json'}):
                continue
            path = Path(parent) / name
            if path.resolve().is_relative_to(folder) and path.stat().st_size <= 1_000_000:
                sources[path.relative_to(folder).as_posix()] = path.read_text(encoding="utf-8-sig", errors="replace")
            if len(sources) >= 200:
                break
        if len(sources) >= 200:
            break
    req = folder / "requirements.txt"
    if req.is_file():
        sources["requirements.txt"] = req.read_text(encoding="utf-8-sig", errors="replace")[:100_000]
    return sources


def read_json(path):
    try:
        if Path(path).stat().st_size <= 1_000_000:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def dependency_status(script):
    script = Path(script).resolve()
    sources = ({script.name: script.read_text(encoding="utf-8-sig", errors="replace")}
               if (script.parent / "model_runtime.py").is_file() and script.name in {"minecraft.py", "mincraft.py"}
               else read_project_sources(script.parent))
    report = read_json(script.parent / "build_report.json")
    planned = report.get("planned_files", report.get("generated_files", []))
    planned = [p for p in planned if isinstance(p, str)] if isinstance(planned, list) else []
    return analyze_imports(sources, planned)


def environment_failure(log, script):
    matches = re.findall(r"ModuleNotFoundError:\s*No module named ['\"]([\w.]+)['\"]", log)
    if not matches:
        return None
    module = matches[-1]
    if '.' in module:
        # A present library with an invalid submodule needs code/API diagnosis.
        try:
            if importlib.machinery.PathFinder.find_spec(module.split('.')[0]) is not None:
                return None
        except (ImportError, ValueError, OSError):
            pass
    sources = read_project_sources(Path(script).parent)
    report = read_json(Path(script).parent / "build_report.json")
    planned = report.get("planned_files", report.get("generated_files", []))
    paths = [p for p in planned if isinstance(p, str)] if isinstance(planned, list) else []
    local = _module_names([*sources, *paths])
    if module.split(".")[0] in {name.split(".")[0] for name in local}:
        return None
    return module


def python_executable():
    executable = Path(sys.executable)
    console = executable.with_name("python.exe")
    return str(console) if executable.name.casefold() == "pythonw.exe" and console.is_file() else str(executable)


def install_args(folder):
    # Isolated mode prevents a generated pip.py from shadowing the installer.
    return [python_executable(), "-I", "-m", "pip", "install", "-r", str(Path(folder) / "requirements.txt"), '--only-binary=:all:']


def install_command(folder, *, windows=None):
    args = install_args(folder)
    on_windows = os.name == "nt" if windows is None else windows
    if on_windows:
        return "& " + " ".join("'" + a.replace("'", "''") + "'" for a in args)
    return shlex.join(args)


def game_title(source, task, fallback):
    try:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_caption":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    return node.args[0].value[:80]
    except SyntaxError:
        pass
    title = re.sub(r"^(?:please\s+)?(?:make|create|build|develop)\s+(?:me\s+)?(?:a\s+|an\s+)?", "", task.strip(), flags=re.I)
    title = re.split(r"[\n.!]", title)[0].strip()[:70]
    return title[:1].upper() + title[1:] if title else fallback


def game_metadata_path(script, built_in=False):
    script = Path(script)
    return script.with_suffix('.game.json') if built_in else script.parent / 'game.json'


def update_game_metadata(script, updates, built_in=False):
    path = game_metadata_path(script, built_in)
    metadata = read_json(path)
    metadata.update(updates)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex[:8] + '.tmp')
    temporary.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
    return metadata


def project_fingerprint(script):
    """Changing game code or dependencies invalidates a previous passing test."""
    script = Path(script).resolve()
    try:
        if (script.parent / 'model_runtime.py').is_file() and script.name in {'minecraft.py', 'mincraft.py'}:
            sources = {script.name: script.read_text(encoding='utf-8-sig', errors='replace')}
        else:
            sources = read_project_sources(script.parent)
        if script.name not in sources:
            return None
        digest = hashlib.sha256()
        for item in (script.name, sys.executable, sys.version):
            digest.update(item.encode('utf-8') + b'\0')
        for name, source in sorted(sources.items()):
            digest.update(name.encode('utf-8') + b'\0' + source.encode('utf-8') + b'\0')
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def game_test_status(script):
    script = Path(script)
    folder = script.parent / 'test_runs'
    if folder.is_dir():
        reports = sorted(folder.glob('run-*/report.json'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for path in reports:
            if not path.resolve().is_relative_to(folder.resolve()):
                continue
            report = read_json(path)
            if report.get('game') != script.name:
                continue
            current = project_fingerprint(script)
            if report.get('source_hash') and report.get('source_hash') != current:
                return {'test_status': 'stale', 'test_label': 'Code changed · retest', 'test_report': path}
            if (current and report.get('status') == 'passed' and report.get('passed') is True
                    and report.get('source_hash') == current):
                label = ('Passed gameplay checks' if report.get('scope') in {'gameplay_and_visual', 'movement_jump_collision_win_lose'}
                         else 'Passed gameplay preview')
                return {'test_status': 'passed', 'test_label': label, 'test_report': path}
            if report.get('status') in {'failed', 'dependencies_missing', 'windows_policy_block', 'no_frame'}:
                return {'test_status': 'failed', 'test_label': 'Needs work · test failed', 'test_report': path}
            return {'test_status': 'incomplete', 'test_label': 'Test incomplete · retest', 'test_report': path}
    return {'test_status': 'untested', 'test_label': 'Not tested', 'test_report': None}


def _project_directories(root):
    root = Path(root).resolve()
    workspace = root / 'workspace'
    if workspace.is_symlink():
        raise ValueError('The workspace must be a regular folder inside Brain AI.')
    return root, workspace


def trash_game(root, script):
    """Move one generated project to recoverable trash; never delete app files."""
    root, workspace = _project_directories(root)
    script = Path(script).resolve()
    try:
        relative = script.relative_to(workspace)
    except ValueError as error:
        raise ValueError('Only generated games inside the workspace can be deleted.') from error
    resumable = script.name == 'main.py' and ((script.parent / '.brain_build.json').is_file() or (script.parent / 'build_report.json').is_file())
    if len(relative.parts) < 2 or not (script.is_file() or resumable):
        raise ValueError('Select a generated game, not the workspace or app folder.')
    project = workspace / relative.parts[0]
    if project.is_symlink() or not project.is_dir():
        raise ValueError('The selected project is not a regular game folder.')
    trash = root / '.game_trash'
    if trash.is_symlink():
        raise ValueError('The game trash folder cannot be a symlink.')
    token = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    container = trash / token
    container.mkdir(parents=True)
    manifest = container / 'deleted_game.json'
    try:
        manifest.write_text(json.dumps({'name': project.name, 'entry_point': relative.as_posix(),
                                       'deleted_at': time.time()}, indent=2), encoding='utf-8')
        project.rename(container / project.name)
    except Exception:
        manifest.unlink(missing_ok=True)
        container.rmdir()
        raise
    return token


def deleted_games(root):
    root, _ = _project_directories(root)
    trash = root / '.game_trash'
    result = []
    if not trash.is_dir() or trash.is_symlink():
        return result
    for container in trash.iterdir():
        if container.is_symlink() or not container.is_dir():
            continue
        manifest = read_json(container / 'deleted_game.json')
        name = manifest.get('name')
        if not isinstance(name, str) or name in {'', '.', '..'} or Path(name).name != name or '/' in name or '\\' in name:
            continue
        project = container / name
        if project.is_dir() and not project.is_symlink():
            result.append({'token': container.name, 'name': name, 'folder': project})
    return sorted(result, key=lambda item: item['token'], reverse=True)


def restore_game(root, token):
    root, workspace = _project_directories(root)
    selected = next((entry for entry in deleted_games(root) if entry['token'] == token), None)
    if selected is None:
        raise ValueError('This deleted game is no longer available.')
    workspace.mkdir(exist_ok=True)
    destination = workspace / selected['name']
    if destination.exists() or destination.is_symlink():
        destination = workspace / (selected['name'] + '-restored-' + uuid.uuid4().hex[:6])
    container = selected['folder'].parent
    selected['folder'].rename(destination)
    (container / 'deleted_game.json').unlink(missing_ok=True)
    container.rmdir()
    return destination


def game_from_message(root, content):
    """Attach actions only to a real, existing project inside the workspace."""
    root = Path(root).resolve()
    workspace = root / 'workspace'
    match = re.search(r'(?m)^Project saved:\s*([^\r\n]+)', str(content))
    candidates = []
    if match:
        location = match[1].strip().strip('`\"').replace('\\', '/')
        candidates = [root / location / name for name in ('main.py', 'game.py', 'braincraft_starter.py')]
    else:
        match = re.search(r'(?m)^Game test:\s*([^\r\n]+)', str(content))
        if match:
            candidates = [workspace / match[1].strip().replace('\\', '/')]
    for candidate in candidates:
        path = candidate.resolve()
        resumable = path.name == 'main.py' and path.parent.is_dir() and (
            (path.parent / '.brain_build.json').is_file() or (path.parent / 'build_report.json').is_file())
        if path.is_relative_to(workspace) and (path.is_file() or resumable) and path.suffix == '.py':
            return path
    return None


def game_info(script, built_in=False):
    script = Path(script)
    metadata = read_json(script.with_suffix(".game.json") if built_in else script.parent / "game.json")
    report = read_json(script.parent / "build_report.json") if not built_in else {}
    task = report.get("task", "")
    task = task if isinstance(task, str) else ""
    try:
        source = script.read_text(encoding="utf-8-sig", errors="replace")[:200_000]
    except OSError:
        source = ""
    fallback = re.sub(r"-\d{8}-\d{6}-[a-f0-9]+$", "", script.parent.name).replace("-", " ").title()
    title = metadata.get("title") or ("BrainCraft" if built_in else game_title(source, task, fallback))
    title = str(title)[:80]
    if script.name == "braincraft_starter.py":
        title += " · Starter"
    cover = None
    candidates = [metadata.get("cover"), "cover.png", "preview.png"]
    for relative in candidates:
        if isinstance(relative, str):
            candidate = (script.parent / relative).resolve()
            if candidate.is_relative_to(script.parent.resolve()) and candidate.is_file():
                cover = candidate
                break
    runs = script.parent / "test_runs"
    if cover is None and runs.is_dir():
        screenshots = list(runs.glob("run-*/startup.png"))
        if screenshots:
            cover = max(screenshots, key=lambda p: p.stat().st_mtime)
    test_state = game_test_status(script) if script.is_file() else {
        'test_status': 'incomplete', 'test_label': 'Build incomplete · Resume', 'test_report': None}
    return {"script": script, "built_in": built_in, "title": title,
            "description": str(metadata.get("description") or task or "Local Python game")[:180],
            "cover": cover, "favorite": metadata.get('favorite') is True,
            **test_state}


def discover_games(root):
    root = Path(root)
    result = []
    for name in ("minecraft.py", "mincraft.py"):
        if (root / name).is_file():
            result.append(game_info((root / name).resolve(), True))
            break
    workspace = (root / "workspace").resolve()
    if workspace.is_dir():
        for project in sorted(workspace.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if project.is_symlink() or not project.is_dir() or not project.resolve().is_relative_to(workspace):
                continue
            found = False
            for name in ("main.py", "game.py", "braincraft_starter.py"):
                script = project / name
                if script.is_file() and script.resolve().is_relative_to(workspace):
                    result.append(game_info(script.resolve()))
                    found = True
                    if name in {"main.py", "game.py"}:
                        break
            if not found and ((project / '.brain_build.json').is_file() or (project / 'build_report.json').is_file()):
                result.append(game_info(project / 'main.py'))
            if len(result) >= 200:
                break
    return result
