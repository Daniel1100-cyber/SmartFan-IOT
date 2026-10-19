import json
import queue
import time
import uuid
import paho.mqtt.client as mqtt
from .config import HOST, PORT, topic


class Link:
    def __init__(self, role, subscriptions):
        self.inbox = queue.Queue()
        self.connected = False
        self.subscriptions = subscriptions
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"smartfan-{role}-{uuid.uuid4().hex[:8]}",
            clean_session=True,
        )
        self.client.on_connect = self._connect
        self.client.on_disconnect = self._disconnect
        self.client.on_message = self._message
        self.client.reconnect_delay_set(1, 4)

    def _connect(self, client, userdata, flags, reason, properties):
        self.connected = not reason.is_failure
        if self.connected:
            for name in self.subscriptions:
                client.subscribe(topic(name), qos=1)
        self.inbox.put(("_connection", self.connected))

    def _disconnect(self, client, userdata, flags, reason, properties):
        self.connected = False
        self.inbox.put(("_connection", False))

    def _message(self, client, userdata, msg):
        if msg.retain:
            return
        name = msg.topic[len(topic("")) :]
        try:
            value = json.loads(msg.payload)
            if not isinstance(value, dict):
                raise ValueError("Expected an object")
            self.inbox.put((name, value))
        except (ValueError, UnicodeError):
            self.inbox.put(("_invalid", {"topic": name}))

    def start(self):
        self.client.connect_async(HOST, PORT, keepalive=10)
        self.client.loop_start()

    def send(self, name, value, qos=1):
        if not self.connected:
            return False
        payload = json.dumps(value, allow_nan=False)
        return (
            self.client.publish(topic(name), payload, qos=qos, retain=False).rc
            == mqtt.MQTT_ERR_SUCCESS
        )

    def drain(self):
        while True:
            try:
                yield self.inbox.get_nowait()
            except queue.Empty:
                return

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()


def message(**fields):
    return {"id": uuid.uuid4().hex, "ts": time.time(), **fields}
