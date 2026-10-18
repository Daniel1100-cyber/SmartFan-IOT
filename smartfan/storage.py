import sqlite3


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS measurements (
          id TEXT PRIMARY KEY, ts REAL NOT NULL, received_at REAL NOT NULL,
          device TEXT NOT NULL, temperature REAL NOT NULL, humidity REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, ts REAL NOT NULL, level TEXT NOT NULL,
          kind TEXT NOT NULL, text TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS commands (
          id TEXT PRIMARY KEY, ts REAL NOT NULL, state INTEGER NOT NULL,
          source TEXT NOT NULL, status TEXT NOT NULL, completed_at REAL);
        CREATE INDEX IF NOT EXISTS measurement_time ON measurements(received_at);
        """)

    def sample(self, reading, now):
        cursor = self.db.execute(
            'INSERT OR IGNORE INTO measurements VALUES (?,?,?,?,?,?)',
            (
                reading['id'],
                reading['ts'],
                now,
                reading['device'],
                reading['temperature'],
                reading['humidity'],
            ),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def event(self, event):
        self.db.execute(
            'INSERT INTO events(ts,level,kind,text) VALUES (?,?,?,?)',
            (event['ts'], event['level'], event['kind'], event['text']),
        )
        self.db.commit()

    def command(self, command):
        self.db.execute(
            'INSERT INTO commands VALUES (?,?,?,?,?,NULL)',
            (
                command['id'],
                command['ts'],
                int(command['state']),
                command['source'],
                'pending',
            ),
        )
        self.db.commit()

    def complete(self, command_id, status, now):
        self.db.execute(
            'UPDATE commands SET status=?,completed_at=? WHERE id=?',
            (status, now, command_id),
        )
        self.db.commit()

    def history(self):
        readings = [
            dict(row)
            for row in self.db.execute(
                'SELECT * FROM measurements ORDER BY received_at DESC LIMIT 120'
            )
        ][::-1]
        events = [
            dict(row)
            for row in self.db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 80')
        ]
        counts = {
            table: self.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            for table in ('measurements', 'events', 'commands')
        }
        return dict(readings=readings, events=events, counts=counts)

    def close(self):
        self.db.close()
