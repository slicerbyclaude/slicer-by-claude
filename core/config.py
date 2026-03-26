"""
Slicer by Claude - Configuración central v1.4.0
"""
import json
import os
from pathlib import Path

APP_NAME = "Slicer by Claude"
APP_VERSION = "2.0.0"
LOG_FILENAME = "slicer_log.txt"

CONFIG_DIR   = Path.home() / ".slicer_by_claude"
HISTORY_FILE = CONFIG_DIR / "history.json"
SETTINGS_FILE= CONFIG_DIR / "settings.json"
PRESETS_FILE = CONFIG_DIR / "text_presets.json"

# FFmpeg export settings
VIDEO_CODEC      = "libx265"
VIDEO_BITRATE    = "2000k"
VIDEO_FPS        = 30
AUDIO_CODEC      = "aac"
AUDIO_BITRATE    = "192k"
PRESET_DEFAULT   = "medium"
PRESETS_SPEED    = ["ultrafast", "fast", "medium", "slow", "veryslow"]
PRESETS_SPEED_DESC = {
    "ultrafast": "Muy rápido — archivo más pesado",
    "fast":      "Rápido — buen balance",
    "medium":    "Balance ideal — recomendado ✓",
    "slow":      "Lento — archivo más liviano",
    "veryslow":  "Muy lento — máxima compresión",
}

# Texto PARTE X — valores por defecto
TEXT_DEFAULTS = {
    "font_size": 80,
    "color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_width": 6,
    "opacity": 1.0,
    "position_y": 0.15,
}

PLAYER_RATIOS = {
    "9:16": (9, 16),
    "16:9": (16, 9),
    "1:1":  (1, 1),
    "4:3":  (4, 3),
}
PLAYER_RATIO_DEFAULT = "9:16"

HISTORY_SIZE_OPTIONS = [5, 10, 20]

def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR

def load_json(path: Path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(path: Path, data):
    ensure_config_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_settings() -> dict:
    defaults = {
        "window_geometry":    "1100x720+80+40",
        "speed_preset":       PRESET_DEFAULT,
        "text_preset_active": "Por defecto",
        "output_dir":         r"C:\Videos_Trabajo",
        "logs_dir":           r"C:\Videos_Trabajo",
        "history_max":        5,
        "warn_max_duration":  600,
        "warn_max_size_mb":   500,
        "player_ratio":       PLAYER_RATIO_DEFAULT,
        "setup_done":         False,
    }
    return {**defaults, **load_json(SETTINGS_FILE, {})}

def save_settings(data: dict):
    save_json(SETTINGS_FILE, data)

def load_history() -> list:
    return load_json(HISTORY_FILE, [])

def save_history(history: list, max_size: int = 5):
    save_json(HISTORY_FILE, history[:max_size])

def load_presets() -> dict:
    saved = load_json(PRESETS_FILE, {})
    saved["Por defecto"] = TEXT_DEFAULTS.copy()
    return saved

def save_presets(presets: dict):
    presets["Por defecto"] = TEXT_DEFAULTS.copy()
    save_json(PRESETS_FILE, presets)

def get_cache_size_mb() -> float:
    """Calcula el tamaño de archivos temporales de exportación."""
    total = 0
    for base in [r"C:\Videos_Trabajo"]:
        base_path = Path(base)
        if base_path.exists():
            for temp_dir in base_path.rglob("_temp"):
                for f in temp_dir.rglob("*"):
                    if f.is_file():
                        total += f.stat().st_size
    return total / (1024 * 1024)

def clear_cache():
    """Borra carpetas _temp de exportaciones anteriores."""
    cleared = 0
    for base in [r"C:\Videos_Trabajo"]:
        base_path = Path(base)
        if base_path.exists():
            for temp_dir in base_path.rglob("_temp"):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
                cleared += 1
    return cleared
