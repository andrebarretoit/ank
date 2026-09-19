"""
ANK Installer - Theme (PySide6)
Colors, fonts, and visual constants.

Palette mirrors the ANK Web Panel (ui-reference/style.css) so the desktop
installer and the web dashboard feel like the same product.
"""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsDropShadowEffect

# ============================================================
# Colors (matches ui-reference/style.css custom properties)
# ============================================================
COLORS = {
    "bg_primary": "#000208",
    "bg_deep": "#050810",
    "bg_base": "#0a0f1e",
    "bg_surface": "rgba(15, 23, 42, 0.6)",
    "bg_elevated": "rgba(22, 32, 54, 0.7)",
    "bg_hover": "rgba(30, 41, 66, 0.5)",

    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "accent_dim": "rgba(59, 130, 246, 0.15)",
    "accent2": "#8b5cf6",

    "success": "#22c55e",
    "success_dim": "rgba(34, 197, 94, 0.15)",
    "warning": "#eab308",
    "warning_dim": "rgba(234, 179, 8, 0.15)",
    "danger": "#ef4444",
    "danger_dim": "rgba(239, 68, 68, 0.15)",

    "text": "#f8fafc",
    "text_secondary": "#94a3b8",
    "text_muted": "#64748b",

    "border": "rgba(56, 189, 248, 0.08)",
    "border_focus": "rgba(59, 130, 246, 0.5)",
    "glass_border": "rgba(56, 189, 248, 0.08)",

    # Back-compat aliases used by older widget code
    "bg_secondary": "#0a0f1e",
    "bg_tertiary": "#16213a",
    "card_bg": "#0f172a",
    "text_primary": "#f8fafc",
    "error": "#ef4444",
    "info": "#3b82f6",
    "purple": "#8b5cf6",
    "sidebar_bg": "#050810",
    "bottom_bar_bg": "#050810",
}

TIER_COLORS = {
    "isolated": "#22c55e",
    "shared_network": "#3b82f6",
    "shared_host": "#eab308",
    "native_host": "#94a3b8",
    "lite": "#8b5cf6",
}

TIER_NAMES = {
    "isolated": "Isolated",
    "shared_network": "Shared Network",
    "shared_host": "Shared Host",
    "native_host": "Native Host",
    "lite": "Lite",
}

# ============================================================
# Fonts
# ============================================================
def make_font(size, bold=False, mono=False):
    families = ["JetBrains Mono", "Consolas", "monospace"] if mono else \
               ["Inter", "Segoe UI", "sans-serif"]
    f = QFont()
    f.setFamilies(families)
    f.setPointSize(size)
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
    "mono": make_font(11, mono=True),
}


