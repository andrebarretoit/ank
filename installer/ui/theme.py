"""
ANK Installer - Theme (PySide6)
Colors, fonts, and visual constants.
"""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtCore import Qt

# ============================================================
# Colors
# ============================================================
COLORS = {
    "bg_primary": "#0f172a",
    "bg_secondary": "#1e293b",
    "bg_tertiary": "#334155",
    "card_bg": "#1e293b",
    "text_primary": "#f8fafc",
    "text_secondary": "#94a3b8",
    "text_muted": "#64748b",
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "success": "#22c55e",
    "warning": "#eab308",
    "error": "#ef4444",
    "info": "#3b82f6",
    "purple": "#a855f7",
    "border": "#334155",
    "sidebar_bg": "#1a1a2e",
    "bottom_bar_bg": "#111827",
}

TIER_COLORS = {
    "isolated": "#22c55e",
    "shared_network": "#3b82f6",
    "shared_host": "#eab308",
    "native_host": "#94a3b8",
    "lite": "#a855f7",
}

# ============================================================
# Fonts
# ============================================================
def make_font(size, bold=False):
    f = QFont("Segoe UI", size)
    if bold:
        f.setBold(True)
    return f

FONTS = {
    "title": make_font(22, True),
    "subtitle": make_font(15, True),
    "body": make_font(12),
    "body_bold": make_font(12, True),
    "small": make_font(10),
    "small_bold": make_font(10, True),
    "mono": QFont("Consolas", 11),
}

# ============================================================
# Layout
# ============================================================
WINDOW_WIDTH = 960
WINDOW_HEIGHT = 620
SIDEBAR_WIDTH = 220
BOTTOM_BAR_HEIGHT = 56
PADDING = 20

# ============================================================
# Steps
# ============================================================
STEPS = [
    "Conectar Device",
    "Compatibilidade",
    "Confirmar",
    "Instalando",
    "Reiniciando",
    "Finalizado",
]

# ============================================================
# Stylesheet
# ============================================================
STYLESHEET = f"""
QMainWindow {{
    background-color: {COLORS['bg_primary']};
}}
QWidget {{
    color: {COLORS['text_primary']};
    font-family: Segoe UI;
    font-size: 12px;
}}

/* Sidebar */
#sidebar {{
    background-color: {COLORS['sidebar_bg']};
}}
#logo-label {{
    color: {COLORS['accent']};
    font-size: 22px;
    font-weight: bold;
}}
#logo-sub {{
    color: {COLORS['text_muted']};
    font-size: 10px;
}}
#step-dot {{
    color: {COLORS['text_muted']};
    font-size: 10px;
}}
#step-label {{
    color: {COLORS['text_muted']};
    font-size: 12px;
}}
#step-label-active {{
    color: {COLORS['text_primary']};
    font-size: 12px;
}}
#device-info {{
    color: {COLORS['text_muted']};
    font-size: 10px;
}}

/* Bottom bar */
#bottom-bar {{
    background-color: {COLORS['bottom_bar_bg']};
    border-top: 1px solid {COLORS['border']};
}}

/* Buttons */
QPushButton#btn-back {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_secondary']};
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 12px;
}}
QPushButton#btn-back:hover {{
    background-color: {COLORS['border']};
}}
QPushButton#btn-back:disabled {{
    background-color: {COLORS['bg_secondary']};
    color: {COLORS['text_muted']};
}}
QPushButton#btn-next {{
    background-color: {COLORS['accent']};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: bold;
}}
QPushButton#btn-next:hover {{
    background-color: {COLORS['accent_hover']};
}}
QPushButton#btn-next:disabled {{
    background-color: {COLORS['bg_secondary']};
    color: {COLORS['text_muted']};
}}

/* Card frames */
#card {{
    background-color: {COLORS['card_bg']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}
#card-success {{
    background-color: {COLORS['card_bg']};
    border: 1px solid {COLORS['success']};
    border-radius: 8px;
}}

/* Labels */
QLabel#title {{
    color: {COLORS['text_primary']};
    font-size: 18px;
    font-weight: bold;
}}
QLabel#subtitle {{
    color: {COLORS['text_secondary']};
    font-size: 13px;
}}
QLabel#text-muted {{
    color: {COLORS['text_muted']};
    font-size: 11px;
}}
QLabel#text-success {{
    color: {COLORS['success']};
    font-size: 13px;
}}
QLabel#text-error {{
    color: {COLORS['error']};
    font-size: 13px;
}}

/* Text area */
QTextEdit {{
    background-color: {COLORS['bg_secondary']};
    color: {COLORS['text_muted']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    font-family: Consolas;
    font-size: 11px;
    padding: 8px;
}}

/* Progress bar */
QProgressBar {{
    background-color: {COLORS['bg_tertiary']};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {COLORS['accent']};
    border-radius: 4px;
}}

/* Combo box */
QComboBox {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
}}
QComboBox::drop-down {{
    border: none;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_secondary']};
    color: {COLORS['text_primary']};
    selection-background-color: {COLORS['accent']};
}}
"""
