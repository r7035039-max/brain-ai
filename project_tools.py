"""Project transactions, API contracts, history and dependency compatibility."""
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from project_support import analyze_imports, clean_requirements, read_json, python_executable

IGNORED = {'.venv', 'venv', '__pycache__', '.git', 'test_runs', '.brain_history',
           '.brain_changes', 'exports', 'dist', 'node_modules'}
HOST_FILES = {'game.json', 'build_report.json', '.brain_build.json', 'dependency_report.json'}
SUFFIXES = {'.py', '.json', '.txt', '.md', '.toml', '.html', '.css', '.js', '.png', '.jpg', '.wav', '.ogg'}


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex[:8] + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def project_root(script, root=None):
    script = Path(script).resolve()
    root = Path(root or Path(__file__).parent).resolve()
    workspace = (root / 'workspace').resolve()
    if not workspace.is_relative_to(root) or not script.is_relative_to(workspace):
        raise ValueError('Select a generated project in Brain AI workspace.')
    relative = script.relative_to(workspace)
    if len(relative.parts) < 2:
        raise ValueError('The workspace itself is not a game project.')
    return workspace / relative.parts[0]


def safe_file(project, name):
    project = Path(project).resolve()
    relative = Path(str(name).replace('\\', '/'))
    if (str(name) in HOST_FILES or relative.is_absolute() or '..' in relative.parts or any(p in IGNORED for p in relative.parts)
            or any(p.startswith('.') for p in relative.parts) or relative.suffix.lower() not in SUFFIXES
            or re.search(r'[:<>"|?*\x00-\x1f]', str(name))):
        raise ValueError('Invalid project file: ' + str(name))
    path = project / relative
    if not path.resolve().is_relative_to(project) or path.is_symlink():
        raise ValueError('Project paths cannot escape the project or follow symlinks.')
    return path


def project_files(project):
    project = Path(project).resolve()
    result = {}
    for parent, directories, files in os.walk(project, followlinks=False):
        directories[:] = [d for d in directories if d not in IGNORED and not d.startswith('.')
                          and not (Path(parent) / d).is_symlink()]
        for name in files:
            path = Path(parent) / name
            if (name in HOST_FILES or name.startswith('.') or path.suffix.lower() not in SUFFIXES
                    or path.is_symlink() or path.stat().st_size > 8_000_000):
                continue
            result[path.relative_to(project).as_posix()] = path
            if len(result) > 500:
                raise ValueError('Project is too large for an automatic checkpoint.')
    if sum(p.stat().st_size for p in result.values()) > 50_000_000:
        raise ValueError('Project checkpoint exceeds 50 MB; move generated outputs outside the source folder.')
    return result


def sources(project):
    return {name: path.read_text(encoding='utf-8-sig', errors='replace')
            for name, path in project_files(project).items() if path.suffix in {'.py', '.json', '.md', '.txt', '.toml', '.html', '.css', '.js'}}


