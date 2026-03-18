from __future__ import annotations

from collections import deque

import simpy

from simulator.config import (
    EPSILON,
    POWER_HISTORY_POINTS,
    POWER_SAMPLE_SIM_SECONDS,
    PayloadKind,
    StationState,
)
from simulator.models import SimulationConfig, Station


def fmt_time(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


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
        self.power_history: deque[tuple[float, float]] = deque(
            maxlen=POWER_HISTORY_POINTS
        )
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
        # Retained for future use. Power reporting excludes all non-test loads.
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
            1
            for station in self.stations.values()
            if station.state is StationState.TESTING
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
            station.get_occupied_time(self.env.now)
            for station in self.stations.values()
        )
        return total / (self.env.now * self.config.num_stations)

    @property
    def testing_utilization(self) -> float:
        if self.env.now <= EPSILON or self.config.num_stations <= 0:
            return 0.0
        total = sum(
            station.get_testing_time(self.env.now)
            for station in self.stations.values()
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
        # Gate timing assumes one continuous constant-speed move for the route.
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
            self.env.process(
                self._schedule_gate_window(gate_name, trigger_time, clear_time)
            )

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

    def _set_gate_target(self, name: str, target: float) -> None:
        self.gate_start_states[name] = self.gate_open_fraction(name)
        self.gate_targets[name] = target
        self.gate_start_times[name] = self.env.now

    def _pick_delivery_station(self) -> int | None:
        idle_stations = [
            station
            for station in self.stations.values()
            if station.state is StationState.IDLE
        ]
        if not idle_stations:
            return None
        return min(
            idle_stations,
            key=lambda station: abs(
                self.rgv_position_val
                - self.station_track_position(station.station_id)
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
            power_start = steady + (peak - steady) * (
                (seg_start - steady_end) / duration
            )
            power_end = steady + (peak - steady) * (
                (seg_end - steady_end) / duration
            )
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
