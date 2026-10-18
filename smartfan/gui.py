import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from PyQt5 import QtCore, QtGui, QtWidgets
from .emulators import DHTEmulator, ButtonEmulator, RelayEmulator
from .mqtt_link import Link, message

ICONS = (Path(__file__).parent / 'icons').as_posix()

STYLE = """
QWidget {font-family: Segoe UI; font-size: 13px; color:#20354b; background:#f3f6fa;}
QGroupBox {background:white; border:1px solid #dae2eb; border-radius:10px; margin-top:14px; padding:16px 12px 10px; font-weight:600;}
QGroupBox::title {subcontrol-origin: margin; left:14px; padding:0 6px;}
QLabel {background:transparent;}
QPushButton {background:#176e83; color:white; border:0; padding:9px 15px; border-radius:5px; font-weight:600;}
QPushButton:hover {background:#11566a;}
QPushButton:disabled {background:#bdc9d3; color:#607183;}
QDoubleSpinBox,QComboBox {background:white; border:1px solid #cad6e0; border-radius:4px; padding:5px;}
QDoubleSpinBox {padding-right:22px;}
QDoubleSpinBox::up-button,QDoubleSpinBox::down-button {subcontrol-origin:border; width:20px; border-left:1px solid #cad6e0; background:#f3f6fa;}
QDoubleSpinBox::up-button {subcontrol-position:top right; border-top-right-radius:4px; border-bottom:1px solid #cad6e0;}
QDoubleSpinBox::down-button {subcontrol-position:bottom right; border-bottom-right-radius:4px;}
QDoubleSpinBox::up-button:hover,QDoubleSpinBox::down-button:hover {background:#daeef2;}
QDoubleSpinBox::up-arrow {image:url(ICONS/up.svg); width:10px; height:6px;}
QDoubleSpinBox::down-arrow {image:url(ICONS/down.svg); width:10px; height:6px;}
QTableWidget {background:white; border:0; gridline-color:#e7edf3; selection-background-color:#daeef2;}
QHeaderView::section {background:#edf3f8; border:0; padding:7px; font-weight:600;}
QCheckBox {background:transparent; spacing:7px;}
""".replace('ICONS', ICONS)


