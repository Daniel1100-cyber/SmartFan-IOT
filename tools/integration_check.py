import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
run_dir = ROOT / "build" / ("integration-" + uuid.uuid4().hex[:8])
run_dir.mkdir(parents=True)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
os.environ["SMARTFAN_PORT"] = str(port)
os.environ["SMARTFAN_DB"] = str(run_dir / "test.sqlite3")
from smartfan.mqtt_link import Link, message
from smartfan.emulators import DHTEmulator, ButtonEmulator, RelayEmulator

children = []
handles = []
devices = []
results = []
state = {}


def start(module):
    f = open(run_dir / (module.split(".")[-1] + ".log"), "w")
    handles.append(f)
    p = subprocess.Popen([sys.executable, "-m", module], cwd=ROOT, stdout=f, stderr=f)
    children.append(p)
    return p


def check(name, predicate, timeout=9):
    global state
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for d in devices:
            d.tick(time.time())
        for topic, data in observer.drain():
            if topic == "manager/state":
                state = data
        if predicate(state):
            results.append({"test": name, "status": "PASS"})
            print("PASS", name, flush=True)
            return
        if any(p.poll() is not None for p in children):
            raise AssertionError("Service exited")
        time.sleep(0.05)
    raise AssertionError(f"{name}: timed out, state={state}")


def set_sample(t, h):
    sensor.temperature = t
    sensor.humidity = h
    sensor.last = 0


try:
    broker = start("smartfan.broker")
    time.sleep(1.5)
    manager = start("smartfan.manager")
    observer = Link("test", ["manager/state"])
    observer.start()
    sensor = DHTEmulator()
    relay = RelayEmulator()
    button = ButtonEmulator()
    devices = [sensor, relay, button]
    check(
        "Initial normal data saved",
        lambda s: s.get("severity") == "Normal"
        and s.get("counts", {}).get("measurements", 0) > 0,
    )
    set_sample(28, 50)
    check(
        "Temperature trigger and relay acknowledgement",
        lambda s: s.get("reported") is True and not s.get("pending"),
    )
    set_sample(27, 50)
    check(
        "Hysteresis holds ON at 27 C",
        lambda s: (s.get("sample") or {}).get("temperature") == 27
        and s.get("reported") is True,
    )
    set_sample(26, 50)
    check(
        "Cooling turns fan OFF",
        lambda s: s.get("reported") is False and not s.get("pending"),
    )
    set_sample(24, 70)
    check(
        "Humidity alone triggers fan",
        lambda s: s.get("reported") is True
        and (s.get("sample") or {}).get("humidity") == 70,
    )
    set_sample(24, 80)
    check("High humidity raises Alarm", lambda s: s.get("severity") == "Alarm")
    observer.send("control/mode", message(mode="MANUAL"), qos=0)
    check("Manual mode accepted", lambda s: s.get("mode") == "MANUAL")
    button.press(False)
    check(
        "Button OFF while Alarm remains",
        lambda s: s.get("reported") is False
        and s.get("severity") == "Alarm"
        and not s.get("pending"),
    )
    observer.send("control/mode", message(mode="AUTO"), qos=0)
    check(
        "Return to AUTO uses fresh reading",
        lambda s: s.get("mode") == "AUTO"
        and s.get("reported") is True
        and not s.get("pending"),
    )
    set_sample(24, 50)
    check(
        "Both low conditions turn OFF",
        lambda s: s.get("reported") is False and not s.get("pending"),
    )

    observer.client.publish("smartfan/room1/sensor/telemetry", "{broken", qos=1)
    check(
        "Malformed JSON rejected without crash",
        lambda s: any(e["kind"] == "validation" for e in s.get("events", [])),
    )
    sensor.enabled = False
    check(
        "Sensor stale warning after 10 seconds",
        lambda s: not s.get("sensor_fresh", True)
        and any(
            e["kind"] == "sensor" and e["level"] == "Warning"
            for e in s.get("events", [])
        ),
        14,
    )
    sensor.enabled = True
    sensor.last = 0
    check(
        "Sensor recovers",
        lambda s: s.get("sensor_fresh")
        and any(
            e["kind"] == "sensor" and e["level"] == "Info" for e in s.get("events", [])
        ),
    )
    relay.enabled = False
    set_sample(33, 50)
    check(
        "Relay acknowledgement timeout", lambda s: s.get("command_failed") is True, 10
    )
    relay.enabled = True
    check(
        "Relay recovery reconciles desired state",
        lambda s: s.get("reported") is True
        and not s.get("command_failed")
        and not s.get("pending"),
    )
    sensor.enabled = False
    previous = state["counts"]["measurements"]
    manager.terminate()
    manager.wait()
    children.remove(manager)
    manager = start("smartfan.manager")
    check(
        "Manager restart retains history without live sensor state",
        lambda s: s.get("counts", {}).get("measurements", 0) >= previous
        and not s.get("sensor_fresh", True)
        and s.get("sample") is None,
    )
    sensor.enabled = True
    sensor.last = 0
    check(
        "Manager restart resumes from fresh telemetry",
        lambda s: s.get("sensor_fresh") and s.get("severity") == "Alarm",
    )
    broker.terminate()
    broker.wait()
    children.remove(broker)
    check("Broker loss suspends control", lambda s: not observer.connected, 5)
    broker = start("smartfan.broker")
    check(
        "Broker restart reconnects and resubscribes",
        lambda s: observer.connected
        and s.get("sensor_fresh")
        and time.time() - s.get("ts", 0) < 2,
        15,
    )
    output = ROOT / "docs" / "test_results.json"
    output.write_text(
        json.dumps(
            {"integration": results, "database": str(run_dir / "test.sqlite3")},
            indent=2,
        )
    )
finally:
    if "observer" in globals():
        observer.close()
    for d in devices:
        d.link.close()
    for p in reversed(children):
        if p.poll() is None:
            p.terminate()
        p.wait(timeout=5)
    for f in handles:
        f.close()
