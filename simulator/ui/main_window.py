from __future__ import annotations

import time
from html import escape

import simpy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

from simulator.config import EPSILON, TIME_SCALES, UI_TICK_MS
from simulator.engine import SimulationEngine, fmt_time
from simulator.models import SimulationConfig
from simulator.ui.theme import C, build_stylesheet
from simulator.ui.visualizers import GraphVisualizer, LineVisualizer
from simulator.ui.widgets import StatusDot


class SimulatorApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Simulation Control Center")
        self.resize(2250, 1020)
        self.setMinimumSize(1750, 800)
        self.setStyleSheet(build_stylesheet())

        self.engine = SimulationEngine(SimulationConfig())
        self.running = False
        self.speed = 10.0
        self.last_wall = time.perf_counter()
        self._needs_refresh = True
        self._solver_running = False

        self._build_ui()
        self._sync_control_states()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(UI_TICK_MS)

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
            lambda checked, s=spin, c=combo: (
                s.setEnabled(not checked),
                c.setEnabled(not checked),
            )
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
        if self._solver_running:
            return
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
        self._solver_running = True
        rows = self._time_rows()
        spin_snapshot = {key: (spin.value(), combo.currentIndex()) for key, (spin, combo, _, _) in rows.items()}
        solved = False
        try:
            target_tput = max(0.1, self.sp_target_tput.value())
            cfg = self._build_cfg()
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
                f"Verified tail-rate {verified_tput:.2f}/hr. {summary}.",
                status_color,
            )
            solved = True
            self._reset()
        finally:
            if not solved:
                for key, (spin, combo, _, _) in rows.items():
                    saved_value, saved_combo_index = spin_snapshot[key]
                    combo.setCurrentIndex(saved_combo_index)
                    spin.setValue(saved_value)
            self._solver_running = False

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
                self.engine.log(f"CRITICAL ERROR: {type(exc).__name__}: {exc}")
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
        metrics["time"].setText(fmt_time(engine.env.now))
        metrics["queue"].setText(f"{len(engine.waiting_servers)} / {engine.peak_queue}")
        metrics["rgv"].setText(engine.rgv_desc)
        metrics["st_pwr"].setText(f"{station_power:,.1f} kW")
        metrics["tot_pwr"].setText(f"{station_power:,.1f} kW")
        metrics["peak_pwr"].setText(
            f"{engine.peak_power:,.1f} kW @ {fmt_time(engine.peak_power_time)}"
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
