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


# ---------------------------------------------------------------------------
#  Line visualizer – industrial HMI / SCADA style
# ---------------------------------------------------------------------------


class LineVisualizer(QWidget):
    """Realistic industrial visualization of the 16-station test line."""

    # Fonts
    FONT_BOLD = QFont("Segoe UI", 9, QFont.Weight.Bold)
    FONT_SMALL = QFont("Segoe UI", 8)
    FONT_TINY = QFont("Segoe UI", 7)
    FONT_MONO = QFont("Cascadia Mono", 8)
    FONT_MONO_SM = QFont("Cascadia Mono", 7)
    FONT_ZONE = QFont("Segoe UI Semibold", 10)
    FONT_HUD = QFont("Segoe UI Semibold", 9)

    # Industrial palette (supplementary to theme.C)
    RAIL_COLOR = QColor("#3a4a5e")
    RAIL_HI = QColor("#5a6a7e")
    RAIL_TIE = QColor("#1a2838")
    FLOOR_GRID = QColor(255, 255, 255, 5)
    SAFETY = QColor("#eab308")
    SAFETY_DIM = QColor(234, 179, 8, 25)
    GATE_STEEL = QColor("#4a5568")
    GATE_STEEL_HI = QColor("#6a7a8e")
    GATE_SLAT = QColor(0, 0, 0, 70)
    GLOW_BLUE = QColor(59, 130, 246, 28)
    GLOW_RED = QColor(239, 68, 68, 28)
    GLOW_AMBER = QColor(245, 158, 11, 28)
    SHADOW = QColor(0, 0, 0, 50)

    def __init__(self, engine: SimulationEngine) -> None:
        super().__init__()
        self.engine = engine
        self.view_scale = 1.0
        self.setMinimumHeight(260)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    # -- coordinate helpers --------------------------------------------------

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

    # -- main paint entry ----------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = float(self.height())
        e = self.engine

        # Layout constants (relative to widget height)
        rail_y = h * 0.70
        st_top = h * 0.16
        st_h = h * 0.38
        st_hw = 26
        zone_top = st_top - h * 0.06
        zone_bot = rail_y + h * 0.10
        rgv_y = rail_y + h * 0.12
        hud_y = max(16.0, h * 0.06)
        term_h = max(34.0, h * 0.12)
        term_top = rail_y - term_h - max(12.0, h * 0.03)

        self._draw_background(p, w, h)
        self._draw_lane_marks(p, w, rail_y)
        self._draw_zones(p, e, zone_top, zone_bot)
        self._draw_track(p, w, rail_y)

        for sid, station in e.stations.items():
            self._draw_station(p, e, sid, station, st_top, st_h, st_hw, rail_y)

        for gate_pos, gate_name in e.gate_boundaries():
            self._draw_gate(p, e, gate_pos, gate_name, rail_y, h)

        self._draw_terminals(p, e, term_top, term_h)
        self._draw_rgv(p, e, rgv_y)
        self._draw_hud(p, e, hud_y, w)
        p.end()

    # -- layer: background ---------------------------------------------------

    def _draw_background(self, p: QPainter, w: float, h: float) -> None:
        """Dark industrial floor with subtle dot grid."""
        p.fillRect(self.rect(), C.BG)
        p.setPen(self.FLOOR_GRID)
        for y in range(20, int(h), 30):
            for x in range(20, int(w), 30):
                p.drawPoint(x, y)

    def _draw_lane_marks(self, p: QPainter, w: float, rail_y: float) -> None:
        """Safety-yellow dashed lane boundaries along the track."""
        pen = QPen(self.SAFETY_DIM, 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        offset = 22
        p.drawLine(60, int(rail_y - offset), int(w - 60), int(rail_y - offset))
        p.drawLine(60, int(rail_y + offset), int(w - 60), int(rail_y + offset))

    # -- layer: track --------------------------------------------------------

    def _draw_track(self, p: QPainter, w: float, rail_y: float) -> None:
        """Dual steel rails with cross-ties."""
        margin = 60
        gap = 10

        # Cross-ties
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.RAIL_TIE)
        for x in range(margin, int(w - margin), 18):
            p.drawRect(QRectF(x - 1.5, rail_y - gap - 2, 3, gap * 2 + 4))

        # Rails with metallic gradient
        for rail_offset in (-gap / 2, gap / 2):
            y0 = rail_y + rail_offset
            grad = QLinearGradient(0, y0 - 3, 0, y0 + 3)
            grad.setColorAt(0.0, self.RAIL_HI)
            grad.setColorAt(0.5, self.RAIL_COLOR)
            grad.setColorAt(1.0, QColor("#2a3a4e"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRect(QRectF(margin, y0 - 2.5, w - 2 * margin, 5))

    # -- layer: zones --------------------------------------------------------

    def _draw_zones(
        self,
        p: QPainter,
        e: SimulationEngine,
        zone_top: float,
        zone_bot: float,
    ) -> None:
        """Tinted zone background panels with labels."""
        z1_left = self._tx(e.GATE_1_POSITION) + 10
        z1_right = self._tx(e.GATE_2_POSITION) - 10
        z2_left = self._tx(e.GATE_2_POSITION) + 10
        z2_right = self._tx(e.GATE_3_POSITION) - 10

        for left, right, bg, bd, label, label_color in (
            (z1_left, z1_right, C.ZONE1_BG, C.ZONE1_BD, "ZONE 1", C.BLUE),
            (z2_left, z2_right, C.ZONE2_BG, C.ZONE2_BD, "ZONE 2", C.GREEN),
        ):
            rect = QRectF(left, zone_top, right - left, zone_bot - zone_top)
            p.setPen(QPen(bd, 1))
            p.setBrush(bg)
            p.drawRoundedRect(rect, 8, 8)
            p.setPen(label_color)
            p.setFont(self.FONT_ZONE)
            p.drawText(
                QRectF(left, zone_top + 2, right - left, 16),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

    # -- layer: station ------------------------------------------------------

    def _draw_station(
        self,
        p: QPainter,
        e: SimulationEngine,
        sid: int,
        station,
        st_top: float,
        st_h: float,
        hw: float,
        rail_y: float,
    ) -> None:
        """Station cabinet with glow, gradient body, LED indicator, and
        progress bar."""
        x = self._tx(e.station_track_position(sid))
        progress = e.station_progress(sid)

        # State-dependent appearance
        if station.state is StationState.TESTING:
            finishing = progress >= FINISHING_THRESHOLD
            body = C.ST_FIN if finishing else C.ST_TEST
            border = C.ST_FIN_BD if finishing else C.ST_TEST_BD
            glow = self.GLOW_AMBER if finishing else self.GLOW_BLUE
            pb_color = C.PB_LATE if finishing else C.PB_FILL
            state_text = "TESTING"
            power_text = f"{e.station_power(sid):.0f} kW"
            led_color = C.GREEN
        elif station.state is StationState.WAITING_UNLOAD:
            body, border, glow = C.ST_BLOCK, C.ST_BLOCK_BD, self.GLOW_RED
            pb_color, progress = C.RED, 1.0
            state_text, power_text, led_color = "BLOCKED", "WAIT", C.RED
        else:
            body, border, glow = C.ST_IDLE, C.ST_IDLE_BD, None
            pb_color, progress = C.PB_FILL, 0.0
            state_text, power_text, led_color = "IDLE", "", QColor("#1a2838")

        rect = QRectF(x - hw, st_top, hw * 2, st_h)

        # Glow halo
        if glow is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(rect.adjusted(-5, -5, 5, 5), 10, 10)

        # Drop shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.SHADOW)
        p.drawRoundedRect(rect.adjusted(2, 2, 2, 2), 6, 6)

        # Cabinet body with vertical gradient
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, body.lighter(112))
        grad.setColorAt(1.0, body)
        p.setPen(QPen(border, 1.5))
        p.setBrush(grad)
        p.drawRoundedRect(rect, 6, 6)

        # Rack-unit lines (decorative horizontal slots)
        p.setPen(QPen(QColor(255, 255, 255, 8), 1))
        for y_off in range(52, max(53, int(st_h) - 18), 8):
            p.drawLine(
                int(rect.left() + 4),
                int(st_top + y_off),
                int(rect.right() - 4),
                int(st_top + y_off),
            )

        # Station ID
        p.setPen(C.FG)
        p.setFont(self.FONT_BOLD)
        p.drawText(
            QRectF(rect.left(), st_top + 2, hw * 2, 16),
            Qt.AlignmentFlag.AlignCenter,
            f"S{sid}",
        )

        # Status LED (top-right corner)
        led_x, led_y = x + hw - 8, st_top + 7
        p.setPen(Qt.PenStyle.NoPen)
        led_glow = QColor(led_color)
        led_glow.setAlphaF(0.4)
        p.setBrush(led_glow)
        p.drawEllipse(QPointF(led_x, led_y), 5, 5)
        p.setBrush(led_color)
        p.drawEllipse(QPointF(led_x, led_y), 2.5, 2.5)

        # State text
        p.setPen(C.FG_DIM)
        p.setFont(self.FONT_TINY)
        p.drawText(
            QRectF(rect.left(), st_top + 22, hw * 2, 12),
            Qt.AlignmentFlag.AlignCenter,
            state_text,
        )

        # Power reading
        if power_text:
            p.setFont(self.FONT_MONO_SM)
            p.drawText(
                QRectF(rect.left() - 8, st_top + 36, hw * 2 + 16, 12),
                Qt.AlignmentFlag.AlignCenter,
                power_text,
            )

        # Progress bar
        bar_y = st_top + st_h - 12
        bar_left = rect.left() + 3
        bar_w = hw * 2 - 6
        bar_h = 5
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(8, 12, 18))
        p.drawRoundedRect(QRectF(bar_left, bar_y, bar_w, bar_h), 2.5, 2.5)
        if progress > 0:
            p.setBrush(pb_color)
            p.drawRoundedRect(
                QRectF(bar_left, bar_y, bar_w * progress, bar_h), 2.5, 2.5
            )

        # Support connector to track
        p.setPen(QPen(C.BORDER_LT, 1, Qt.PenStyle.DotLine))
        p.drawLine(int(x), int(st_top + st_h), int(x), int(rail_y - 8))

    # -- layer: gate ---------------------------------------------------------

    def _draw_gate(
        self,
        p: QPainter,
        e: SimulationEngine,
        gate_pos: float,
        gate_name: str,
        rail_y: float,
        h: float,
    ) -> None:
        """Industrial roller-shutter gate with steel frame and warning
        stripes."""
        gate_x = self._tx(gate_pos)
        openness = e.gate_open_fraction(gate_name)

        frame_w = 34
        frame_h = max(36.0, min(44.0, h * 0.16))
        post_w = 5

        frame_rect = QRectF(
            gate_x - frame_w / 2,
            rail_y - frame_h / 2 - 2,
            frame_w,
            frame_h,
        )

        # Opening void
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(3, 5, 10))
        p.drawRect(frame_rect)

        # Steel frame posts (left and right)
        for px_start, px_end in (
            (frame_rect.left() - post_w, frame_rect.left()),
            (frame_rect.right(), frame_rect.right() + post_w),
        ):
            steel = QLinearGradient(px_start, 0, px_end, 0)
            steel.setColorAt(0.0, self.GATE_STEEL)
            steel.setColorAt(0.5, self.GATE_STEEL_HI)
            steel.setColorAt(1.0, self.GATE_STEEL)
            p.setBrush(steel)
            p.drawRect(
                QRectF(px_start, frame_rect.top() - 3, post_w, frame_rect.height() + 6)
            )

        # Top beam
        beam = QLinearGradient(0, frame_rect.top() - 5, 0, frame_rect.top())
        beam.setColorAt(0.0, self.GATE_STEEL_HI)
        beam.setColorAt(1.0, self.GATE_STEEL)
        p.setBrush(beam)
        p.drawRect(
            QRectF(
                frame_rect.left() - post_w,
                frame_rect.top() - 5,
                frame_w + 2 * post_w,
                5,
            )
        )

        # Guide rail tick above frame
        p.setPen(QPen(C.BORDER_LT, 1))
        p.drawLine(
            int(gate_x), int(frame_rect.top() - 10), int(gate_x), int(frame_rect.top() - 5)
        )

        # Roller door (slides upward when opening)
        visible_h = frame_h * (1.0 - openness)
        if visible_h > 1:
            door_rect = QRectF(
                frame_rect.left() + 1,
                frame_rect.bottom() - visible_h,
                frame_w - 2,
                visible_h,
            )

            # Door body with corrugated metallic look
            door_grad = QLinearGradient(door_rect.left(), 0, door_rect.right(), 0)
            door_grad.setColorAt(0.0, QColor("#48566a"))
            door_grad.setColorAt(0.3, QColor("#5a6a7e"))
            door_grad.setColorAt(0.7, QColor("#5a6a7e"))
            door_grad.setColorAt(1.0, QColor("#48566a"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(door_grad)
            p.drawRect(door_rect)

            # Corrugation lines
            p.setPen(QPen(self.GATE_SLAT, 1))
            y = door_rect.top()
            while y < door_rect.bottom() - 1:
                p.drawLine(
                    int(door_rect.left()), int(y), int(door_rect.right()), int(y)
                )
                y += 4

            # Warning stripe at bottom edge
            stripe_w = 5
            stripe_h = min(5, visible_h)
            if stripe_h > 1:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self.SAFETY)
                sx = int(door_rect.left())
                while sx < int(door_rect.right()):
                    p.drawRect(QRectF(sx, door_rect.bottom() - stripe_h, stripe_w, stripe_h))
                    sx += stripe_w * 2

        # Gate label
        p.setPen(C.FG_DIM)
        p.setFont(self.FONT_SMALL)
        p.drawText(
            QRectF(gate_x - 30, frame_rect.bottom() + 10, 60, 14),
            Qt.AlignmentFlag.AlignCenter,
            gate_name,
        )

    # -- layer: terminals ----------------------------------------------------

    def _draw_terminals(
        self,
        p: QPainter,
        e: SimulationEngine,
        term_top: float,
        term_h: float,
    ) -> None:
        """Load and Pack docking bays with hazard markings."""
        for pos, label, fill, border in (
            (e.LOAD_POSITION, "LOAD", C.LOAD_FILL, C.LOAD_BD),
            (e.PACKING_POSITION, "PACK", C.PACK_FILL, C.PACK_BD),
        ):
            bx = self._tx(pos)
            rect = QRectF(bx - 30, term_top, 60, term_h)

            # Shadow
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.SHADOW)
            p.drawRoundedRect(rect.adjusted(2, 2, 2, 2), 5, 5)

            # Body with gradient
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0.0, fill.lighter(120))
            grad.setColorAt(1.0, fill)
            p.setPen(QPen(border, 2))
            p.setBrush(grad)
            p.drawRoundedRect(rect, 5, 5)

            # Hazard stripe along bottom edge
            stripe_w = 6
            p.setPen(Qt.PenStyle.NoPen)
            stripe_color = QColor(border.red(), border.green(), border.blue(), 80)
            p.setBrush(stripe_color)
            for sx in range(int(rect.left() + 2), int(rect.right() - 2), stripe_w * 2):
                p.drawRect(QRectF(sx, rect.bottom() - 5, stripe_w, 4))

            # Label
            p.setPen(border)
            p.setFont(self.FONT_BOLD)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    # -- layer: RGV ----------------------------------------------------------

    def _draw_rgv(self, p: QPainter, e: SimulationEngine, rgv_y: float) -> None:
        """RGV vehicle with wheel bogies, gradient body, cabin window, and
        directional arrow."""
        rx = self._tx(e.rgv_position)
        bw, bh = 66, 28
        body_rect = QRectF(rx - bw / 2, rgv_y - bh / 2, bw, bh)

        # Drop shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawRoundedRect(body_rect.adjusted(3, 3, 3, 3), 8, 8)

        # Wheel bogies (four corners)
        wheel_fill = QColor("#2d3748")
        wheel_border = QColor("#4a5568")
        for dx in (-bw / 2 + 8, bw / 2 - 18):
            for dy in (-bh / 2 - 2, bh / 2 - 2):
                p.setPen(QPen(wheel_border, 1))
                p.setBrush(wheel_fill)
                p.drawRoundedRect(QRectF(rx + dx, rgv_y + dy, 10, 4), 2, 2)

        # Body (payload colour gradient)
        payload_color = C.RGV[e.rgv_payload]
        body_grad = QLinearGradient(body_rect.topLeft(), body_rect.bottomLeft())
        body_grad.setColorAt(0.0, payload_color.lighter(135))
        body_grad.setColorAt(0.45, payload_color)
        body_grad.setColorAt(1.0, payload_color.darker(115))
        p.setPen(QPen(C.FG, 2))
        p.setBrush(body_grad)
        p.drawRoundedRect(body_rect, 7, 7)

        # Cabin window (dark inset on the left side)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(
            QRectF(rx - bw / 2 + 4, rgv_y - bh / 2 + 3, 14, bh - 6), 3, 3
        )

        # "RGV" label
        p.setPen(C.BG)
        p.setFont(self.FONT_BOLD)
        p.drawText(body_rect, Qt.AlignmentFlag.AlignCenter, "RGV")

        # Direction arrow when in motion
        if e.rgv_is_moving:
            arrow_color = QColor(payload_color)
            arrow_color.setAlphaF(0.75)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(arrow_color)

            if e.rgv_phase_target_pos > e.rgv_phase_start_pos:
                ax = rx + bw / 2 + 5
                tri = QPolygonF(
                    [
                        QPointF(ax, rgv_y - 5),
                        QPointF(ax + 8, rgv_y),
                        QPointF(ax, rgv_y + 5),
                    ]
                )
            else:
                ax = rx - bw / 2 - 5
                tri = QPolygonF(
                    [
                        QPointF(ax, rgv_y - 5),
                        QPointF(ax - 8, rgv_y),
                        QPointF(ax, rgv_y + 5),
                    ]
                )
            p.drawPolygon(tri)

        # Status line below vehicle
        payload_label = {
            PayloadKind.EMPTY: "",
            PayloadKind.INCOMING: "\u25b2 server",
            PayloadKind.OUTGOING: "\u25bc packing",
        }[e.rgv_payload]
        motion = "\u25cf Moving" if e.rgv_is_moving else "\u25cb Parked"
        p.setPen(C.FG_DIM)
        p.setFont(self.FONT_SMALL)
        p.drawText(
            QRectF(rx - 80, rgv_y + bh / 2 + 6, 160, 14),
            Qt.AlignmentFlag.AlignCenter,
            f"{motion}  {payload_label}".strip(),
        )

    # -- layer: HUD ----------------------------------------------------------

    def _draw_hud(
        self,
        p: QPainter,
        e: SimulationEngine,
        hud_y: float,
        w: float,
    ) -> None:
        """Overlay badges for queue depth and RGV task."""
        # Queue badge (top-left)
        queue_text = f"Queue: {len(e.waiting_servers)}  (peak {e.peak_queue})"
        queue_rect = QRectF(10, hud_y - 10, 200, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 100))
        p.drawRoundedRect(queue_rect, 6, 6)
        p.setPen(self.SAFETY)
        p.setFont(self.FONT_HUD)
        p.drawText(
            queue_rect.adjusted(10, 0, 0, 0),
            Qt.AlignmentFlag.AlignVCenter,
            queue_text,
        )

        # RGV task badge (top-right)
        rgv_text = f"RGV: {e.rgv_desc}"
        text_w = max(160, len(rgv_text) * 8)
        task_rect = QRectF(w - text_w - 20, hud_y - 10, text_w + 10, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 100))
        p.drawRoundedRect(task_rect, 6, 6)
        p.setPen(C.FG_SEC)
        p.setFont(self.FONT_HUD)
        p.drawText(
            task_rect.adjusted(10, 0, -4, 0),
            Qt.AlignmentFlag.AlignVCenter,
            rgv_text,
        )


