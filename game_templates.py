"""Stage playable foundations; the game and the test runner use the same Game class."""
from pathlib import Path
import hashlib
import json
import html
import re
import zipfile
from project_tools import atomic_json, extract_api
from project_tools import project_files

ROOT = Path(__file__).resolve().parent
TEMPLATES = {
    'platformer': {'title': 'Skyline Sprint', 'description': 'Jump the skyline, collect coins and reach the green flag.', 'kind': 'platformer'},
    'racing': {'title': 'Neon Circuit', 'description': 'Steer, accelerate and jump over obstacles on the neon road.', 'kind': 'racing'},
    'voxel': {'title': 'Goldblock Island', 'description': 'Explore a small 3D island and mine four golden blocks.', 'kind': 'voxel'},
}


def choose_template(task):
    value = task.casefold()
    if any(word in value for word in ('minecraft', 'voxel', 'майнкрафт', 'воксел')): return 'voxel'
    if any(word in value for word in ('racing', 'race game', 'гонк', 'driving')): return 'racing'
    if any(word in value for word in ('platform', 'mario', 'платформ', 'марио')): return 'platformer'
    return None


def seed_template(project, kind):
    if kind not in TEMPLATES: raise ValueError('Unknown game template: ' + str(kind))
    project = Path(project)
    project.mkdir(parents=True, exist_ok=True)
    for source, target in [('template_core.py', 'game_core.py'), ('template_view.py', 'game_view.py')]:
        (project / target).write_bytes((ROOT / source).read_bytes())
    (project / 'main.py').write_text('from game_view import main\n\nif __name__ == "__main__":\n    main()\n', encoding='utf-8')
    (project / 'requirements.txt').write_text('pygame-ce>=2.5.7,<3\n', encoding='utf-8')
    atomic_json(project / 'level.json', TEMPLATES[kind])
    contracts = {name: extract_api((project / name).read_text(encoding='utf-8'))
                 for name in ('game_core.py', 'game_view.py', 'main.py')}
    atomic_json(project / 'contracts.json', {'version': 1, 'modules': contracts})
    atomic_json(project / 'game.json', {**TEMPLATES[kind], 'entry_point': 'main.py', 'template': kind,
                                      'template_core_sha256': hashlib.sha256((project / 'game_core.py').read_bytes()).hexdigest()})
    (project / 'README.md').write_text(
        '# ' + TEMPLATES[kind]['title'] + '\n\n' + TEMPLATES[kind]['description'] + '\n\n'
        'Install: `python -m pip install -r requirements.txt`\nRun: `python main.py`\n\n'
        'A/D or arrows: move. Space: jump. W: walk/accelerate. R: restart. Escape: menu.\n'
        'Voxel: Tab toggles mouse look, E/left click breaks, Q/right click places blocks.\n\n'
        'Edit level.json for level design. Game logic is in game_core.py; rendering is in game_view.py.\n'
        'The deterministic gameplay suite calls the same Game class used during play.\n', encoding='utf-8')
    return project / 'main.py'


def export_demo(script, destination=None, format='auto'):
    project = Path(script).resolve().parent
    config = json.loads((project / 'level.json').read_text(encoding='utf-8')) if (project / 'level.json').exists() else {}
    compatible = (config.get('kind') in TEMPLATES and all(
        (project / name).is_file() and (project / name).read_bytes() == (ROOT / original).read_bytes()
        for name, original in [('game_core.py', 'template_core.py'), ('game_view.py', 'template_view.py')]))
    if format == 'html' and not compatible:
        raise ValueError('This game has custom Python logic/rendering. Export a Python source demo to preserve it exactly.')
    use_html = compatible and format != 'zip'
    title = str(config.get('title') or project.name)
    slug = re.sub(r'[^a-zA-Z0-9_-]', '-', title).strip('-')[:60] or 'brain-game'
    suffix = '.html' if use_html else '.zip'
    path = Path(destination) if destination else project / 'exports' / (slug + '-demo' + suffix)
    if path.suffix.lower() != suffix:
        path = path.with_suffix(suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    if use_html:
        template = (ROOT / 'template_demo.html').read_text(encoding='utf-8')
        data = json.dumps(config, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
        path.write_text(template.replace('__BRAIN_CONFIG_JSON__', data).replace('__BRAIN_TITLE__', html.escape(title)), encoding='utf-8')
    else:
        files = project_files(project)
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, source in files.items():
                if source.resolve() != path.resolve(): archive.write(source, name)
            archive.writestr('RUN_WINDOWS.cmd', '@echo off\r\ncd /d "%~dp0"\r\n'
                'if not exist ".demo_venv\\Scripts\\python.exe" py -m venv .demo_venv\r\n'
                '".demo_venv\\Scripts\\python.exe" -m pip install --only-binary=:all: -r requirements.txt\r\n'
                'if errorlevel 1 goto failed\r\n".demo_venv\\Scripts\\python.exe" main.py\r\n:failed\r\npause\r\n')
            archive.writestr('DEMO_SETUP.txt', 'Python 3.11+ must be installed. On Windows run RUN_WINDOWS.cmd.\n'
                'On other systems: create a venv, install requirements.txt, then run python main.py.\n'
                'This source export preserves custom game code. No model files or chat databases are included.\n')
    return {'path': str(path), 'format': 'html' if use_html else 'python_source_zip',
            'note': 'Standalone offline browser demo, with touch controls.' if use_html else 'Exact Python source demo; Python must be installed.'}
