from __future__ import annotations

from enum import Enum, auto


EPSILON = 1e-9
POWER_HISTORY_POINTS = 300
POWER_SAMPLE_SIM_SECONDS = 5.0
UI_TICK_MS = 45
FINISHING_THRESHOLD = 0.85
TIME_SCALES: dict[str, float] = {"sec": 1.0, "min": 60.0, "hr": 3600.0}


class StationState(Enum):
    IDLE = auto()
    TESTING = auto()
    WAITING_UNLOAD = auto()


class PayloadKind(Enum):
    EMPTY = auto()
    INCOMING = auto()
    OUTGOING = auto()
