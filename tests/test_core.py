import itertools
import pytest
from smartfan.core import (
    Controller,
    environment_status,
    fan_target,
    is_valid_measurement,
)
from smartfan.storage import Store


def sample(temperature=24, humidity=50, timestamp=100, message_id="m1"):
    return dict(
        id=message_id,
        ts=timestamp,
        device="dht-1",
        temperature=temperature,
        humidity=humidity,
    )


@pytest.mark.parametrize(
    "temperature,humidity,previous,expected",
    [
        (28, 50, False, True),
        (24, 70, False, True),
        (26, 65, True, False),
        (27, 60, True, True),
        (27, 60, False, False),
        (25, 66, True, True),
        (25, 72, True, True),
    ],
)
def test_hysteresis(temperature, humidity, previous, expected):
    assert fan_target(temperature, humidity, previous) == expected


@pytest.mark.parametrize(
    "temperature,humidity,level",
    [
        (24, 50, "Normal"),
        (28, 50, "Warning"),
        (24, 70, "Warning"),
        (32, 50, "Alarm"),
        (24, 80, "Alarm"),
    ],
)
def test_severity(temperature, humidity, level):
    assert environment_status(temperature, humidity) == level


@pytest.mark.parametrize(
    "change",
    [
        {"temperature": float("nan")},
        {"humidity": 101},
        {"temperature": True},
        {"ts": 80},
        {"ts": 104},
        {"id": ""},
        {"device": "other"},
    ],
)
def test_bad_measurements(change):
    assert not is_valid_measurement({**sample(), **change}, 100)


def controller():
    ids = iter(map(str, itertools.count()))
    fan_controller = Controller(100, lambda: next(ids))
    fan_controller.connection(True, 100)
    fan_controller.handle_relay_state(dict(ts=100, state=False, command_id=None), 100)
    return fan_controller


def test_auto_ack_and_cooldown():
    fan_controller = controller()
    fan_controller.handle_measurement(sample(28), 100)
    assert fan_controller.reported is False and fan_controller.pending["state"] is True
    command_id = fan_controller.pending["id"]
    assert (
        fan_controller.handle_relay_state(
            dict(ts=101, state=True, command_id=command_id), 101
        )
        == command_id
    )
    fan_controller.handle_measurement(sample(27, timestamp=102), 102)
    assert fan_controller.desired is True
    fan_controller.handle_measurement(sample(26, timestamp=103), 103)
    assert fan_controller.pending["state"] is False


def test_manual_does_not_override_auto_and_alarms_remain():
    fan_controller = controller()
    fan_controller.manual(True, 100)
    assert fan_controller.pending is None
    fan_controller.set_mode("MANUAL", 100)
    fan_controller.handle_measurement(sample(33), 100)
    assert fan_controller.severity == "Alarm" and fan_controller.desired is False
    fan_controller.manual(True, 100)
    assert fan_controller.pending["state"] is True


def test_timeout_and_stale():
    fan_controller = controller()
    fan_controller.handle_measurement(sample(33), 100)
    command_id = fan_controller.pending["id"]
    assert fan_controller.tick(106) == command_id and fan_controller.command_failed
    fan_controller.tick(111)
    assert fan_controller.stale
    assert sum(event["kind"] == "command" for event in fan_controller.events) == 1
    fan_controller.handle_measurement(sample(24, timestamp=112), 112)
    assert not fan_controller.stale


def test_wrong_ack_does_not_complete():
    fan_controller = controller()
    fan_controller.handle_measurement(sample(33), 100)
    assert (
        fan_controller.handle_relay_state(
            dict(ts=101, state=True, command_id="wrong"), 101
        )
        is None
    )
    assert fan_controller.pending is not None


def test_mode_change_during_pending_command():
    fan_controller = controller()
    fan_controller.handle_measurement(sample(33), 100)
    previous_command_id = fan_controller.pending["id"]
    fan_controller.set_mode("MANUAL", 100)
    fan_controller.manual(False, 100)
    fan_controller.handle_relay_state(
        dict(ts=101, state=True, command_id=previous_command_id), 101
    )
    assert fan_controller.pending["state"] is False


def test_restart_does_not_restore_old_live_measurements():
    fan_controller = controller()
    fan_controller.handle_measurement(sample(33), 100)
    fan_controller.connection(False, 101)
    fan_controller.connection(True, 102)
    assert not fan_controller.snapshot(102)["sensor_fresh"]


def test_database_dedup_and_persistence(tmp_path):
    path = tmp_path / "test.sqlite3"
    store = Store(path)
    assert store.save_measurement(sample(), 100)
    assert not store.save_measurement(sample(), 101)
    store.close()
    store = Store(path)
    assert store.recent_history()["counts"]["measurements"] == 1
    store.close()