class Plot(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.readings = []
        self.setMinimumHeight(175)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        area = QtCore.QRectF(38, 15, self.width() - 54, self.height() - 44)
        for tick_value in [0, 25, 50, 75, 100]:
            y = area.bottom() - area.height() * tick_value / 100
            painter.setPen(QtGui.QColor('#e3eaf0'))
            painter.drawLine(
                QtCore.QPointF(area.left(), y), QtCore.QPointF(area.right(), y)
            )
            painter.setPen(QtGui.QColor('#65778b'))
            painter.drawText(3, int(y + 4), str(tick_value))
        if len(self.readings) > 1:
            start, end = (
                self.readings[0]['received_at'],
                self.readings[-1]['received_at'],
            )
            for key, color in [('temperature', '#e4873a'), ('humidity', '#177a91')]:
                path = QtGui.QPainterPath()
                for index, reading in enumerate(self.readings):
                    x = area.left() + area.width() * (
                        reading['received_at'] - start
                    ) / max(end - start, 1)
                    y = area.bottom() - area.height() * reading[key] / 100
                    if index == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                painter.setPen(QtGui.QPen(QtGui.QColor(color), 2.5))
                painter.drawPath(path)
            painter.setPen(QtGui.QColor('#65778b'))
            painter.drawText(
                int(area.left()),
                self.height() - 5,
                datetime.fromtimestamp(start).strftime('%H:%M:%S'),
            )
            painter.drawText(
                int(area.right() - 65),
                self.height() - 5,
                datetime.fromtimestamp(end).strftime('%H:%M:%S'),
            )
        else:
            painter.setPen(QtGui.QColor('#65778b'))
            painter.drawText(
                area, QtCore.Qt.AlignCenter, 'Waiting for measurement history'
            )


def make_group(title):
    group = QtWidgets.QGroupBox(title)
    layout = QtWidgets.QVBoxLayout(group)
    return group, layout


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SmartFan | Daniel Kam | IoT course project')
        self.resize(1280, 850)
        self.setStyleSheet(STYLE)
        self.link = Link('gui', ['manager/state'])
        self.link.start()
        self.sensor = DHTEmulator()
        self.button = ButtonEmulator()
        self.relay = RelayEmulator()
        self.state = {}
        self.last_state = 0
        self.last_events = None
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(10)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel('SmartFan')
        title.setStyleSheet('font-size:30px;font-weight:700;')
        header.addWidget(title)
        description = QtWidgets.QLabel(
            'ROOM 01   /   Public building ventilation simulator'
        )
        description.setStyleSheet('color:#63778b;')
        header.addWidget(description)
        header.addStretch()
        self.connection = QtWidgets.QLabel('Connecting...')
        header.addWidget(self.connection)
        outer.addLayout(header)
        self.caption = QtWidgets.QLabel(
            'Live MQTT control • Three device emulators • Local SQLite history'
        )
        self.caption.setStyleSheet(
            'background:#e4eef4;padding:9px;border-radius:5px;font-size:14px;'
        )
        outer.addWidget(self.caption)
        body = QtWidgets.QHBoxLayout()
        outer.addLayout(body, 1)
        left = QtWidgets.QVBoxLayout()
        right = QtWidgets.QVBoxLayout()
        body.addLayout(left, 3)
        body.addLayout(right, 2)
        metrics = QtWidgets.QHBoxLayout()
        left.addLayout(metrics)
        self.temp, self.humidity, self.fan = (
            QtWidgets.QLabel('--'),
            QtWidgets.QLabel('--'),
            QtWidgets.QLabel('UNKNOWN'),
        )
        for name, label in [
            ('Temperature', self.temp),
            ('Relative humidity', self.humidity),
            ('Fan status', self.fan),
        ]:
            group, layout = make_group(name)
            label.setStyleSheet('font-size:27px;font-weight:600;')
            layout.addWidget(label)
            metrics.addWidget(group)
        control, layout = make_group('Operating mode and status')
        left.addWidget(control)
        row = QtWidgets.QHBoxLayout()
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(['AUTO', 'MANUAL'])
        self.mode.activated[str].connect(self.set_mode)
        row.addWidget(QtWidgets.QLabel('Control mode'))
        row.addWidget(self.mode)
        row.addStretch()
        self.severity = QtWidgets.QLabel('Waiting for data')
        row.addWidget(self.severity)
        layout.addLayout(row)
        self.status = QtWidgets.QLabel('Waiting for manager and device reports')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(
            QtWidgets.QLabel('ON: ≥28°C or ≥70% RH     OFF: ≤26°C and ≤65% RH')
        )
        group, layout = make_group('Recent history')
        left.addWidget(group, 1)
        layout.addWidget(
            QtWidgets.QLabel(
                '<span style="color:#e4873a; font-size:16px;">●</span> Temperature °C'
                '&nbsp;&nbsp;&nbsp;&nbsp;'
                '<span style="color:#177a91; font-size:16px;">●</span> Humidity %'
            )
        )
        self.plot = Plot()
        layout.addWidget(self.plot)
        self.counts = QtWidgets.QLabel('SQLite: waiting for manager')
        layout.addWidget(self.counts)
        group, layout = make_group('DHT sensor emulator')
        right.addWidget(group)
        form = QtWidgets.QFormLayout()
        self.temperature_input = QtWidgets.QDoubleSpinBox()
        self.temperature_input.setRange(-20, 60)
        self.temperature_input.setValue(24)
        self.temperature_input.setSuffix(' °C')
        self.humidity_input = QtWidgets.QDoubleSpinBox()
        self.humidity_input.setRange(0, 100)
        self.humidity_input.setValue(50)
        self.humidity_input.setSuffix(' %')
        form.addRow('Temperature', self.temperature_input)
        form.addRow('Humidity', self.humidity_input)
        layout.addLayout(form)
        self.temperature_input.valueChanged.connect(self.inputs)
        self.humidity_input.valueChanged.connect(self.inputs)
        presets = QtWidgets.QHBoxLayout()
        for label, temperature, humidity in [
            ('Normal', 24, 50),
            ('Heat', 33, 50),
            ('Humid', 24, 82),
        ]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(
                lambda checked,
                temperature=temperature,
                humidity=humidity: self.set_sample(temperature, humidity)
            )
            presets.addWidget(button)
        layout.addLayout(presets)
        self.pause = QtWidgets.QCheckBox('Pause sensor updates (fault demo)')
        self.pause.toggled.connect(
            lambda paused: setattr(self.sensor, 'enabled', not paused)
        )
        layout.addWidget(self.pause)
        group, layout = make_group('Button emulator')
        right.addWidget(group)
        layout.addWidget(QtWidgets.QLabel('Manual requests travel through MQTT.'))
        row = QtWidgets.QHBoxLayout()
        self.on = QtWidgets.QPushButton('Fan ON')
        self.off = QtWidgets.QPushButton('Fan OFF')
        self.on.clicked.connect(lambda: self.button.press(True))
        self.off.clicked.connect(lambda: self.button.press(False))
        row.addWidget(self.on)
        row.addWidget(self.off)
        layout.addLayout(row)
        group, layout = make_group('Relay emulator')
        right.addWidget(group)
        self.relay_label = QtWidgets.QLabel('Physical simulation: OFF')
        layout.addWidget(self.relay_label)
        self.relay_pause = QtWidgets.QCheckBox('Pause relay processing (fault demo)')
        self.relay_pause.toggled.connect(
            lambda paused: setattr(self.relay, 'enabled', not paused)
        )
        layout.addWidget(self.relay_pause)
        layout.addWidget(QtWidgets.QLabel('Commands expire after 5 seconds.'))
        right.addStretch()
        events, layout = make_group('Info / Warning / Alarm event history')
        outer.addWidget(events)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Time', 'Level', 'Source', 'Message'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.Stretch
        )
        self.table.setColumnWidth(0, 95)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 100)
        self.table.setMinimumHeight(190)
        layout.addWidget(self.table)
        footer = QtWidgets.QHBoxLayout()
        footer.addWidget(
            QtWidgets.QLabel(
                'Daniel Kam  •  IoT Software Development in a Smart City Environment  •  Simulation only'
            )
        )
        footer.addStretch()
        export = QtWidgets.QPushButton('Export recent readings')
        export.clicked.connect(self.export)
        footer.addWidget(export)
        outer.addLayout(footer)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def inputs(self):
        self.sensor.temperature = self.temperature_input.value()
        self.sensor.humidity = self.humidity_input.value()

    def set_sample(self, temperature, humidity):
        self.temperature_input.setValue(temperature)
        self.humidity_input.setValue(humidity)
        self.sensor.last = 0

    def set_mode(self, mode):
        self.link.send('control/mode', message(mode=mode), qos=0)

    def tick(self):
        now = time.time()
        self.sensor.tick(now)
        self.button.tick(now)
        self.relay.tick(now)
        for name, data in self.link.drain():
            if name == 'manager/state':
                self.state = data
                self.last_state = now
                self.refresh()
        live = self.link.connected and now - self.last_state < 3
        self.connection.setText(
            '● MQTT + manager online' if live else '● Waiting for MQTT / manager'
        )
        self.connection.setStyleSheet('color:#19745c;' if live else 'color:#b35226;')
        manual = (
            live and self.state.get('mode') == 'MANUAL' and self.button.link.connected
        )
        self.on.setEnabled(manual)
        self.off.setEnabled(manual)
        self.mode.setEnabled(live)
        self.relay_label.setText(
            f'Physical simulation: {"ON" if self.relay.state else "OFF"}'
            + (' / paused' if not self.relay.enabled else '')
        )
        if not live:
            self.status.setText(
                'Live state unavailable. Displayed values are last known; commands disabled.'
            )

    def refresh(self):
        state = self.state
        sample = state.get('sample') or {}
        sensor_fresh = state.get('sensor_fresh')
        self.temp.setText(f'{sample["temperature"]:.1f} °C' if sample else '--')
        self.humidity.setText(f'{sample["humidity"]:.1f} %' if sample else '--')
        value = state.get('reported')
        self.fan.setText(
            'UNKNOWN'
            if value is None
            else ('ON' if value else 'OFF')
            + (' *' if not state.get('relay_fresh') else '')
        )
        self.mode.setCurrentText(state.get('mode', 'AUTO'))
        severity = (
            state.get('severity', 'Unknown') if sensor_fresh else 'STALE / WAITING'
        )
        self.severity.setText(severity)
        self.severity.setStyleSheet(
            'font-weight:700;color:'
            + {'Normal': '#19745c', 'Warning': '#b97819', 'Alarm': '#bc3b43'}.get(
                severity, '#62758a'
            )
            + ';'
        )
        if state.get('storage_error'):
            status = 'DATABASE ERROR: measurements may not be saved'
        elif state.get('command_failed'):
            status = 'ALARM: command was not acknowledged. Reported state is not the requested state.'
        elif state.get('pending'):
            status = 'Command pending: waiting for relay acknowledgement'
        elif not sensor_fresh:
            status = 'Sensor unavailable or stale. Automatic control is suspended.'
        else:
            status = 'Fresh sensor data • Relay ' + (
                'confirmed'
                if state.get('relay_fresh')
                else 'unavailable / last known state'
            )
        self.status.setText(status)
        self.plot.readings = state.get('readings', [])
        self.plot.update()
        counts = state.get('counts', {})
        self.counts.setText(
            f'SQLite totals: {counts.get("measurements", 0)} readings   {counts.get("events", 0)} events   {counts.get("commands", 0)} commands'
        )
        rows = state.get('events', [])
        if rows != self.last_events:
            self.last_events = rows
            self.table.setRowCount(len(rows))
            for index, entry in enumerate(rows):
                for column, value in enumerate(
                    [
                        datetime.fromtimestamp(entry['ts']).strftime('%H:%M:%S'),
                        entry['level'],
                        entry['kind'],
                        entry['text'],
                    ]
                ):
                    item = QtWidgets.QTableWidgetItem(value)
                    if column == 1:
                        item.setForeground(
                            QtGui.QColor(
                                {
                                    'Info': '#19745c',
                                    'Warning': '#ad741b',
                                    'Alarm': '#b83540',
                                }[entry['level']]
                            )
                        )
                    self.table.setItem(index, column, item)

    def export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Export recent readings', 'readings.csv', 'CSV (*.csv)'
        )
        if path:
            rows = self.state.get('readings', [])
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        'id',
                        'ts',
                        'received_at',
                        'device',
                        'temperature',
                        'humidity',
                    ],
                )
                writer.writeheader()
                writer.writerows(rows)

    def closeEvent(self, event):
        for link in [self.link, self.sensor.link, self.button.link, self.relay.link]:
            link.close()
        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
