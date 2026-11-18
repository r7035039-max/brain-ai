"""Safely install the Brain AI coding-agent + search upgrade over an existing project."""
from __future__ import annotations

import datetime
import shutil
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
DEFAULT_TARGET = Path.home() / 'PycharmProjects' / 'brain_ai_2999elo'
TARGET = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_TARGET
FILES = ('agent.py', 'desktop_app.py', 'web_search.py')


def main():
    if not (TARGET / 'main.py').is_file() or not (TARGET / 'desktop_app.py').is_file():
        print(f'ERROR: Could not find your working Brain AI project at: {TARGET}')
        print('No files were changed. You can provide the path as an argument.')
        return 1
    for name in FILES:
        if not (SOURCE / name).is_file():
            print(f'ERROR: Upgrade archive is incomplete (missing {name}).')
            return 2
    backup = TARGET / ('backup_before_upgrade_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    backup.mkdir(exist_ok=False)
    for name in FILES:
        if (TARGET / name).exists():
            shutil.copy2(TARGET / name, backup / name)
    for name in FILES:
        shutil.copy2(SOURCE / name, TARGET / name)
        print('Updated:', TARGET / name)
    print('\nInstalled successfully. Existing main.py, GGUF models, SQLite DB and games were NOT modified.')
    print('Backup:', backup)
    print('\nNow run: python -u main.py')
    print('Try: /search minecraft ursina documentation')
    print('Then: /build create a Minecraft-style voxel game with saving and block placement')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
