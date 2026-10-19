import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--smoke", action="store_true")
args = parser.parse_args()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    os.environ["SMARTFAN_PORT"] = str(s.getsockname()[1])
work = ROOT / "build" / ("demo-" + uuid.uuid4().hex[:8])
work.mkdir(parents=True)
os.environ["SMARTFAN_DB"] = str(work / "demo.sqlite3")
from PyQt5 import QtWidgets as W, QtCore, QtGui
from smartfan.gui import MainWindow
import imageio_ffmpeg

out = ROOT / "submission"
out.mkdir(exist_ok=True)
assets = out / "assets"
assets.mkdir(exist_ok=True)
services = []
files = []
for module in ["broker", "manager"]:
    f = open(work / (module + ".log"), "w")
    files.append(f)
    services.append(
        subprocess.Popen(
            [sys.executable, "-m", "smartfan." + module], cwd=ROOT, stdout=f, stderr=f
        )
    )
    time.sleep(1)
app = W.QApplication([])
app.setStyle("Fusion")

for filename in ["segoeui.ttf", "segoeuib.ttf", "arial.ttf"]:
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
    if font.exists():
        QtGui.QFontDatabase.addApplicationFont(str(font))
app.setFont(QtGui.QFont("Segoe UI", 10))
window = MainWindow()
window.resize(1506, 970)
window.show()
window.setFixedSize(1506, 970)
started = time.monotonic()
index = 0
frames = 0
encoder = None
if not args.smoke:
    encoder = subprocess.Popen(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "bgra",
            "-video_size",
            f"{window.width()}x{window.height()}",
            "-framerate",
            "6",
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            str(out / "SmartFan_Demo.mp4"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=open(work / "ffmpeg.log", "w"),
    )


def mode(m):
    window.set_mode(m)


timeline = [
    (
        0,
        "Normal operation: 24 C / 50% RH. All readings pass through MQTT.",
        lambda: window.set_sample(24, 50),
    ),
    (
        9,
        "Temperature reaches 28 C. The manager requests fan ON.",
        lambda: window.set_sample(28, 50),
    ),
    (
        18,
        "At 33 C the environment status becomes Alarm.",
        lambda: window.set_sample(33, 50),
    ),
    (
        27,
        "Cooling to 27 C clears the warning. Hysteresis keeps the fan ON.",
        lambda: window.set_sample(27, 50),
    ),
    (
        36,
        "At 26 C and 50% RH both OFF conditions are met.",
        lambda: window.set_sample(26, 50),
    ),
    (
        45,
        "Humidity alone: 24 C / 80% RH triggers Alarm and fan ON.",
        lambda: window.set_sample(24, 80),
    ),
    (
        54,
        "Switch to MANUAL. Environmental monitoring continues.",
        lambda: mode("MANUAL"),
    ),
    (
        58,
        "The button sends OFF through MQTT. Alarm remains visible.",
        lambda: window.off.click(),
    ),
    (65, "Return to AUTO. High humidity turns the fan ON again.", lambda: mode("AUTO")),
    (
        72,
        "Pause the sensor. After 10 seconds, automatic control is suspended.",
        lambda: window.pause.setChecked(True),
    ),
    (
        86,
        "Resume readings at 24 C / 50% RH. The system recovers.",
        lambda: (window.set_sample(24, 50), window.pause.setChecked(False)),
    ),
    (
        96,
        "Measurements, events and command results are preserved in SQLite.",
        lambda: None,
    ),
]
saved = set()


def capture():
    global index, frames
    elapsed = time.monotonic() - started
    while index < len(timeline) and elapsed >= timeline[index][0]:
        _, caption, action = timeline[index]
        window.caption.setText(caption)
        action()
        index += 1
    pixmap = window.grab()
    for at, name in [
        (7, "dashboard_normal"),
        (23, "dashboard_alarm"),
        (62, "dashboard_manual"),
        (84, "dashboard_stale"),
        (99, "dashboard_history"),
    ]:
        if elapsed >= at and name not in saved:
            pixmap.save(str(assets / (name + ".png")))
            saved.add(name)
    if encoder:
        im = pixmap.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        ptr = im.bits()
        ptr.setsize(im.byteCount())
        encoder.stdin.write(bytes(ptr))
        frames += 1
    if elapsed >= (8 if args.smoke else 103):
        app.quit()


timer = QtCore.QTimer()
timer.timeout.connect(capture)
timer.start(167)
try:
    app.exec_()
finally:
    window.close()
    if encoder:
        encoder.stdin.close()
        encoder.wait(timeout=30)
    for p in reversed(services):
        p.terminate()
        p.wait(timeout=5)
    for f in files:
        f.close()
print(
    "Saved screenshots" if args.smoke else f"Saved {frames} real application frames",
    flush=True,
)
