from __future__ import annotations

from PySide6.QtGui import QColor

from simulator.config import PayloadKind


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
    YELLOW = AMBER
    ORANGE = AMBER
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


def build_stylesheet() -> str:
    return f"""
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
