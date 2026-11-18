"""Read old desktop_chats.db without modifying it. Idempotent import."""
import argparse
import sqlite3
from pathlib import Path
from core import App

def migrate(source, app):
    path=Path(source).expanduser().resolve()
    if not path.is_file(): raise ValueError('Файл не найден')
    old=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True); old.row_factory=sqlite3.Row
    prefix='legacy-'+__import__('hashlib').sha256(str(path).encode()).hexdigest()[:12]+'-'
    count=0
    try:
        with app.connect() as c:
            for p in old.execute('SELECT * FROM projects'):
                c.execute('INSERT OR IGNORE INTO projects VALUES(?,?,?)',(prefix+str(p['id']),p['name'],p['instructions']))
            for ch in old.execute('SELECT * FROM chats'):
                c.execute('INSERT OR IGNORE INTO chats VALUES(?,?,?,0,0)',(prefix+str(ch['id']),ch['title'],prefix+str(ch['project_id']) if ch['project_id'] else None))
            for m in old.execute('SELECT * FROM messages ORDER BY id'):
                cur=c.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?)',(prefix+str(m['id']),prefix+str(m['chat_id']),m['role'],m['content'],m['id']))
                count+=cur.rowcount
    finally: old.close()
    return count

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('database');args=p.parse_args()
    print('Импортировано сообщений:',migrate(args.database,App()))
