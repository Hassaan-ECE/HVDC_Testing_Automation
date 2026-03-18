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

    def __post_init__(self) -> None:
        if self.arrival_interval <= 0:
            raise ValueError(f"arrival_interval must be > 0, got {self.arrival_interval}")
        if self.num_stations < 1:
            raise ValueError(f"num_stations must be >= 1, got {self.num_stations}")
        if self.startup_ramp_duration < 0:
            raise ValueError(f"startup_ramp_duration must be >= 0, got {self.startup_ramp_duration}")
        if self.steady_state_duration < 0:
            raise ValueError(f"steady_state_duration must be >= 0, got {self.steady_state_duration}")
        if self.shutdown_ramp_duration < 0:
            raise ValueError(f"shutdown_ramp_duration must be >= 0, got {self.shutdown_ramp_duration}")
        if self.move_time_per_station <= 0:
            raise ValueError(f"move_time_per_station must be > 0, got {self.move_time_per_station}")
        if self.peak_station_power < 0:
            raise ValueError(f"peak_station_power must be >= 0, got {self.peak_station_power}")
        if not (0.0 <= self.steady_state_power_pct <= 100.0):
            raise ValueError(f"steady_state_power_pct must be in [0, 100], got {self.steady_state_power_pct}")

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
