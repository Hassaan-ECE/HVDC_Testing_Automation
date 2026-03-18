from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from simulator.ui.main_window import SimulatorApp


def main() -> None:
    app = QApplication(sys.argv)
    window = SimulatorApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