def apply_glass_shadow(widget, blur=28, alpha=140, y_offset=6):
    """Attach a soft drop shadow to approximate the web UI's glass cards."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
    return effect


# ============================================================
# Layout
# ============================================================
WINDOW_WIDTH = 1040
WINDOW_HEIGHT = 680
SIDEBAR_WIDTH = 240
BOTTOM_BAR_HEIGHT = 60
PADDING = 24

# ============================================================
# Modes (initial screen, before the step flow starts)
# ============================================================
MODES = [
    {
        "key": "install",
        "title": "Install",
        "subtitle": "Set up ANK on a new device",
        "desc": "Connects to a device, detects its capabilities and installs "
                "the ANK engine automatically.",
        "icon": "\u2913",
    },
    {
        "key": "restore",
        "title": "Restore",
        "subtitle": "Restore from a .ankengine backup",
        "desc": "Loads a previously exported .ankengine backup file and "
                "restores it onto a connected device.",
        "icon": "\u21bb",
    },
    {
        "key": "clone",
        "title": "Clone",
        "subtitle": "Copy one device's setup to another",
        "desc": "Connects two devices at once and copies the full ANK "
                "configuration from the source to the target.",
        "icon": "\u29c9",
    },
    {
        "key": "migrate",
        "title": "Migrate",
        "subtitle": "Move from an old device to a new one",
        "desc": "Like Clone, with control over network configuration, "
                "port remapping and which containers come along.",
        "icon": "\u2192",
    },
]

MODES_INSTALLED = [
    {
        "key": "uninstall",
        "title": "Uninstall",
        "subtitle": "Remove ANK completely",
        "desc": "Full removal of ANK from the device. All containers, "
                "data and configuration will be permanently deleted.",
        "icon": "\u2716",
        "danger": True,
    },
    {
        "key": "reinstall",
        "title": "Reinstall",
        "subtitle": "Fresh install over existing",
        "desc": "Removes current installation and reinstalls ANK. "
                "Use this to fix issues or update to a new version.",
        "icon": "\u21bb",
    },
    {
        "key": "export",
        "title": "Export .ankengine",
        "subtitle": "Backup device to a file",
        "desc": "Exports the full ANK setup (containers, config, images) "
                "into a portable .ankengine file.",
        "icon": "\u2913",
    },
    {
        "key": "restore_engine",
        "title": "Restore .ankengine",
        "subtitle": "Import from a backup file",
        "desc": "Loads a previously exported .ankengine backup file and "
                "restores it onto this device.",
        "icon": "\u2192",
    },
    {
        "key": "clone",
        "title": "Clone",
        "subtitle": "Copy setup to another device",
        "desc": "Connects two devices at once and copies the full ANK "
                "configuration from this device to the target.",
        "icon": "\u29c9",
    },
    {
        "key": "migrate",
        "title": "Migrate",
        "subtitle": "Move to a new device",
        "desc": "Like Clone, with control over network configuration, "
                "port remapping and which containers come along.",
        "icon": "\u2192",
    },
]

# ============================================================
# Steps (sidebar labels), one list per mode
# ============================================================
STEPS_BY_MODE = {
    "install": ["Connect Device", "Compatibility", "Confirm", "Installing", "Rebooting", "Finished"],
    "restore": ["Connect Device", "Select Backup", "Confirm", "Restoring", "Rebooting", "Finished"],
    "clone": ["Connect Devices", "Confirm", "Cloning", "Rebooting", "Finished"],
    "migrate": ["Connect Devices", "Migration Options", "Confirm", "Migrating", "Rebooting", "Finished"],
    "uninstall": ["Connect Device", "Confirm", "Uninstalling", "Finished"],
    "reinstall": ["Connect Device", "Compatibility", "Confirm", "Installing", "Rebooting", "Finished"],
    "export": ["Connect Device", "Confirm", "Exporting", "Finished"],
    "restore_engine": ["Connect Device", "Select Backup", "Confirm", "Restoring", "Rebooting", "Finished"],
}

# Back-compat: default step list (install flow) for any code that still
# imports the flat STEPS constant.
STEPS = STEPS_BY_MODE["install"]

# ============================================================
# Stylesheet
# ============================================================
STYLESHEET = f"""
QMainWindow {{
    background-color: {COLORS['bg_primary']};
}}
QWidget {{
    color: {COLORS['text']};
    font-family: Inter, "Segoe UI";
    font-size: 12px;
    background-color: transparent;
}}
QToolTip {{
    background-color: {COLORS['bg_base']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['glass_border']};
    padding: 4px 8px;
    border-radius: 4px;
}}

/* Sidebar */
#sidebar {{
    background-color: {COLORS['bg_deep']};
    border-right: 1px solid {COLORS['glass_border']};
}}
#logo-mark {{
    color: {COLORS['accent']};
    font-size: 24px;
    font-weight: bold;
}}
#logo-label {{
    color: {COLORS['text']};
    font-size: 18px;
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
#device-info {{
    color: {COLORS['text_muted']};
    font-size: 10px;
}}

/* Main content area background */
#content-area {{
    background-color: {COLORS['bg_base']};
}}

/* Bottom bar */
#bottom-bar {{
    background-color: {COLORS['bg_deep']};
    border-top: 1px solid {COLORS['glass_border']};
}}

/* Buttons */
QPushButton#btn-back {{
    background-color: transparent;
    color: {COLORS['text_secondary']};
    border: 1px solid {COLORS['glass_border']};
    border-radius: 8px;
    padding: 9px 20px;
    font-size: 12px;
    font-weight: bold;
}}
QPushButton#btn-back:hover {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text']};
}}
QPushButton#btn-back:disabled {{
    color: {COLORS['text_muted']};
    border-color: transparent;
}}
QPushButton#btn-next {{
    background-color: {COLORS['accent']};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 9px 22px;
    font-size: 12px;
    font-weight: bold;
}}
QPushButton#btn-next:hover {{
    background-color: {COLORS['accent_hover']};
}}
QPushButton#btn-next:disabled {{
    background-color: {COLORS['bg_elevated']};
    color: {COLORS['text_muted']};
}}

