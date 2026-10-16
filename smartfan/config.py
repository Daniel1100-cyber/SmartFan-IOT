import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = os.getenv('SMARTFAN_HOST', '127.0.0.1')
PORT = int(os.getenv('SMARTFAN_PORT', '18883'))
PREFIX = os.getenv('SMARTFAN_PREFIX', 'smartfan/room1')
DB = Path(os.getenv('SMARTFAN_DB', str(ROOT / 'data' / 'smartfan.sqlite3')))
SENSOR_INTERVAL = 2
STALE_SECONDS = 10
ACK_SECONDS = 5


def topic(name):
    return f'{PREFIX}/{name}'
