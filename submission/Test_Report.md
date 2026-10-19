# Test report

Executed 12 October 2026 on Windows, Python 3.12.14.

## Unit and persistence tests

`python -m pytest -q`: **26 passed**.

Coverage: threshold boundaries, humidity triggers, hysteresis, severity, invalid measurements, matching acknowledgements, command timeout, sensor recovery, manual control, mode changes while a command is pending, restart freshness and SQLite deduplication/persistence.

## Real MQTT integration checks

| Check | Result |
|---|---|
| Initial normal data saved | PASS |
| Temperature trigger and relay acknowledgement | PASS |
| Hysteresis holds ON at 27 C | PASS |
| Cooling turns fan OFF | PASS |
| Humidity alone triggers fan | PASS |
| High humidity raises Alarm | PASS |
| Manual mode accepted | PASS |
| Button OFF while Alarm remains | PASS |
| Return to AUTO uses fresh reading | PASS |
| Both low conditions turn OFF | PASS |
| Malformed JSON rejected without crash | PASS |
| Sensor stale warning after 10 seconds | PASS |
| Sensor recovers | PASS |
| Relay acknowledgement timeout | PASS |
| Relay recovery reconciles desired state | PASS |
| Manager restart retains history without live sensor state | PASS |
| Manager restart resumes from fresh telemetry | PASS |
| Broker loss suspends control | PASS |
| Broker restart reconnects and resubscribes | PASS |

The integration test uses real MQTT traffic and separate broker/manager processes. It does not claim hardware validation, large-scale load testing or internet security testing.

The short demonstration was captured from the working Qt application, with a fresh isolated database.