import argparse
import os
import socket
import subprocess
import sys
import time
from smartfan.config import ROOT, HOST, PORT


def wait_port(process, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError('Broker exited; inspect logs/broker.log')
        try:
            with socket.create_connection((HOST, PORT), timeout=0.3):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError('Broker startup timed out')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--external-broker', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    (ROOT / 'logs').mkdir(exist_ok=True)
    children = []
    logs = []
    try:
        if not args.external_broker:
            with socket.socket() as probe:
                try:
                    probe.bind((HOST, PORT))
                except OSError:
                    raise RuntimeError(
                        f'Port {PORT} is in use. Close the previous app or choose SMARTFAN_PORT.'
                    )
            log_file = open(ROOT / 'logs/broker.log', 'w')
            logs.append(log_file)
            process = subprocess.Popen(
                [sys.executable, '-m', 'smartfan.broker'],
                stdout=log_file,
                stderr=log_file,
            )
            children.append(process)
            wait_port(process)
        log_file = open(ROOT / 'logs/manager.log', 'w')
        logs.append(log_file)
        process = subprocess.Popen(
            [sys.executable, '-m', 'smartfan.manager'], stdout=log_file, stderr=log_file
        )
        children.append(process)
        gui = subprocess.Popen([sys.executable, '-m', 'smartfan.gui'])
        children.append(gui)
        while gui.poll() is None:
            if any(child.poll() is not None for child in children[:-1]):
                raise RuntimeError('A background service exited. Inspect logs.')
            time.sleep(0.4)
    except (RuntimeError, KeyboardInterrupt) as exc:
        print(exc)
        return 1
    finally:
        for process in reversed(children):
            if process.poll() is None:
                process.terminate()
        for process in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log_file in logs:
            log_file.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
