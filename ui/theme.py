"""Identité visuelle centralisée de l'application CarvEx."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


class Colors:
    BACKGROUND = "#1E1E1E"
    PANEL = "#252526"
    PANEL_SECONDARY = "#2D2D30"
    SELECTED = "#094771"
    HOVER = "#2A4365"
    ACCENT = "#4FC3F7"
    TEXT = "#F3F3F3"
    TEXT_SECONDARY = "#BFBFBF"
    BORDER = "#3A3A3D"


class Metrics:
    PANEL_MARGIN = 14
    PANEL_SPACING = 10
    CONTROL_HEIGHT = 32
    TABLE_ROW_PADDING = 7
    PREVIEW_MIN_HEIGHT = 190
    TEXT_FIELD_MIN_HEIGHT = 30
    TEXT_FIELD_EXTRA_HEIGHT = 10


STYLE_SHEET = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {Colors.BACKGROUND}; color: {Colors.TEXT}; }}
QWidget {{ color: {Colors.TEXT}; }}
QMenuBar {{ background: {Colors.PANEL}; border-bottom: 1px solid {Colors.BORDER}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 6px 10px; border-radius: 4px; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {Colors.HOVER}; }}
QMenu {{ background: {Colors.PANEL}; border: 1px solid {Colors.BORDER}; padding: 4px; }}
QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: 3px; }}
QToolBar {{ background: {Colors.PANEL}; border: 0; border-bottom: 1px solid {Colors.BORDER}; padding: 6px; spacing: 5px; }}
QToolButton {{ min-height: {Metrics.CONTROL_HEIGHT}px; padding: 4px 9px; border: 1px solid transparent; border-radius: 5px; color: {Colors.TEXT}; }}
QToolButton:hover {{ background: {Colors.HOVER}; border-color: #39617D; }}
QToolButton:checked {{ background: {Colors.SELECTED}; }}
QToolButton:disabled {{ color: #767676; }}
QLineEdit {{ min-height: {Metrics.CONTROL_HEIGHT}px; background: {Colors.PANEL_SECONDARY}; border: 1px solid {Colors.BORDER}; border-radius: 5px; padding: 0 10px; selection-background-color: {Colors.SELECTED}; }}
QLineEdit:focus {{ border: 1px solid {Colors.ACCENT}; }}
QTableView {{ background: {Colors.PANEL}; alternate-background-color: #29292B; border: 1px solid {Colors.BORDER}; border-radius: 5px; gridline-color: #343438; selection-background-color: {Colors.SELECTED}; selection-color: {Colors.TEXT}; }}
QTableView::item {{ padding: {Metrics.TABLE_ROW_PADDING}px 8px; border-bottom: 1px solid #303034; }}
QTableView::item:hover {{ background: {Colors.HOVER}; }}
QTableView::item:selected {{ background: {Colors.SELECTED}; color: {Colors.TEXT}; }}
QHeaderView::section {{ background: {Colors.PANEL_SECONDARY}; color: {Colors.TEXT_SECONDARY}; border: 0; border-right: 1px solid {Colors.BORDER}; border-bottom: 1px solid {Colors.BORDER}; padding: 8px; font-weight: 600; }}
QHeaderView::section:hover {{ background: #343438; color: {Colors.TEXT}; }}
QScrollArea, #detailsPanel {{ background: {Colors.PANEL}; border: 1px solid {Colors.BORDER}; border-radius: 5px; }}
QGroupBox {{ background: {Colors.PANEL}; border: 1px solid {Colors.BORDER}; border-radius: 6px; margin-top: 11px; padding: 12px 9px 9px 9px; font-weight: 600; color: {Colors.ACCENT}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
QTextEdit {{ background: {Colors.PANEL_SECONDARY}; border: 1px solid #38383C; border-radius: 4px; padding: 4px; color: {Colors.TEXT}; selection-background-color: {Colors.SELECTED}; }}
#previewPanel {{ background: {Colors.PANEL_SECONDARY}; border: 1px solid {Colors.BORDER}; border-radius: 6px; }}
#previewPanel QLabel {{ color: {Colors.TEXT_SECONDARY}; }}
#detailsTitle {{ color: {Colors.TEXT}; font-size: 12pt; font-weight: 600; }}
#artifactBadge {{ background: #163B52; border: 1px solid #39617D; border-radius: 9px; color: {Colors.TEXT}; font-weight: 600; padding: 3px 8px; }}
#artifactBadge[severity="warning"] {{ background: #4A3520; border-color: #9D6C2B; }}
QStatusBar {{ background: {Colors.PANEL}; color: {Colors.TEXT_SECONDARY}; border-top: 1px solid {Colors.BORDER}; }}
QStatusBar::item {{ border: 0; }}
QSplitter::handle {{ background: {Colors.BACKGROUND}; width: 5px; }}
QSplitter::handle:hover {{ background: {Colors.ACCENT}; }}
"""


def apply_theme(application: QApplication) -> None:
    """Applique une palette Fusion sombre et les styles communs à toute l'UI."""
    application.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(Colors.BACKGROUND))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(Colors.TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(Colors.PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#29292B"))
    palette.setColor(QPalette.ColorRole.Text, QColor(Colors.TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(Colors.PANEL_SECONDARY))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(Colors.TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(Colors.SELECTED))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(Colors.TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(Colors.PANEL_SECONDARY))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(Colors.TEXT))
    application.setPalette(palette)
    application.setStyleSheet(STYLE_SHEET)
