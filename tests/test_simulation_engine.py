import unittest

from server_line_simulator import SimulationConfig, SimulationEngine, StationState


class SimulationEngineTests(unittest.TestCase):
    def test_first_server_reaches_station_and_starts_testing(self) -> None:
        config = SimulationConfig(
            num_stations=2,
            arrival_interval=30.0,
            startup_ramp_duration=5.0,
            steady_state_duration=20.0,
            shutdown_ramp_duration=5.0,
            move_time_per_station=1.0,
            transfer_time=1.0,
            gate_cycle_time=0.0,
            peak_station_power=1000.0,
            steady_state_power_pct=90.0,
            rgv_moving_power=500.0,
            rgv_idle_power=100.0,
        )
        engine = SimulationEngine(config)

        engine.advance(4.0)

        self.assertIs(engine.stations[1].state, StationState.TESTING)
        self.assertEqual(engine.stations[1].server_id, 1)
        self.assertEqual(engine.active_test_count, 1)
        self.assertEqual(len(engine.waiting_servers), 0)
        self.assertEqual(engine.current_station_power, 1000.0)
        self.assertEqual(engine.current_power(), 1000.0)

    def test_server_stays_queued_until_pickup_finishes(self) -> None:
        config = SimulationConfig(
            num_stations=1,
            arrival_interval=30.0,
            startup_ramp_duration=5.0,
            steady_state_duration=20.0,
            shutdown_ramp_duration=5.0,
            move_time_per_station=1.0,
            transfer_time=2.0,
            gate_cycle_time=0.0,
        )
        engine = SimulationEngine(config)

        engine.advance(1.5)
        self.assertEqual(len(engine.waiting_servers), 1)

        engine.advance(0.5)
        self.assertEqual(len(engine.waiting_servers), 0)

    def test_station_blocks_until_rgv_unloads_completed_server(self) -> None:
        config = SimulationConfig(
            num_stations=1,
            arrival_interval=100.0,
            startup_ramp_duration=0.0,
            steady_state_duration=10.0,
            shutdown_ramp_duration=0.0,
            move_time_per_station=0.5,
            transfer_time=1.0,
            gate_cycle_time=0.0,
            peak_station_power=1000.0,
            steady_state_power_pct=90.0,
            rgv_moving_power=500.0,
            rgv_idle_power=100.0,
        )
        engine = SimulationEngine(config)

        engine.advance(13.0)
        self.assertIs(engine.stations[1].state, StationState.WAITING_UNLOAD)
        self.assertEqual(engine.active_test_count, 0)
        self.assertEqual(engine.blocked_station_count, 1)

        engine.advance(2.0)
        self.assertIs(engine.stations[1].state, StationState.IDLE)
        self.assertEqual(engine.blocked_station_count, 0)

        engine.advance(10.0)
        self.assertEqual(engine.completed_servers, 1)

    def test_queue_builds_when_arrivals_outrun_single_station_capacity(self) -> None:
        config = SimulationConfig(
            num_stations=1,
            arrival_interval=3.0,
            startup_ramp_duration=5.0,
            steady_state_duration=15.0,
            shutdown_ramp_duration=5.0,
            move_time_per_station=1.0,
            transfer_time=1.0,
            gate_cycle_time=0.0,
            peak_station_power=800.0,
            steady_state_power_pct=90.0,
            rgv_moving_power=400.0,
            rgv_idle_power=100.0,
        )
        engine = SimulationEngine(config)

        engine.advance(40.0)

        self.assertGreater(len(engine.waiting_servers), 0)
        self.assertGreaterEqual(engine.peak_queue, len(engine.waiting_servers))
        self.assertLessEqual(
            engine.peak_power,
            config.num_stations * config.peak_station_power,
        )

    def test_power_outputs_ignore_idle_non_test_loads(self) -> None:
        config = SimulationConfig(
            num_stations=1,
            rgv_moving_power=500.0,
            rgv_idle_power=100.0,
        )
        engine = SimulationEngine(config)

        self.assertEqual(engine.current_power(), 0.0)
        self.assertEqual(engine.current_station_power, 0.0)
        self.assertEqual(engine.average_power, 0.0)
        self.assertEqual(engine.average_station_power, 0.0)
        self.assertEqual(engine.peak_power, 0.0)
        self.assertEqual(engine.peak_station_power, 0.0)
        self.assertEqual(list(engine.power_history), [(0.0, 0.0)])

    def test_gate_cycle_does_not_force_rgv_to_wait_before_crossing(self) -> None:
        config = SimulationConfig(
            num_stations=2,
            arrival_interval=30.0,
            startup_ramp_duration=5.0,
            steady_state_duration=20.0,
            shutdown_ramp_duration=5.0,
            move_time_per_station=1.0,
            transfer_time=1.0,
            gate_cycle_time=3.0,
            peak_station_power=1000.0,
            steady_state_power_pct=90.0,
            rgv_moving_power=500.0,
            rgv_idle_power=100.0,
        )
        engine = SimulationEngine(config)

        engine.advance(4.0)

        self.assertIs(engine.stations[1].state, StationState.TESTING)
        self.assertEqual(engine.stations[1].server_id, 1)

    def test_station_assignment_is_not_reused_before_test_process_runs(self) -> None:
        config = SimulationConfig(
            num_stations=2,
            arrival_interval=1.0,
            startup_ramp_duration=10.0,
            steady_state_duration=20.0,
            shutdown_ramp_duration=10.0,
            move_time_per_station=1.0,
            transfer_time=1.0,
            gate_cycle_time=0.0,
        )
        engine = SimulationEngine(config)

        engine.advance(19.0)

        self.assertIs(engine.stations[1].state, StationState.TESTING)
        self.assertIs(engine.stations[2].state, StationState.TESTING)
        self.assertEqual(engine.stations[1].server_id, 1)
        self.assertEqual(engine.stations[2].server_id, 2)


if __name__ == "__main__":
    unittest.main()