# ---------------------------------------------------------------------------
#  Power-demand graph – enhanced with glow trace and live readout
# ---------------------------------------------------------------------------


class GraphVisualizer(QWidget):
    FONT_LABEL = QFont("Segoe UI", 9)
    FONT_MONO = QFont("Cascadia Mono", 8)
    FONT_AXIS = QFont("Segoe UI", 9)
    FONT_POWER = QFont("Cascadia Mono", 16, QFont.Weight.Bold)
    FONT_POWER_UNIT = QFont("Segoe UI", 8)
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
        if history[-1][0] < current_time - EPSILON or abs(
            history[-1][1] - current_power
        ) > EPSILON:
            history.append((current_time, current_power))
        return history

    # -- interaction ---------------------------------------------------------

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
        zoom_factor = 0.85**steps
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

    # -- rendering -----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        canvas_path = QPainterPath()
        canvas_path.addRoundedRect(rect, 8, 8)

        # Canvas background
        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor("#080c14"))
        gradient.setColorAt(1.0, QColor("#0c1420"))
        painter.fillPath(canvas_path, gradient)

        # Subtle dot pattern
        painter.save()
        painter.setClipPath(canvas_path)
        painter.setPen(QColor(255, 255, 255, 8))
        for x in range(20, int(rect.width()), 30):
            for y in range(20, int(rect.height()), 30):
                painter.drawPoint(x, y)
        painter.restore()

        # Data
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
            (t, pw)
            for t, pw in history
            if view_start <= t <= view_end
        ]
        previous_samples = [
            (t, pw)
            for t, pw in history
            if t < view_start
        ]
        if previous_samples:
            visible_history.insert(0, (view_start, previous_samples[-1][1]))
        if not visible_history:
            latest_power = history[-1][1]
            visible_history = [(view_start, latest_power), (view_end, latest_power)]

        max_power = (
            max(
                max(pw for _, pw in visible_history),
                self.engine.peak_station_power,
                1.0,
            )
            * 1.12
        )

        def sx(t: float) -> float:
            return left + (t - view_start) / span_t * plot_rect.width()

        def sy(pw: float) -> float:
            return bottom - (pw / max_power) * span_y

        # Plot area inset
        painter.setPen(QPen(QColor(12, 15, 22, 160), 1))
        painter.setBrush(QColor(8, 12, 20, 80))
        painter.drawRoundedRect(plot_rect, 8, 8)

        # Axes
        painter.setPen(QPen(C.BORDER_LT, 1))
        painter.drawLine(left, top, left, bottom)
        painter.drawLine(left, bottom, right, bottom)

        # Horizontal grid + Y labels
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

        # Vertical time grid
        num_vlines = max(2, min(8, int(span_t / 30)))
        vline_pen = QPen(C.GRAPH_GRID, 1, Qt.PenStyle.DotLine)
        for i in range(1, num_vlines):
            t = view_start + i * span_t / num_vlines
            tx = sx(t)
            painter.setPen(vline_pen)
            painter.drawLine(int(tx), int(top), int(tx), int(bottom))
            if left + 60 < tx < right - 60:
                painter.setPen(C.FG_MUTED)
                painter.setFont(self.FONT_MONO)
                painter.drawText(
                    QRectF(tx - 25, bottom + 2, 50, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    fmt_time(t),
                )

        # Clipped data area
        painter.save()
        painter.setClipRect(plot_rect.adjusted(0, 0, 0, 1))

        if len(visible_history) >= 2:
            # Fill polygon
            poly = QPolygonF()
            poly.append(QPointF(left, bottom))
            for t, pw in visible_history:
                poly.append(QPointF(sx(t), sy(pw)))
            poly.append(QPointF(sx(visible_history[-1][0]), bottom))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(C.GRAPH_FILL)
            painter.drawPolygon(poly)

            # Build the line path once
            path = QPainterPath()
            path.moveTo(sx(visible_history[0][0]), sy(visible_history[0][1]))
            for t, pw in visible_history[1:]:
                path.lineTo(sx(t), sy(pw))

            # Glow layer (wide, semi-transparent)
            painter.setPen(
                QPen(
                    QColor(59, 130, 246, 50),
                    6,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

            # Main trace line
            painter.setPen(QPen(C.GRAPH_LINE, 2.5))
            painter.drawPath(path)

        # Current-value dot
        latest_time, latest_power = visible_history[-1]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(C.GRAPH_LINE)
        painter.drawEllipse(QPointF(sx(latest_time), sy(latest_power)), 4.0, 4.0)

        painter.restore()

        # Peak reference line
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

        # Average reference line
        average_power = self.engine.average_station_power
        if average_power > 0:
            avg_y = sy(average_power)
            painter.setPen(QPen(C.GRAPH_AVG, 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(left), int(avg_y), int(right), int(avg_y))
            painter.setPen(C.GRAPH_AVG)
            painter.drawText(
                QRectF(right - 140, avg_y + 2, 140, 16),
                Qt.AlignmentFlag.AlignRight,
                f"Avg {average_power:,.0f} kW",
            )

        # Time axis labels (endpoints)
        painter.setPen(C.FG_MUTED)
        painter.setFont(self.FONT_MONO)
        painter.drawText(int(left), int(bottom + 16), fmt_time(view_start))
        painter.drawText(
            QRectF(right - 80, bottom + 4, 80, 16),
            Qt.AlignmentFlag.AlignRight,
            fmt_time(view_end),
        )

        # Live power readout (top-left pill)
        power_now = self.engine.current_station_power
        pill = QRectF(left + 6, top + 4, 130, 38)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 12, 20, 190))
        painter.drawRoundedRect(pill, 8, 8)

        painter.setPen(C.GRAPH_LINE)
        painter.setFont(self.FONT_POWER)
        painter.drawText(
            QRectF(pill.left() + 8, pill.top() + 2, 120, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            f"{power_now:,.0f}",
        )
        painter.setPen(QColor(59, 130, 246, 140))
        painter.setFont(self.FONT_POWER_UNIT)
        painter.drawText(
            QRectF(pill.left() + 8, pill.top() + 24, 120, 14),
            Qt.AlignmentFlag.AlignLeft,
            "kW station power",
        )

        # Help text (top-right)
        painter.setFont(self.FONT_LABEL)
        painter.setPen(C.FG_MUTED)
        painter.drawText(
            QRectF(left, top - 2, plot_rect.width(), 14),
            Qt.AlignmentFlag.AlignRight,
            "Wheel zoom  Drag pan  Double-click reset",
        )

        # Border
        painter.setPen(QPen(C.BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(canvas_path)
        painter.end()
