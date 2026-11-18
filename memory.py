
import sqlite3

db = sqlite3.connect("memory.db")


def search(terms):
    if isinstance(terms, str):
        terms = [terms]

    terms = list(dict.fromkeys(
        str(term).strip()
        for term in terms
        if str(term).strip()
    ))

    if not terms:
        return []

    # Escape FTS5 special characters by quoting every term.
    fts_query = " OR ".join(
        '"' + term.replace('"', '""') + '"'
        for term in terms
    )

    cursor = db.cursor()

    cursor.execute("""
        SELECT DISTINCT
            m.date,
            m.chat_name,
            m.speaker,
            snippet(messages_fts, 0, '[', ']', '...', 15)
        FROM messages_fts
        JOIN messages m
            ON m.id = messages_fts.rowid
        WHERE messages_fts MATCH ?
        ORDER BY rank
        LIMIT 15
    """, (fts_query,))

    return cursor.fetchall()