/* Secondary / outline buttons used inside steps */
QPushButton#btn-secondary {{
    background-color: {COLORS['bg_elevated']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['glass_border']};
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 12px;
}}
QPushButton#btn-secondary:hover {{
    background-color: {COLORS['bg_hover']};
    border-color: {COLORS['border_focus']};
}}
QPushButton#btn-secondary:disabled {{
    color: {COLORS['text_muted']};
}}
QPushButton#btn-danger {{
    background-color: {COLORS['danger_dim']};
    color: {COLORS['danger']};
    border: 1px solid {COLORS['danger']};
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: bold;
}}
QPushButton#btn-danger:hover {{
    background-color: {COLORS['danger']};
    color: white;
}}
QPushButton#btn-danger:disabled {{
    background-color: transparent;
    color: {COLORS['text_muted']};
    border-color: {COLORS['glass_border']};
}}

/* Card frames (glass effect approximation) */
#card {{
    background-color: {COLORS['bg_surface']};
    border: 1px solid {COLORS['glass_border']};
    border-radius: 12px;
}}
#card-success {{
    background-color: {COLORS['success_dim']};
    border: 1px solid {COLORS['success']};
    border-radius: 12px;
}}
#card-warning {{
    background-color: {COLORS['warning_dim']};
    border: 1px solid {COLORS['warning']};
    border-radius: 12px;
}}
#card-danger {{
    background-color: {COLORS['danger_dim']};
    border: 1px solid {COLORS['danger']};
    border-radius: 12px;
}}

/* Mode selector cards */
#mode-card {{
    background-color: {COLORS['bg_surface']};
    border: 1px solid {COLORS['glass_border']};
    border-radius: 16px;
}}
#mode-card:hover {{
    border: 1px solid {COLORS['border_focus']};
    background-color: {COLORS['bg_elevated']};
}}
#mode-card-icon {{
    color: {COLORS['accent']};
    font-size: 26px;
    font-weight: bold;
}}
#mode-card-title {{
    color: {COLORS['text']};
    font-size: 15px;
    font-weight: bold;
}}
#mode-card-subtitle {{
    color: {COLORS['text_secondary']};
    font-size: 11px;
    font-weight: bold;
}}
#mode-card-desc {{
    color: {COLORS['text_muted']};
    font-size: 11px;
}}

/* Labels */
QLabel#title {{
    color: {COLORS['text']};
    font-size: 20px;
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
    color: {COLORS['danger']};
    font-size: 13px;
}}
QLabel#field-label {{
    color: {COLORS['text_secondary']};
    font-size: 11px;
    font-weight: bold;
}}
QCheckBox {{
    color: {COLORS['text']};
    font-size: 12px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {COLORS['glass_border']};
    background-color: {COLORS['bg_elevated']};
}}
QCheckBox::indicator:checked {{
    background-color: {COLORS['accent']};
    border-color: {COLORS['accent']};
}}
QLineEdit, QSpinBox {{
    background-color: {COLORS['bg_elevated']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['glass_border']};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
}}
QLineEdit:focus, QSpinBox:focus {{
    border-color: {COLORS['border_focus']};
}}

/* Text area */
QTextEdit, QListWidget {{
    background-color: {COLORS['bg_deep']};
    color: {COLORS['text_secondary']};
    border: 1px solid {COLORS['glass_border']};
    border-radius: 10px;
    font-family: "JetBrains Mono", Consolas;
    font-size: 11px;
    padding: 8px;
}}
QListWidget::item {{
    padding: 6px 4px;
    border-radius: 6px;
}}
QListWidget::item:selected {{
    background-color: {COLORS['accent_dim']};
    color: {COLORS['text']};
}}

/* Progress bar */
QProgressBar {{
    background-color: {COLORS['bg_elevated']};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {COLORS['accent']};
    border-radius: 5px;
}}

/* Combo box */
QComboBox {{
    background-color: {COLORS['bg_elevated']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['glass_border']};
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 12px;
}}
QComboBox:hover {{
    border-color: {COLORS['border_focus']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_base']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['glass_border']};
    selection-background-color: {COLORS['accent']};
    outline: none;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(100, 116, 139, 0.35);
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""
