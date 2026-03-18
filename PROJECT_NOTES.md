# Project Notes

## Purpose

This project is a PySide6 + SimPy desktop simulator for a server test line with:

- 16 test stations
- 1 RGV
- 3 gates
- station-only reported power demand

The current repo is intentionally a bare runtime package, not a development-heavy repo.

## Current Structure

```text
main.py
README.md
requirements.txt
.gitignore
simulator/
  __init__.py
  config.py
  models.py
  engine.py
  ui/
    __init__.py
    theme.py
    widgets.py
    visualizers.py
    main_window.py
```

## Major Changes Already Done

### UI / Structure

- Reworked the app into modular files under `simulator/`
- Added `main.py` as the main entry point
- Removed the old `GUI_Only` prototype from the repo
- Removed the compatibility wrapper `server_line_simulator.py`
- Removed the test file and `tests/` folder to keep the repo barebones
- Cleaned out `__pycache__` folders

### Graph Behavior

- Removed the fake startup future sample that made the graph look like it already had a 1-second result
- Made the graph interactive:
  - mouse wheel zoom
  - drag pan
  - double-click reset
- Set the default graph window to be more zoomed out
- Changed graph/history/peak/average displays to use station test power only

### Power Reporting

- Removed non-test loads from reported power metrics
- RGV power is not included in:
  - graph
  - startup power
  - peak power
  - average power
  - power cards
- Doors/gates are also not included in reported power
- Reported power is intended to represent only the units under test

### Gate / Door Behavior

- Replaced the original shrinking/disappearing gate look with a wall-like sliding panel
- Changed the door motion to slide up/down instead of left/right
- Changed gate timing so the RGV no longer stops before a gate to wait for it
- Gate opening is scheduled like a sensor-triggered system so the RGV can keep moving
- Gate 2 was corrected to open in the same upward direction as the others

### Simulation Logic Fixes

- Fixed the station assignment race where a later server could be placed onto a station that had just been loaded
- The fix was to start the station test state transition synchronously before the timed SimPy process continues
- Added a solver-running guard so solver-driven UI changes do not overwrite the solver status message mid-run
- Removed the dead `_operate_gate` path during refactoring

## User Preferences

These are strong preferences and should be preserved unless explicitly changed.

### Power

- Only show unit testing power
- Do not include RGV power in reported metrics
- Do not include gate/door power in reported metrics
- Do not include any non-test subsystem power in the graph or power cards

### Gates / Doors

- Doors should look like physical walls/panels
- Doors should be about as tall as, or slightly taller than, the RGV
- Doors must slide vertically, not horizontally
- Doors should open just in time like a sensor-triggered system
- The RGV should not stop or slow down just because a gate is opening

### Graph

- Graph should not show fake startup data
- Graph should be interactive
- Graph should default to a more zoomed-out view

### Repo / Codebase

- Prefer modular files over a giant single-file script
- Prefer a barebones repo layout
- Avoid keeping prototype files or legacy wrappers unless they are explicitly needed
- Keep the runtime repo clean and minimal

## Assessment of the Current External Review

The recent assessment is partly right, but not fully accurate.

### Fair Points

- The modular split is good
- Type hints are consistently used
- The theme centralization is good
- The power model is more sophisticated than a simple steady-state model
- `log()` is currently a no-op and does reduce diagnostics
- There is currently no test suite in the repo
- Config persistence is not implemented
- `PySide6` is not pinned

### Incorrect or Overstated Points

- "Solver has no rollback on failure" is imprecise
  - The engine is not mutated mid-solve
  - The real issue is that the solver mutates UI values while solving, so a failed solve can leave changed inputs
- "Zero input validation" is overstated
  - The UI spinboxes already apply ranges and lower bounds in several places
  - Model-level validation is still missing
- "UI not updated after solver runs" is not accurate
  - The UI values change during solving and `_reset()` refreshes the engine at the end
- "Test coverage: zero" is true only for the current barebones repo
  - The project previously had engine tests before the repo was intentionally stripped down

## Known Remaining Gaps

- No runtime logging sink
- No persistence for scenarios/configs
- No automated tests in the current repo
- Some API naming still reflects earlier versions
- Layout constants in the visualizers are still mostly hardcoded

## Guidance for Future Changes

- Do not reintroduce non-test power into any displayed power metric
- Do not revert gates back to horizontal motion or stop-and-wait behavior
- If tests are brought back, focus first on:
  - station assignment state machine
  - gate timing behavior
  - station-only power accounting
  - solver behavior
