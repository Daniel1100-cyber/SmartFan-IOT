import math
from .config import STALE_SECONDS, ACK_SECONDS


def is_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def is_recent(data, now, max_age=10):
    return is_number(data.get("ts")) and -2 <= now - data["ts"] <= max_age


def is_valid_measurement(data, now):
    return (
        isinstance(data.get("id"), str)
        and 0 < len(data["id"]) <= 64
        and data.get("device") == "dht-1"
        and is_recent(data, now)
        and is_number(data.get("temperature"))
        and -20 <= data["temperature"] <= 60
        and is_number(data.get("humidity"))
        and 0 <= data["humidity"] <= 100
    )


def fan_target(temperature, humidity, previous):
    if temperature >= 28 or humidity >= 70:
        return True
    if temperature <= 26 and humidity <= 65:
        return False
    return previous


def environment_status(temperature, humidity):
    if temperature >= 32 or humidity >= 80:
        return "Alarm"
    if temperature >= 28 or humidity >= 70:
        return "Warning"
    return "Normal"


class Controller:
    def __init__(self, now, command_id):
        self.command_id = command_id
        self.started = now
        self.connected = False
        self.mode = "AUTO"
        self.desired = False
        self.reported = None
        self.relay_at = None
        self.sample = None
        self.sample_at = None
        self.severity = "Unknown"
        self.stale = False
        self.pending = None
        self.command_failed = False
        self.events = []
        self.commands = []

    def add_event(self, level, kind, text, now):
        self.events.append(dict(ts=now, level=level, kind=kind, text=text))

    def connection(self, connected, now):
        self.connected = connected
        self.sample_at = None
        self.relay_at = None
        self.severity = "Unknown"
        self.started = now
        if self.pending:
            self.command_failed = True
        self.pending = None
        self.add_event(
            "Info" if connected else "Warning",
            "broker",
            "Broker connected; waiting for fresh device reports"
            if connected
            else "Broker disconnected; control suspended",
            now,
        )

    def handle_measurement(self, data, now):
        if not is_valid_measurement(data, now):
            raise ValueError("Invalid or expired DHT measurement")
        self.sample = data
        self.sample_at = now
        if self.stale:
            self.add_event("Info", "sensor", "Sensor updates recovered", now)
        self.stale = False
        severity = environment_status(data["temperature"], data["humidity"])
        if severity != self.severity:
            self.add_event(
                "Info" if severity == "Normal" else severity,
                "environment",
                f"{severity}: {data['temperature']:.1f} C, {data['humidity']:.1f}% RH",
                now,
            )
            self.severity = severity
        if self.mode == "AUTO":
            desired = fan_target(data["temperature"], data["humidity"], self.desired)
            changed = desired != self.desired
            self.desired = desired
            self.sync_relay(now, force=changed)

    def set_mode(self, mode, now):
        if mode not in ("AUTO", "MANUAL"):
            raise ValueError("Unknown mode")
        if mode != self.mode:
            self.mode = mode
            self.add_event("Info", "mode", f"{mode} mode selected", now)
            if (
                mode == "AUTO"
                and self.sample_at is not None
                and now - self.sample_at <= STALE_SECONDS
            ):
                self.desired = fan_target(
                    self.sample["temperature"], self.sample["humidity"], self.desired
                )
                self.sync_relay(now, force=True)

    def manual(self, state, now):
        if type(state) is not bool:
            raise ValueError("State must be boolean")
        if self.mode != "MANUAL":
            self.add_event("Info", "button", "Manual button ignored in AUTO mode", now)
            return
        self.desired = state
        self.sync_relay(now, force=True)

    def sync_relay(self, now, force=False):
        if not self.connected or self.pending:
            return
        if self.mode == "AUTO" and (
            self.sample_at is None or now - self.sample_at > STALE_SECONDS
        ):
            return
        if (
            self.reported == self.desired
            and self.relay_at is not None
            and now - self.relay_at <= 5
        ):
            return
        if self.command_failed and not force:
            return
        self.command_failed = False
        command = dict(
            id=self.command_id(),
            ts=now,
            expires_at=now + ACK_SECONDS,
            state=self.desired,
            source=self.mode,
        )
        self.pending = command
        self.commands.append(command)

    def handle_relay_state(self, data, now):
        if type(data.get("state")) is not bool or not is_recent(data, now, 5):
            raise ValueError("Invalid relay status")
        recovering = self.relay_at is None or now - self.relay_at > 5
        changed = self.reported != data["state"]
        self.reported = data["state"]
        self.relay_at = now
        acknowledged_id = None
        if (
            self.pending
            and data.get("command_id") == self.pending["id"]
            and data["state"] == self.pending["state"]
        ):
            acknowledged_id = self.pending["id"]
            self.pending = None
            self.command_failed = False
            self.add_event(
                "Info",
                "relay",
                f"Relay confirmed {'ON' if self.reported else 'OFF'}",
                now,
            )
        elif changed:
            self.add_event(
                "Info",
                "relay",
                f"Relay reported {'ON' if self.reported else 'OFF'}",
                now,
            )
        self.sync_relay(now, force=recovering)
        return acknowledged_id

    def tick(self, now):
        if (
            self.connected
            and now - (self.sample_at if self.sample_at is not None else self.started)
            > STALE_SECONDS
            and not self.stale
        ):
            self.stale = True
            self.add_event(
                "Warning", "sensor", "No valid sensor reading for over 10 seconds", now
            )
        expired = None
        if self.pending and now > self.pending["expires_at"]:
            expired = self.pending["id"]
            self.pending = None
            self.command_failed = True
            self.add_event(
                "Alarm",
                "command",
                "Relay did not acknowledge the command within 5 seconds",
                now,
            )
        return expired

    def snapshot(self, now):
        return dict(
            ts=now,
            connected=self.connected,
            mode=self.mode,
            desired=self.desired,
            reported=self.reported,
            relay_at=self.relay_at,
            sample=self.sample,
            sensor_fresh=self.sample_at is not None
            and now - self.sample_at <= STALE_SECONDS,
            relay_fresh=self.relay_at is not None and now - self.relay_at <= 5,
            severity=self.severity,
            pending=self.pending,
            command_failed=self.command_failed,
        )
