# HVDC Server Line Power Simulator

This project is a PySide6-based simulator for a 16-station server test line served by a single RGV. It is intended for power-demand analysis, not hardware control.

The simulation engine uses `SimPy` for event scheduling and PySide6 for the desktop UI.

Physical path:

`Load -> Gate -> Zone 1 (8 stations) -> Gate -> Zone 2 (8 stations) -> Gate -> Packing`

## What it models

- Server arrivals at a single load point
- One RGV that crosses three gated boundaries, loads stations, and takes completed racks to packing
- Station occupancy, testing time, pack blocking, and load-zone parking when idle
- A staged station power profile: startup ramp, steady test phase, shutdown ramp
- Real-time test power, peak test power, average test power, throughput, and utilization
- Live power trace for station demand only

## Assumptions

- A completed test stops drawing station test power immediately.
- The station stays blocked until the RGV removes the rack and transfers it to packing.
- Incoming deliveries are prioritized over packing moves when an empty station exists.
- RGV power has two states internally for motion logic, but it is excluded from the reported power metrics.
- Station loading, unloading, and gate open/close all use configurable times.

## Run

```bash
pip install -r requirements.txt
python server_line_simulator.py
```

## Test

```bash
python -m unittest discover -s tests -v
```
