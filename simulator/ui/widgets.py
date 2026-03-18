from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from simulator.ui.theme import C


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
        painter.drawEllipse(
            QPointF(center_x, center_y), self._size / 2, self._size / 2
        )
        painter.end()
