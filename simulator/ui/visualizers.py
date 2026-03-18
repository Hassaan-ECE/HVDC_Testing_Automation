from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from simulator.config import EPSILON, FINISHING_THRESHOLD, PayloadKind, StationState
from simulator.engine import SimulationEngine, fmt_time
from simulator.ui.theme import C


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
        terminal_top = (
            rail_y - max(34.0, height * 0.12) - max(14.0, height * 0.03)
        )
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
            QRectF(zone1_left, zone_top, zone1_right - zone1_left, zone_bottom - zone_top),
            8,
            8,
        )
        painter.setPen(self.PEN_ZONE2)
        painter.setBrush(C.ZONE2_BG)
        painter.drawRoundedRect(
            QRectF(zone2_left, zone_top, zone2_right - zone2_left, zone_bottom - zone_top),
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
                progress_color = C.PB_LATE if progress >= FINISHING_THRESHOLD else C.PB_FILL
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
                QRectF(x - station_half_width - 8, station_top + 42, station_half_width * 2 + 16, 16),
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
        return QRectF(
            56.0,
            18.0,
            max(1.0, self.width() - 74.0),
            max(1.0, self.height() - 50.0),
        )

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
        view_start, _ = self._current_view(current_time)
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
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._plot_rect().contains(event.position())
        ):
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
        painter.drawText(int(left), int(bottom + 16), fmt_time(view_start))
        painter.drawText(
            QRectF(right - 80, bottom + 4, 80, 16),
            Qt.AlignmentFlag.AlignRight,
            fmt_time(view_end),
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