def checkpoint(project, label, changed=()):
    project = Path(project).resolve()
    files = project_files(project)
    history = project / '.brain_history'
    if history.is_symlink():
        raise ValueError('History folder cannot be a symlink.')
    token = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    folder = history / token
    hashes = {}
    for name, path in files.items():
        destination = folder / 'files' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        hashes[name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    atomic_json(folder / 'checkpoint.json', {'id': token, 'label': str(label)[:200], 'time': time.time(),
                'files': hashes, 'changed': list(changed)})
    return token


def checkpoints(project):
    folder = Path(project) / '.brain_history'
    if not folder.is_dir() or folder.is_symlink():
        return []
    items = []
    for path in folder.glob('*/checkpoint.json'):
        if path.parent.is_symlink() or not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{8}', path.parent.name): continue
        item = read_json(path)
        if item.get('id') == path.parent.name: items.append(item)
    return sorted([item for item in items if isinstance(item.get('files'), dict)],
                  key=lambda item: item.get('time', 0), reverse=True)


def apply_files(project, changes, label='AI edit', *, make_checkpoint=True):
    project = Path(project).resolve()
    paths = {name: safe_file(project, name) for name in changes}
    before = {name: path.read_bytes() if path.exists() else None for name, path in paths.items()}
    token = checkpoint(project, label, changes) if make_checkpoint else None
    stage = Path(tempfile.mkdtemp(prefix='.brain-stage-', dir=project))
    written = []
    try:
        for name, value in changes.items():
            if value is None:
                continue
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(value.encode('utf-8') if isinstance(value, str) else value)
        for name, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if changes[name] is None:
                path.unlink(missing_ok=True)
            else:
                (stage / name).replace(path)
            written.append(name)
    except Exception:
        for name in reversed(written):
            if before[name] is None:
                paths[name].unlink(missing_ok=True)
            else:
                paths[name].write_bytes(before[name])
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return token


def restore_checkpoint(project, token, selected=None):
    project = Path(project).resolve()
    item = next((item for item in checkpoints(project) if item.get('id') == token), None)
    if item is None:
        raise ValueError('Checkpoint not found.')
    changes = {}
    names = set(selected) if selected else set(item['files']) | set(project_files(project))
    for name in names:
        safe_file(project, name)
        if name in item['files']:
            source = project / '.brain_history' / token / 'files' / name
            if not source.resolve().is_relative_to((project / '.brain_history' / token).resolve()):
                raise ValueError('Invalid checkpoint path.')
            value = source.read_bytes()
            if hashlib.sha256(value).hexdigest() != item['files'][name]:
                raise ValueError('Checkpoint file was changed or damaged: ' + name)
            changes[name] = value
        else:
            changes[name] = None
    return apply_files(project, changes, 'Before undo: ' + str(item.get('label', token)))


def _signature(node, *, method=False):
    args = [a.arg for a in [*node.args.posonlyargs, *node.args.args]]
    if method and args and args[0] in {'self', 'cls'}:
        args = args[1:]
    return {'args': args, 'required': max(0, len(args) - len(node.args.defaults)),
            'kwonly': [a.arg for a in node.args.kwonlyargs],
            'required_kwonly': [a.arg for a, value in zip(node.args.kwonlyargs, node.args.kw_defaults) if value is None],
            'vararg': node.args.vararg is not None, 'kwarg': node.args.kwarg is not None}


def extract_api(source):
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('_'):
            result[node.name] = {'kind': 'function', **_signature(node)}
        elif isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
            result[node.name] = {'kind': 'class', 'methods': {
                method.name: _signature(method, method=True) for method in node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (not method.name.startswith('_') or method.name == '__init__')}}
    return result


def contract_errors(source, expected):
    actual = extract_api(source)
    errors = []
    def check_signature(name, old, new):
        if new['args'][:len(old['args'])] != old['args'] or new['required'] > old['required']:
            errors.append(name + ': incompatible arguments; expected ' + ', '.join(old['args']))
        if not set(new['required_kwonly']).issubset(old.get('required_kwonly', [])):
            errors.append(name + ': new required keyword argument')
    for name, old in expected.items():
        new = actual.get(name)
        if not new or new['kind'] != old['kind']:
            errors.append('Missing public API: ' + name)
        elif old['kind'] == 'function':
            check_signature(name, old, new)
        else:
            for method, signature in old.get('methods', {}).items():
                if method not in new['methods']:
                    errors.append('Missing method: ' + name + '.' + method)
                else:
                    check_signature(name + '.' + method, signature, new['methods'][method])
    return errors


def validate_project(files, contracts=None, planned=()):
    errors = []
    apis = {}
    exports = {}
    for name, source in files.items():
        if name.endswith('.py'):
            try:
                compile(source, name, 'exec', dont_inherit=True)
                module = name[:-3].replace('/', '.')
                if module.endswith('.__init__'): module = module[:-9]
                apis[module] = extract_api(source)
                visible = set(apis[module])
                for node in ast.parse(source).body:
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        visible.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
                    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        visible.update(child.id for target in targets for child in ast.walk(target) if isinstance(child, ast.Name))
                exports[module] = visible
                errors.extend(name + ': ' + error for error in contract_errors(source, (contracts or {}).get(name, {})))
            except (SyntaxError, ValueError) as error:
                errors.append(name + ': ' + str(error))
        elif name.endswith('.json'):
            try:
                json.loads(source)
            except ValueError as error:
                errors.append(name + ': ' + str(error))
    if errors:
        return errors
    for name, failures in analyze_imports(files, planned)['local_errors'].items():
        errors.extend(name + ': ' + issue for issue in failures)
    for name, source in files.items():
        if not name.endswith('.py'):
            continue
        tree = ast.parse(source)
        bindings, instances = {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and not node.level and node.module in apis:
                for alias in node.names:
                    if alias.name != '*' and alias.name not in exports[node.module] and node.module+'.'+alias.name not in apis:
                        errors.append(f'{name}:{node.lineno}: {node.module} does not export {alias.name}')
                    if alias.name in apis[node.module]:
                        bindings[alias.asname or alias.name] = apis[node.module][alias.name]
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                api = bindings.get(node.value.func.id)
                if api and api['kind'] == 'class':
                    for target in node.targets:
                        if isinstance(target, ast.Name): instances[target.id] = api
            if not isinstance(node, ast.Call) or any(isinstance(arg, ast.Starred) for arg in node.args) or any(k.arg is None for k in node.keywords):
                continue
            signature = None
            if isinstance(node.func, ast.Name) and node.func.id in bindings:
                api = bindings[node.func.id]
                signature = api.get('methods', {}).get('__init__') if api['kind'] == 'class' else api
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                signature = instances.get(node.func.value.id, {}).get('methods', {}).get(node.func.attr)
            if signature:
                positionals = len(node.args)
                keywords = {k.arg for k in node.keywords}
                missing = set(signature['args'][positionals:signature['required']]) - keywords
                invalid = keywords - set(signature['args']) - set(signature['kwonly'])
                if (missing or (positionals > len(signature['args']) and not signature['vararg'])
                        or (invalid and not signature['kwarg'])):
                    errors.append(f'{name}:{node.lineno}: call does not match the shared API')
    return errors


def dependency_fixes(text, python_version=None):
    version = python_version or sys.version_info[:2]
    text = clean_requirements(text)
    notices = []
    if tuple(version) >= (3, 14):
        lines = []
        for line in text.splitlines():
            if re.match(r'^\s*pygame(?:\s*(?:[<>=!~;\[]|$))', line, re.I):
                marker = line.split(';', 1)[1] if ';' in line else None
                line = 'pygame-ce>=2.5.7,<3' + ('; ' + marker.strip() if marker else '')
                notices.append('Use pygame-ce wheels with Python 3.14+; imports remain pygame.')
            lines.append(line)
        text = '\n'.join(lines).rstrip() + '\n'
    return text, notices


def check_dependencies(script, progress=lambda _: None, *, repair=True, timeout=180):
    folder = Path(script).resolve().parent
    req = folder / 'requirements.txt'
    if not req.is_file():
        raise ValueError('This project has no requirements.txt.')
    original = req.read_text(encoding='utf-8-sig')
    cleaned, notices = dependency_fixes(original)
    if repair and original != cleaned:
        apply_files(folder, {'requirements.txt': cleaned}, 'Dependency compatibility fix')
    progress('Resolving compatible binary packages for Python ' + sys.version.split()[0] + ' ...')
    report_path = folder / 'dependency_report.json'
    with tempfile.TemporaryDirectory(prefix='brain-wheel-check-') as temporary:
        pip_report = Path(temporary) / 'pip.json'
        command = [python_executable(), '-I', '-m', 'pip', 'install', '--dry-run', '--ignore-installed',
                   '--only-binary=:all:', '--disable-pip-version-check', '--report', str(pip_report), '-r', str(req)]
        try:
            result = subprocess.run(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', timeout=timeout,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            resolved = read_json(pip_report)
            data = {'ready': result.returncode == 0, 'python': sys.version.split()[0], 'notices': notices,
                    'packages': [{'name': row.get('metadata', {}).get('name'), 'version': row.get('metadata', {}).get('version')}
                                 for row in resolved.get('install', [])], 'log': result.stdout[-10000:],
                    'requirements_hash': hashlib.sha256(req.read_bytes()).hexdigest(), 'checked_at': time.time()}
        except (OSError, subprocess.TimeoutExpired) as error:
            data = {'ready': False, 'python': sys.version.split()[0], 'notices': notices, 'log': str(error)}
    atomic_json(report_path, data)
    return data
