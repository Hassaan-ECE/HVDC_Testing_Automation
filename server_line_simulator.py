from __future__ import annotations

import sys
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from html import escape

import simpy
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


EPSILON = 1e-9
POWER_HISTORY_POINTS = 300
POWER_SAMPLE_SIM_SECONDS = 5.0
UI_TICK_MS = 45
FINISHING_THRESHOLD = 0.85


class StationState(Enum):
    IDLE = auto()
    TESTING = auto()
    WAITING_UNLOAD = auto()


class PayloadKind(Enum):
    EMPTY = auto()
    INCOMING = auto()
    OUTGOING = auto()


class C:
    BG = QColor("#080c14")
    SURFACE = QColor("#0d1219")
    CARD = QColor("#111820")
    RAISED = QColor("#182030")
    INPUT_BG = QColor("#0a0f16")
    HOVER = QColor("#1c2838")
    GROUP_BG = QColor("#0e141e")
    OVERLAY = QColor("#1c2838")
    BORDER = QColor("#1c2636")
    BORDER_LT = QColor("#253344")
    BORDER_DIM = QColor("#1c2636")

    FG = QColor("#e2e8f0")
    FG_SEC = QColor("#94a3b8")
    FG_DIM = QColor("#64748b")
    FG_MUTED = QColor("#3d4856")

    ACCENT = QColor("#3b82f6")
    ACCENT_DK = QColor("#2563eb")
    BLUE = QColor("#3b82f6")
    GREEN = QColor("#22c55e")
    GREEN_DK = QColor("#16a34a")
    AMBER = QColor("#f59e0b")
    YELLOW = QColor("#f59e0b")
    ORANGE = QColor("#f59e0b")
    RED = QColor("#ef4444")
    RED_DK = QColor("#dc2626")
    PURPLE = QColor("#a855f7")
    CYAN = QColor("#06b6d4")

    TRACK = QColor("#2a3a4e")
    ZONE1_BG = QColor("#0b1730")
    ZONE1_BD = QColor("#3b82f6")
    ZONE2_BG = QColor("#102317")
    ZONE2_BD = QColor("#22c55e")
    GATE_DOOR = QColor("#5b6678")
    GATE_FRAME = QColor("#253344")

    ST_IDLE = QColor("#0e141e")
    ST_IDLE_BD = QColor("#253344")
    ST_TEST = QColor("#123766")
    ST_TEST_BD = QColor("#3b82f6")
    ST_FIN = QColor("#4a3208")
    ST_FIN_BD = QColor("#f59e0b")
    ST_BLOCK = QColor("#43161b")
    ST_BLOCK_BD = QColor("#ef4444")

    PB_BG = QColor("#0a0f16")
    PB_FILL = QColor("#3b82f6")
    PB_LATE = QColor("#f59e0b")

    LOAD_FILL = QColor("#20170a")
    LOAD_BD = QColor("#f59e0b")
    PACK_FILL = QColor("#241115")
    PACK_BD = QColor("#ef4444")

    GRAPH_LINE = QColor("#3b82f6")
    GRAPH_FILL = QColor(59, 130, 246, 90)
    GRAPH_PEAK = QColor("#ef4444")
    GRAPH_AVG = QColor("#22c55e")
    GRAPH_GRID = QColor("#1c2636")

    LOG_BG = QColor("#080c14")
    LOG_FG = QColor("#22c55e")

    RGV = {
        PayloadKind.EMPTY: QColor("#f59e0b"),
        PayloadKind.INCOMING: QColor("#3b82f6"),
        PayloadKind.OUTGOING: QColor("#ef4444"),
    }


class StatusDot(QWidget):
    def __init__(self, color: QColor | None = None, size: int = 8) -> None:
        super().__init__()
        self._color = color or C.GREEN
        self._size = size
        self._opacity = 1.0
        self._growing = False
        self.setFixedSize(size + 10, size + 10)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def _tick(self) -> None:
        if self._growing:
            self._opacity = min(self._opacity + 0.04, 1.0)
            if self._opacity >= 1.0:
                self._growing = False
        else:
            self._opacity = max(self._opacity - 0.04, 0.3)
            if self._opacity <= 0.3:
                self._growing = True
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_x = self.width() / 2
        center_y = self.height() / 2

        glow = QColor(self._color)
        glow.setAlphaF(self._opacity * 0.22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(center_x, center_y), self._size, self._size)

        core = QColor(self._color)
        core.setAlphaF(self._opacity)
        painter.setBrush(core)
        painter.drawEllipse(QPointF(center_x, center_y), self._size / 2, self._size / 2)
        painter.end()


@dataclass
class SimulationConfig:
    num_stations: int = 16
    arrival_interval: float = 45.0
    startup_ramp_duration: float = 300.0
    steady_state_duration: float = 7200.0
    shutdown_ramp_duration: float = 300.0
    move_time_per_station: float = 12.0
    transfer_time: float = 6.0
    gate_cycle_time: float = 4.0
    peak_station_power: float = 1000.0
    steady_state_power_pct: float = 10.0
    rgv_moving_power: float = 35.0
    rgv_idle_power: float = 5.0

    @property
    def test_duration(self) -> float:
        return (
            self.startup_ramp_duration
            + self.steady_state_duration
            + self.shutdown_ramp_duration
        )


@dataclass
class Station:
    station_id: int
    state: StationState = StationState.IDLE
    server_id: int | None = None
    test_start_time: float | None = None
    waiting_unload_since: float | None = None
    occupied_start_time: float | None = None
    accumulated_testing_time: float = 0.0
    accumulated_occupied_time: float = 0.0

    def get_testing_time(self, now: float) -> float:
        total = self.accumulated_testing_time
        if self.state is StationState.TESTING and self.test_start_time is not None:
            total += max(0.0, now - self.test_start_time)
        return total

    def get_occupied_time(self, now: float) -> float:
        total = self.accumulated_occupied_time
        if self.is_occupied and self.occupied_start_time is not None:
            total += max(0.0, now - self.occupied_start_time)
        return total

    @property
    def is_occupied(self) -> bool:
        return self.state in (StationState.TESTING, StationState.WAITING_UNLOAD)


