from __future__ import annotations

from dataclasses import dataclass

from simulator.config import StationState


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
