from .mqtt_link import Link, message
from .core import is_recent
from .config import SENSOR_INTERVAL


class DHTEmulator:
    def __init__(self):
        self.link = Link("dht", [])
        self.temperature, self.humidity = 24.0, 50.0
        self.enabled = True
        self.last = 0
        self.link.start()

    def tick(self, now):
        for _ in self.link.drain():
            pass
        if self.enabled and now - self.last >= SENSOR_INTERVAL:
            if self.link.send(
                "sensor/telemetry",
                message(
                    device="dht-1", temperature=self.temperature, humidity=self.humidity
                ),
            ):
                self.last = now


class ButtonEmulator:
    def __init__(self):
        self.link = Link("button", [])
        self.link.start()

    def press(self, state):
        return self.link.send("button/request", message(state=state), qos=0)

    def tick(self, now):
        for _ in self.link.drain():
            pass


class RelayEmulator:
    def __init__(self):
        self.link = Link("relay", ["relay/command"])
        self.state = False
        self.enabled = True
        self.last = 0
        self.command_id = None
        self.link.start()

    def report(self):
        self.link.send(
            "relay/state", message(state=self.state, command_id=self.command_id)
        )

    def tick(self, now):
        for name, data in self.link.drain():
            if not self.enabled:
                continue
            if (
                name == "relay/command"
                and is_recent(data, now, 5)
                and type(data.get("state")) is bool
            ):
                if (
                    not isinstance(data.get("id"), str)
                    or not isinstance(data.get("expires_at"), (int, float))
                    or now > data["expires_at"]
                ):
                    continue
                self.state = data["state"]
                self.command_id = data["id"]
                self.report()
        if self.enabled and now - self.last >= 1:
            self.report()
            self.last = now
