
import sqlite3

db = sqlite3.connect("memory.db")
cursor = db.cursor()

cursor.execute("""
INSERT INTO messages_fts(messages_fts)
VALUES ('rebuild')
""")

db.commit()

print("Search index rebuilt!")

cursor.execute("SELECT COUNT(*) FROM messages")
print("Database messages:", cursor.fetchone()[0])

db.close()
