"""Run actual game-rule assertions in a bounded subprocess, separate from the UI."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_support import project_fingerprint, python_executable, environment_failure
from project_tools import atomic_json


def exercise(script):
    folder = Path(script).resolve().parent
    sys.path.insert(0, str(folder))
    module_path = folder / 'game_core.py'
    if not module_path.is_file():
        return {'status': 'unsupported', 'passed': False, 'cases': [], 'scope': 'Game API not implemented'}
    spec = importlib.util.spec_from_file_location('brain_game_under_test', module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, 'Game') or not all(hasattr(module.Game, name) for name in ('configure_test', 'snapshot', 'step')):
        return {'status': 'unsupported', 'passed': False, 'cases': [], 'scope': 'Game API not implemented'}
    config_path = folder / 'level.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    cases = []
    for case in ('movement', 'jump', 'collision', 'win', 'lose'):
        try:
            game = module.Game(config)
            game.configure_test(case)
            before = game.snapshot()
            if case == 'movement':
                for _ in range(20): game.step({'right': True, 'forward': True}, 1/60)
                after = game.snapshot()
                assert abs(after['x'] - before['x']) + abs(after['z'] - before['z']) > .1, 'Player did not move'
                assert after['alive'], 'Ordinary movement killed the player'
            elif case == 'jump':
                game.step({'jump': True}, 1/60)
                for _ in range(8): game.step({}, 1/60)
                assert game.snapshot()['y'] > before['y'] + .1, 'Jump did not move upward'
                for _ in range(100): game.step({}, 1/60)
                assert game.snapshot()['grounded'] and abs(game.snapshot()['y'] - before['y']) < .02, 'Player did not land'
            elif case == 'collision':
                for _ in range(120): game.step({'right': True}, 1/60)
                after = game.snapshot()
                assert after['collisions'] > before['collisions'], 'Collision was not registered'
                assert after['x'] < (2.7 if game.kind == 'racing' else 1.3), 'Player passed through the obstacle'
            elif case == 'win':
                for _ in range(180): game.step({'right': game.kind == 'platformer', 'forward': True, 'break': True}, 1/60)
                assert game.snapshot()['won'] and game.snapshot()['alive'], 'Winning condition did not trigger'
            else:
                for _ in range(180): game.step({'right': game.kind == 'platformer', 'forward': True}, 1/60)
                assert not game.snapshot()['alive'] and not game.snapshot()['won'], 'Losing condition did not trigger'
            cases.append({'name': case, 'passed': True})
        except Exception as error:
            missing = (environment_failure("ModuleNotFoundError: No module named '" + str(error.name) + "'", script)
                       if isinstance(error, ModuleNotFoundError) else None)
            cases.append({'name': case, 'passed': False, 'error': str(error), 'missing_module': missing})
    return {'status': 'dependencies_missing' if any(case.get('missing_module') for case in cases)
            else 'passed' if all(case['passed'] for case in cases) else 'failed',
            'passed': all(case['passed'] for case in cases), 'cases': cases, 'scope': 'movement_jump_collision_win_lose'}


def run_checks(script, progress=lambda _: None, *, timeout=30):
    script = Path(script).resolve()
    folder = script.parent / 'test_runs'
    folder.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=folder))
    fingerprint = project_fingerprint(script)
    report = {'game': script.name, 'status': 'incomplete', 'passed': False, 'source_hash': fingerprint, 'scope': 'gameplay_rules'}
    atomic_json(run / 'report.json', report)
    progress('Testing movement, jumping, collisions, winning and losing ...')
    result_file = run / 'rules.json'
    command = [python_executable(), '-I', str(Path(__file__).resolve()), '--script', str(script), '--output', str(result_file)]
    try:
        result = subprocess.run(command, cwd=script.parent, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        data = json.loads(result_file.read_text(encoding='utf-8')) if result_file.exists() else {
            'passed': False, 'status': 'failed', 'cases': [], 'error': result.stdout[-4000:]}
        data['log'] = result.stdout[-4000:]
        if result.returncode != 0: data['passed'], data['status'] = False, 'failed'
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        data = {'status': 'failed', 'passed': False, 'cases': [], 'error': str(error)}
    report.update(data)
    if project_fingerprint(script) != fingerprint:
        report.update(status='stale', passed=False)
    atomic_json(run / 'report.json', report)
    report['report_path'] = str(run / 'report.json')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--script', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = exercise(args.script)
    except Exception as error:
        missing = (environment_failure("ModuleNotFoundError: No module named '" + str(error.name) + "'", Path(args.script))
                   if isinstance(error, ModuleNotFoundError) else None)
        result = {'status': 'dependencies_missing' if missing else 'failed', 'passed': False,
                  'missing_module': missing, 'cases': [], 'error': str(error)}
    atomic_json(args.output, result)
    sys.exit(0)