class SimulationEngine:
    LOAD_POSITION = 0.0
    GATE_1_POSITION = 1.0
    GATE_2_POSITION = 10.0
    GATE_3_POSITION = 19.0
    PACKING_POSITION = 20.0
    GATE_CLEARANCE = 0.85

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config
        self.reset()

    def reset(self) -> None:
        self.env = simpy.Environment()
        self.waiting_servers: deque[int] = deque()
        self.peak_queue = 0
        self.completed_servers = 0
        self.next_server_id = 1

        self.energy_watt_seconds = 0.0
        self.station_energy_watt_seconds = 0.0
        self.last_power_checkpoint = 0.0
        self.peak_power = 0.0
        self.peak_power_time = 0.0
        self.peak_station_power_value = 0.0
        self.power_history: deque[tuple[float, float]] = deque(maxlen=POWER_HISTORY_POINTS)
        self.stations = {
            i: Station(i) for i in range(1, self.config.num_stations + 1)
        }

        self.gate_targets: dict[str, float] = {}
        self.gate_start_states: dict[str, float] = {}
        self.gate_start_times: dict[str, float] = {}
        for _, name in self.gate_boundaries():
            self.gate_targets[name] = 0.0
            self.gate_start_states[name] = 0.0
            self.gate_start_times[name] = 0.0

        self.rgv_position_val = self.LOAD_POSITION
        self.rgv_is_moving = False
        self.rgv_payload = PayloadKind.EMPTY
        self.rgv_desc = "Idle"
        self.rgv_phase_start_pos = self.LOAD_POSITION
        self.rgv_phase_target_pos = self.LOAD_POSITION
        self.rgv_phase_start_time = 0.0
        self.rgv_phase_duration = 0.0
        self.rgv_wake_event = self.env.event()
        self.power_history.append((0.0, self.current_station_power))

        self._update_peak_power()
        self.env.process(self._arrival_loop())
        self.env.process(self._rgv_loop())
        self.env.process(self._power_monitor_loop())

    def log(self, message: str) -> None:
        del message

    def advance(self, dt: float) -> None:
        dt = max(0.0, dt)
        if dt <= EPSILON:
            self._checkpoint_power()
            return

        target = self.env.now + dt
        self.env.run(until=target)
        while self.env.peek() <= target + EPSILON:
            self.env.step()

        self._checkpoint_power()

    @property
    def current_rgv_power(self) -> float:
        return (
            self.config.rgv_moving_power
            if self.rgv_is_moving
            else self.config.rgv_idle_power
        )

    def current_power(self) -> float:
        return self.current_station_power

    @property
    def current_station_power(self) -> float:
        return sum(
            self._station_power_at(station, self.env.now)
            for station in self.stations.values()
        )

    @property
    def peak_station_power(self) -> float:
        return self.peak_station_power_value

    @property
    def rgv_position(self) -> float:
        if not self.rgv_is_moving or self.rgv_phase_duration <= EPSILON:
            return self.rgv_position_val

        fraction = min(
            1.0,
            max(
                0.0,
                (self.env.now - self.rgv_phase_start_time) / self.rgv_phase_duration,
            ),
        )
        return self.rgv_phase_start_pos + (
            self.rgv_phase_target_pos - self.rgv_phase_start_pos
        ) * fraction

    @property
    def active_test_count(self) -> int:
        return sum(
            1 for station in self.stations.values() if station.state is StationState.TESTING
        )

    @property
    def blocked_station_count(self) -> int:
        return sum(
            1
            for station in self.stations.values()
            if station.state is StationState.WAITING_UNLOAD
        )

    @property
    def idle_station_count(self) -> int:
        return sum(
            1 for station in self.stations.values() if station.state is StationState.IDLE
        )

    @property
    def average_power(self) -> float:
        if self.env.now <= EPSILON:
            return 0.0
        return self.energy_watt_seconds / self.env.now

    @property
    def average_station_power(self) -> float:
        if self.env.now <= EPSILON:
            return 0.0
        return self.station_energy_watt_seconds / self.env.now

    @property
    def throughput_per_hour(self) -> float:
        if self.env.now <= EPSILON:
            return 0.0
        return self.completed_servers * 3600.0 / self.env.now

    @property
    def occupied_utilization(self) -> float:
        if self.env.now <= EPSILON or self.config.num_stations <= 0:
            return 0.0
        total = sum(
            station.get_occupied_time(self.env.now) for station in self.stations.values()
        )
        return total / (self.env.now * self.config.num_stations)

    @property
    def testing_utilization(self) -> float:
        if self.env.now <= EPSILON or self.config.num_stations <= 0:
            return 0.0
        total = sum(
            station.get_testing_time(self.env.now) for station in self.stations.values()
        )
        return total / (self.env.now * self.config.num_stations)

    def station_remaining_test(self, sid: int) -> float:
        station = self.stations[sid]
        if station.state is not StationState.TESTING or station.test_start_time is None:
            return 0.0
        end_time = station.test_start_time + self.config.test_duration
        return max(0.0, end_time - self.env.now)

    def station_progress(self, sid: int) -> float:
        station = self.stations[sid]
        if station.state is not StationState.TESTING or station.test_start_time is None:
            return 0.0
        elapsed = max(0.0, self.env.now - station.test_start_time)
        return min(1.0, elapsed / max(self.config.test_duration, EPSILON))

    def station_power(self, sid: int) -> float:
        return self._station_power_at(self.stations[sid], self.env.now)

    def constraint_label(self) -> str:
        if len(self.waiting_servers) > 0 and self.idle_station_count == 0:
            return "Stations saturated"
        if len(self.waiting_servers) > 0 and self.idle_station_count > 0:
            return "RGV dispatch limited"
        if self.blocked_station_count > 0:
            return "Unload blocking"
        return "Balanced"

    def gate_open_fraction(self, gate_name: str) -> float:
        start = self.gate_start_states.get(gate_name, 0.0)
        target = self.gate_targets.get(gate_name, 0.0)
        start_time = self.gate_start_times.get(gate_name, 0.0)
        cycle = max(EPSILON, self.config.gate_cycle_time)
        if self.env.now >= start_time + cycle:
            return target
        fraction = (self.env.now - start_time) / cycle
        return start + (target - start) * fraction

    @classmethod
    def station_track_position(cls, sid: int) -> float:
        if sid <= 8:
            return cls.GATE_1_POSITION + sid
        return cls.GATE_2_POSITION + sid - 8

    @classmethod
    def gate_boundaries(cls) -> list[tuple[float, str]]:
        return [
            (cls.GATE_1_POSITION, "Gate 1"),
            (cls.GATE_2_POSITION, "Gate 2"),
            (cls.GATE_3_POSITION, "Gate 3"),
        ]

    def _wake_rgv(self) -> None:
        if not self.rgv_wake_event.triggered:
            self.rgv_wake_event.succeed()

    def _arrival_loop(self):
        while True:
            server_id = self.next_server_id
            self.next_server_id += 1
            self.waiting_servers.append(server_id)
            self.peak_queue = max(self.peak_queue, len(self.waiting_servers))
            self.log(f"Server {server_id} arrived at load point")
            self._wake_rgv()
            yield self.env.timeout(self.config.arrival_interval)

    def _power_monitor_loop(self):
        while True:
            self.power_history.append((self.env.now, self.current_station_power))
            yield self.env.timeout(POWER_SAMPLE_SIM_SECONDS)

    def _rgv_loop(self):
        while True:
            deliver_id = self._pick_delivery_station()
            unload_station = self._pick_unload_station()

            if deliver_id is not None and self.waiting_servers:
                yield from self._do_delivery(deliver_id)
                continue

            if unload_station is not None:
                yield from self._do_pack(unload_station)
                continue

            if abs(self.rgv_position_val - self.LOAD_POSITION) > EPSILON:
                self.rgv_desc = "Return to load zone"
                yield from self._route_to(self.LOAD_POSITION, "Parking at load zone")

            self.rgv_desc = "Idle"
            self.rgv_wake_event = self.env.event()
            yield self.rgv_wake_event

    def _start_station_test(self, station: Station, server_id: int) -> None:
        self._checkpoint_power()
        station.state = StationState.TESTING
        station.server_id = server_id
        station.test_start_time = self.env.now
        station.occupied_start_time = self.env.now
        station.waiting_unload_since = None
        self._update_peak_power()
        self.env.process(self._station_test(station))

    def _station_test(self, station: Station):

        if self.config.startup_ramp_duration > EPSILON:
            yield self.env.timeout(self.config.startup_ramp_duration)
            self._checkpoint_power()

        if self.config.steady_state_duration > EPSILON:
            yield self.env.timeout(self.config.steady_state_duration)
            self._checkpoint_power()

        if self.config.shutdown_ramp_duration > EPSILON:
            yield self.env.timeout(self.config.shutdown_ramp_duration)
            self._checkpoint_power()

        station.accumulated_testing_time += self.config.test_duration
        station.test_start_time = None
        station.state = StationState.WAITING_UNLOAD
        station.waiting_unload_since = self.env.now
        self.log(f"Station {station.station_id} test complete -- awaiting unload")
        self._update_peak_power()
        self._wake_rgv()

    def _do_delivery(self, station_id: int):
        destination = self.station_track_position(station_id)
        self.log(f"RGV -> deliver to Station {station_id}")

        self.rgv_desc = "To load point"
        yield from self._route_to(self.LOAD_POSITION, "Approach load")

        self.rgv_desc = "Picking up server"
        yield self.env.timeout(self.config.transfer_time)
        self._checkpoint_power()

        if not self.waiting_servers:
            return

        server_id = self.waiting_servers.popleft()
        self.rgv_payload = PayloadKind.INCOMING
        self.log(f"Picked up Server {server_id}")

        yield from self._route_to(destination, f"To Station {station_id}")

        self.rgv_desc = f"Loading Station {station_id}"
        yield self.env.timeout(self.config.transfer_time)
        self._checkpoint_power()

        self.rgv_payload = PayloadKind.EMPTY
        self.log(f"Server {server_id} -> Station {station_id}")
        self._start_station_test(self.stations[station_id], server_id)

    def _do_pack(self, station: Station):
        server_id = station.server_id or 0
        station_position = self.station_track_position(station.station_id)

        self.log(f"RGV -> pack from Station {station.station_id}")
        yield from self._route_to(station_position, f"To Station {station.station_id}")

        self.rgv_desc = f"Unloading Station {station.station_id}"
        yield self.env.timeout(self.config.transfer_time)
        self._checkpoint_power()

        if station.occupied_start_time is not None:
            station.accumulated_occupied_time += self.env.now - station.occupied_start_time
        station.state = StationState.IDLE
        station.server_id = None
        station.test_start_time = None
        station.waiting_unload_since = None
        station.occupied_start_time = None
        self.rgv_payload = PayloadKind.OUTGOING
        self.log(f"Removed Server {server_id} from Station {station.station_id}")

        yield from self._route_to(self.PACKING_POSITION, "To packing")

        self.rgv_desc = "Packing server"
        yield self.env.timeout(self.config.transfer_time)
        self._checkpoint_power()

        self.completed_servers += 1
        self.rgv_payload = PayloadKind.EMPTY
        self.log(f"Server {server_id} packed")

    def _route_to(self, target: float, description: str):
        current = self.rgv_position_val
        if abs(current - target) <= EPSILON:
            self.rgv_desc = description
            return

        moving_right = target > current
        if moving_right:
            gates = [
                (position, name)
                for position, name in self.gate_boundaries()
                if current < position < target
            ]
        else:
            gates = [
                (position, name)
                for position, name in reversed(self.gate_boundaries())
                if target < position < current
            ]

        route_start = self.env.now
        unit_time = self.config.move_time_per_station
        gate_lead_distance = max(
            self.GATE_CLEARANCE,
            self.config.gate_cycle_time / max(unit_time, EPSILON),
        )
        for gate_position, gate_name in gates:
            sensor_position = (
                gate_position - gate_lead_distance
                if moving_right
                else gate_position + gate_lead_distance
            )
            clear_position = (
                gate_position + self.GATE_CLEARANCE
                if moving_right
                else gate_position - self.GATE_CLEARANCE
            )
            trigger_time = route_start + abs(sensor_position - current) * unit_time
            clear_time = route_start + abs(clear_position - current) * unit_time
            self.env.process(self._schedule_gate_window(gate_name, trigger_time, clear_time))

        yield from self._move_segment(target, description)

    def _schedule_gate_window(self, name: str, open_time: float, close_time: float):
        wait_to_open = max(0.0, open_time - self.env.now)
        if wait_to_open > EPSILON:
            yield self.env.timeout(wait_to_open)

        self._set_gate_target(name, 1.0)

        wait_to_close = max(0.0, close_time - self.env.now)
        if wait_to_close > EPSILON:
            yield self.env.timeout(wait_to_close)

        self._set_gate_target(name, 0.0)

    def _move_segment(self, target: float, description: str):
        distance = abs(target - self.rgv_position_val)
        if distance <= EPSILON:
            return

        self._checkpoint_power()
        duration = distance * self.config.move_time_per_station
        self.rgv_phase_start_time = self.env.now
        self.rgv_phase_duration = duration
        self.rgv_phase_start_pos = self.rgv_position_val
        self.rgv_phase_target_pos = target
        self.rgv_is_moving = True
        self.rgv_desc = description
        self._update_peak_power()

        yield self.env.timeout(duration)

        self._checkpoint_power()
        self.rgv_position_val = target
        self.rgv_is_moving = False
        self._update_peak_power()

    def _operate_gate(self, name: str, target: float, description: str):
        self.rgv_desc = description
        self._set_gate_target(name, target)
        yield self.env.timeout(self.config.gate_cycle_time)
        self._checkpoint_power()

    def _set_gate_target(self, name: str, target: float) -> None:
        self.gate_start_states[name] = self.gate_open_fraction(name)
        self.gate_targets[name] = target
        self.gate_start_times[name] = self.env.now

    def _pick_delivery_station(self) -> int | None:
        idle_stations = [
            station for station in self.stations.values() if station.state is StationState.IDLE
        ]
        if not idle_stations:
            return None
        return min(
            idle_stations,
            key=lambda station: abs(
                self.rgv_position_val - self.station_track_position(station.station_id)
            ),
        ).station_id

    def _pick_unload_station(self) -> Station | None:
        candidates = [
            station
            for station in self.stations.values()
            if station.state is StationState.WAITING_UNLOAD
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda station: (
                station.waiting_unload_since
                if station.waiting_unload_since is not None
                else self.env.now,
                abs(
                    self.rgv_position_val
                    - self.station_track_position(station.station_id)
                ),
            ),
        )

    def _station_power_at(self, station: Station, now: float) -> float:
        if station.state is not StationState.TESTING or station.test_start_time is None:
            return 0.0

        elapsed = max(0.0, now - station.test_start_time)
        peak = self.config.peak_station_power
        steady = peak * (self.config.steady_state_power_pct / 100.0)
        ramp_up = self.config.startup_ramp_duration
        steady_duration = self.config.steady_state_duration
        ramp_down = self.config.shutdown_ramp_duration

        if ramp_up > EPSILON and elapsed < ramp_up:
            return peak - (peak - steady) * (elapsed / ramp_up)

        elapsed -= ramp_up
        if elapsed < 0:
            return peak
        if elapsed < steady_duration:
            return steady

        elapsed -= steady_duration
        if ramp_down > EPSILON and elapsed < ramp_down:
            return steady + (peak - steady) * (elapsed / ramp_down)
        return peak

    def _integrate_station_power(self, station: Station, start: float, end: float) -> float:
        if (
            start >= end - EPSILON
            or station.state is not StationState.TESTING
            or station.test_start_time is None
        ):
            return 0.0

        relative_start = max(0.0, start - station.test_start_time)
        relative_end = max(0.0, end - station.test_start_time)

        peak = self.config.peak_station_power
        steady = peak * (self.config.steady_state_power_pct / 100.0)
        ramp_up_end = self.config.startup_ramp_duration
        steady_end = ramp_up_end + self.config.steady_state_duration
        ramp_down_end = steady_end + self.config.shutdown_ramp_duration

        def trapezoid(a: float, b: float, pa: float, pb: float) -> float:
            if b <= a + EPSILON:
                return 0.0
            return (pa + pb) * 0.5 * (b - a)

        energy = 0.0

        seg_start = max(relative_start, 0.0)
        seg_end = min(relative_end, ramp_up_end)
        if seg_end > seg_start + EPSILON and self.config.startup_ramp_duration > EPSILON:
            duration = self.config.startup_ramp_duration
            power_start = peak - (peak - steady) * (seg_start / duration)
            power_end = peak - (peak - steady) * (seg_end / duration)
            energy += trapezoid(seg_start, seg_end, power_start, power_end)

        seg_start = max(relative_start, ramp_up_end)
        seg_end = min(relative_end, steady_end)
        if seg_end > seg_start + EPSILON:
            energy += steady * (seg_end - seg_start)

        seg_start = max(relative_start, steady_end)
        seg_end = min(relative_end, ramp_down_end)
        if seg_end > seg_start + EPSILON and self.config.shutdown_ramp_duration > EPSILON:
            duration = self.config.shutdown_ramp_duration
            power_start = steady + (peak - steady) * ((seg_start - steady_end) / duration)
            power_end = steady + (peak - steady) * ((seg_end - steady_end) / duration)
            energy += trapezoid(seg_start, seg_end, power_start, power_end)

        return energy

    def _checkpoint_power(self) -> None:
        now = self.env.now
        if now <= self.last_power_checkpoint + EPSILON:
            self._update_peak_power()
            return

        for station in self.stations.values():
            station_energy = self._integrate_station_power(
                station,
                self.last_power_checkpoint,
                now,
            )
            self.energy_watt_seconds += station_energy
            self.station_energy_watt_seconds += station_energy

        self.last_power_checkpoint = now
        self._update_peak_power()

    def _update_peak_power(self) -> None:
        station_power = self.current_station_power
        if station_power > self.peak_power + EPSILON:
            self.peak_power = station_power
            self.peak_power_time = self.env.now

        if station_power > self.peak_station_power_value + EPSILON:
            self.peak_station_power_value = station_power


