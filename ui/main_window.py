"""
Slicer by Claude - v2.0.1
"""
import os
import time
import struct
import threading
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime
from tkinter import filedialog, messagebox, colorchooser
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

try:
    import vlc
    VLC_AVAILABLE = True
except ImportError:
    VLC_AVAILABLE = False

from core.config import (
    APP_NAME, APP_VERSION,
    PRESETS_SPEED, PRESETS_SPEED_DESC, PRESET_DEFAULT,
    TEXT_DEFAULTS, PLAYER_RATIOS, PLAYER_RATIO_DEFAULT,
    MAX_HISTORY_ITEMS,
    VIDEO_CODEC, VIDEO_BITRATE, VIDEO_FPS, AUDIO_CODEC, AUDIO_BITRATE,
    load_settings, save_settings, load_history, save_history,
    load_presets, save_presets, get_cache_size_mb, clear_cache,
)
from core.utils import (
    parse_time, seconds_to_str, format_duration, format_size,
    validate_cuts, estimate_segment_size_mb, get_segment_durations,
)
from core.engine import (
    ExportEngine, get_video_info, extract_frame, write_log,
    find_ffmpeg, find_ffprobe, check_anton_font,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── Paleta morada original ────────────────────────────────────────────────────
ACCENT        = "#9b30d9"
ACCENT_GLOW   = "#c060ff"
ACCENT_HOVER  = "#7a22b0"
BG_ROOT       = "#0a0a0f"
BG_PANEL      = "#111118"
BG_CARD       = "#18181f"
BG_ELEVATED   = "#1f1f2a"
BG_INPUT      = "#14141c"
BORDER        = "#2a2a3a"
BORDER_ACCENT = "#3d2060"
TEXT_PRIMARY  = "#e8e8f0"
TEXT_SEC      = "#9090a8"
TEXT_MUTED    = "#505068"
SUCCESS       = "#22c55e"
WARNING       = "#f59e0b"
DANGER        = "#ef4444"
SEGMENT_COLORS = ["#9b30d9","#2563eb","#059669","#d97706","#dc2626","#7c3aed"]


# ── Toast ─────────────────────────────────────────────────────────────────────
class Toast(ctk.CTkToplevel):
    def __init__(self, parent, message, kind="success", duration=3500):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        colors = {
            "success": (SUCCESS,     "#0d2b1a"),
            "error":   (DANGER,      "#2b0d0d"),
            "info":    (ACCENT_GLOW, BG_CARD),
            "warning": (WARNING,     "#2b1f0d"),
        }
        bc, bg = colors.get(kind, colors["info"])
        frame = ctk.CTkFrame(self, fg_color=bg, corner_radius=10,
                              border_width=1, border_color=bc)
        frame.pack(padx=2, pady=2)
        icons = {"success":"✅","error":"❌","info":"✦","warning":"⚠️"}
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(padx=16, pady=10)
        ctk.CTkLabel(inner, text=icons.get(kind,"✦"),
                     font=ctk.CTkFont(size=15)).pack(side="left", padx=(0,8))
        ctk.CTkLabel(inner, text=message, font=ctk.CTkFont(size=11),
                     text_color=TEXT_PRIMARY, wraplength=260).pack(side="left")
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{sw-w-20}+{sh-h-60}")
        self._fade(0.0, 1.0, 20, lambda: self.after(duration, lambda: self._fade(1.0, 0.0, 30, self._close)))

    def _fade(self, start, end, step_ms, on_done=None):
        delta = 0.08 if end > start else -0.07
        alpha = max(0.0, min(1.0, start + delta))
        if (end > start and alpha >= end) or (end < start and alpha <= end):
            self.attributes("-alpha", end)
            if on_done: on_done()
        else:
            self.attributes("-alpha", alpha)
            self.after(step_ms, lambda: self._fade(alpha, end, step_ms, on_done))

    def _close(self):
        try: self.destroy()
        except: pass

def show_toast(parent, msg, kind="success", duration=3500):
    try: Toast(parent, msg, kind, duration)
    except: pass


# ── VLC Player ────────────────────────────────────────────────────────────────
class VLCPlayer:
    def __init__(self, widget):
        self.widget = widget
        self.instance = None
        self.player = None
        self._ok = False
        if VLC_AVAILABLE:
            try:
                self.instance = vlc.Instance("--no-xlib", "--quiet")
                self.player = self.instance.media_player_new()
                self._ok = True
            except: pass

    def load(self, path):
        if not self._ok: return False
        try:
            self.player.set_media(self.instance.media_new(path))
            self.player.set_hwnd(self.widget.winfo_id())
            return True
        except: return False

    def set_aspect_ratio(self, ratio_key: str):
        """Fuerza relación de aspecto en VLC para que el video no desborde el marco."""
        if not self._ok or not self.player:
            return
        try:
            # Formato tipo "16:9", "9:16", "4:3", "1:1"
            self.player.video_set_aspect_ratio(ratio_key)
        except Exception:
            pass

    def play(self):
        if self._ok and self.player: self.player.play()
    def pause(self):
        if self._ok and self.player: self.player.pause()
    def stop(self):
        if self._ok and self.player: self.player.stop()
    def is_playing(self):
        return self.player.is_playing() if self._ok and self.player else False
    def get_time(self):
        if self._ok and self.player:
            t = self.player.get_time()
            return t / 1000.0 if t >= 0 else 0.0
        return 0.0
    def set_time(self, sec):
        if self._ok and self.player: self.player.set_time(int(sec * 1000))
    def get_duration(self):
        if self._ok and self.player:
            d = self.player.get_length()
            return d / 1000.0 if d > 0 else 0.0
        return 0.0
    def toggle_mute(self):
        if self._ok and self.player:
            m = self.player.audio_get_mute()
            self.player.audio_set_mute(not m)
            return not m
        return False
    def release(self):
        if self.player: self.player.stop(); self.player.release()
        if self.instance: self.instance.release()


# ── App ───────────────────────────────────────────────────────────────────────
class SlicerApp(ctk.CTk):
    def __init__(self, dep_results):
        super().__init__()
        self.dep_results   = dep_results
        self.ffmpeg_path   = find_ffmpeg()
        self.ffprobe_path  = find_ffprobe()
        self.anton_path    = check_anton_font()
        self.engine        = ExportEngine()
        self.settings      = load_settings()
        self.history       = load_history()
        self.presets       = load_presets()

        self.video_path    = None
        self.video_info    = {}
        self.cuts_entries  = []
        self.is_exporting  = False
        self.log_entries   = []
        self.export_results= []
        self.export_start_time = None
        self._player_time  = 0.0
        self._vlc          = None
        self._player_job   = None
        self._text_color   = TEXT_DEFAULTS["color"]
        self._outline_color= TEXT_DEFAULTS["outline_color"]
        self._overlay_bg   = None
        self._overlay_panel= None
        self.speed_var     = ctk.StringVar(value=self.settings.get("speed_preset", PRESET_DEFAULT))

        self._build_window()
        self._build_ui()
        self._apply_shortcuts()
        self._restore_geometry()

    # ── Ventana ───────────────────────────────────────────────────────────────
    def _build_window(self):
        self.title(APP_NAME)
        self.configure(fg_color=BG_ROOT)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.minsize(1200, 720)
        try:
            ico = Path(__file__).parent.parent / "assets" / "icon.ico"
            if ico.exists(): self.iconbitmap(str(ico))
        except: pass

    def _restore_geometry(self):
        try: self.geometry(self.settings.get("window_geometry", "1380x820+60+40"))
        except: self.geometry("1380x820+60+40")

    def _on_close(self):
        if self.is_exporting:
            if not messagebox.askyesno("Exportación en curso",
                "¿Cerrar y cancelar?", icon="warning"): return
            self.engine.cancel()
        if self._vlc: self._vlc.release()
        if self._player_job: self.after_cancel(self._player_job)
        self.settings["window_geometry"] = self.geometry()
        save_settings(self.settings)
        self.destroy()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_titlebar()
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=10, pady=(4,10))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=4)
        content.columnconfigure(2, weight=3)
        content.rowconfigure(0, weight=1)
        self._build_left(content)
        self._build_center(content)
        self._build_right(content)

    def _build_titlebar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=52)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkFrame(bar, fg_color=ACCENT, height=2, corner_radius=0).pack(fill="x", side="top")
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16)
        # Logo
        logo = ctk.CTkFrame(inner, fg_color="transparent")
        logo.pack(side="left", pady=8)
        ctk.CTkLabel(logo, text="S",
                     font=ctk.CTkFont(size=20, weight="bold", family="Georgia"),
                     text_color=ACCENT_GLOW).pack(side="left", padx=(0,8))
        ctk.CTkLabel(logo, text=APP_NAME,
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkLabel(logo, text=f"  v{APP_VERSION}",
                     font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(side="left", pady=(4,0))
        # Botones derecha
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(side="right", pady=10)
        ctk.CTkButton(btn_frame, text="▶  Exportar", width=110, height=30,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#fff",
                      font=ctk.CTkFont(size=11, weight="bold"),
                      command=self._show_export_panel).pack(side="left", padx=(0,6))
        ctk.CTkButton(btn_frame, text="⚙", width=34, height=30,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT_SEC, hover_color=BG_ELEVATED,
                      font=ctk.CTkFont(size=13),
                      command=self._show_settings_panel).pack(side="left", padx=(0,4))
        ctk.CTkButton(btn_frame, text="S", width=34, height=30,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT_SEC, hover_color=BG_ELEVATED,
                      font=ctk.CTkFont(size=13, weight="bold", family="Georgia"),
                      command=self._show_about_panel).pack(side="left")

    # ── Panel izquierdo ───────────────────────────────────────────────────────
    def _build_left(self, parent):
        panel = self._panel(parent, col=0)

        self._sec(panel, "ARCHIVO DE VIDEO")
        drop = ctk.CTkFrame(panel, fg_color=BG_INPUT, corner_radius=8,
                            border_width=1, border_color=BORDER_ACCENT, height=80)
        drop.pack(fill="x", padx=12, pady=(0,8))
        drop.pack_propagate(False)
        self.drop_label = ctk.CTkLabel(drop, text="Arrastra el video aquí",
                                        font=ctk.CTkFont(size=12), text_color=TEXT_MUTED)
        self.drop_label.pack(expand=True)
        drop.bind("<Button-1>", lambda e: self._browse_video())
        self.drop_label.bind("<Button-1>", lambda e: self._browse_video())

        ctk.CTkButton(panel, text="Seleccionar archivo",
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#fff",
                      height=36, font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._browse_video).pack(fill="x", padx=12, pady=(0,10))

        self._sec(panel, "MINI REPRODUCTOR")
        # Selector de proporción
        ratio_row = ctk.CTkFrame(panel, fg_color="transparent")
        ratio_row.pack(fill="x", padx=12, pady=(0,4))
        ctk.CTkLabel(ratio_row, text="Proporción:",
                     font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(side="left", padx=(0,6))
        self._ratio_var = ctk.StringVar(value=self.settings.get("player_ratio", PLAYER_RATIO_DEFAULT))
        for ratio in PLAYER_RATIOS:
            ctk.CTkRadioButton(ratio_row, text=ratio,
                               variable=self._ratio_var, value=ratio,
                               radiobutton_width=11, radiobutton_height=11,
                               fg_color=ACCENT, hover_color=ACCENT_HOVER,
                               font=ctk.CTkFont(size=10), text_color=TEXT_SEC,
                               command=self._on_ratio_change).pack(side="left", padx=4)

        self.vlc_frame = ctk.CTkFrame(panel, fg_color="#000000", corner_radius=8, height=200)
        self.vlc_frame.pack(fill="x", padx=12, pady=(0,4))
        self.vlc_frame.pack_propagate(False)
        self.vlc_placeholder = ctk.CTkLabel(self.vlc_frame, text="Sin video",
                                             fg_color="transparent",
                                             text_color=TEXT_MUTED,
                                             font=ctk.CTkFont(size=12))
        self.vlc_placeholder.place(relx=0.5, rely=0.5, anchor="center")
        self._apply_ratio()
        self.vlc_frame.bind("<Configure>", self._on_vlc_frame_configure)

        self.player_var = ctk.DoubleVar(value=0)
        self.player_slider = ctk.CTkSlider(panel, from_=0, to=100,
                                            variable=self.player_var,
                                            progress_color=ACCENT,
                                            button_color=ACCENT_GLOW,
                                            button_hover_color=ACCENT,
                                            height=12, command=self._on_seek)
        self.player_slider.pack(fill="x", padx=12, pady=(0,4))

        # Grid: evita que el área de video (proporciones altas) empuje o solape los controles
        ctrl = ctk.CTkFrame(panel, fg_color="transparent")
        ctrl.pack(fill="x", padx=12, pady=(0,8))
        ctrl.grid_columnconfigure(1, weight=1)
        left_btns = ctk.CTkFrame(ctrl, fg_color="transparent")
        left_btns.grid(row=0, column=0, sticky="w")
        self.play_btn = ctk.CTkButton(left_btns, text="▶", width=36, height=32,
                                       fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                       text_color="#fff", font=ctk.CTkFont(size=13),
                                       command=self._toggle_play)
        self.play_btn.pack(side="left", padx=(0,4))
        self.mute_btn = ctk.CTkButton(left_btns, text="🔊", width=32, height=32,
                                       fg_color=BG_ELEVATED, hover_color=BG_CARD,
                                       font=ctk.CTkFont(size=12),
                                       command=self._toggle_mute)
        self.mute_btn.pack(side="left")
        self.time_lbl = ctk.CTkLabel(ctrl, text="0:00.00",
                                      font=ctk.CTkFont(size=12, family="Courier"),
                                      text_color=ACCENT_GLOW)
        self.time_lbl.grid(row=0, column=1, sticky="w", padx=(8, 8))
        ctk.CTkButton(ctrl, text="✂  Usar tiempo", height=32,
                      fg_color=BG_ELEVATED, border_width=1, border_color=BORDER_ACCENT,
                      text_color=ACCENT_GLOW, hover_color=BG_CARD,
                      font=ctk.CTkFont(size=10),
                      command=self._use_current_time).grid(row=0, column=2, sticky="e")

        self.after(200, self._init_vlc)

        self._sec(panel, "INFORMACIÓN DEL VIDEO")
        info_card = ctk.CTkFrame(panel, fg_color=BG_ELEVATED, corner_radius=8,
                                  border_width=1, border_color=BORDER)
        info_card.pack(fill="x", padx=12, pady=(0,8))
        self.info_labels = {}
        for i, (lbl, key) in enumerate([
            ("Archivo","name"), ("Duración","duration"),
            ("Resolución","resolution"), ("FPS","fps"),
            ("Codec video","codec"), ("Codec audio","audio"),
        ]):
            bg = BG_ELEVATED if i % 2 == 0 else BG_CARD
            row = ctk.CTkFrame(info_card, fg_color=bg, corner_radius=0)
            row.pack(fill="x")
            ctk.CTkLabel(row, text=lbl, width=85, anchor="w",
                         font=ctk.CTkFont(size=11), text_color=TEXT_MUTED
                         ).pack(side="left", padx=(10,0), pady=4)
            val = ctk.CTkLabel(row, text="—", anchor="w",
                               font=ctk.CTkFont(size=11), text_color=TEXT_PRIMARY)
            val.pack(side="left", padx=4)
            self.info_labels[key] = val

    # ── Panel central ─────────────────────────────────────────────────────────
    def _build_center(self, parent):
        panel = self._panel(parent, col=1, padx=(6,6))
        scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent",
                                         scrollbar_button_color=BORDER)
        scroll.pack(fill="both", expand=True, padx=1, pady=1)

        self._sec(scroll, "DURACIÓN DE LA INTRO")
        intro_row = ctk.CTkFrame(scroll, fg_color="transparent")
        intro_row.pack(fill="x", padx=12, pady=(0,10))
        self.intro_entry = self._entry(intro_row, "Ej: 0:15.30", width=160)
        self.intro_entry.pack(side="left", padx=(0,8))
        self._help(intro_row, "Tiempo donde termina la intro.\nFormato: MM:SS.cc\nEj: 0:15.30")

        self._sec(scroll, "TIEMPOS DE CORTE")
        self.cuts_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.cuts_frame.pack(fill="x", padx=12)
        self._add_cut()

        ctk.CTkButton(scroll, text="＋  Agregar corte",
                      fg_color="transparent", border_width=1, border_color=BORDER_ACCENT,
                      text_color=ACCENT_GLOW, hover_color=BG_ELEVATED,
                      height=34, font=ctk.CTkFont(size=12),
                      command=self._add_cut).pack(fill="x", padx=12, pady=(4,10))

        self._sec(scroll, "VELOCIDAD DE EXPORTACIÓN")
        speed_card = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                                   border_width=1, border_color=BORDER)
        speed_card.pack(fill="x", padx=12, pady=(0,10))
        self._speed_name_labels = {}
        for preset in PRESETS_SPEED:
            row = ctk.CTkFrame(speed_card, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)
            ctk.CTkRadioButton(row, text="", variable=self.speed_var, value=preset,
                               radiobutton_width=14, radiobutton_height=14,
                               fg_color=ACCENT, hover_color=ACCENT_HOVER,
                               width=20).pack(side="left")
            name_lbl = ctk.CTkLabel(row, text=preset,
                                    font=ctk.CTkFont(size=11, weight="bold"),
                                    text_color=TEXT_PRIMARY,
                                    width=75, anchor="w")
            name_lbl.pack(side="left", padx=(2,0))
            self._speed_name_labels[preset] = name_lbl
            ctk.CTkLabel(row, text=PRESETS_SPEED_DESC[preset],
                         font=ctk.CTkFont(size=10), text_color=TEXT_MUTED,
                         anchor="w").pack(side="left")
        self.speed_var.trace_add("write", lambda *_: self._refresh_speed_label_colors())
        self._refresh_speed_label_colors()

        self._sec(scroll, "LÍNEA DE TIEMPO")
        self.timeline_canvas = ctk.CTkCanvas(scroll, height=52, bg=BG_INPUT,
                                              highlightthickness=1,
                                              highlightbackground=BORDER)
        self.timeline_canvas.pack(fill="x", padx=12, pady=(0,10))
        self.timeline_canvas.bind("<Motion>", lambda e: self._draw_timeline(
            self.video_info.get("duration",0), self._get_cuts()))
        self.timeline_canvas.bind("<Leave>", lambda e: self._update_timeline())

        self._sec(scroll, "SEGMENTOS ESTIMADOS")
        self.segments_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.segments_frame.pack(fill="x", padx=12, pady=(0,10))

    # ── Panel derecho ─────────────────────────────────────────────────────────
    def _build_right(self, parent):
        panel = self._panel(parent, col=2)
        scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent",
                                         scrollbar_button_color=BORDER)
        scroll.pack(fill="both", expand=True, padx=1, pady=1)

        self._sec(scroll, "PROGRESO DE EXPORTACIÓN")
        prog_card = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                                  border_width=1, border_color=BORDER)
        prog_card.pack(fill="x", padx=12, pady=(0,10))
        self.progress_bar = ctk.CTkProgressBar(prog_card, height=6,
                                                progress_color=ACCENT, fg_color=BG_INPUT)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=10, pady=(10,4))
        self.progress_lbl = ctk.CTkLabel(prog_card, text="En espera",
                                          font=ctk.CTkFont(size=11),
                                          text_color=TEXT_SEC, anchor="w")
        self.progress_lbl.pack(fill="x", padx=10)
        stats = ctk.CTkFrame(prog_card, fg_color="transparent")
        stats.pack(fill="x", padx=10, pady=(2,8))
        self.speed_lbl = ctk.CTkLabel(stats, text="",
                                       font=ctk.CTkFont(size=10, family="Courier"),
                                       text_color=TEXT_MUTED, anchor="w")
        self.speed_lbl.pack(side="left")
        self.eta_lbl = ctk.CTkLabel(stats, text="",
                                     font=ctk.CTkFont(size=10),
                                     text_color=TEXT_MUTED, anchor="e")
        self.eta_lbl.pack(side="right")

        self._sec(scroll, "ESTILO DEL TEXTO PARTE X")
        preset_row = ctk.CTkFrame(scroll, fg_color="transparent")
        preset_row.pack(fill="x", padx=12, pady=(0,6))
        self.preset_var = ctk.StringVar(value=self.settings.get("text_preset_active","Por defecto"))
        self.preset_menu = ctk.CTkOptionMenu(preset_row, variable=self.preset_var,
                                              values=list(self.presets.keys()),
                                              command=self._load_preset,
                                              fg_color=BG_ELEVATED, button_color=ACCENT,
                                              button_hover_color=ACCENT_HOVER,
                                              dropdown_fg_color=BG_CARD,
                                              text_color=TEXT_PRIMARY,
                                              font=ctk.CTkFont(size=11))
        self.preset_menu.pack(side="left", fill="x", expand=True, padx=(0,4))
        ctk.CTkButton(preset_row, text="💾", width=32, height=32,
                      fg_color=BG_ELEVATED, border_width=1, border_color=BORDER,
                      hover_color=BG_CARD, command=self._save_preset).pack(side="left", padx=2)
        ctk.CTkButton(preset_row, text="🗑", width=32, height=32,
                      fg_color=BG_ELEVATED, border_width=1, border_color=BORDER,
                      hover_color=BG_CARD, command=self._delete_preset).pack(side="left", padx=2)

        self.text_controls = {}
        for key, label, mn, mx, default in [
            ("font_size","Tamaño fuente",20,250,80),
            ("outline_width","Grosor contorno",0,30,6),
            ("position_y_pct","Posición vertical %",5,95,15),
            ("opacity_pct","Opacidad %",10,100,100),
        ]:
            lbl_row = ctk.CTkFrame(scroll, fg_color="transparent")
            lbl_row.pack(fill="x", padx=12, pady=(6,0))
            ctk.CTkLabel(lbl_row, text=label, font=ctk.CTkFont(size=11),
                         text_color=TEXT_SEC, anchor="w").pack(side="left")
            vl = ctk.CTkLabel(lbl_row, text=str(default),
                               font=ctk.CTkFont(size=11, family="Courier"),
                               text_color=ACCENT_GLOW, width=36, anchor="e")
            vl.pack(side="right")
            sl = ctk.CTkSlider(scroll, from_=mn, to=mx, number_of_steps=mx-mn,
                                progress_color=ACCENT, button_color=ACCENT_GLOW,
                                button_hover_color=ACCENT,
                                fg_color=BG_INPUT, height=12)
            sl.set(default)
            sl.pack(fill="x", padx=12, pady=(2,0))
            sl.configure(command=lambda v, k=key, vl=vl: self._on_slider(k, v, vl))
            self.text_controls[key] = {"slider": sl, "label": vl}

        color_row = ctk.CTkFrame(scroll, fg_color="transparent")
        color_row.pack(fill="x", padx=12, pady=8)
        self.text_color_btn = ctk.CTkButton(color_row, text="● Color texto",
                                             width=120, height=32,
                                             fg_color=BG_ELEVATED, border_width=1,
                                             border_color=BORDER,
                                             text_color=TEXT_DEFAULTS["color"],
                                             hover_color=BG_CARD, font=ctk.CTkFont(size=11),
                                             command=lambda: self._pick_color("color"))
        self.text_color_btn.pack(side="left", padx=(0,6))
        self.outline_color_btn = ctk.CTkButton(color_row, text="● Contorno",
                                                width=100, height=32,
                                                fg_color=BG_ELEVATED, border_width=1,
                                                border_color=BORDER,
                                                text_color=TEXT_DEFAULTS["outline_color"],
                                                hover_color=BG_CARD, font=ctk.CTkFont(size=11),
                                                command=lambda: self._pick_color("outline_color"))
        self.outline_color_btn.pack(side="left")

        self._sec(scroll, "VISTA PREVIA DEL TEXTO")
        self.text_preview = ctk.CTkLabel(scroll, text="", fg_color=BG_INPUT,
                                          corner_radius=8, height=90)
        self.text_preview.pack(fill="x", padx=12, pady=(0,10))
        self._update_preview()

        self._sec(scroll, "REGISTRO DE ACTIVIDAD")
        self.log_box = ctk.CTkTextbox(scroll, height=160,
                                       font=ctk.CTkFont(size=10, family="Courier"),
                                       fg_color=BG_INPUT, border_width=1,
                                       border_color=BORDER, text_color=TEXT_SEC,
                                       scrollbar_button_color=BORDER, state="disabled")
        self.log_box.pack(fill="x", padx=12, pady=(0,8))

    # ── Helpers UI ────────────────────────────────────────────────────────────
    def _panel(self, parent, col, padx=(0,0)):
        pl = 6 if col > 0 else 0
        pr = 6 if col < 2 else 0
        f = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=10,
                          border_width=1, border_color=BORDER)
        f.grid(row=0, column=col, sticky="nsew", padx=(pl,pr))
        return f

    def _sec(self, parent, text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(10,4))
        ctk.CTkLabel(row, text=text, font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=TEXT_MUTED).pack(side="left")
        ctk.CTkFrame(row, fg_color=BORDER, height=1, corner_radius=0
                     ).pack(side="left", fill="x", expand=True, padx=(8,0), pady=6)

    def _entry(self, parent, placeholder="", width=180):
        return ctk.CTkEntry(parent, placeholder_text=placeholder, width=width,
                            fg_color=BG_INPUT, border_color=BORDER_ACCENT,
                            border_width=1, text_color=ACCENT_GLOW,
                            placeholder_text_color=TEXT_MUTED,
                            font=ctk.CTkFont(size=12, family="Courier"))

    def _help(self, parent, text):
        ctk.CTkButton(parent, text="?", width=24, height=24,
                      fg_color=BG_ELEVATED, border_width=1, border_color=BORDER,
                      text_color=TEXT_MUTED, hover_color=BG_CARD,
                      font=ctk.CTkFont(size=10),
                      command=lambda: messagebox.showinfo("Ayuda", text)).pack(side="left")

    def _toast(self, msg, kind="success"):
        show_toast(self, msg, kind)

    # ── Paneles flotantes internos ────────────────────────────────────────────
    def _show_overlay(self, build_fn, width=460):
        self._close_overlay()
        # Fondo oscuro usando tk nativo para capturar clicks correctamente
        import tkinter as tk
        self._overlay_bg = tk.Frame(self, bg="#000000")
        self._overlay_bg.place(x=0, y=0, relwidth=1, relheight=1)
        self._overlay_bg.configure(cursor="arrow")
        self._overlay_bg.bind("<Button-1>", lambda e: self._close_overlay())
        # Reducir opacidad del fondo visualmente con un label negro semi-transparente
        # Panel flotante centrado
        self._overlay_panel = ctk.CTkFrame(self._overlay_bg,
                                            fg_color=BG_PANEL, corner_radius=12,
                                            border_width=1, border_color=BORDER_ACCENT,
                                            width=width)
        self.update_idletasks()
        self._overlay_panel.place(relx=0.5, rely=0.5, anchor="center")
        # Evitar que clicks en el panel cierren el overlay
        self._overlay_panel.bind("<Button-1>", lambda e: "break")
        build_fn(self._overlay_panel)
        self._overlay_panel.lift()
        self._overlay_bg.lift()
        self._overlay_panel.lift()

    def _bind_panel_children(self, widget):
        """Evita que clicks en cualquier hijo del panel cierren el overlay."""
        try:
            widget.bind("<Button-1>", lambda e: "break")
            for child in widget.winfo_children():
                self._bind_panel_children(child)
        except: pass

    def _close_overlay(self):
        try:
            if self._overlay_bg:
                self._overlay_bg.destroy()
                self._overlay_bg = None
                self._overlay_panel = None
        except: pass

    def _overlay_header(self, parent, title, width=460):
        hdr = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=0, height=46, width=width)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkFrame(hdr, fg_color=ACCENT, height=2, corner_radius=0).pack(fill="x", side="top")
        inner = ctk.CTkFrame(hdr, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14)
        ctk.CTkLabel(inner, text=title,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(side="left", pady=10)
        ctk.CTkButton(inner, text="✕", width=28, height=28,
                      fg_color="transparent", hover_color=BG_ELEVATED,
                      text_color=TEXT_MUTED, font=ctk.CTkFont(size=12),
                      command=self._close_overlay).pack(side="right", pady=8)

    def _overlay_sec(self, parent, text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(6,3))
        ctk.CTkLabel(row, text=text, font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=TEXT_MUTED).pack(side="left")
        ctk.CTkFrame(row, fg_color=BORDER, height=1, corner_radius=0
                     ).pack(side="left", fill="x", expand=True, padx=(8,0), pady=5)

    # ── Panel Exportar ────────────────────────────────────────────────────────
    def _show_export_panel(self):
        def build(panel):
            self._overlay_header(panel, "▶  Exportar video", width=440)
            body = ctk.CTkFrame(panel, fg_color="transparent")
            body.pack(fill="x", padx=18, pady=12)

            # Estado actual
            self._overlay_sec(body, "ESTADO ACTUAL")
            sc = ctk.CTkFrame(body, fg_color=BG_ELEVATED, corner_radius=8,
                               border_width=1, border_color=BORDER)
            sc.pack(fill="x", pady=(0,10))
            video_ok  = bool(self.video_path)
            intro_sec = parse_time(self.intro_entry.get()) if hasattr(self,"intro_entry") else None
            cuts      = self._get_cuts()
            for ok, lbl, val in [
                (video_ok,             "Video",  os.path.basename(self.video_path)[:26] if self.video_path else "Sin video"),
                (intro_sec is not None,"Intro",  format_duration(intro_sec) if intro_sec else "No configurada"),
                (bool(cuts),           "Cortes", f"{len(cuts)} corte(s) — {len(cuts)+1} partes" if cuts else "Sin cortes"),
            ]:
                r = ctk.CTkFrame(sc, fg_color="transparent")
                r.pack(fill="x", padx=10, pady=4)
                ctk.CTkLabel(r, text="✅" if ok else "❌",
                             font=ctk.CTkFont(size=12),
                             text_color=SUCCESS if ok else DANGER,
                             width=24).pack(side="left")
                ctk.CTkLabel(r, text=lbl, font=ctk.CTkFont(size=11),
                             text_color=TEXT_SEC, width=55, anchor="w").pack(side="left")
                ctk.CTkLabel(r, text=val, font=ctk.CTkFont(size=10),
                             text_color=TEXT_MUTED).pack(side="left", padx=4)

            # Config de exportación (solo lectura, no editable)
            self._overlay_sec(body, "CONFIGURACIÓN DE EXPORTACIÓN")
            cfg = ctk.CTkFrame(body, fg_color=BG_ELEVATED, corner_radius=8,
                               border_width=1, border_color=BORDER)
            cfg.pack(fill="x", pady=(0,14))
            for i, (lbl, val, icon) in enumerate([
                ("Codec",        "HEVC  (H.265)",  "🎬"),
                ("Resolución",   "1080p",          "📐"),
                ("Cuadros/seg",  "30 fps",         "🎞"),
                ("Tasa de bits", "2000 kbps",      "📊"),
                ("Audio",        "AAC  192k",      "🔊"),
                ("Formato",      ".mp4",           "📁"),
            ]):
                bg = BG_ELEVATED if i % 2 == 0 else BG_CARD
                r = ctk.CTkFrame(cfg, fg_color=bg, corner_radius=0)
                r.pack(fill="x")
                ctk.CTkLabel(r, text=icon, font=ctk.CTkFont(size=12),
                             width=28).pack(side="left", padx=(8,0), pady=5)
                ctk.CTkLabel(r, text=lbl, width=90, anchor="w",
                             font=ctk.CTkFont(size=11), text_color=TEXT_MUTED
                             ).pack(side="left", padx=(4,0))
                ctk.CTkLabel(r, text=val, anchor="w",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=TEXT_PRIMARY).pack(side="left", padx=4)

            # Botones
            all_ok = video_ok and intro_sec is not None and bool(cuts)
            ctk.CTkButton(body,
                          text="✔  CONFIRMAR Y EXPORTAR" if all_ok else "⚠  Completa la configuración primero",
                          fg_color=ACCENT if all_ok else BG_ELEVATED,
                          hover_color=ACCENT_HOVER if all_ok else BG_ELEVATED,
                          text_color="#fff" if all_ok else TEXT_MUTED,
                          height=44,
                          font=ctk.CTkFont(size=13, weight="bold"),
                          state="normal" if all_ok else "disabled",
                          command=lambda: [self._close_overlay(), self._start_export()]
                          ).pack(fill="x", pady=(0,6))
            ctk.CTkButton(body, text="Cancelar", height=32,
                          fg_color="transparent", border_width=1, border_color=BORDER,
                          text_color=TEXT_MUTED, hover_color=BG_ELEVATED,
                          font=ctk.CTkFont(size=11),
                          command=self._close_overlay).pack(fill="x")
        self._show_overlay(build, width=440)

    # ── Panel Configuración ───────────────────────────────────────────────────
    def _show_settings_panel(self):
        def build(panel):
            self._overlay_header(panel, "⚙  Configuración", width=500)
            scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent",
                                             scrollbar_button_color=BORDER,
                                             height=420, width=500)
            scroll.pack(fill="x", padx=18, pady=10)

            def sec(t): self._overlay_sec(scroll, t)

            sec("CARPETA DE SALIDA")
            row = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                               border_width=1, border_color=BORDER)
            row.pack(fill="x", pady=(0,8))
            self._out_dir_var = ctk.StringVar(value=self.settings.get("output_dir", r"C:\Videos_Trabajo"))
            ctk.CTkEntry(row, textvariable=self._out_dir_var,
                         fg_color=BG_INPUT, border_color=BORDER,
                         text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=11)
                         ).pack(side="left", fill="x", expand=True, padx=10, pady=6)
            ctk.CTkButton(row, text="...", width=36, height=26,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#fff",
                          command=lambda: self._browse_folder(self._out_dir_var)
                          ).pack(side="right", padx=6)

            sec("CARPETA DE LOGS")
            row2 = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                                border_width=1, border_color=BORDER)
            row2.pack(fill="x", pady=(0,8))
            self._log_dir_var = ctk.StringVar(value=self.settings.get("logs_dir", r"C:\Videos_Trabajo"))
            ctk.CTkEntry(row2, textvariable=self._log_dir_var,
                         fg_color=BG_INPUT, border_color=BORDER,
                         text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=11)
                         ).pack(side="left", fill="x", expand=True, padx=10, pady=6)
            ctk.CTkButton(row2, text="...", width=36, height=26,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#fff",
                          command=lambda: self._browse_folder(self._log_dir_var)
                          ).pack(side="right", padx=6)

            sec("LÍMITES DE ADVERTENCIA")
            lc = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                              border_width=1, border_color=BORDER)
            lc.pack(fill="x", pady=(0,8))
            li = ctk.CTkFrame(lc, fg_color="transparent")
            li.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(li, text="Duración máx (min):", font=ctk.CTkFont(size=11),
                         text_color=TEXT_SEC).pack(side="left")
            self._warn_dur_var = ctk.StringVar(
                value=str(int(self.settings.get("warn_max_duration", 600) // 60)))
            ctk.CTkEntry(li, textvariable=self._warn_dur_var, width=50,
                         fg_color=BG_INPUT, border_color=BORDER,
                         text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=11)
                         ).pack(side="left", padx=6)
            ctk.CTkLabel(li, text="Tamaño máx (MB):", font=ctk.CTkFont(size=11),
                         text_color=TEXT_SEC).pack(side="left", padx=(12,0))
            self._warn_size_var = ctk.StringVar(
                value=str(self.settings.get("warn_max_size_mb", 500)))
            ctk.CTkEntry(li, textvariable=self._warn_size_var, width=50,
                         fg_color=BG_INPUT, border_color=BORDER,
                         text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=11)
                         ).pack(side="left", padx=6)

            sec("CACHÉ")
            cc = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                              border_width=1, border_color=BORDER)
            cc.pack(fill="x", pady=(0,8))
            ci = ctk.CTkFrame(cc, fg_color="transparent")
            ci.pack(fill="x", padx=12, pady=8)
            self._cache_lbl = ctk.CTkLabel(ci,
                                            text=f"Ocupado: {get_cache_size_mb():.1f} MB",
                                            font=ctk.CTkFont(size=11), text_color=TEXT_SEC)
            self._cache_lbl.pack(side="left")
            ctk.CTkButton(ci, text="Borrar caché", width=100, height=26,
                          fg_color="transparent", border_width=1, border_color="#5a2a2a",
                          text_color=DANGER, hover_color="#2b0d0d",
                          font=ctk.CTkFont(size=10),
                          command=self._do_clear_cache).pack(side="right")

            sec("DEPENDENCIAS")
            dc = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                              border_width=1, border_color=BORDER)
            dc.pack(fill="x", pady=(0,8))
            ffmpeg = find_ffmpeg()
            ffmpeg_ver = "No encontrado"
            if ffmpeg:
                try:
                    r = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
                    line = r.stdout.split("\n")[0]
                    ffmpeg_ver = line.split("version")[1].strip().split(" ")[0] if "version" in line else "Detectado"
                except: ffmpeg_ver = "Detectado"
            for lbl, val, ok in [
                ("FFmpeg", ffmpeg_ver, bool(ffmpeg)),
                ("Anton", "Instalada" if self.anton_path else "No encontrada", bool(self.anton_path)),
                ("python-vlc", "Disponible" if VLC_AVAILABLE else "No instalado", VLC_AVAILABLE),
            ]:
                dr = ctk.CTkFrame(dc, fg_color="transparent")
                dr.pack(fill="x", padx=10, pady=3)
                ctk.CTkLabel(dr, text="✅" if ok else "❌",
                             font=ctk.CTkFont(size=11),
                             text_color=SUCCESS if ok else DANGER, width=24).pack(side="left")
                ctk.CTkLabel(dr, text=lbl, font=ctk.CTkFont(size=11),
                             text_color=TEXT_SEC, width=80, anchor="w").pack(side="left")
                ctk.CTkLabel(dr, text=val, font=ctk.CTkFont(size=10),
                             text_color=TEXT_MUTED).pack(side="left", padx=4)

            sec("ZONA DE PELIGRO")
            ctk.CTkButton(scroll, text="⚠  Restablecer configuración de fábrica",
                          height=32, fg_color="transparent",
                          border_width=1, border_color="#5a2a2a",
                          text_color=DANGER, hover_color="#2b0d0d",
                          font=ctk.CTkFont(size=11),
                          command=self._factory_reset).pack(fill="x", pady=(0,8))

            ctk.CTkButton(panel, text="Guardar configuración",
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#fff",
                          height=36, font=ctk.CTkFont(size=12, weight="bold"),
                          command=self._save_settings_inline
                          ).pack(fill="x", padx=18, pady=(0,14))
        self._show_overlay(build, width=500)

    def _browse_folder(self, var):
        path = filedialog.askdirectory(title="Seleccionar carpeta")
        if path: var.set(path)

    def _do_clear_cache(self):
        if messagebox.askyesno("Borrar caché", "¿Borrar archivos temporales?", icon="warning"):
            n = clear_cache()
            if hasattr(self, "_cache_lbl"):
                self._cache_lbl.configure(text="Ocupado: 0.0 MB")
            self._toast(f"Caché borrada ({n} carpetas)", "success")

    def _factory_reset(self):
        if messagebox.askyesno("Restablecer", "¿Restablecer configuración de fábrica?", icon="warning"):
            try: (Path.home() / ".slicer_by_claude" / "settings.json").unlink()
            except: pass
            self.settings = load_settings()
            self._close_overlay()
            self._toast("Configuración restablecida", "success")

    def _save_settings_inline(self):
        try:
            dur_min = int(self._warn_dur_var.get())
            size_mb = int(self._warn_size_var.get())
        except:
            self._toast("Valores de límite inválidos", "error"); return
        self.settings["output_dir"]          = self._out_dir_var.get()
        self.settings["logs_dir"]            = self._log_dir_var.get()
        self.settings["warn_max_duration"]   = dur_min * 60
        self.settings["warn_max_size_mb"]    = size_mb
        save_settings(self.settings)
        self._close_overlay()
        self._toast("Configuración guardada", "success")

    # ── Panel Acerca de ───────────────────────────────────────────────────────
    def _show_about_panel(self):
        def build(panel):
            self._overlay_header(panel, "Acerca de", width=360)
            body = ctk.CTkFrame(panel, fg_color="transparent", width=360)
            body.pack(padx=20, pady=16)
            ctk.CTkLabel(body, text="S",
                         font=ctk.CTkFont(size=42, weight="bold", family="Georgia"),
                         text_color=ACCENT_GLOW).pack()
            ctk.CTkLabel(body, text=APP_NAME,
                         font=ctk.CTkFont(size=16, weight="bold"),
                         text_color=TEXT_PRIMARY).pack()
            ctk.CTkLabel(body, text=f"Versión {APP_VERSION}",
                         font=ctk.CTkFont(size=10), text_color=ACCENT).pack(pady=2)
            ctk.CTkLabel(body,
                         text="Herramienta de corte para historias de Reddit.\nDiseñado y construido con Claude.",
                         font=ctk.CTkFont(size=11), text_color=TEXT_SEC,
                         justify="center").pack(pady=10)
            ctk.CTkButton(body, text="Cerrar",
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#fff",
                          command=self._close_overlay).pack(pady=4)
        self._show_overlay(build, width=360)

    # ── Panel Resumen exportación ─────────────────────────────────────────────
    def _show_summary_panel(self, out_folder, time_str=""):
        def build(panel):
            self._overlay_header(panel, "✅  Exportación completada", width=460)
            body = ctk.CTkFrame(panel, fg_color="transparent")
            body.pack(fill="x", padx=18, pady=8)
            if time_str:
                ctk.CTkLabel(body, text=f"⏱  Tiempo total: {time_str}",
                             font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(pady=(0,8))
            scroll = ctk.CTkScrollableFrame(body, fg_color="transparent",
                                             scrollbar_button_color=BORDER, height=180)
            scroll.pack(fill="x", pady=(0,8))
            for r in self.export_results:
                if not r.get("success"): continue
                row = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=6,
                                   border_width=1, border_color=BORDER)
                row.pack(fill="x", pady=2)
                lbl = "Parte Final" if "final" in r["label"] else f"Parte {r['part']}"
                ctk.CTkLabel(row, text=lbl,
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=TEXT_PRIMARY, width=75).pack(side="left", padx=10, pady=6)
                ctk.CTkLabel(row, text=format_size(r.get("size_bytes", 0)),
                             font=ctk.CTkFont(size=10, family="Courier"),
                             text_color=TEXT_SEC).pack(side="left", padx=4)
                ctk.CTkButton(row, text="Renombrar", width=76, height=22,
                              fg_color="transparent", border_width=1, border_color=BORDER,
                              text_color=TEXT_SEC, hover_color=BG_CARD,
                              font=ctk.CTkFont(size=9),
                              command=lambda rv=r: self._rename(rv, out_folder)
                              ).pack(side="right", padx=8)
            bf = ctk.CTkFrame(body, fg_color="transparent")
            bf.pack(fill="x", pady=(0,6))
            ctk.CTkButton(bf, text="📂  Abrir carpeta",
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#fff",
                          font=ctk.CTkFont(size=11),
                          command=lambda: os.startfile(str(out_folder))
                          ).pack(side="left", padx=(0,6))
            ctk.CTkButton(bf, text="▶  Nuevo video",
                          fg_color=BG_ELEVATED, border_width=1, border_color=BORDER_ACCENT,
                          text_color=ACCENT_GLOW, hover_color=BG_CARD,
                          font=ctk.CTkFont(size=11),
                          command=lambda: [self._close_overlay(), self._reset_all(), self._browse_video()]
                          ).pack(side="left")
            ctk.CTkButton(bf, text="Cerrar",
                          fg_color="transparent", border_width=1, border_color=BORDER,
                          text_color=TEXT_MUTED, hover_color=BG_ELEVATED,
                          font=ctk.CTkFont(size=11),
                          command=self._close_overlay).pack(side="right")
        self._show_overlay(build, width=460)

    # ── Proporción reproductor ────────────────────────────────────────────────
    def _on_ratio_change(self):
        ratio = self._ratio_var.get()
        self.settings["player_ratio"] = ratio
        save_settings(self.settings)
        self._apply_ratio()
        if self._vlc and self._vlc._ok:
            self._vlc.set_aspect_ratio(ratio)
        if self._vlc and self._vlc._ok and self.video_path:
            self.after(100, lambda: [
                self._vlc.load(self.video_path),
                self._vlc.play(),
                self.after(300, lambda: self._vlc.pause()),
            ])

    def _apply_ratio(self):
        ratio = self._ratio_var.get() if self._ratio_var else PLAYER_RATIO_DEFAULT
        w_parts, h_parts = PLAYER_RATIOS.get(ratio, (9, 16))
        # Altura del marco: en 9:16 (vertical) no subir tanto para no empujar
        # slider/controles fuera de la ventana visible.
        base_w = 280
        h = int(base_w * h_parts / w_parts)
        max_h = 200 if h_parts > w_parts else 248
        h = max(140, min(h, max_h))
        self.vlc_frame.configure(height=h)

    def _on_vlc_frame_configure(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self.vlc_frame:
            return
        if self._vlc and self._vlc._ok and self._ratio_var:
            self._vlc.set_aspect_ratio(self._ratio_var.get())

    def _refresh_speed_label_colors(self):
        if not getattr(self, "_speed_name_labels", None):
            return
        cur = self.speed_var.get()
        for preset, lbl in self._speed_name_labels.items():
            lbl.configure(
                text_color=ACCENT_GLOW if preset == cur else TEXT_PRIMARY
            )

    # ── VLC ───────────────────────────────────────────────────────────────────
    def _init_vlc(self):
        self._vlc = VLCPlayer(self.vlc_frame)
        if not self._vlc._ok:
            self.vlc_placeholder.configure(
                text="python-vlc no disponible\npip install python-vlc")

    def _start_player_loop(self):
        if self._player_job: self.after_cancel(self._player_job)
        self._player_loop()

    def _player_loop(self):
        if self._vlc and self._vlc._ok:
            t = self._vlc.get_time()
            d = self._vlc.get_duration()
            if d > 0:
                self.player_var.set(t / d * 100)
                self.time_lbl.configure(text=seconds_to_str(t))
                self._player_time = t
            self.play_btn.configure(text="⏸" if self._vlc.is_playing() else "▶")
        self._player_job = self.after(200, self._player_loop)

    def _on_seek(self, value):
        if self._vlc and self._vlc._ok:
            d = self._vlc.get_duration()
            if d > 0:
                t = float(value) / 100.0 * d
                self._vlc.set_time(t)
                self._player_time = t
                self.time_lbl.configure(text=seconds_to_str(t))

    def _toggle_play(self):
        if not self._vlc or not self._vlc._ok: return
        if self._vlc.is_playing():
            self._vlc.pause(); self.play_btn.configure(text="▶")
        else:
            self._vlc.play(); self.play_btn.configure(text="⏸")

    def _toggle_mute(self):
        if not self._vlc: return
        muted = self._vlc.toggle_mute()
        self.mute_btn.configure(text="🔇" if muted else "🔊")

    def _use_current_time(self):
        if self.cuts_entries:
            self.cuts_entries[-1].delete(0, "end")
            self.cuts_entries[-1].insert(0, seconds_to_str(self._player_time))
            self._toast(f"Tiempo {seconds_to_str(self._player_time)} copiado", "info")

    # ── Video ─────────────────────────────────────────────────────────────────
    def _browse_video(self):
        path = filedialog.askopenfilename(
            title="Seleccionar video",
            filetypes=[("Video","*.mp4 *.mov *.avi *.mkv *.wmv *.flv *.webm *.m4v"),
                       ("Todos","*.*")])
        if path: self._load_video(path)

    def _load_video(self, path):
        if not os.path.isfile(path):
            self._toast("No se encontró el archivo", "error"); return
        self.video_path = path
        name = os.path.basename(path)
        self.drop_label.configure(text=f"✦  {name[:30]}", text_color=ACCENT_GLOW,
                                   font=ctk.CTkFont(size=11, weight="bold"))
        if self.ffprobe_path:
            info = get_video_info(path, self.ffprobe_path)
            self.video_info = info
            self.info_labels["name"].configure(text=name[:26])
            self.info_labels["duration"].configure(text=format_duration(info.get("duration",0)))
            self.info_labels["resolution"].configure(
                text=f"{info.get('width','?')}×{info.get('height','?')}")
            self.info_labels["fps"].configure(text=f"{info.get('fps','?')} fps")
            self.info_labels["codec"].configure(text=info.get("video_codec","—").upper())
            self.info_labels["audio"].configure(text=info.get("audio_codec","—"))
            if info.get("is_hevc"):
                self._toast("El video ya es HEVC — se recodificará", "info")
        if self._vlc and self._vlc._ok:
            self.vlc_placeholder.place_forget()
            self._vlc.load(path)
            self._vlc.play()
            self.after(400, lambda: self._vlc.pause())
            self._start_player_loop()
        # Auto-detectar proporción
        w = self.video_info.get("width", 0)
        h = self.video_info.get("height", 0)
        if w > 0 and h > 0:
            ratio = "9:16" if h > w else ("16:9" if w > h else "1:1")
            if self._ratio_var: self._ratio_var.set(ratio)
            self._apply_ratio()
        if self._vlc and self._vlc._ok and self._ratio_var:
            self._vlc.set_aspect_ratio(self._ratio_var.get())
        self._update_timeline()
        self._toast(f"Video cargado: {name[:28]}", "success")

    # ── Cortes ────────────────────────────────────────────────────────────────
    def _add_cut(self):
        idx = len(self.cuts_entries) + 1
        row = ctk.CTkFrame(self.cuts_frame, fg_color=BG_ELEVATED, corner_radius=6,
                           border_width=1, border_color=BORDER)
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=f"Corte {idx}",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=TEXT_MUTED, width=52, anchor="w"
                     ).pack(side="left", padx=(10,0), pady=8)
        entry = self._entry(row, "MM:SS.cc — Ej: 4:19.23", width=190)
        entry.pack(side="left", padx=8, pady=6)
        entry.bind("<FocusOut>", lambda e: self._update_timeline())
        entry.bind("<Return>",   lambda e: self._update_timeline())
        self._help(row, f"Tiempo del corte {idx}.\nFormato: MM:SS.cc\nEj: 4:19.23")
        ctk.CTkButton(row, text="✕", width=24, height=24,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT_MUTED, hover_color="#3a0a0a",
                      font=ctk.CTkFont(size=10),
                      command=lambda r=row, e=entry: self._remove_cut(r, e)
                      ).pack(side="right", padx=8)
        self.cuts_entries.append(entry)
        if hasattr(self, "timeline_canvas"): self._update_timeline()

    def _remove_cut(self, row, entry):
        if len(self.cuts_entries) <= 1: return
        self.cuts_entries.remove(entry)
        row.destroy()
        self._renumber_cuts()
        if hasattr(self, "timeline_canvas"): self._update_timeline()

    def _renumber_cuts(self):
        for i, e in enumerate(self.cuts_entries):
            for c in e.master.winfo_children():
                if isinstance(c, ctk.CTkLabel) and "Corte" in str(c.cget("text")):
                    c.configure(text=f"Corte {i+1}"); break

    def _get_cuts(self):
        return sorted([t for e in self.cuts_entries
                       if (t := parse_time(e.get().strip())) is not None])

    # ── Línea de tiempo ───────────────────────────────────────────────────────
    def _update_timeline(self):
        d = self.video_info.get("duration", 0)
        cuts = self._get_cuts()
        self._draw_timeline(d, cuts)
        self._update_segments(d, cuts)

    def _draw_timeline(self, duration, cuts):
        if not hasattr(self, "timeline_canvas"): return
        c = self.timeline_canvas
        c.delete("all")
        w = c.winfo_width() or 500
        h = 52
        if duration <= 0:
            c.create_text(w//2, h//2, text="Carga un video para ver la línea de tiempo",
                          fill=TEXT_MUTED, font=("Courier", 9))
            return
        points = [0.0] + cuts + [duration]
        segs = [(points[i], points[i+1]) for i in range(len(points)-1)]
        for idx, (s, e) in enumerate(segs):
            x1 = int(s/duration*w); x2 = int(e/duration*w)
            c.create_rectangle(x1+1, 8, x2-1, h-8,
                               fill=SEGMENT_COLORS[idx % len(SEGMENT_COLORS)], outline="")
            lbl = "FINAL" if idx == len(segs)-1 else f"P{idx+1}"
            if x2 - x1 > 28:
                c.create_text((x1+x2)//2, h//2, text=lbl,
                               fill="#fff", font=("Courier", 8, "bold"))
        for cut in cuts:
            x = int(cut/duration*w)
            c.create_line(x, 0, x, h, fill="#fff", width=1, dash=(3,2))
            c.create_rectangle(x-3, 0, x+3, 6, fill="#fff", outline="")
        if self._player_time > 0:
            px = int(self._player_time/duration*w)
            c.create_line(px, 0, px, h, fill=ACCENT_GLOW, width=2)

    def _update_segments(self, duration, cuts):
        for w in self.segments_frame.winfo_children(): w.destroy()
        if duration <= 0 or not cuts: return
        intro_t = parse_time(self.intro_entry.get()) or 0.0
        warn_dur = self.settings.get("warn_max_duration", 600)
        warn_mb  = self.settings.get("warn_max_size_mb", 500)
        durs = get_segment_durations(cuts, duration)
        total = len(durs)
        for idx, dur in enumerate(durs):
            pn = idx+1; lbl = "Parte Final" if pn==total else f"Parte {pn}"
            td = intro_t+dur; mb = estimate_segment_size_mb(td)
            over = td > warn_dur or mb > warn_mb
            row = ctk.CTkFrame(self.segments_frame, fg_color=BG_ELEVATED,
                               corner_radius=6, border_width=1,
                               border_color=DANGER if over else BORDER)
            row.pack(fill="x", pady=2)
            ctk.CTkFrame(row, fg_color=SEGMENT_COLORS[idx % len(SEGMENT_COLORS)],
                         width=4, corner_radius=0).pack(side="left", fill="y")
            ctk.CTkLabel(row, text=lbl,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=TEXT_PRIMARY, width=72, anchor="w"
                         ).pack(side="left", padx=8, pady=5)
            ctk.CTkLabel(row, text=format_duration(td),
                         font=ctk.CTkFont(size=11, family="Courier"),
                         text_color=DANGER if td > warn_dur else TEXT_SEC
                         ).pack(side="left", padx=4)
            ctk.CTkLabel(row, text=f"~{mb:.0f} MB",
                         font=ctk.CTkFont(size=10, family="Courier"),
                         text_color=DANGER if mb > warn_mb else TEXT_MUTED
                         ).pack(side="right", padx=10)
            if over:
                ctk.CTkLabel(row, text="⚠", font=ctk.CTkFont(size=12),
                             text_color=WARNING).pack(side="right", padx=4)

    # ── Texto PARTE X ─────────────────────────────────────────────────────────
    def _on_slider(self, key, value, label):
        label.configure(text=str(int(value)))
        self._update_preview()

    def _pick_color(self, target):
        current = self._text_color if target == "color" else self._outline_color
        color = colorchooser.askcolor(color=current, title="Elegir color")[1]
        if color:
            if target == "color":
                self._text_color = color
                self.text_color_btn.configure(text_color=color)
            else:
                self._outline_color = color
                self.outline_color_btn.configure(text_color=color)
            self._update_preview()

    def _update_preview(self):
        try:
            w, h = 380, 90
            img = Image.new("RGB", (w, h), color="#0a0a14")
            draw = ImageDraw.Draw(img)
            fs  = int(self.text_controls["font_size"]["slider"].get())
            ow  = int(self.text_controls["outline_width"]["slider"].get())
            py  = int(self.text_controls["position_y_pct"]["slider"].get())
            try:
                font = ImageFont.truetype(self.anton_path, fs) if self.anton_path else ImageFont.load_default()
            except: font = ImageFont.load_default()
            text = "PARTE 1"
            bbox = draw.textbbox((0,0), text, font=font)
            tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
            x = (w-tw)//2
            y = max(4, int(h*py/100)-th//2)
            for dx in range(-ow, ow+1):
                for dy in range(-ow, ow+1):
                    if dx*dx+dy*dy <= ow*ow:
                        draw.text((x+dx,y+dy), text, font=font, fill=self._outline_color)
            draw.text((x,y), text, font=font, fill=self._text_color)
            photo = ctk.CTkImage(light_image=img, dark_image=img, size=(w,h))
            self.text_preview.configure(image=photo, text="")
            self.text_preview._image = photo
        except: pass

    def _get_text_cfg(self):
        return {
            "font_size":    int(self.text_controls["font_size"]["slider"].get()),
            "color":        self._text_color,
            "outline_color":self._outline_color,
            "outline_width":int(self.text_controls["outline_width"]["slider"].get()),
            "opacity":      self.text_controls["opacity_pct"]["slider"].get()/100.0,
            "position_y":   self.text_controls["position_y_pct"]["slider"].get()/100.0,
        }

    def _load_preset(self, name):
        p = self.presets.get(name, TEXT_DEFAULTS)
        self.text_controls["font_size"]["slider"].set(p.get("font_size",80))
        self.text_controls["outline_width"]["slider"].set(p.get("outline_width",6))
        self.text_controls["position_y_pct"]["slider"].set(int(p.get("position_y",0.15)*100))
        self.text_controls["opacity_pct"]["slider"].set(int(p.get("opacity",1.0)*100))
        self._text_color = p.get("color","#FFFFFF")
        self._outline_color = p.get("outline_color","#000000")
        self.text_color_btn.configure(text_color=self._text_color)
        self.outline_color_btn.configure(text_color=self._outline_color)
        for v in self.text_controls.values():
            v["label"].configure(text=str(int(v["slider"].get())))
        self._update_preview()

    def _save_preset(self):
        d = ctk.CTkInputDialog(text="Nombre del preset:", title="Guardar preset")
        name = d.get_input()
        if name and name.strip() and name.strip() != "Por defecto":
            self.presets[name.strip()] = self._get_text_cfg()
            save_presets(self.presets)
            self.preset_menu.configure(values=list(self.presets.keys()))
            self.preset_var.set(name.strip())
            self._toast(f"Preset '{name.strip()}' guardado", "success")

    def _delete_preset(self):
        name = self.preset_var.get()
        if name == "Por defecto":
            self._toast("No puedes borrar el preset por defecto", "warning"); return
        if name in self.presets:
            del self.presets[name]
            save_presets(self.presets)
            self.preset_menu.configure(values=list(self.presets.keys()))
            self.preset_var.set("Por defecto")
            self._load_preset("Por defecto")
            self._toast("Preset eliminado", "info")

    # ── Exportación ───────────────────────────────────────────────────────────
    def _start_export(self):
        if not self.video_path:
            self._toast("Selecciona un video primero", "error"); return
        intro_sec = parse_time(self.intro_entry.get())
        if intro_sec is None:
            self._toast("Duración de intro inválida. Formato: MM:SS.cc", "error"); return
        cuts = self._get_cuts()
        if not cuts:
            self._toast("Agrega al menos un corte", "error"); return
        duration = self.video_info.get("duration", 0)
        if duration <= 0:
            self._toast("No se pudo leer la duración del video", "error"); return
        errors = validate_cuts(cuts, duration, intro_sec, 30)
        if errors:
            msg = "Problemas detectados:\n\n" + "\n".join(f"• {e}" for e in errors)
            if not messagebox.askyesno("Validación", msg+"\n\n¿Continuar?", icon="warning"): return

        total = len(cuts) + 1
        out_dir = self.settings.get("output_dir", r"C:\Videos_Trabajo")
        vname   = Path(self.video_path).stem
        out     = Path(out_dir) / f"{vname}_partes"
        if out.exists():
            choice = messagebox.askyesnocancel("Carpeta existente",
                f"Ya existe:\n{out}\n\n¿Sobreescribir?")
            if choice is None: return
            if choice:
                import shutil; shutil.rmtree(out)
            else:
                return
        out.mkdir(parents=True, exist_ok=True)

        if self._vlc and self._vlc.is_playing(): self._vlc.pause()
        self.is_exporting = True
        self.export_start_time = time.time()
        self.engine.reset_cancel()
        self.export_results = []
        self.log_entries = [f"Inicio: {datetime.now()}", f"Video: {self.video_path}",
                            f"Partes: {total}"]
        # Limpiar log
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0","end")
        self.log_box.configure(state="disabled")
        self.progress_bar.set(0)
        self.progress_lbl.configure(text="Iniciando...")
        threading.Thread(target=self._export_thread,
                         args=(cuts, intro_sec, duration, out, total),
                         daemon=True).start()

    def _export_thread(self, cuts, intro_sec, duration, out_folder, total):
        text_cfg = self._get_text_cfg()
        speed    = self.speed_var.get()
        points   = [0.0] + cuts + [duration]
        for idx in range(total):
            if self.engine.is_cancelled(): break
            pn = idx+1; is_last = pn == total
            seg_start = points[idx]; seg_end = points[idx+1]
            label     = "parte_final" if is_last else f"parte_{pn}"
            vname     = Path(self.video_path).stem
            out_path  = str(out_folder / f"{vname}_{label}.mp4")
            self._log(f"\n── Parte {pn}/{total} ──")
            self.after(0, lambda p=pn, t=total:
                       self.progress_lbl.configure(text=f"Exportando parte {p} de {t}..."))
            def on_prog(pct, spd, eta, pn=pn, tt=total):
                overall = ((pn-1) + pct/100) / tt
                self.after(0, lambda: [
                    self.progress_bar.set(overall),
                    self.speed_lbl.configure(text=f"Velocidad: {spd}"),
                    self.eta_lbl.configure(text=f"ETA: {eta}"),
                ])
            result = self.engine.export_part(
                video_path=self.video_path, intro_end_sec=intro_sec,
                segment_start_sec=seg_start, segment_end_sec=seg_end,
                output_path=out_path, part_number=pn, total_parts=total,
                is_last_part=is_last, text_config=text_cfg,
                anton_font_path=self.anton_path or "", speed_preset=speed,
                on_progress=on_prog, on_log=self._log)
            self.export_results.append({"part":pn, "label":label, **result})
            if not result["success"]:
                err = result.get("error","Error desconocido")
                self._log(f"ERROR: {err}")
                self.after(0, lambda e=err, p=pn: self._on_error(p, e)); return
            sz = format_size(result.get("size_bytes",0))
            self._log(f"✓ Parte {pn} — {sz}")
            self.after(0, lambda s=sz, p=pn:
                       self.progress_lbl.configure(text=f"✓ Parte {p} — {s}"))
        self.engine.cleanup_temp(str(out_folder))
        write_log(str(out_folder), self.log_entries)
        if not self.engine.is_cancelled():
            self.after(0, lambda: self._on_complete(out_folder))
        else:
            self.after(0, self._on_cancelled)

    def _on_complete(self, out_folder):
        self.is_exporting = False
        self.progress_bar.set(1.0)
        self.progress_lbl.configure(text="✅ Exportación completada")
        elapsed = time.time() - (self.export_start_time or time.time())
        mins = int(elapsed//60); secs = int(elapsed%60)
        time_str = f"{mins}m {secs:02d}s"
        try:
            import winsound; winsound.MessageBeep(winsound.MB_OK)
        except: pass
        self._toast(f"¡Listo en {time_str}!", "success")
        self._add_to_history(out_folder)
        self._show_summary_panel(out_folder, time_str)

    def _on_error(self, pn, error):
        self.is_exporting = False
        friendly = self._friendly_error(error)
        self._toast(f"Error parte {pn}: {friendly}", "error")
        messagebox.showerror(f"Error en parte {pn}",
                              f"{friendly}\n\nDetalle:\n{error[:300]}")

    def _on_cancelled(self):
        self.is_exporting = False
        self.progress_lbl.configure(text="Exportación cancelada")
        self._toast("Exportación cancelada", "warning")

    def _friendly_error(self, error):
        e = error.lower()
        if "no such file" in e or "not found" in e: return "No se encontró el archivo."
        if "permission" in e or "access" in e: return "Sin permiso en la carpeta de salida."
        if "codec" in e or "encoder" in e: return "Error de codificación con FFmpeg."
        if "font" in e: return "No se encontró la fuente Anton."
        if "space" in e or "disk" in e: return "Espacio insuficiente en disco."
        return "Error durante la exportación. Revisa el log."

    def _rename(self, result, out_folder):
        d = ctk.CTkInputDialog(text="Nuevo nombre:", title="Renombrar")
        name = d.get_input()
        if name and name.strip():
            vname = Path(self.video_path).stem
            old = out_folder / f"{vname}_{result['label']}.mp4"
            new = out_folder / f"{name.strip()}.mp4"
            try:
                old.rename(new); result["label"] = name.strip()
                self._toast(f"Renombrado a '{name.strip()}'", "success")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # ── Historial ─────────────────────────────────────────────────────────────
    def _add_to_history(self, out_folder):
        entry = {"path": self.video_path, "name": os.path.basename(self.video_path),
                 "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
                 "parts": len(self.export_results),
                 "duration": format_duration(self.video_info.get("duration",0))}
        self.history = [entry] + [h for h in self.history if h["path"] != self.video_path]
        self.history = self.history[:MAX_HISTORY_ITEMS]
        save_history(self.history, MAX_HISTORY_ITEMS)

    # ── Reset ─────────────────────────────────────────────────────────────────
    def _reset_all(self):
        if self.is_exporting:
            self._toast("Cancela la exportación antes de resetear", "warning"); return
        if self._vlc: self._vlc.stop()
        if self._player_job: self.after_cancel(self._player_job); self._player_job = None
        self.video_path = None; self.video_info = {}
        self.drop_label.configure(text="Arrastra el video aquí", text_color=TEXT_MUTED,
                                   font=ctk.CTkFont(size=12))
        for k in self.info_labels: self.info_labels[k].configure(text="—")
        self.vlc_placeholder.place(relx=0.5, rely=0.5, anchor="center")
        self.vlc_placeholder.configure(text="Sin video")
        self.intro_entry.delete(0,"end")
        for e in self.cuts_entries: e.master.destroy()
        self.cuts_entries.clear()
        self._add_cut()
        self.progress_bar.set(0)
        self.progress_lbl.configure(text="En espera")
        self.speed_lbl.configure(text=""); self.eta_lbl.configure(text="")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0","end")
        self.log_box.configure(state="disabled")
        self._player_time = 0.0
        self.play_btn.configure(text="▶")
        self.time_lbl.configure(text="0:00.00")
        self.player_var.set(0)
        if hasattr(self,"timeline_canvas"): self._draw_timeline(0,[])
        for w in self.segments_frame.winfo_children(): w.destroy()

    # ── Log ───────────────────────────────────────────────────────────────────
    def _log(self, msg):
        self.log_entries.append(msg)
        self.after(0, lambda m=msg: self._append_log(m))

    def _append_log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg+"\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ── Atajos ────────────────────────────────────────────────────────────────
    def _apply_shortcuts(self):
        self.bind("<Return>",    lambda e: self._show_export_panel())
        self.bind("<space>",     lambda e: self._toggle_play())
        self.bind("<Control-a>", lambda e: self._add_cut())
        self.bind("<Control-r>", lambda e: self._reset_all())
        self.bind("<Control-o>", lambda e: self._browse_video())
