import sqlite3
import time
import uuid
from collections import deque
from .core import Controller, fresh, valid_measurement
from .mqtt_link import Link
from .storage import Store
from .config import DB


def run():
    store = Store(DB)

    store.db.execute(
        "UPDATE commands SET status='interrupted', completed_at=? WHERE status='pending'",
        (time.time(),),
    )
    store.db.commit()
    link = Link(
        'manager', ['sensor/telemetry', 'relay/state', 'button/request', 'control/mode']
    )
    controller = Controller(time.time(), lambda: uuid.uuid4().hex)
    recent_request_ids = deque(maxlen=2000)
    last_snapshot_at = 0
    storage_error = None
    link.start()
    try:
        while True:
            now = time.time()
            for name, data in link.drain():
                try:
                    if name == '_connection':
                        if controller.pending:
                            store.complete(controller.pending['id'], 'interrupted', now)
                        controller.connection(data, now)
                    elif name == 'sensor/telemetry':
                        if not valid_measurement(data, now):
                            raise ValueError(
                                'Rejected invalid or expired sensor message'
                            )
                        if store.sample(data, now):
                            controller.sample_received(data, now)
                    elif name == 'relay/state':
                        acknowledged_id = controller.relay_received(data, now)
                        if acknowledged_id:
                            store.complete(acknowledged_id, 'acknowledged', now)
                    elif name in ('button/request', 'control/mode'):
                        request_id = data.get('id')
                        if not isinstance(request_id, str) or not fresh(data, now, 5):
                            raise ValueError('Rejected invalid or expired user request')
                        if request_id in recent_request_ids:
                            continue
                        recent_request_ids.append(request_id)
                        if name == 'button/request':
                            controller.manual(data.get('state'), now)
                        else:
                            controller.set_mode(data.get('mode'), now)
                    elif name == '_invalid':
                        raise ValueError('Rejected malformed JSON')
                except (ValueError, KeyError, TypeError) as exc:
                    controller.event('Warning', 'validation', str(exc), now)
                except sqlite3.Error as exc:
                    storage_error = str(exc)
                    controller.event(
                        'Alarm',
                        'database',
                        'Database write failed; check disk and permissions',
                        now,
                    )
            expired = controller.tick(now)
            try:
                if expired:
                    store.complete(expired, 'timeout', now)
                while controller.commands:
                    command = controller.commands.pop(0)
                    store.command(command)
                    if not link.send('relay/command', command):
                        store.complete(command['id'], 'send_failed', now)
                        controller.pending = None
                        controller.command_failed = True
                while controller.events:
                    event = controller.events.pop(0)
                    store.event(event)
                    link.send('events', event)
                if now - last_snapshot_at >= 0.75:
                    state = controller.snapshot(now)
                    state.update(store.history())
                    state['storage_error'] = storage_error
                    link.send('manager/state', state, qos=0)
                    last_snapshot_at = now
            except sqlite3.Error as exc:
                storage_error = str(exc)
                link.send(
                    'manager/state',
                    {**controller.snapshot(now), 'storage_error': storage_error},
                    qos=0,
                )
            time.sleep(0.04)
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
        store.close()


if __name__ == '__main__':
    run()