class LineVisualizer(QWidget):
    FONT_BOLD = QFont("Segoe UI", 9, QFont.Weight.Bold)
    FONT_SMALL = QFont("Segoe UI", 8)
    FONT_MONO = QFont("Cascadia Mono", 8)
    FONT_ZONE = QFont("Segoe UI Semibold", 11)
    PEN_DASH = QPen(C.BORDER, 1, Qt.PenStyle.DashLine)
    PEN_TRACK = QPen(C.TRACK, 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    PEN_ZONE1 = QPen(C.ZONE1_BD, 1)
    PEN_ZONE2 = QPen(C.ZONE2_BD, 1)
    PEN_GATE = QPen(C.GATE_FRAME, 1)
    PEN_GATE_EDGE = QPen(C.BORDER, 2)
    PEN_RGV = QPen(C.FG, 2)
    PEN_ST_IDLE = QPen(C.ST_IDLE_BD, 2)
    PEN_ST_TEST = QPen(C.ST_TEST_BD, 2)
    PEN_ST_FIN = QPen(C.ST_FIN_BD, 2)
    PEN_ST_BLOCK = QPen(C.ST_BLOCK_BD, 2)

    def __init__(self, engine: SimulationEngine) -> None:
        super().__init__()
        self.engine = engine
        self.view_scale = 1.0
        self.setMinimumHeight(250)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def _tx(self, pos: float) -> float:
        margin = 70
        base_width = max(120.0, self.width() - 2 * margin)
        usable = base_width * self.view_scale
        offset = (self.width() - usable) / 2.0
        return offset + usable * pos / max(self.engine.PACKING_POSITION, 1.0)

    def adjust_zoom(self, delta: float) -> None:
        self.view_scale = min(2.25, max(0.75, self.view_scale + delta))
        self.update()

    def reset_zoom(self) -> None:
        self.view_scale = 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), C.BG)
        engine = self.engine

        width = self.width()
        height = float(self.height())
        margin = 70
        rail_y = height * 0.69
        station_top = height * 0.21
        station_bottom = height * 0.54
        station_half_width = 26
        zone_top = station_top - height * 0.10
        zone_bottom = rail_y + height * 0.13
        gate_top = station_top - height * 0.05
        gate_bottom = rail_y + height * 0.12
        gate_label_y = min(height - 18, rail_y + height * 0.10)
        terminal_top = rail_y - max(34.0, height * 0.12) - max(14.0, height * 0.03)
        terminal_height = max(34.0, height * 0.12)
        queue_y = max(18.0, height * 0.08)
        rgv_y = min(height - 26.0, rail_y + height * 0.08)

        painter.setPen(self.PEN_TRACK)
        painter.drawLine(margin, rail_y, width - margin, rail_y)

        zone1_left = self._tx(engine.GATE_1_POSITION) + 10
        zone1_right = self._tx(engine.GATE_2_POSITION) - 10
        zone2_left = self._tx(engine.GATE_2_POSITION) + 10
        zone2_right = self._tx(engine.GATE_3_POSITION) - 10

        painter.setPen(self.PEN_ZONE1)
        painter.setBrush(C.ZONE1_BG)
        painter.drawRoundedRect(
            QRectF(
                zone1_left,
                zone_top,
                zone1_right - zone1_left,
                zone_bottom - zone_top,
            ),
            8,
            8,
        )
        painter.setPen(self.PEN_ZONE2)
        painter.setBrush(C.ZONE2_BG)
        painter.drawRoundedRect(
            QRectF(
                zone2_left,
                zone_top,
                zone2_right - zone2_left,
                zone_bottom - zone_top,
            ),
            8,
            8,
        )
        painter.setPen(C.BLUE)
        painter.setFont(self.FONT_ZONE)
        painter.drawText(
            QRectF(zone1_left, zone_top + 2, zone1_right - zone1_left, 18),
            Qt.AlignmentFlag.AlignCenter,
            "Zone 1",
        )
        painter.setPen(C.GREEN)
        painter.drawText(
            QRectF(zone2_left, zone_top + 2, zone2_right - zone2_left, 18),
            Qt.AlignmentFlag.AlignCenter,
            "Zone 2",
        )

        for sid, station in engine.stations.items():
            x = self._tx(engine.station_track_position(sid))
            progress = engine.station_progress(sid)

            if station.state is StationState.TESTING:
                fill = C.ST_FIN if progress >= FINISHING_THRESHOLD else C.ST_TEST
                pen = self.PEN_ST_FIN if progress >= FINISHING_THRESHOLD else self.PEN_ST_TEST
                progress_color = (
                    C.PB_LATE if progress >= FINISHING_THRESHOLD else C.PB_FILL
                )
                state_text = "Testing"
                power_text = f"{engine.station_power(sid):.0f} kW"
            elif station.state is StationState.WAITING_UNLOAD:
                fill, pen, progress_color = C.ST_BLOCK, self.PEN_ST_BLOCK, C.RED
                progress = 1.0
                state_text = "Blocked"
                power_text = "awaiting RGV"
            else:
                fill, pen, progress_color = C.ST_IDLE, self.PEN_ST_IDLE, C.PB_FILL
                progress = 0.0
                state_text = "Idle"
                power_text = ""

            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawRoundedRect(
                QRectF(
                    x - station_half_width,
                    station_top,
                    station_half_width * 2,
                    station_bottom - station_top,
                ),
                6,
                6,
            )

            bar_left = x - station_half_width + 5
            bar_full_width = station_half_width * 2 - 10
            bar_y = station_bottom - 16
            bar_height = 8
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(C.PB_BG)
            painter.drawRect(QRectF(bar_left, bar_y, bar_full_width, bar_height))
            painter.setBrush(progress_color)
            painter.drawRect(
                QRectF(bar_left, bar_y, bar_full_width * max(0.0, progress), bar_height)
            )

            painter.setPen(self.PEN_DASH)
            painter.drawLine(int(x), station_bottom, int(x), rail_y - 10)

            painter.setPen(C.FG)
            painter.setFont(self.FONT_BOLD)
            painter.drawText(
                QRectF(x - station_half_width, station_top + 4, station_half_width * 2, 18),
                Qt.AlignmentFlag.AlignCenter,
                f"S{sid}",
            )
            painter.setPen(C.FG_DIM)
            painter.setFont(self.FONT_SMALL)
            painter.drawText(
                QRectF(x - station_half_width, station_top + 24, station_half_width * 2, 16),
                Qt.AlignmentFlag.AlignCenter,
                state_text,
            )
            painter.setFont(self.FONT_MONO)
            painter.drawText(
                QRectF(
                    x - station_half_width - 8,
                    station_top + 42,
                    station_half_width * 2 + 16,
                    16,
                ),
                Qt.AlignmentFlag.AlignCenter,
                power_text,
            )

        for gate_position, gate_name in engine.gate_boundaries():
            gate_x = self._tx(gate_position)
            opening_height = max(34.0, min(42.0, height * 0.16))
            opening_width = 32.0
            frame_rect = QRectF(
                gate_x - opening_width / 2,
                rail_y - opening_height / 2 - 2.0,
                opening_width,
                opening_height,
            )
            wall_width = 16.0
            wall_height = frame_rect.height() + 4.0
            slide_direction = -1.0
            slide_distance = frame_rect.height() / 2 + wall_height / 2 + 6.0

            painter.setPen(self.PEN_GATE)
            painter.setBrush(QColor(C.SURFACE.red(), C.SURFACE.green(), C.SURFACE.blue(), 220))
            painter.drawRoundedRect(frame_rect, 5, 5)
            guide_pen = QPen(C.BORDER_LT, 2)
            painter.setPen(guide_pen)
            painter.drawLine(
                int(frame_rect.center().x()),
                int(frame_rect.top() - 10),
                int(frame_rect.center().x()),
                int(frame_rect.top()),
            )
            painter.drawLine(
                int(frame_rect.center().x()),
                int(frame_rect.bottom()),
                int(frame_rect.center().x()),
                int(frame_rect.bottom() + 10),
            )

            openness = engine.gate_open_fraction(gate_name)
            wall_center_y = frame_rect.center().y() + slide_direction * openness * slide_distance
            wall_rect = QRectF(
                gate_x - wall_width / 2,
                wall_center_y - wall_height / 2,
                wall_width,
                wall_height,
            )

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(C.GATE_DOOR)
            painter.drawRoundedRect(wall_rect, 4, 4)
            painter.setPen(self.PEN_GATE_EDGE)
            painter.drawRoundedRect(wall_rect, 4, 4)

            painter.setPen(C.FG_DIM)
            painter.setFont(self.FONT_SMALL)
            painter.drawText(
                QRectF(gate_x - 30, rail_y + 28.0, 60, 16),
                Qt.AlignmentFlag.AlignCenter,
                gate_name,
            )

        load_x = self._tx(engine.LOAD_POSITION)
        pack_x = self._tx(engine.PACKING_POSITION)
        for box_x, label, fill, border in [
            (load_x, "LOAD", C.LOAD_FILL, C.LOAD_BD),
            (pack_x, "PACK", C.PACK_FILL, C.PACK_BD),
        ]:
            painter.setPen(QPen(border, 2))
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(box_x - 28, terminal_top, 56, terminal_height), 5, 5)
            painter.setPen(border)
            painter.setFont(self.FONT_BOLD)
            painter.drawText(
                QRectF(box_x - 28, terminal_top, 56, terminal_height),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

        painter.setPen(C.YELLOW)
        painter.setFont(self.FONT_BOLD)
        painter.drawText(
            12,
            int(queue_y),
            f"Queue: {len(engine.waiting_servers)}  (peak {engine.peak_queue})",
        )

        rgv_x = self._tx(engine.rgv_position)
        painter.setPen(self.PEN_RGV)
        painter.setBrush(C.RGV[engine.rgv_payload])
        painter.drawRoundedRect(QRectF(rgv_x - 32, rgv_y - 16, 64, 28), 7, 7)
        painter.setPen(C.BG)
        painter.setFont(self.FONT_BOLD)
        painter.drawText(
            QRectF(rgv_x - 32, rgv_y - 16, 64, 28),
            Qt.AlignmentFlag.AlignCenter,
            "RGV",
        )

        payload_text = {
            PayloadKind.EMPTY: "",
            PayloadKind.INCOMING: " | server in",
            PayloadKind.OUTGOING: " | packed out",
        }[engine.rgv_payload]
        motion = "Moving" if engine.rgv_is_moving else "Stopped"
        painter.setPen(C.FG_DIM)
        painter.setFont(self.FONT_SMALL)
        painter.drawText(
            QRectF(rgv_x - 70, rgv_y + 16, 140, 16),
            Qt.AlignmentFlag.AlignCenter,
            f"{motion}{payload_text}",
        )
        painter.end()


class GraphVisualizer(QWidget):
    FONT_LABEL = QFont("Segoe UI", 9)
    FONT_MONO = QFont("Cascadia Mono", 8)
    FONT_AXIS = QFont("Segoe UI", 9)
    DEFAULT_WINDOW_SECONDS = 60.0
    MIN_WINDOW_SECONDS = 15.0
    MAX_WINDOW_SECONDS = 3600.0

    def __init__(self, engine: SimulationEngine) -> None:
        super().__init__()
        self.engine = engine
        self.setMinimumHeight(200)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.view_window_seconds = self.DEFAULT_WINDOW_SECONDS
        self.view_end_time = self.DEFAULT_WINDOW_SECONDS
        self.follow_latest = True
        self._drag_last_x: float | None = None
        self.setMouseTracking(True)
        self.setToolTip("Mouse wheel: zoom. Drag: pan. Double-click: reset view.")

    def _plot_rect(self) -> QRectF:
        return QRectF(56.0, 18.0, max(1.0, self.width() - 74.0), max(1.0, self.height() - 50.0))

    def _current_view(self, current_time: float) -> tuple[float, float]:
        if self.follow_latest:
            view_end = max(self.view_window_seconds, current_time)
            self.view_end_time = view_end
        else:
            view_end = max(self.view_window_seconds, self.view_end_time)
        view_start = max(0.0, view_end - self.view_window_seconds)
        return view_start, view_end

    def _sample_history(self) -> list[tuple[float, float]]:
        history = list(self.engine.power_history)
        if not history:
            history = [(0.0, self.engine.current_station_power)]

        current_time = self.engine.env.now
        current_power = self.engine.current_station_power
        if history[-1][0] < current_time - EPSILON or abs(history[-1][1] - current_power) > EPSILON:
            history.append((current_time, current_power))
        return history

    def wheelEvent(self, event) -> None:
        plot_rect = self._plot_rect()
        pos = event.position()
        if not plot_rect.contains(pos):
            super().wheelEvent(event)
            return

        current_time = self.engine.env.now
        view_start, view_end = self._current_view(current_time)
        span = max(self.view_window_seconds, EPSILON)
        ratio = (pos.x() - plot_rect.left()) / max(plot_rect.width(), 1.0)
        ratio = max(0.0, min(1.0, ratio))
        anchor_time = view_start + ratio * span

        steps = event.angleDelta().y() / 120.0
        if abs(steps) <= EPSILON:
            return
        zoom_factor = 0.85 ** steps
        new_window = min(
            self.MAX_WINDOW_SECONDS,
            max(self.MIN_WINDOW_SECONDS, self.view_window_seconds * zoom_factor),
        )

        new_start = anchor_time - ratio * new_window
        new_end = new_start + new_window
        if new_start < 0.0:
            new_start = 0.0
            new_end = new_window

        self.view_window_seconds = new_window
        self.view_end_time = new_end
        self.follow_latest = False
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._plot_rect().contains(event.position()):
            self._drag_last_x = event.position().x()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_last_x is None:
            super().mouseMoveEvent(event)
            return

        plot_rect = self._plot_rect()
        dx = event.position().x() - self._drag_last_x
        seconds_per_pixel = self.view_window_seconds / max(plot_rect.width(), 1.0)
        shift_seconds = -dx * seconds_per_pixel
        next_end = max(self.view_window_seconds, self.view_end_time + shift_seconds)
        if next_end - self.view_window_seconds < 0.0:
            next_end = self.view_window_seconds

        self.view_end_time = next_end
        self.follow_latest = False
        self._drag_last_x = event.position().x()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_last_x = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.view_window_seconds = self.DEFAULT_WINDOW_SECONDS
            self.view_end_time = self.DEFAULT_WINDOW_SECONDS
            self.follow_latest = True
            self._drag_last_x = None
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        canvas_path = QPainterPath()
        canvas_path.addRoundedRect(rect, 8, 8)

        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor("#080c14"))
        gradient.setColorAt(1.0, QColor("#0c1420"))
        painter.fillPath(canvas_path, gradient)

        painter.save()
        painter.setClipPath(canvas_path)
        painter.setPen(QColor(255, 255, 255, 8))
        for x in range(20, int(rect.width()), 30):
            for y in range(20, int(rect.height()), 30):
                painter.drawPoint(x, y)
        painter.restore()

        history = self._sample_history()
        current_time = self.engine.env.now
        view_start, view_end = self._current_view(current_time)
        plot_rect = self._plot_rect()
        left, top, right, bottom = (
            plot_rect.left(),
            plot_rect.top(),
            plot_rect.right(),
            plot_rect.bottom(),
        )
        span_t = max(view_end - view_start, 1.0)
        span_y = plot_rect.height()

        visible_history = [
            (sample_time, power)
            for sample_time, power in history
            if view_start <= sample_time <= view_end
        ]
        previous_samples = [
            (sample_time, power)
            for sample_time, power in history
            if sample_time < view_start
        ]
        if previous_samples:
            visible_history.insert(0, (view_start, previous_samples[-1][1]))
        if not visible_history:
            latest_power = history[-1][1]
            visible_history = [(view_start, latest_power), (view_end, latest_power)]

        max_power = max(
            max(power for _, power in visible_history),
            self.engine.peak_station_power,
            1.0,
        ) * 1.12

        def sx(sample_time: float) -> float:
            return left + (sample_time - view_start) / span_t * plot_rect.width()

        def sy(power: float) -> float:
            return bottom - (power / max_power) * span_y

        painter.setPen(QPen(QColor(12, 15, 22, 160), 1))
        painter.setBrush(QColor(8, 12, 20, 80))
        painter.drawRoundedRect(plot_rect, 8, 8)

        painter.setPen(QPen(C.BORDER_LT, 1))
        painter.drawLine(left, top, left, bottom)
        painter.drawLine(left, bottom, right, bottom)

        painter.setFont(self.FONT_MONO)
        dash_pen = QPen(C.GRAPH_GRID, 1, Qt.PenStyle.DashLine)
        for fraction in (0.25, 0.5, 0.75, 1.0):
            y = sy(max_power * fraction)
            painter.setPen(dash_pen)
            painter.drawLine(int(left), int(y), int(right), int(y))
            painter.setPen(C.FG_MUTED)
            painter.drawText(
                QRectF(0, y - 10, left - 6, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{max_power * fraction:,.0f}",
            )

        painter.save()
        painter.setClipRect(plot_rect.adjusted(0, 0, 0, 1))
        if len(visible_history) >= 2:
            poly = QPolygonF()
            poly.append(QPointF(left, bottom))
            for sample_time, power in visible_history:
                poly.append(QPointF(sx(sample_time), sy(power)))
            poly.append(QPointF(sx(visible_history[-1][0]), bottom))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(C.GRAPH_FILL)
            painter.drawPolygon(poly)

            path = QPainterPath()
            path.moveTo(sx(visible_history[0][0]), sy(visible_history[0][1]))
            for sample_time, power in visible_history[1:]:
                path.lineTo(sx(sample_time), sy(power))
            painter.setPen(QPen(C.GRAPH_LINE, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        latest_time, latest_power = visible_history[-1]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(C.GRAPH_LINE)
        painter.drawEllipse(QPointF(sx(latest_time), sy(latest_power)), 3.0, 3.0)
        painter.restore()

        peak = self.engine.peak_station_power
        if peak > 0:
            peak_y = sy(peak)
            painter.setPen(QPen(C.GRAPH_PEAK, 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(left), int(peak_y), int(right), int(peak_y))
            painter.setFont(self.FONT_LABEL)
            painter.setPen(C.GRAPH_PEAK)
            painter.drawText(
                QRectF(right - 140, peak_y - 18, 140, 16),
                Qt.AlignmentFlag.AlignRight,
                f"Peak {peak:,.0f} kW",
            )

        average_power = self.engine.average_station_power
        if average_power > 0:
            average_y = sy(average_power)
            painter.setPen(QPen(C.GRAPH_AVG, 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(left), int(average_y), int(right), int(average_y))
            painter.setPen(C.GRAPH_AVG)
            painter.drawText(
                QRectF(right - 140, average_y + 2, 140, 16),
                Qt.AlignmentFlag.AlignRight,
                f"Avg {average_power:,.0f} kW",
            )

        painter.setPen(C.FG_MUTED)
        painter.setFont(self.FONT_MONO)
        painter.drawText(int(left), int(bottom + 16), _fmt_time(view_start))
        painter.drawText(
            QRectF(right - 80, bottom + 4, 80, 16),
            Qt.AlignmentFlag.AlignRight,
            _fmt_time(view_end),
        )

        painter.setPen(C.FG_DIM)
        painter.setFont(self.FONT_AXIS)
        painter.drawText(int(left + 4), int(top + 12), "kW")
        painter.setFont(self.FONT_LABEL)
        painter.setPen(C.FG_MUTED)
        painter.drawText(
            QRectF(left, top - 2, plot_rect.width(), 14),
            Qt.AlignmentFlag.AlignRight,
            "Wheel zoom  Drag pan  Double-click reset",
        )
        painter.setPen(QPen(C.BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(canvas_path)
        painter.end()


def _fmt_time(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


TIME_SCALES = {"sec": 1.0, "min": 60.0, "hr": 3600.0}


class SimulatorApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Simulation Control Center")
        self.resize(2250, 1020)
        self.setMinimumSize(1750, 800)
        self._apply_stylesheet()

        self.engine = SimulationEngine(SimulationConfig())
        self.running = False
        self.speed = 10.0
        self.last_wall = time.perf_counter()
        self._needs_refresh = True

        self._build_ui()
        self._sync_control_states()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(UI_TICK_MS)

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget#central {{
                background: {C.BG.name()};
            }}
            QWidget {{
                color: {C.FG.name()};
                font-family: 'Segoe UI', 'SF Pro Display', system-ui;
                font-size: 13px;
            }}
            QFrame#card {{
                background: {C.CARD.name()};
                border: 1px solid {C.BORDER.name()};
                border-radius: 12px;
            }}
            QFrame#inputGroup {{
                background: {C.GROUP_BG.name()};
                border: none;
                border-radius: 8px;
            }}
            QLabel {{
                background: transparent;
            }}
            QLabel#secHead {{
                font-size: 11px;
                font-weight: 700;
                color: {C.FG_DIM.name()};
                letter-spacing: 1.5px;
            }}
            QLabel#subHead {{
                font-size: 11px;
                font-weight: 600;
                color: {C.FG_DIM.name()};
                letter-spacing: 0.5px;
            }}
            QLabel#inputLbl {{
                color: {C.FG_SEC.name()};
                font-size: 12px;
            }}
            QFrame#mc {{
                background: {C.RAISED.name()};
                border-left: 3px solid transparent;
                border-radius: 8px;
            }}
            QFrame#mcBlue {{
                background: {C.RAISED.name()};
                border-left: 3px solid {C.ACCENT.name()};
                border-radius: 8px;
            }}
            QFrame#mcGreen {{
                background: {C.RAISED.name()};
                border-left: 3px solid {C.GREEN.name()};
                border-radius: 8px;
            }}
            QFrame#mcRed {{
                background: {C.RAISED.name()};
                border-left: 3px solid {C.RED.name()};
                border-radius: 8px;
            }}
            QFrame#mcAmber {{
                background: {C.RAISED.name()};
                border-left: 3px solid {C.AMBER.name()};
                border-radius: 8px;
            }}
            QFrame#mcPurple {{
                background: {C.RAISED.name()};
                border-left: 3px solid {C.PURPLE.name()};
                border-radius: 8px;
            }}
            QFrame#mcCyan {{
                background: {C.RAISED.name()};
                border-left: 3px solid {C.CYAN.name()};
                border-radius: 8px;
            }}
            QLabel#mLbl {{
                font-size: 10px;
                font-weight: 600;
                color: {C.FG_DIM.name()};
                letter-spacing: 0.5px;
            }}
            QLabel#mVal {{
                font-size: 20px;
                font-weight: 700;
                color: {C.FG.name()};
            }}
            QLabel#mValB {{
                font-size: 20px;
                font-weight: 700;
                color: {C.ACCENT.name()};
            }}
            QLabel#mValR {{
                font-size: 20px;
                font-weight: 700;
                color: {C.RED.name()};
            }}
            QLabel#mValG {{
                font-size: 20px;
                font-weight: 700;
                color: {C.GREEN.name()};
            }}
            QLabel#mValA {{
                font-size: 20px;
                font-weight: 700;
                color: {C.AMBER.name()};
            }}
            QDoubleSpinBox, QComboBox {{
                background: {C.INPUT_BG.name()};
                border: 1px solid {C.BORDER.name()};
                padding: 4px 8px;
                border-radius: 6px;
                min-height: 26px;
                color: {C.FG.name()};
                selection-background-color: {C.ACCENT.name()};
            }}
            QDoubleSpinBox:hover, QComboBox:hover {{
                border-color: {C.BORDER_LT.name()};
            }}
            QDoubleSpinBox:focus, QComboBox:focus {{
                border-color: {C.ACCENT.name()};
            }}
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
                width: 0;
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                background: {C.CARD.name()};
                border: 1px solid {C.BORDER.name()};
                selection-background-color: {C.HOVER.name()};
                padding: 4px;
                outline: none;
            }}
            QPushButton {{
                background: {C.RAISED.name()};
                border: 1px solid {C.BORDER.name()};
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {C.HOVER.name()};
                border-color: {C.BORDER_LT.name()};
            }}
            QPushButton:pressed {{
                background: {C.BG.name()};
            }}
            QPushButton#btnPrimary {{
                background: {C.ACCENT.name()};
                border: none;
                color: #ffffff;
            }}
            QPushButton#btnPrimary:hover {{
                background: {C.ACCENT_DK.name()};
            }}
            QPushButton#btnSuccess {{
                background: {C.GREEN_DK.name()};
                border: none;
                color: #ffffff;
            }}
            QPushButton#btnSuccess:hover {{
                background: {C.GREEN.name()};
            }}
            QPushButton#btnDanger {{
                background: transparent;
                border: 1px solid {C.RED_DK.name()};
                color: {C.RED.name()};
            }}
            QPushButton#btnDanger:hover {{
                background: {C.RED_DK.name()};
                color: #ffffff;
            }}
            QPushButton#btnSmall {{
                padding: 0;
                min-width: 28px;
                max-width: 28px;
                min-height: 28px;
                max-height: 28px;
                font-size: 14px;
                border-radius: 6px;
            }}
            QCheckBox {{
                color: {C.FG_DIM.name()};
                spacing: 5px;
                font-size: 11px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 4px;
                background: {C.INPUT_BG.name()};
                border: 1px solid {C.BORDER.name()};
            }}
            QCheckBox::indicator:hover {{
                border-color: {C.BORDER_LT.name()};
            }}
            QCheckBox::indicator:checked {{
                background: {C.ACCENT.name()};
                border-color: {C.ACCENT.name()};
            }}
            QCheckBox:checked {{
                color: {C.FG.name()};
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QWidget#scroll {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER.name()};
                border-radius: 3px;
                min-height: 40px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C.FG_DIM.name()};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QFrame#sep {{
                background: {C.BORDER.name()};
                min-height: 1px;
                max-height: 1px;
            }}
            QFrame#statusBox {{
                background: {C.SURFACE.name()};
                border: 1px solid {C.BORDER.name()};
                border-radius: 8px;
            }}
            QLabel#legend {{
                font-size: 11px;
                font-weight: 600;
                margin-left: 10px;
            }}
            """
        )

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QGridLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)
        root.setRowStretch(0, 3)
        root.setRowStretch(1, 2)
        root.setColumnStretch(0, 0)
        root.setColumnStretch(1, 1)
        root.setColumnStretch(2, 0)

        root.addWidget(self._build_inputs_panel(), 0, 0, 2, 1)
        root.addWidget(self._build_line_panel(), 0, 1)
        root.addWidget(self._build_graph_panel(), 1, 1)
        root.addWidget(self._build_metrics_panel(), 0, 2, 2, 1)

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        return frame

    def _group(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("inputGroup")
        return frame

    def _sep(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("sep")
        frame.setFrameShape(QFrame.Shape.HLine)
        return frame

    def _section_label(self, text: str, object_name: str = "secHead") -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        return label

    @staticmethod
    def _grid4() -> QGridLayout:
        layout = QGridLayout()
        layout.setColumnStretch(0, 1)
        for column in (1, 2, 3):
            layout.setColumnStretch(column, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        return layout

    def _button(
        self,
        text: str,
        object_name: str | None = None,
        min_height: int = 36,
    ) -> QPushButton:
        button = QPushButton(text)
        if object_name:
            button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(min_height)
        return button

    def _add_time_row(
        self,
        layout: QGridLayout,
        row: int,
        label: str,
        value: float,
        unit: str,
        spin_name: str,
        combo_name: str,
        lock_name: str,
        tip: str = "",
    ) -> None:
        label_widget = QLabel(label)
        label_widget.setObjectName("inputLbl")
        if tip:
            label_widget.setToolTip(tip)

        spin = QDoubleSpinBox()
        spin.setRange(0, 100_000)
        spin.setDecimals(2)
        spin.setValue(value)
        spin.setFixedWidth(78)
        if tip:
            spin.setToolTip(tip)

        combo = QComboBox()
        combo.addItems(["sec", "min", "hr"])
        combo.setCurrentText(unit)
        combo.setFixedWidth(58)
        if tip:
            combo.setToolTip(tip)

        lock = QCheckBox("Lock")
        lock.setCursor(Qt.CursorShape.PointingHandCursor)
        lock.setToolTip(f"Lock {label} so the solver cannot change it")
        lock.toggled.connect(
            lambda checked, s=spin, c=combo: (s.setEnabled(not checked), c.setEnabled(not checked))
        )

        layout.addWidget(label_widget, row, 0)
        layout.addWidget(spin, row, 1)
        layout.addWidget(combo, row, 2)
        layout.addWidget(lock, row, 3)

        setattr(self, spin_name, spin)
        setattr(self, combo_name, combo)
        setattr(self, lock_name, lock)

    def _add_scalar_row(
        self,
        layout: QGridLayout,
        row: int,
        label: str,
        value: float,
        attr_name: str,
        step: float = 1.0,
        lo: float = 0.0,
        hi: float = 100_000.0,
        tip: str = "",
    ) -> None:
        label_widget = QLabel(label)
        label_widget.setObjectName("inputLbl")
        if tip:
            label_widget.setToolTip(tip)

        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setDecimals(2)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setFixedWidth(78)
        if tip:
            spin.setToolTip(tip)

        layout.addWidget(label_widget, row, 0)
        layout.addWidget(spin, row, 1, 1, 3)
        setattr(self, attr_name, spin)

    def _add_combo_row(
        self,
        layout: QGridLayout,
        row: int,
        label: str,
        items: list[tuple[str, float]],
        current_index: int,
        attr_name: str,
        tip: str = "",
    ) -> None:
        label_widget = QLabel(label)
        label_widget.setObjectName("inputLbl")
        if tip:
            label_widget.setToolTip(tip)

        combo = QComboBox()
        for text, value in items:
            combo.addItem(text, value)
        combo.setCurrentIndex(current_index)
        combo.setFixedWidth(78)
        if tip:
            combo.setToolTip(tip)

        layout.addWidget(label_widget, row, 0)
        layout.addWidget(combo, row, 1, 1, 3)
        setattr(self, attr_name, combo)

    def _set_solver_status(self, message: str, color: QColor | None = None) -> None:
        display_message = message
        if len(message) > 110:
            display_message = message.split(". ", 1)[0].strip()
            if display_message and not display_message.endswith("."):
                display_message += "."
        self.lbl_solver_status.setText(f"Solver Status: <b>{escape(display_message)}</b>")
        self.lbl_solver_status.setToolTip(message)
        applied_color = color or C.FG_SEC
        self.lbl_solver_status.setStyleSheet(
            f"color: {applied_color.name()}; font-size: 12px;"
        )
        self.status_dot.set_color(color or C.FG_DIM)

    def _invalidate_solver_status(self) -> None:
        self._set_solver_status("Inputs changed. Awaiting manual solve.", C.AMBER)

    def _connect_solver_input_tracking(self) -> None:
        tracked_spins = [
            self.sp_target_tput,
            self.sp_arrival,
            self.sp_startup,
            self.sp_steady,
            self.sp_shutdown,
            self.sp_move,
            self.sp_xfer,
            self.sp_gate,
            self.sp_peak_kw,
            self.sp_ss_pct,
        ]
        tracked_combos = [
            self.cb_arrival_u,
            self.cb_startup_u,
            self.cb_steady_u,
            self.cb_shutdown_u,
            self.cb_move_u,
            self.cb_xfer_u,
            self.cb_gate_u,
        ]
        tracked_locks = [
            self.lk_arrival,
            self.lk_startup,
            self.lk_steady,
            self.lk_shutdown,
            self.lk_move,
            self.lk_xfer,
            self.lk_gate,
        ]
        for spin in tracked_spins:
            spin.valueChanged.connect(lambda _value: self._invalidate_solver_status())
        for combo in tracked_combos:
            combo.currentIndexChanged.connect(lambda _index: self._invalidate_solver_status())
        for lock in tracked_locks:
            lock.toggled.connect(lambda _checked: self._invalidate_solver_status())

    def _build_inputs_panel(self) -> QFrame:
        card = self._card()
        card.setFixedWidth(385)
        shell_layout = QVBoxLayout(card)
        shell_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("scroll")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("SCENARIO INPUTS"))

        general = self._group()
        general_layout = QVBoxLayout(general)
        general_layout.setContentsMargins(14, 12, 14, 14)
        general_layout.setSpacing(8)
        general_layout.addWidget(self._section_label("General", "subHead"))
        general_grid = self._grid4()
        self._add_scalar_row(
            general_grid,
            0,
            "Target Throughput (/hr)",
            10.0,
            "sp_target_tput",
            step=0.5,
            lo=0.1,
            hi=500.0,
            tip="Target number of servers processed per hour",
        )
        speed_items = [
            (f"{speed}\u00d7", float(speed))
            for speed in (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000)
        ]
        self._add_combo_row(
            general_grid,
            1,
            "Simulation Speed",
            speed_items,
            2,
            "speed_combo",
            tip="Clock multiplier for the simulation",
        )
        general_layout.addLayout(general_grid)
        layout.addWidget(general)

        timings = self._group()
        timings_layout = QVBoxLayout(timings)
        timings_layout.setContentsMargins(14, 12, 14, 14)
        timings_layout.setSpacing(8)
        timings_layout.addWidget(self._section_label("Process Timings", "subHead"))
        timing_grid = self._grid4()
        timing_rows = [
            ("Arrival Interval", 45.0, "sec", "sp_arrival", "cb_arrival_u", "lk_arrival", "Time between server arrivals"),
            ("Startup Ramp", 5.0, "min", "sp_startup", "cb_startup_u", "lk_startup", "Warm-up before steady state"),
            ("Steady Duration", 2.0, "hr", "sp_steady", "cb_steady_u", "lk_steady", "Duration of steady-state operation"),
            ("Shutdown Ramp", 5.0, "min", "sp_shutdown", "cb_shutdown_u", "lk_shutdown", "Cool-down after steady state"),
            ("RGV Move / Station", 12.0, "sec", "sp_move", "cb_move_u", "lk_move", "Travel time between adjacent stations"),
            ("Load / Unload", 6.0, "sec", "sp_xfer", "cb_xfer_u", "lk_xfer", "Time to load or unload one server"),
            ("Gate Cycle", 4.0, "sec", "sp_gate", "cb_gate_u", "lk_gate", "Full gate open to close cycle"),
        ]
        for row_index, row in enumerate(timing_rows):
            self._add_time_row(timing_grid, row_index, *row)
        timings_layout.addLayout(timing_grid)
        layout.addWidget(timings)

        power = self._group()
        power_layout = QVBoxLayout(power)
        power_layout.setContentsMargins(14, 12, 14, 14)
        power_layout.setSpacing(8)
        power_layout.addWidget(self._section_label("Power Constraints", "subHead"))
        power_grid = self._grid4()
        self._add_scalar_row(
            power_grid,
            0,
            "Peak Power (kW)",
            1000.0,
            "sp_peak_kw",
            step=25.0,
            lo=0.0,
            hi=5000.0,
            tip="Maximum allowable power draw",
        )
        self._add_scalar_row(
            power_grid,
            1,
            "Steady (% of peak)",
            10.0,
            "sp_ss_pct",
            step=1.0,
            lo=0.0,
            hi=100.0,
            tip="Steady-state power as a percent of peak draw",
        )
        power_layout.addLayout(power_grid)
        layout.addWidget(power)

        layout.addSpacing(4)
        button_grid = QGridLayout()
        button_grid.setSpacing(8)

        self.btn_start = self._button("\u25b6  Start", "btnSuccess")
        self.btn_start.clicked.connect(self._start)
        button_grid.addWidget(self.btn_start, 0, 0)

        self.btn_pause = self._button("\u23f8  Pause", "btnDanger")
        self.btn_pause.clicked.connect(self._pause)
        button_grid.addWidget(self.btn_pause, 0, 1)

        self.btn_reset = self._button("\u21ba  Reset")
        self.btn_reset.clicked.connect(self._reset)
        button_grid.addWidget(self.btn_reset, 1, 0)

        self.btn_solve = self._button("\u26a1 Solve Target", "btnPrimary")
        self.btn_solve.clicked.connect(self._solve_for_target)
        button_grid.addWidget(self.btn_solve, 1, 1)
        layout.addLayout(button_grid)

        layout.addSpacing(4)
        status_box = QFrame()
        status_box.setObjectName("statusBox")
        status_layout = QHBoxLayout(status_box)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(8)
        self.status_dot = StatusDot(C.FG_DIM, 6)
        status_layout.addWidget(self.status_dot)
        self.lbl_solver_status = QLabel("Solver Status: <b>Idle</b>")
        self.lbl_solver_status.setWordWrap(True)
        self.lbl_solver_status.setStyleSheet(
            f"color: {C.FG_SEC.name()}; font-size: 12px;"
        )
        status_layout.addWidget(self.lbl_solver_status)
        status_layout.addStretch()
        layout.addWidget(status_box)

        note = QLabel(
            "<b>Path:</b> Load \u2192 Gate 1 \u2192 Zone 1 \u2192 Gate 2 \u2192 "
            "Zone 2 \u2192 Gate 3 \u2192 Packing<br><br>"
            "Delivery prioritised over packing when idle stations exist."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {C.FG_MUTED.name()}; font-size: 11px; line-height: 1.5;"
        )
        layout.addWidget(note)
        layout.addStretch()

        scroll.setWidget(container)
        shell_layout.addWidget(scroll)

        self._connect_solver_input_tracking()
        return card

    def _build_line_panel(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(self._section_label("LINE LAYOUT"))
        header.addStretch()

        self.line_vis = LineVisualizer(self.engine)
        zoom_out = self._button("\u2212", "btnSmall", 28)
        zoom_out.setToolTip("Zoom out")
        zoom_out.clicked.connect(lambda: self.line_vis.adjust_zoom(-0.25))
        zoom_in = self._button("+", "btnSmall", 28)
        zoom_in.setToolTip("Zoom in")
        zoom_in.clicked.connect(lambda: self.line_vis.adjust_zoom(0.25))
        zoom_reset = self._button("\u229e", "btnSmall", 28)
        zoom_reset.setToolTip("Reset zoom")
        zoom_reset.clicked.connect(self.line_vis.reset_zoom)
        header.addWidget(zoom_out)
        header.addWidget(zoom_in)
        header.addWidget(zoom_reset)

        layout.addLayout(header)
        layout.addWidget(self.line_vis)
        return card

    def _build_graph_panel(self) -> QFrame:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(self._section_label("POWER DEMAND"))
        header.addStretch()
        for color, text in ((C.ACCENT, "Total"), (C.RED, "Peak"), (C.GREEN, "Avg")):
            legend = QLabel(f"\u25cf {text}")
            legend.setObjectName("legend")
            legend.setStyleSheet(
                f"color: {color.name()}; font-size: 11px; font-weight: 600; margin-left: 10px;"
            )
            header.addWidget(legend)
        layout.addLayout(header)

        self.graph_vis = GraphVisualizer(self.engine)
        layout.addWidget(self.graph_vis)
        return card

    def _build_metrics_panel(self) -> QWidget:
        card = self._card()
        card.setFixedWidth(340)
        shell_layout = QVBoxLayout(card)
        shell_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("scroll")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.metrics = {}
        layout.addWidget(self._section_label("SYSTEM METRICS"))
        layout.addWidget(self._sep())
        layout.addWidget(self._metric_card("Simulation Time", "time", "00:00:00", "mcBlue", "mVal"))
        layout.addWidget(self._metric_card("Active Constraint", "cstr", "None", "mcAmber", "mValA"))

        layout.addSpacing(4)
        layout.addWidget(self._section_label("PERFORMANCE", "subHead"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        items = [
            ("Throughput", "tput", "mcBlue", "mValB"),
            ("Servers Done", "done", "mcGreen", "mValG"),
            ("Test Power", "tot_pwr", "mcPurple", "mVal"),
            ("Peak Test", "peak_pwr", "mcRed", "mValR"),
            ("Avg Test", "avg_pwr", "mc", "mVal"),
            ("Test Demand", "st_pwr", "mc", "mVal"),
            ("Occupied Util.", "occ", "mcCyan", "mVal"),
            ("Testing Util.", "tst", "mcCyan", "mVal"),
            ("Queue Now/Pk", "queue", "mcAmber", "mValA"),
            ("RGV Task", "rgv", "mc", "mVal"),
        ]
        for index, (title, key, frame_id, value_object) in enumerate(items):
            grid.addWidget(
                self._metric_card(title, key, "--", frame_id, value_object),
                index // 2,
                index % 2,
            )
        layout.addLayout(grid)
        layout.addStretch()

        scroll.setWidget(container)
        shell_layout.addWidget(scroll)
        return card

    def _metric_card(
        self,
        title: str,
        key: str,
        initial: str = "--",
        frame_id: str = "mc",
        value_object: str = "mVal",
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName(frame_id)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        title_label = QLabel(title.upper())
        title_label.setObjectName("mLbl")
        value_label = QLabel(initial)
        value_label.setObjectName(value_object)
        value_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        self.metrics[key] = value_label
        return frame

    def _tsec(self, spin: QDoubleSpinBox, combo: QComboBox, lo: float = 0.0) -> float:
        return max(lo, spin.value() * TIME_SCALES[combo.currentText()])

    def _build_cfg(self) -> SimulationConfig:
        return SimulationConfig(
            arrival_interval=self._tsec(self.sp_arrival, self.cb_arrival_u, 1.0),
            startup_ramp_duration=self._tsec(self.sp_startup, self.cb_startup_u),
            steady_state_duration=self._tsec(self.sp_steady, self.cb_steady_u, 1.0),
            shutdown_ramp_duration=self._tsec(self.sp_shutdown, self.cb_shutdown_u),
            move_time_per_station=self._tsec(self.sp_move, self.cb_move_u, 0.1),
            transfer_time=self._tsec(self.sp_xfer, self.cb_xfer_u),
            gate_cycle_time=self._tsec(self.sp_gate, self.cb_gate_u),
            peak_station_power=max(0.0, self.sp_peak_kw.value()),
            steady_state_power_pct=min(100.0, max(0.0, self.sp_ss_pct.value())),
        )

    def _set_time_seconds(self, spin: QDoubleSpinBox, combo: QComboBox, seconds: float) -> None:
        scale = TIME_SCALES[combo.currentText()]
        spin.setValue(seconds / scale)

    @staticmethod
    def _arrival_capacity(cfg: SimulationConfig) -> float:
        if cfg.arrival_interval <= EPSILON:
            return float("inf")
        return 3600.0 / cfg.arrival_interval

    @staticmethod
    def _station_capacity(cfg: SimulationConfig) -> float:
        if cfg.test_duration <= EPSILON:
            return float("inf")
        return cfg.num_stations * 3600.0 / cfg.test_duration

    @staticmethod
    def _estimate_rgv_cycle_time(cfg: SimulationConfig) -> float:
        avg_station_position = sum(
            SimulationEngine.station_track_position(sid)
            for sid in range(1, cfg.num_stations + 1)
        ) / max(cfg.num_stations, 1)
        avg_delivery_units = avg_station_position - SimulationEngine.LOAD_POSITION
        avg_pack_units = SimulationEngine.PACKING_POSITION - avg_station_position
        gate_clearance_units = 6.0 * SimulationEngine.GATE_CLEARANCE
        travel_units = avg_delivery_units + avg_pack_units + gate_clearance_units
        return (
            4.0 * cfg.transfer_time
            + 6.0 * cfg.gate_cycle_time
            + travel_units * cfg.move_time_per_station
        )

    @classmethod
    def _estimate_rgv_capacity(cls, cfg: SimulationConfig) -> float:
        cycle = cls._estimate_rgv_cycle_time(cfg)
        if cycle <= EPSILON:
            return float("inf")
        return 3600.0 / cycle

    def _verify_throughput(self, cfg: SimulationConfig, target_tput: float) -> float:
        engine = SimulationEngine(cfg)
        completions_goal = max(24, cfg.num_stations + 8)
        max_time = max(
            cfg.test_duration * 2.5,
            completions_goal * 3600.0 / max(target_tput, 0.1) * 2.0,
            3600.0,
        )
        step = max(10.0, min(120.0, max(cfg.test_duration / 30.0, 30.0)))
        completion_times: list[float] = []
        last_completed = 0
        while engine.completed_servers < completions_goal and engine.env.now < max_time:
            engine.advance(step)
            if engine.completed_servers > last_completed:
                completion_times.extend([engine.env.now] * (engine.completed_servers - last_completed))
                last_completed = engine.completed_servers

        if len(completion_times) >= 6:
            tail = completion_times[-6:]
            interval = tail[-1] - tail[0]
            if interval > EPSILON:
                return (len(tail) - 1) * 3600.0 / interval
        return engine.throughput_per_hour

    def _time_rows(self) -> dict[str, tuple[QDoubleSpinBox, QComboBox, QCheckBox, float]]:
        return {
            "arrival_interval": (self.sp_arrival, self.cb_arrival_u, self.lk_arrival, 1.0),
            "startup_ramp_duration": (self.sp_startup, self.cb_startup_u, self.lk_startup, 0.0),
            "steady_state_duration": (self.sp_steady, self.cb_steady_u, self.lk_steady, 1.0),
            "shutdown_ramp_duration": (self.sp_shutdown, self.cb_shutdown_u, self.lk_shutdown, 0.0),
            "move_time_per_station": (self.sp_move, self.cb_move_u, self.lk_move, 0.1),
            "transfer_time": (self.sp_xfer, self.cb_xfer_u, self.lk_xfer, 0.0),
            "gate_cycle_time": (self.sp_gate, self.cb_gate_u, self.lk_gate, 0.0),
        }

    def _reduce_duration_fields(
        self,
        cfg: SimulationConfig,
        rows: dict[str, tuple[QDoubleSpinBox, QComboBox, QCheckBox, float]],
        max_test_duration: float,
        changes: list[str],
    ) -> bool:
        if cfg.test_duration <= max_test_duration + EPSILON:
            return True

        reduce_needed = cfg.test_duration - max_test_duration
        for field_name in (
            "steady_state_duration",
            "startup_ramp_duration",
            "shutdown_ramp_duration",
        ):
            spin, combo, lock, min_value = rows[field_name]
            if lock.isChecked():
                continue
            current_value = getattr(cfg, field_name)
            new_value = max(min_value, current_value - reduce_needed)
            reduced = current_value - new_value
            if reduced > EPSILON:
                self._set_time_seconds(spin, combo, new_value)
                setattr(cfg, field_name, new_value)
                reduce_needed -= reduced
                changes.append(f"{field_name.replace('_', ' ')} {new_value:.1f}s")
            if reduce_needed <= EPSILON:
                break
        return reduce_needed <= EPSILON

    def _reduce_transport_fields(
        self,
        cfg: SimulationConfig,
        rows: dict[str, tuple[QDoubleSpinBox, QComboBox, QCheckBox, float]],
        max_cycle_time: float,
        changes: list[str],
    ) -> bool:
        current_cycle = self._estimate_rgv_cycle_time(cfg)
        if current_cycle <= max_cycle_time + EPSILON:
            return True

        move_coeff = 20.0 + 6.0 * SimulationEngine.GATE_CLEARANCE
        transport_fields = (
            ("move_time_per_station", move_coeff),
            ("transfer_time", 4.0),
            ("gate_cycle_time", 6.0),
        )
        for field_name, coeff in transport_fields:
            spin, combo, lock, min_value = rows[field_name]
            if lock.isChecked():
                continue
            current_value = getattr(cfg, field_name)
            needed_reduction = current_cycle - max_cycle_time
            max_reduction = coeff * max(0.0, current_value - min_value)
            if max_reduction <= EPSILON:
                continue
            applied_reduction = min(needed_reduction, max_reduction)
            new_value = current_value - applied_reduction / coeff
            self._set_time_seconds(spin, combo, new_value)
            setattr(cfg, field_name, new_value)
            current_cycle = self._estimate_rgv_cycle_time(cfg)
            changes.append(f"{field_name.replace('_', ' ')} {new_value:.2f}s")
            if current_cycle <= max_cycle_time + EPSILON:
                break
        return current_cycle <= max_cycle_time + EPSILON

    def _refine_solution_with_verification(
        self,
        cfg: SimulationConfig,
        rows: dict[str, tuple[QDoubleSpinBox, QComboBox, QCheckBox, float]],
        target_tput: float,
        changes: list[str],
    ) -> tuple[bool, float]:
        verified_tput = self._verify_throughput(cfg, target_tput)
        for _ in range(4):
            if verified_tput >= target_tput * 0.95:
                return True, verified_tput

            ratio = max(0.1, verified_tput / target_tput)
            previous_cfg = SimulationConfig(**cfg.__dict__)
            desired_test_duration = max(
                rows["steady_state_duration"][3]
                + rows["startup_ramp_duration"][3]
                + rows["shutdown_ramp_duration"][3],
                cfg.test_duration * ratio,
            )
            desired_cycle_time = max(0.0, self._estimate_rgv_cycle_time(cfg) * ratio)
            changed = False

            if self._reduce_duration_fields(cfg, rows, desired_test_duration, changes):
                changed = changed or cfg.test_duration < previous_cfg.test_duration - EPSILON
            if self._reduce_transport_fields(cfg, rows, desired_cycle_time, changes):
                changed = changed or (
                    self._estimate_rgv_cycle_time(cfg)
                    < self._estimate_rgv_cycle_time(previous_cfg) - EPSILON
                )

            if not changed:
                return False, verified_tput

            verified_tput = self._verify_throughput(cfg, target_tput)

        return verified_tput >= target_tput * 0.95, verified_tput

    def _solve_for_target(self) -> None:
        target_tput = max(0.1, self.sp_target_tput.value())
        cfg = self._build_cfg()
        rows = self._time_rows()
        changes: list[str] = []

        required_arrival_interval = 3600.0 / target_tput
        arrival_spin, arrival_combo, arrival_lock, _ = rows["arrival_interval"]
        if arrival_lock.isChecked():
            if cfg.arrival_interval > required_arrival_interval + EPSILON:
                self._set_solver_status(
                    f"Infeasible: arrivals cap at {self._arrival_capacity(cfg):.2f}/hr. "
                    f"Unlock Arrival Interval or lower the target.",
                    C.RED,
                )
                return
        elif abs(cfg.arrival_interval - required_arrival_interval) > EPSILON:
            self._set_time_seconds(arrival_spin, arrival_combo, required_arrival_interval)
            cfg.arrival_interval = required_arrival_interval
            changes.append(f"arrival {required_arrival_interval:.1f}s")

        required_test_duration = cfg.num_stations * 3600.0 / target_tput
        if not self._reduce_duration_fields(cfg, rows, required_test_duration, changes):
            self._set_solver_status(
                f"Infeasible: station capacity is {self._station_capacity(cfg):.2f}/hr "
                f"with the locked test durations.",
                C.RED,
            )
            return

        required_cycle_time = 3600.0 / target_tput
        if not self._reduce_transport_fields(cfg, rows, required_cycle_time, changes):
            self._set_solver_status(
                f"Infeasible: estimated RGV capacity is {self._estimate_rgv_capacity(cfg):.2f}/hr "
                f"with the locked transport timings.",
                C.RED,
            )
            return

        cfg = self._build_cfg()
        arrival_cap = self._arrival_capacity(cfg)
        station_cap = self._station_capacity(cfg)
        rgv_cap = self._estimate_rgv_capacity(cfg)
        analytical_limit = min(arrival_cap, station_cap, rgv_cap)
        solved, verified_tput = self._refine_solution_with_verification(
            cfg,
            rows,
            target_tput,
            changes,
        )
        cfg = self._build_cfg()
        arrival_cap = self._arrival_capacity(cfg)
        station_cap = self._station_capacity(cfg)
        rgv_cap = self._estimate_rgv_capacity(cfg)
        analytical_limit = min(arrival_cap, station_cap, rgv_cap)

        summary = ", ".join(changes) if changes else "No changes needed"
        status_prefix = "Target solved." if solved else "Target estimated; verify manually."
        status_color = C.GREEN if solved else C.YELLOW
        self._set_solver_status(
            f"{status_prefix} "
            f"Target {target_tput:.2f}/hr. "
            f"Analytical limits: arrivals {arrival_cap:.2f}/hr, stations {station_cap:.2f}/hr, "
            f"RGV est {rgv_cap:.2f}/hr, overall {analytical_limit:.2f}/hr. "
            f"Verified tail-rate {verified_tput:.2f}/hr. {summary}."
            ,
            status_color,
        )
        self._reset()

    def _start(self) -> None:
        self._parse_speed()
        if self.running:
            return
        self.running = True
        self.last_wall = time.perf_counter()
        self.engine.log("Simulation started")
        self._sync_control_states()
        self._needs_refresh = True

    def _pause(self) -> None:
        if self.running:
            self.engine.log("Simulation paused")
        self.running = False
        self._sync_control_states()
        self._needs_refresh = True

    def _reset(self) -> None:
        self._pause()
        self.engine = SimulationEngine(self._build_cfg())
        self.line_vis.engine = self.engine
        self.graph_vis.engine = self.engine
        self._refresh()
        self._sync_control_states()
        self._needs_refresh = False

    def _parse_speed(self) -> None:
        speed = self.speed_combo.currentData()
        self.speed = float(speed) if isinstance(speed, (int, float)) else 10.0

    def _sync_control_states(self) -> None:
        self.btn_start.setEnabled(not self.running)
        self.btn_pause.setEnabled(self.running)
        self.btn_reset.setEnabled(True)

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.25, max(0.0, now - self.last_wall))
        self.last_wall = now

        if self.running:
            self._parse_speed()
            try:
                self.engine.advance(dt * self.speed)
            except simpy.core.EmptySchedule:
                self.running = False
                self.engine.log("CRITICAL ERROR: Simulation schedule is empty. Halting.")
                self._set_solver_status(
                    "Simulation crashed: event schedule became empty. Run paused.",
                    C.RED,
                )
                self._sync_control_states()
                self._needs_refresh = True
            except Exception as exc:
                self.running = False
                self.engine.log(
                    f"CRITICAL ERROR: {type(exc).__name__}: {exc}"
                )
                self._set_solver_status(
                    f"Simulation crashed: {type(exc).__name__}: {exc}",
                    C.RED,
                )
                self._sync_control_states()
                self._needs_refresh = True
            self._refresh()
            self._needs_refresh = False
            return

        if self._needs_refresh:
            self._refresh()
            self._needs_refresh = False

    def _refresh(self) -> None:
        self.line_vis.update()
        self.graph_vis.update()

        engine = self.engine
        metrics = self.metrics
        station_power = engine.current_station_power
        metrics["time"].setText(_fmt_time(engine.env.now))
        metrics["queue"].setText(f"{len(engine.waiting_servers)} / {engine.peak_queue}")
        metrics["rgv"].setText(engine.rgv_desc)
        metrics["st_pwr"].setText(f"{station_power:,.1f} kW")
        metrics["tot_pwr"].setText(f"{station_power:,.1f} kW")
        metrics["peak_pwr"].setText(
            f"{engine.peak_power:,.1f} kW @ {_fmt_time(engine.peak_power_time)}"
        )
        metrics["avg_pwr"].setText(f"{engine.average_power:,.1f} kW")
        metrics["done"].setText(str(engine.completed_servers))
        metrics["tput"].setText(f"{engine.throughput_per_hour:.2f} /hr")
        metrics["occ"].setText(f"{engine.occupied_utilization * 100:.1f}%")
        metrics["tst"].setText(f"{engine.testing_utilization * 100:.1f}%")
        metrics["cstr"].setText(engine.constraint_label())
        metrics["cstr"].setToolTip(
            "Testing / Blocked / Idle: "
            f"{engine.active_test_count} / {engine.blocked_station_count} / {engine.idle_station_count}"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SimulatorApp()
    window.show()
    sys.exit(app.exec())
