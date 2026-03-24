"""
Slicer by Claude - Ventana principal v1.9.0
Novedades:
- Miniaturas eliminadas de la línea de tiempo (rendimiento)
- Botón "Quitar video" para limpiar el video cargado
- Controles del reproductor siempre visibles
- Fuentes más grandes en línea de tiempo y cortes
- Botones ⚙ y S (Acerca de) corregidos
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
from PIL import Image, ImageDraw, ImageFont, ImageTk
import tkinter as tk

try:
    import vlc
    VLC_AVAILABLE = True
except ImportError:
    VLC_AVAILABLE = False

from core.config import (
    APP_NAME, APP_VERSION,
    PRESETS_SPEED, PRESETS_SPEED_DESC, PRESET_DEFAULT,
    TEXT_DEFAULTS, PLAYER_RATIOS, PLAYER_RATIO_DEFAULT,
    HISTORY_SIZE_OPTIONS,
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

ACCENT        = "#ffffff"
ACCENT_DIM    = "#d4c8b4"
BG_ROOT       = "#1c1610"
BG_PANEL      = "#232018"
BG_CARD       = "#2a2418"
BG_ELEVATED   = "#302a1e"
BG_INPUT      = "#161210"
BG_TL         = "#0e0c08"   # fondo línea de tiempo
BORDER        = "#3d3528"
BORDER_LIGHT  = "#4a4030"
TEXT_PRIMARY  = "#ffffff"
TEXT_SEC      = "#c8bca8"
TEXT_MUTED    = "#7a6a55"
SUCCESS       = "#4ade80"
WARNING       = "#fbbf24"
DANGER        = "#f87171"
SEGMENT_COLORS = ["#c8a882","#7a9ec8","#7ac89e","#c8a07a","#c87a7a","#9a7ac8"]
TAB_NAMES = ["✦  Editor", "T  Texto", "◷  Historial"]

TL_H          = 140   # altura total línea de tiempo (sin miniaturas)
TL_RULER_H    = 28    # altura regla de tiempo
TL_WAVE_H     = 70    # altura franja de onda
TL_SEG_H      = 42    # altura franja de segmentos


# ── Toast ─────────────────────────────────────────────────────────────────────
class Toast(ctk.CTkToplevel):
    def __init__(self, parent, message, kind="success", duration=3500):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        colors = {"success":(SUCCESS,"#0d2b1a"),"error":(DANGER,"#2b0d0d"),
                  "info":(ACCENT_DIM,BG_CARD),"warning":(WARNING,"#2b1f0d")}
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
        w,h = self.winfo_reqwidth(), self.winfo_reqheight()
        sw,sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{sw-w-20}+{sh-h-60}")
        self._fade(0.0,1.0,20, lambda: self.after(duration, lambda: self._fade(1.0,0.0,30,self._close)))

    def _fade(self, start, end, step_ms, on_done=None):
        delta = 0.08 if end>start else -0.07
        alpha = max(0.0, min(1.0, start+delta))
        if (end>start and alpha>=end) or (end<start and alpha<=end):
            self.attributes("-alpha", end)
            if on_done: on_done()
        else:
            self.attributes("-alpha", alpha)
            self.after(step_ms, lambda: self._fade(alpha,end,step_ms,on_done))

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
                self.instance = vlc.Instance("--no-xlib","--quiet")
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
            return t/1000.0 if t>=0 else 0.0
        return 0.0
    def set_time(self, sec):
        if self._ok and self.player: self.player.set_time(int(sec*1000))
    def get_duration(self):
        if self._ok and self.player:
            d = self.player.get_length()
            return d/1000.0 if d>0 else 0.0
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
        self.dep_results = dep_results
        self.ffmpeg_path = find_ffmpeg()
        self.ffprobe_path = find_ffprobe()
        self.anton_path = check_anton_font()
        self.engine = ExportEngine()
        self.settings = load_settings()
        self.history = load_history()
        self.presets = load_presets()

        self.video_path = None
        self.video_info = {}
        self.cuts_entries = []
        self.is_exporting = False
        self.log_entries = []
        self.export_results = []
        self.export_start_time = None
        self._player_time = 0.0
        self._vlc = None
        self._player_job = None
        self._muted = False
        self._text_color = TEXT_DEFAULTS["color"]
        self._outline_color = TEXT_DEFAULTS["outline_color"]
        self._active_tab = 0
        self._tab_frames = []
        self._ratio_var = None
        self._overlay_bg = None
        self._overlay_panel = None
        self.speed_var = ctk.StringVar(value=self.settings.get("speed_preset", PRESET_DEFAULT))

        # Timeline state
        self._zoom = 1.0
        self._tl_offset = 0.0      # segundos visibles desde la izquierda
        self._playhead_sec = 0.0   # posición del playhead blanco
        self._dragging_playhead = False
        self._dragging_cut_idx = None
        self._drag_cursor_x = -1   # posición x al arrastrar marcador
        self._waveform_data = []
        self._tl_hover_sec = -1

        self._build_window()
        self._build_ui()
        self._apply_shortcuts()
        self._restore_geometry()

    # ── Ventana ───────────────────────────────────────────────────────────────
    def _build_window(self):
        self.title(APP_NAME)
        self.configure(fg_color=BG_ROOT)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.minsize(1100, 700)
        try:
            ico = Path(__file__).parent.parent / "assets" / "icon.ico"
            if ico.exists(): self.iconbitmap(str(ico))
        except: pass

    def _restore_geometry(self):
        try: self.geometry(self.settings.get("window_geometry","1280x800+60+30"))
        except: self.geometry("1280x800+60+30")

    def _on_close(self):
        if self.is_exporting:
            if not messagebox.askyesno("Exportación en curso",
                "¿Cerrar y cancelar la exportación?", icon="warning"): return
            self.engine.cancel()
        if self._vlc: self._vlc.release()
        if self._player_job: self.after_cancel(self._player_job)
        self.settings["window_geometry"] = self.geometry()
        save_settings(self.settings)
        self.destroy()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_titlebar()
        self._build_tabs()
        self._build_content()
        self._switch_tab(0)

    def _build_titlebar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=48)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkFrame(bar, fg_color=ACCENT, height=2, corner_radius=0).pack(fill="x", side="top")
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16)
        logo = ctk.CTkFrame(inner, fg_color="transparent")
        logo.pack(side="left", pady=8)
        ctk.CTkLabel(logo, text="S", font=ctk.CTkFont(size=20, weight="bold", family="Georgia"),
                     text_color=ACCENT).pack(side="left", padx=(0,8))
        ctk.CTkLabel(logo, text=APP_NAME, font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkLabel(logo, text=f"  v{APP_VERSION}", font=ctk.CTkFont(size=9),
                     text_color=TEXT_MUTED).pack(side="left", pady=(3,0))
        btn_frame = ctk.CTkFrame(inner, fg_color="transparent")
        btn_frame.pack(side="right", pady=10)
        # Botón Exportar destacado
        ctk.CTkButton(btn_frame, text="▶  Exportar", width=110, height=30,
                      fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=BG_ROOT,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      command=self._show_export_panel).pack(side="left", padx=(0,6))
        ctk.CTkButton(btn_frame, text="⚙", width=34, height=30,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT_MUTED, hover_color=BG_ELEVATED,
                      font=ctk.CTkFont(size=13),
                      command=self._show_settings_panel).pack(side="left", padx=(0,4))
        ctk.CTkButton(btn_frame, text="S", width=34, height=30,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT_MUTED, hover_color=BG_ELEVATED,
                      font=ctk.CTkFont(size=13, weight="bold", family="Georgia"),
                      command=self._show_about_panel).pack(side="left", padx=3)

    # ── Sistema de paneles flotantes internos ─────────────────────────────────
    def _show_overlay(self, build_fn, width=480):
        """Muestra un panel flotante interno sobre la interfaz."""
        self._close_overlay()
        # Overlay oscuro de fondo — color sólido (alpha hex no funciona en tkinter/Windows)
        self._overlay_bg = ctk.CTkFrame(self, fg_color="#0d0b08", corner_radius=0)
        self._overlay_bg.place(x=0, y=0, relwidth=1, relheight=1)
        self._overlay_bg.bind("<Button-1>", lambda e: self._close_overlay())
        self._overlay_bg.lift()
        # Panel flotante centrado
        self._overlay_panel = ctk.CTkFrame(self._overlay_bg,
                                            fg_color=BG_PANEL, corner_radius=12,
                                            border_width=1, border_color=BORDER_LIGHT,
                                            width=width)
        self._overlay_panel.place(relx=0.5, rely=0.5, anchor="center")
        self._overlay_panel.bind("<Button-1>", lambda e: "break")
        # Construir contenido del panel
        build_fn(self._overlay_panel)
        self._overlay_panel.lift()

    def _close_overlay(self):
        try:
            if hasattr(self, "_overlay_bg") and self._overlay_bg:
                self._overlay_bg.destroy()
                self._overlay_bg = None
                self._overlay_panel = None
        except: pass

    def _panel_header(self, parent, title, width=480):
        """Header estándar para paneles flotantes."""
        hdr = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=0,
                            height=46, width=width)
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

    # ── Panel Exportar ────────────────────────────────────────────────────────
    def _show_export_panel(self):
        def build(panel):
            self._panel_header(panel, "▶  Exportar video")
            body = ctk.CTkFrame(panel, fg_color="transparent")
            body.pack(fill="x", padx=18, pady=12)

            # Estado actual
            self._sec_inline(body, "ESTADO")
            status_card = ctk.CTkFrame(body, fg_color=BG_ELEVATED, corner_radius=8,
                                        border_width=1, border_color=BORDER)
            status_card.pack(fill="x", pady=(0,10))
            video_ok = bool(self.video_path)
            intro_sec = parse_time(self.intro_entry.get()) if hasattr(self,"intro_entry") else None
            cuts = self._get_cuts() if hasattr(self,"cuts_entries") else []
            for ok, lbl, val in [
                (video_ok, "Video", os.path.basename(self.video_path)[:24] if self.video_path else "Sin video"),
                (intro_sec is not None, "Intro", format_duration(intro_sec) if intro_sec else "No configurada"),
                (bool(cuts), "Cortes", f"{len(cuts)} corte(s)" if cuts else "Sin cortes"),
            ]:
                row = ctk.CTkFrame(status_card, fg_color="transparent")
                row.pack(fill="x", padx=10, pady=3)
                ctk.CTkLabel(row, text="✅" if ok else "❌",
                             font=ctk.CTkFont(size=12),
                             text_color=SUCCESS if ok else DANGER,
                             width=24).pack(side="left")
                ctk.CTkLabel(row, text=lbl, font=ctk.CTkFont(size=11),
                             text_color=TEXT_SEC, width=50, anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=val, font=ctk.CTkFont(size=10),
                             text_color=TEXT_MUTED, anchor="w").pack(side="left", padx=4)

            # Config de exportación
            self._sec_inline(body, "CONFIGURACIÓN")
            cfg = ctk.CTkFrame(body, fg_color=BG_ELEVATED, corner_radius=8,
                               border_width=1, border_color=BORDER)
            cfg.pack(fill="x", pady=(0,10))
            fps = self.video_info.get("fps", 0)
            for i,(lbl,val) in enumerate([
                ("Codec","HEVC (H.265)"),("Resolución","1080p forzado"),
                ("FPS",f"30fps" + (f"  ⚠ video: {fps}fps" if fps and abs(fps-30)>1 else "")),
                ("Bits","3000 kbps"),("Audio","AAC 192k"),("Formato",".mp4"),
            ]):
                bg = BG_ELEVATED if i%2==0 else BG_CARD
                r = ctk.CTkFrame(cfg, fg_color=bg, corner_radius=0)
                r.pack(fill="x")
                ctk.CTkLabel(r, text=lbl, width=80, anchor="w",
                             font=ctk.CTkFont(size=10), text_color=TEXT_MUTED
                             ).pack(side="left", padx=(10,0), pady=3)
                ctk.CTkLabel(r, text=val, anchor="w",
                             font=ctk.CTkFont(size=10, weight="bold"),
                             text_color=WARNING if "⚠" in val else TEXT_PRIMARY
                             ).pack(side="left", padx=4)

            # Velocidad
            self._sec_inline(body, "VELOCIDAD")
            speed_row = ctk.CTkFrame(body, fg_color="transparent")
            speed_row.pack(fill="x", pady=(0,10))
            for preset in PRESETS_SPEED:
                ctk.CTkRadioButton(speed_row, text=preset,
                                   variable=self.speed_var, value=preset,
                                   radiobutton_width=12, radiobutton_height=12,
                                   fg_color=ACCENT, hover_color=ACCENT_DIM,
                                   font=ctk.CTkFont(size=10), text_color=TEXT_SEC
                                   ).pack(side="left", padx=8)

            # Botones
            btn_row = ctk.CTkFrame(body, fg_color="transparent")
            btn_row.pack(fill="x", pady=(4,8))
            all_ok = video_ok and intro_sec is not None and bool(cuts)
            ctk.CTkButton(btn_row,
                          text="✔  PROCESAR VIDEO" if all_ok else "▶  PROCESAR VIDEO",
                          fg_color=SUCCESS if all_ok else ACCENT,
                          hover_color="#16a34a" if all_ok else ACCENT_DIM,
                          text_color=BG_ROOT, height=42,
                          font=ctk.CTkFont(size=13, weight="bold"),
                          state="normal" if all_ok else "disabled",
                          command=lambda: [self._close_overlay(), self._start_export()]
                          ).pack(fill="x", pady=(0,6))
            ctk.CTkButton(btn_row, text="Cancelar", height=32,
                          fg_color="transparent", border_width=1, border_color=BORDER,
                          text_color=TEXT_MUTED, hover_color=BG_ELEVATED,
                          font=ctk.CTkFont(size=11),
                          command=self._close_overlay).pack(fill="x")
        self._show_overlay(build, width=440)

    def _sec_inline(self, parent, text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(6,3))
        ctk.CTkLabel(row, text=text, font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=TEXT_MUTED).pack(side="left")
        ctk.CTkFrame(row, fg_color=BORDER, height=1, corner_radius=0
                     ).pack(side="left", fill="x", expand=True, padx=(8,0), pady=5)

    # ── Panel Configuración ───────────────────────────────────────────────────
    def _show_settings_panel(self):
        def build(panel):
            self._panel_header(panel, "⚙  Configuración", width=500)
            scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent",
                                             scrollbar_button_color=BORDER,
                                             height=420, width=500)
            scroll.pack(fill="x", padx=18, pady=10)

            def section(t):
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x", pady=(8,3))
                ctk.CTkLabel(row, text=t, font=ctk.CTkFont(size=9, weight="bold"),
                             text_color=TEXT_MUTED).pack(side="left")
                ctk.CTkFrame(row, fg_color=BORDER, height=1, corner_radius=0
                             ).pack(side="left", fill="x", expand=True, padx=(8,0), pady=5)

            section("CARPETA DE SALIDA")
            out_row = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                                   border_width=1, border_color=BORDER)
            out_row.pack(fill="x", pady=(0,8))
            self._out_dir_var = ctk.StringVar(value=self.settings.get("output_dir",r"C:\Videos_Trabajo"))
            ctk.CTkEntry(out_row, textvariable=self._out_dir_var,
                         fg_color=BG_INPUT, border_color=BORDER,
                         text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=11)
                         ).pack(side="left", fill="x", expand=True, padx=10, pady=6)
            ctk.CTkButton(out_row, text="...", width=36, height=26,
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=BG_ROOT,
                          command=lambda: self._browse_folder(self._out_dir_var)
                          ).pack(side="right", padx=6)

            section("CARPETA DE LOGS")
            log_row = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                                   border_width=1, border_color=BORDER)
            log_row.pack(fill="x", pady=(0,8))
            self._log_dir_var = ctk.StringVar(value=self.settings.get("logs_dir",r"C:\Videos_Trabajo"))
            ctk.CTkEntry(log_row, textvariable=self._log_dir_var,
                         fg_color=BG_INPUT, border_color=BORDER,
                         text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=11)
                         ).pack(side="left", fill="x", expand=True, padx=10, pady=6)
            ctk.CTkButton(log_row, text="...", width=36, height=26,
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=BG_ROOT,
                          command=lambda: self._browse_folder(self._log_dir_var)
                          ).pack(side="right", padx=6)

            section("TAMAÑO DEL HISTORIAL")
            hist_row = ctk.CTkFrame(scroll, fg_color="transparent")
            hist_row.pack(fill="x", pady=(0,8))
            self._hist_size_var = ctk.IntVar(value=self.settings.get("history_max",5))
            for size in HISTORY_SIZE_OPTIONS:
                ctk.CTkRadioButton(hist_row, text=f"{size} videos",
                                   variable=self._hist_size_var, value=size,
                                   radiobutton_width=12, radiobutton_height=12,
                                   fg_color=ACCENT, hover_color=ACCENT_DIM,
                                   font=ctk.CTkFont(size=11), text_color=TEXT_SEC
                                   ).pack(side="left", padx=8)

            section("LÍMITES DE ADVERTENCIA")
            lim = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                               border_width=1, border_color=BORDER)
            lim.pack(fill="x", pady=(0,8))
            li = ctk.CTkFrame(lim, fg_color="transparent")
            li.pack(fill="x", padx=12, pady=8)
            ctk.CTkLabel(li, text="Duración máx (min):", font=ctk.CTkFont(size=11),
                         text_color=TEXT_SEC).pack(side="left")
            self._warn_dur_var = ctk.StringVar(
                value=str(int(self.settings.get("warn_max_duration",600)//60)))
            ctk.CTkEntry(li, textvariable=self._warn_dur_var, width=50,
                         fg_color=BG_INPUT, border_color=BORDER,
                         text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=11)
                         ).pack(side="left", padx=6)
            ctk.CTkLabel(li, text="Tamaño máx (MB):", font=ctk.CTkFont(size=11),
                         text_color=TEXT_SEC).pack(side="left", padx=(12,0))
            self._warn_size_var = ctk.StringVar(
                value=str(self.settings.get("warn_max_size_mb",500)))
            ctk.CTkEntry(li, textvariable=self._warn_size_var, width=50,
                         fg_color=BG_INPUT, border_color=BORDER,
                         text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=11)
                         ).pack(side="left", padx=6)

            section("CACHÉ")
            cache_row = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                                     border_width=1, border_color=BORDER)
            cache_row.pack(fill="x", pady=(0,8))
            ci = ctk.CTkFrame(cache_row, fg_color="transparent")
            ci.pack(fill="x", padx=12, pady=8)
            cache_mb = get_cache_size_mb()
            self._cache_lbl = ctk.CTkLabel(ci, text=f"Ocupado: {cache_mb:.1f} MB",
                                            font=ctk.CTkFont(size=11), text_color=TEXT_SEC)
            self._cache_lbl.pack(side="left")
            ctk.CTkButton(ci, text="Borrar caché", width=100, height=26,
                          fg_color="transparent", border_width=1, border_color="#5a2a2a",
                          text_color=DANGER, hover_color="#2b0d0d",
                          font=ctk.CTkFont(size=10),
                          command=lambda: self._do_clear_cache_inline()
                          ).pack(side="right")

            section("DEPENDENCIAS")
            dep = ctk.CTkFrame(scroll, fg_color=BG_ELEVATED, corner_radius=8,
                               border_width=1, border_color=BORDER)
            dep.pack(fill="x", pady=(0,8))
            ffmpeg = find_ffmpeg()
            ffmpeg_ver = "No encontrado"
            if ffmpeg:
                try:
                    r = subprocess.run([ffmpeg,"-version"], capture_output=True, text=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
                    line = r.stdout.split("\n")[0]
                    ffmpeg_ver = line.split("version")[1].strip().split(" ")[0] if "version" in line else "Detectado"
                except: ffmpeg_ver = "Detectado"
            for lbl,val,ok in [
                ("FFmpeg", ffmpeg_ver, bool(ffmpeg)),
                ("Anton", "Instalada" if self.anton_path else "No encontrada", bool(self.anton_path)),
                ("python-vlc", "Disponible" if VLC_AVAILABLE else "No instalado", VLC_AVAILABLE),
            ]:
                r = ctk.CTkFrame(dep, fg_color="transparent")
                r.pack(fill="x", padx=10, pady=3)
                ctk.CTkLabel(r, text="✅" if ok else "❌",
                             font=ctk.CTkFont(size=11),
                             text_color=SUCCESS if ok else DANGER, width=24).pack(side="left")
                ctk.CTkLabel(r, text=lbl, font=ctk.CTkFont(size=11),
                             text_color=TEXT_SEC, width=80, anchor="w").pack(side="left")
                ctk.CTkLabel(r, text=val, font=ctk.CTkFont(size=10),
                             text_color=TEXT_MUTED, anchor="w").pack(side="left", padx=4)

            section("ZONA DE PELIGRO")
            ctk.CTkButton(scroll, text="⚠  Restablecer configuración de fábrica",
                          height=32, fg_color="transparent",
                          border_width=1, border_color="#5a2a2a",
                          text_color=DANGER, hover_color="#2b0d0d",
                          font=ctk.CTkFont(size=11),
                          command=lambda: self._factory_reset_inline()).pack(fill="x", pady=(0,8))

            # Guardar
            ctk.CTkButton(panel, text="Guardar configuración",
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=BG_ROOT,
                          height=36, font=ctk.CTkFont(size=12, weight="bold"),
                          command=self._save_settings_inline
                          ).pack(fill="x", padx=18, pady=(0,14))

        self._show_overlay(build, width=500)

    def _do_clear_cache_inline(self):
        if messagebox.askyesno("Borrar caché","¿Borrar archivos temporales?",icon="warning"):
            n = clear_cache()
            if hasattr(self,"_cache_lbl"):
                self._cache_lbl.configure(text="Ocupado: 0.0 MB")
            self._toast(f"Caché borrada ({n} carpetas)","success")

    def _factory_reset_inline(self):
        if messagebox.askyesno("Restablecer","¿Restablecer configuración de fábrica?",icon="warning"):
            try: (Path.home()/".slicer_by_claude"/"settings.json").unlink()
            except: pass
            self.settings = load_settings()
            self._close_overlay()
            self._toast("Configuración restablecida","success")

    def _save_settings_inline(self):
        try:
            dur_min = int(self._warn_dur_var.get())
            size_mb = int(self._warn_size_var.get())
        except:
            self._toast("Valores de límite inválidos","error"); return
        self.settings["output_dir"] = self._out_dir_var.get()
        self.settings["logs_dir"]   = self._log_dir_var.get()
        self.settings["history_max"] = self._hist_size_var.get()
        self.settings["warn_max_duration"] = dur_min * 60
        self.settings["warn_max_size_mb"]  = size_mb
        save_settings(self.settings)
        self._close_overlay()
        self._toast("Configuración guardada","success")

    # ── Panel Acerca de ───────────────────────────────────────────────────────
    def _show_about_panel(self):
        def build(panel):
            self._panel_header(panel, "Acerca de", width=360)
            body = ctk.CTkFrame(panel, fg_color="transparent", width=360)
            body.pack(padx=20, pady=16)
            ctk.CTkLabel(body, text="S",
                         font=ctk.CTkFont(size=40, weight="bold", family="Georgia"),
                         text_color=ACCENT).pack()
            ctk.CTkLabel(body, text=APP_NAME,
                         font=ctk.CTkFont(size=16, weight="bold"),
                         text_color=TEXT_PRIMARY).pack()
            ctk.CTkLabel(body, text=f"Versión {APP_VERSION}",
                         font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(pady=2)
            ctk.CTkLabel(body,
                         text="Herramienta de corte para historias de Reddit.\nDiseñado y construido con Claude.",
                         font=ctk.CTkFont(size=11), text_color=TEXT_SEC,
                         justify="center").pack(pady=10)
            ctk.CTkButton(body, text="Cerrar",
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=BG_ROOT,
                          command=self._close_overlay).pack(pady=4)
        self._show_overlay(build, width=360)

    # ── Panel Resumen exportación ─────────────────────────────────────────────
    def _show_summary_panel(self, out_folder, time_str=""):
        def build(panel):
            self._panel_header(panel, "✅  Exportación completada", width=460)
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
                ctk.CTkLabel(row, text=format_size(r.get("size_bytes",0)),
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
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=BG_ROOT,
                          font=ctk.CTkFont(size=11),
                          command=lambda: os.startfile(str(out_folder))
                          ).pack(side="left", padx=(0,6))
            ctk.CTkButton(bf, text="▶  Nuevo video",
                          fg_color=BG_ELEVATED, border_width=1, border_color=BORDER_LIGHT,
                          text_color=TEXT_SEC, hover_color=BG_CARD,
                          font=ctk.CTkFont(size=11),
                          command=lambda: [self._close_overlay(), self._reset_all(), self._browse_video()]
                          ).pack(side="left")
            ctk.CTkButton(bf, text="Cerrar",
                          fg_color="transparent", border_width=1, border_color=BORDER,
                          text_color=TEXT_MUTED, hover_color=BG_ELEVATED,
                          font=ctk.CTkFont(size=11),
                          command=self._close_overlay).pack(side="right")
        self._show_overlay(build, width=460)

    def _build_tabs(self):
        self.tabs_bar = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=40)
        self.tabs_bar.pack(fill="x")
        self.tabs_bar.pack_propagate(False)
        ctk.CTkFrame(self.tabs_bar, fg_color=BORDER, height=1,
                     corner_radius=0).pack(fill="x", side="bottom")
        inner = ctk.CTkFrame(self.tabs_bar, fg_color="transparent")
        inner.pack(side="left", padx=8, fill="y")
        self._tab_btns = []
        for i, name in enumerate(TAB_NAMES):
            btn = ctk.CTkButton(inner, text=name, width=120, height=38,
                                fg_color="transparent", hover_color=BG_ELEVATED,
                                text_color=TEXT_MUTED, font=ctk.CTkFont(size=11),
                                corner_radius=0,
                                command=lambda i=i: self._switch_tab(i))
            btn.pack(side="left", padx=1)
            self._tab_btns.append(btn)
        self._tab_indicator = ctk.CTkFrame(self.tabs_bar, fg_color=ACCENT,
                                            height=2, corner_radius=0, width=120)
        self._tab_indicator.place(x=9, y=38)

    def _switch_tab(self, idx):
        self._active_tab = idx
        for i, btn in enumerate(self._tab_btns):
            btn.configure(text_color=TEXT_PRIMARY if i==idx else TEXT_MUTED)
        self._tab_indicator.place(x=9+idx*122, y=38)
        for i, f in enumerate(self._tab_frames):
            if i==idx: f.pack(fill="both", expand=True)
            else: f.pack_forget()

    def _build_content(self):
        self.content = ctk.CTkFrame(self, fg_color=BG_ROOT)
        self.content.pack(fill="both", expand=True)
        for builder in [self._build_tab_editor, self._build_tab_texto,
                        self._build_tab_historial]:
            f = ctk.CTkFrame(self.content, fg_color="transparent")
            builder(f)
            self._tab_frames.append(f)

    # ── Tab 0: Editor (Video + Cortes + Timeline) ─────────────────────────────
    def _build_tab_editor(self, parent):
        # Layout: top area + timeline bottom
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)
        parent.columnconfigure(0, weight=1)

        # Top area
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8,4))
        top.columnconfigure(0, weight=2)
        top.columnconfigure(1, weight=3)
        top.rowconfigure(0, weight=1)

        # ── Panel izquierdo: Reproductor ──
        left = self._card(top)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,5))

        self._sec(left, "ARCHIVO DE VIDEO")
        drop = ctk.CTkFrame(left, fg_color=BG_INPUT, corner_radius=8,
                            border_width=1, border_color=BORDER_LIGHT, height=60)
        drop.pack(fill="x", padx=12, pady=(0,6))
        drop.pack_propagate(False)
        self.drop_label = ctk.CTkLabel(drop, text="Arrastra el video aquí",
                                        font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        self.drop_label.pack(expand=True)
        drop.bind("<Button-1>", lambda e: self._browse_video())
        self.drop_label.bind("<Button-1>", lambda e: self._browse_video())
        ctk.CTkButton(left, text="Seleccionar archivo",
                      fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=BG_ROOT,
                      height=32, font=ctk.CTkFont(size=11, weight="bold"),
                      command=self._browse_video).pack(fill="x", padx=12, pady=(0,2))
        ctk.CTkButton(left, text="✕  Quitar video",
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT_MUTED, hover_color="#2b0d0d",
                      height=26, font=ctk.CTkFont(size=10),
                      command=self._reset_all).pack(fill="x", padx=12, pady=(0,6))

        # Selector proporción
        ratio_row = ctk.CTkFrame(left, fg_color="transparent")
        ratio_row.pack(fill="x", padx=12, pady=(0,4))
        ctk.CTkLabel(ratio_row, text="Proporción:",
                     font=ctk.CTkFont(size=10), text_color=TEXT_MUTED).pack(side="left", padx=(0,6))
        self._ratio_var = ctk.StringVar(value=self.settings.get("player_ratio", PLAYER_RATIO_DEFAULT))
        for ratio in PLAYER_RATIOS:
            ctk.CTkRadioButton(ratio_row, text=ratio,
                               variable=self._ratio_var, value=ratio,
                               radiobutton_width=11, radiobutton_height=11,
                               fg_color=ACCENT, hover_color=ACCENT_DIM,
                               font=ctk.CTkFont(size=10), text_color=TEXT_SEC,
                               command=self._on_ratio_change).pack(side="left", padx=4)

        # VLC frame - altura fija para que los controles siempre sean visibles
        self.vlc_frame = ctk.CTkFrame(left, fg_color="#000000", corner_radius=8, height=280)
        self.vlc_frame.pack(fill="x", padx=12, pady=(0,4))
        self.vlc_frame.pack_propagate(False)
        self.vlc_placeholder = ctk.CTkLabel(self.vlc_frame, text="Sin video",
                                             fg_color="transparent",
                                             text_color=TEXT_MUTED, font=ctk.CTkFont(size=12))
        self.vlc_placeholder.place(relx=0.5, rely=0.5, anchor="center")

        # Controles reproductor
        self.player_var = ctk.DoubleVar(value=0)
        self.player_slider = ctk.CTkSlider(left, from_=0, to=100,
                                            variable=self.player_var,
                                            progress_color=ACCENT, button_color=ACCENT,
                                            button_hover_color=ACCENT_DIM,
                                            height=10, command=self._on_seek)
        self.player_slider.pack(fill="x", padx=12, pady=(0,4))
        ctrl = ctk.CTkFrame(left, fg_color="transparent")
        ctrl.pack(fill="x", padx=12, pady=(0,4))
        # Prev/Next cut buttons
        ctk.CTkButton(ctrl, text="⏮", width=28, height=28,
                      fg_color=BG_ELEVATED, hover_color=BG_CARD,
                      text_color=TEXT_SEC, font=ctk.CTkFont(size=11),
                      command=self._go_prev_cut).pack(side="left", padx=(0,2))
        self.play_btn = ctk.CTkButton(ctrl, text="▶", width=34, height=30,
                                       fg_color=ACCENT, hover_color=ACCENT_DIM,
                                       text_color=BG_ROOT, font=ctk.CTkFont(size=12),
                                       command=self._toggle_play)
        self.play_btn.pack(side="left", padx=(0,2))
        ctk.CTkButton(ctrl, text="⏭", width=28, height=28,
                      fg_color=BG_ELEVATED, hover_color=BG_CARD,
                      text_color=TEXT_SEC, font=ctk.CTkFont(size=11),
                      command=self._go_next_cut).pack(side="left", padx=(0,4))
        self.mute_btn = ctk.CTkButton(ctrl, text="🔊", width=28, height=28,
                                       fg_color=BG_ELEVATED, hover_color=BG_CARD,
                                       font=ctk.CTkFont(size=11),
                                       command=self._toggle_mute)
        self.mute_btn.pack(side="left", padx=(0,4))
        self.time_lbl = ctk.CTkLabel(ctrl, text="0:00 / -0:00",
                                      font=ctk.CTkFont(size=10, family="Courier"),
                                      text_color=ACCENT_DIM)
        self.time_lbl.pack(side="left")

        # Fila 2: velocidad + usar tiempo
        ctrl2 = ctk.CTkFrame(left, fg_color="transparent")
        ctrl2.pack(fill="x", padx=12, pady=(0,8))
        ctk.CTkLabel(ctrl2, text="Vel:", font=ctk.CTkFont(size=10),
                     text_color=TEXT_MUTED).pack(side="left", padx=(0,4))
        self._speed_var = ctk.StringVar(value="1x")
        for spd in ["0.5x","1x","1.5x","2x"]:
            ctk.CTkButton(ctrl2, text=spd, width=36, height=22,
                          fg_color=ACCENT if spd=="1x" else BG_ELEVATED,
                          hover_color=ACCENT_DIM,
                          text_color=BG_ROOT if spd=="1x" else TEXT_SEC,
                          font=ctk.CTkFont(size=9),
                          command=lambda s=spd: self._set_speed(s)
                          ).pack(side="left", padx=1)
        ctk.CTkButton(ctrl2, text="✂  Usar tiempo", height=24,
                      fg_color=BG_ELEVATED, border_width=1, border_color=BORDER_LIGHT,
                      text_color=TEXT_SEC, hover_color=BG_CARD, font=ctk.CTkFont(size=9),
                      command=self._use_current_time).pack(side="right")

        self.after(200, self._init_vlc)

        # ── Panel derecho: Cortes + Info ──
        right = self._card(top)
        right.grid(row=0, column=1, sticky="nsew", padx=(5,0))
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)
        right.rowconfigure(0, weight=1)

        # Info video (arriba izquierda)
        info_panel = ctk.CTkFrame(right, fg_color="transparent")
        info_panel.grid(row=0, column=0, sticky="nsew", padx=(0,4))
        self._sec(info_panel, "INFORMACIÓN DEL VIDEO")
        info_card = ctk.CTkFrame(info_panel, fg_color=BG_ELEVATED, corner_radius=8,
                                  border_width=1, border_color=BORDER)
        info_card.pack(fill="x", padx=12, pady=(0,8))
        self.info_labels = {}
        for i,(lbl,key) in enumerate([("Archivo","name"),("Duración","duration"),
                                       ("Resolución","resolution"),("FPS","fps"),
                                       ("Codec","codec"),("Audio","audio")]):
            bg = BG_ELEVATED if i%2==0 else BG_CARD
            row = ctk.CTkFrame(info_card, fg_color=bg, corner_radius=0)
            row.pack(fill="x")
            ctk.CTkLabel(row, text=lbl, width=75, anchor="w",
                         font=ctk.CTkFont(size=10), text_color=TEXT_MUTED
                         ).pack(side="left", padx=(8,0), pady=3)
            val = ctk.CTkLabel(row, text="—", anchor="w",
                               font=ctk.CTkFont(size=10), text_color=TEXT_PRIMARY)
            val.pack(side="left", padx=3)
            self.info_labels[key] = val

        # Cortes (arriba derecha)
        cuts_panel = ctk.CTkFrame(right, fg_color="transparent")
        cuts_panel.grid(row=0, column=1, sticky="nsew", padx=(4,0))
        self._sec(cuts_panel, "DURACIÓN DE LA INTRO")
        intro_row = ctk.CTkFrame(cuts_panel, fg_color="transparent")
        intro_row.pack(fill="x", padx=12, pady=(0,6))
        self.intro_entry = self._entry(intro_row, "Ej: 0:15.30", width=140)
        self.intro_entry.pack(side="left", padx=(0,6))
        self._help(intro_row, "Tiempo donde termina la intro.\nFormato: MM:SS.cc")

        self._sec(cuts_panel, "TIEMPOS DE CORTE")
        self.cuts_frame = ctk.CTkFrame(cuts_panel, fg_color="transparent")
        self.cuts_frame_scroll = ctk.CTkScrollableFrame(cuts_panel, fg_color="transparent",
                                                         scrollbar_button_color=BORDER, height=140)
        self.cuts_frame_scroll.pack(fill="x", padx=12)
        self.cuts_frame = self.cuts_frame_scroll
        self._add_cut()
        ctk.CTkButton(cuts_panel, text="＋  Agregar corte",
                      fg_color="transparent", border_width=1, border_color=BORDER_LIGHT,
                      text_color=TEXT_SEC, hover_color=BG_ELEVATED,
                      height=30, font=ctk.CTkFont(size=10),
                      command=self._add_cut).pack(fill="x", padx=12, pady=(4,4))

        self._sec(cuts_panel, "SEGMENTOS")
        self.segments_scroll = ctk.CTkScrollableFrame(cuts_panel, fg_color="transparent",
                                                       scrollbar_button_color=BORDER)
        self.segments_scroll.pack(fill="both", expand=True, padx=12, pady=(0,8))

        # ── Línea de tiempo (parte inferior, ancho completo) ──
        tl_container = ctk.CTkFrame(parent, fg_color=BG_TL, corner_radius=0,
                                     border_width=1, border_color=BORDER, height=TL_H+30)
        tl_container.grid(row=1, column=0, sticky="ew", padx=8, pady=(0,8))
        tl_container.pack_propagate(False)
        tl_container.grid_propagate(False)

        # Barra superior de la TL con controles
        tl_top = ctk.CTkFrame(tl_container, fg_color=BG_CARD, corner_radius=0, height=28)
        tl_top.pack(fill="x")
        tl_top.pack_propagate(False)
        ctk.CTkLabel(tl_top, text="LÍNEA DE TIEMPO",
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=TEXT_MUTED).pack(side="left", padx=10)
        ctk.CTkLabel(tl_top, text="Rueda del ratón = zoom  ·  Arrastra marcadores  ·  Doble clic = nuevo corte",
                     font=ctk.CTkFont(size=9), text_color=TEXT_MUTED).pack(side="left", padx=4)
        ctk.CTkButton(tl_top, text="↺", width=24, height=20,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT_MUTED, hover_color=BG_ELEVATED,
                      font=ctk.CTkFont(size=10),
                      command=self._tl_reset_zoom).pack(side="right", padx=6)
        self._zoom_lbl = ctk.CTkLabel(tl_top, text="1.0x",
                                       font=ctk.CTkFont(size=9, family="Courier"),
                                       text_color=ACCENT_DIM)
        self._zoom_lbl.pack(side="right", padx=4)

        # Canvas principal de la línea de tiempo
        self.tl_canvas = tk.Canvas(tl_container, bg=BG_TL,
                                    highlightthickness=0, cursor="crosshair")
        self.tl_canvas.pack(fill="both", expand=True)

        # Bindings
        self.tl_canvas.bind("<MouseWheel>",       self._tl_scroll_zoom)
        self.tl_canvas.bind("<Button-1>",         self._tl_click)
        self.tl_canvas.bind("<B1-Motion>",        self._tl_drag)
        self.tl_canvas.bind("<ButtonRelease-1>",  self._tl_release)
        self.tl_canvas.bind("<Double-Button-1>",  self._tl_double_click)
        self.tl_canvas.bind("<Motion>",           self._tl_hover)
        self.tl_canvas.bind("<Leave>",            lambda e: self._tl_draw())
        self.tl_canvas.bind("<Configure>",        lambda e: self._tl_draw())

    # ── Proporción reproductor ────────────────────────────────────────────────
    def _on_ratio_change(self):
        ratio = self._ratio_var.get()
        self.settings["player_ratio"] = ratio
        save_settings(self.settings)
        self._apply_ratio()
        if self._vlc and self._vlc._ok and self.video_path:
            self.after(100, lambda: [self._vlc.load(self.video_path),
                                     self._vlc.play(),
                                     self.after(300, lambda: self._vlc.pause())])

    def _apply_ratio(self):
        ratio = self._ratio_var.get() if self._ratio_var else PLAYER_RATIO_DEFAULT
        w_parts, h_parts = PLAYER_RATIOS.get(ratio, (9,16))
        self.update_idletasks()
        pw = self.vlc_frame.winfo_width() or 300
        if pw < 50: pw = 300
        h = int(pw * h_parts / w_parts)
        h = max(120, min(h, 360))
        self.vlc_frame.configure(height=h)

    def _auto_detect_ratio(self):
        w = self.video_info.get("width", 0)
        h = self.video_info.get("height", 0)
        if w > 0 and h > 0:
            ratio = "9:16" if h > w else ("16:9" if w > h else "1:1")
            if self._ratio_var:
                self._ratio_var.set(ratio)
            self._apply_ratio()

    # ── VLC ───────────────────────────────────────────────────────────────────
    def _init_vlc(self):
        self._vlc = VLCPlayer(self.vlc_frame)
        if not self._vlc._ok:
            self.vlc_placeholder.configure(text="python-vlc no disponible\npip install python-vlc")

    def _start_player_loop(self):
        if self._player_job: self.after_cancel(self._player_job)
        self._player_loop()

    def _player_loop(self):
        if self._vlc and self._vlc._ok:
            t = self._vlc.get_time()
            d = self._vlc.get_duration()
            if d > 0:
                self.player_var.set(t/d*100)
                remaining = d - t
                self.time_lbl.configure(
                    text=f"{seconds_to_str(t)} / -{seconds_to_str(remaining)}")
                self._player_time = t
                self._playhead_sec = t
                self._tl_draw()
            self.play_btn.configure(text="⏸" if self._vlc.is_playing() else "▶")
        self._player_job = self.after(200, self._player_loop)

    def _set_speed(self, spd_str):
        self._speed_var.set(spd_str)
        rate = float(spd_str.replace("x",""))
        if self._vlc and self._vlc._ok and self._vlc.player:
            try: self._vlc.player.set_rate(rate)
            except: pass
        # Actualizar estilos botones velocidad
        for widget in self.winfo_children():
            pass  # los botones se actualizan al recrear, suficiente con el comando

    def _go_prev_cut(self):
        cuts = self._get_cuts()
        if not cuts: return
        t = self._player_time
        prev = [c for c in cuts if c < t - 0.5]
        target = prev[-1] if prev else 0.0
        self._seek_player(target)

    def _go_next_cut(self):
        cuts = self._get_cuts()
        if not cuts: return
        t = self._player_time
        nxt = [c for c in cuts if c > t + 0.5]
        if nxt: self._seek_player(nxt[0])

    def _seek_player(self, sec):
        if self._vlc and self._vlc._ok:
            d = self._vlc.get_duration()
            self._vlc.set_time(sec)
            self._player_time = sec
            self._playhead_sec = sec
            remaining = d - sec if d > 0 else 0
            self.time_lbl.configure(
                text=f"{seconds_to_str(sec)} / -{seconds_to_str(remaining)}")
            self.player_var.set(sec / max(d,1) * 100)
            self._tl_draw()

    def _on_seek(self, value):
        if self._vlc and self._vlc._ok:
            d = self._vlc.get_duration()
            if d > 0:
                t = float(value)/100.0*d
                self._vlc.set_time(t)
                self._player_time = t
                self._playhead_sec = t
                self.time_lbl.configure(text=seconds_to_str(t))
                self._tl_draw()

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
            self.cuts_entries[-1].delete(0,"end")
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
            self._toast("No se encontró el archivo","error"); return
        self.video_path = path
        name = os.path.basename(path)
        self.drop_label.configure(text=f"✦  {name[:28]}", text_color=ACCENT_DIM,
                                   font=ctk.CTkFont(size=10, weight="bold"))
        if self.ffprobe_path:
            info = get_video_info(path, self.ffprobe_path)
            self.video_info = info
            self.info_labels["name"].configure(text=name[:24])
            self.info_labels["duration"].configure(text=format_duration(info.get("duration",0)))
            self.info_labels["resolution"].configure(
                text=f"{info.get('width','?')}×{info.get('height','?')}")
            self.info_labels["fps"].configure(text=f"{info.get('fps','?')} fps")
            self.info_labels["codec"].configure(text=info.get("video_codec","—").upper())
            self.info_labels["audio"].configure(text=info.get("audio_codec","—"))
        if self._vlc and self._vlc._ok:
            self.vlc_placeholder.place_forget()
            self._vlc.load(path)
            self._vlc.play()
            self.after(400, lambda: self._vlc.pause())
            self._start_player_loop()
        self._auto_detect_ratio()
        # Reset timeline
        self._zoom = 1.0
        self._tl_offset = 0.0
        self._playhead_sec = 0.0
        self._waveform_data = []
        self._tl_draw()
        self._update_segments()
        # Generar waveform en background
        threading.Thread(target=self._generate_waveform, daemon=True).start()
        self._toast(f"Video cargado: {name[:26]}","success")

    # ── Cortes ────────────────────────────────────────────────────────────────
    def _add_cut(self):
        idx = len(self.cuts_entries)+1
        row = ctk.CTkFrame(self.cuts_frame, fg_color=BG_ELEVATED, corner_radius=6,
                           border_width=1, border_color=BORDER)
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=f"Corte {idx}",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_SEC, width=52, anchor="w"
                     ).pack(side="left", padx=(8,0), pady=6)
        entry = self._entry(row, "MM:SS.cc", width=160)
        entry.pack(side="left", padx=6, pady=4)
        entry.bind("<FocusOut>", lambda e: self._on_cuts_changed())
        entry.bind("<Return>",   lambda e: self._on_cuts_changed())
        ctk.CTkButton(row, text="✕", width=22, height=22,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT_MUTED, hover_color="#3a0a0a",
                      font=ctk.CTkFont(size=9),
                      command=lambda r=row,e=entry: self._remove_cut(r,e)
                      ).pack(side="right", padx=6)
        self.cuts_entries.append(entry)
        self._on_cuts_changed()

    def _remove_cut(self, row, entry):
        if len(self.cuts_entries)<=1: return
        self.cuts_entries.remove(entry)
        row.destroy()
        self._renumber_cuts()
        self._on_cuts_changed()

    def _renumber_cuts(self):
        for i,e in enumerate(self.cuts_entries):
            for c in e.master.winfo_children():
                if isinstance(c, ctk.CTkLabel) and "Corte" in str(c.cget("text")):
                    c.configure(text=f"Corte {i+1}",
                                font=ctk.CTkFont(size=11, weight="bold"),
                                text_color=TEXT_SEC)
                    break

    def _get_cuts(self):
        return sorted([t for e in self.cuts_entries
                       if (t:=parse_time(e.get().strip())) is not None])

    def _on_cuts_changed(self):
        if hasattr(self, "tl_canvas"): self._tl_draw()
        self._update_segments()
        self._refresh_process_btn()

    # ── Segmentos ─────────────────────────────────────────────────────────────
    def _update_segments(self):
        if not hasattr(self,"segments_scroll"): return
        for w in self.segments_scroll.winfo_children(): w.destroy()
        duration = self.video_info.get("duration",0)
        cuts = self._get_cuts()
        if duration<=0 or not cuts: return
        intro_t = parse_time(self.intro_entry.get()) or 0.0
        warn_dur = self.settings.get("warn_max_duration",600)
        warn_mb  = self.settings.get("warn_max_size_mb",500)
        durs = get_segment_durations(cuts, duration)
        total = len(durs)
        points = [0.0]+cuts+[duration]
        for idx,dur in enumerate(durs):
            pn=idx+1; lbl="Parte Final" if pn==total else f"Parte {pn}"
            td=intro_t+dur; mb=estimate_segment_size_mb(td)
            over=td>warn_dur or mb>warn_mb
            row=ctk.CTkFrame(self.segments_scroll,fg_color=BG_ELEVATED,corner_radius=5,
                              border_width=1,border_color=DANGER if over else BORDER)
            row.pack(fill="x",pady=2)
            ctk.CTkFrame(row,fg_color=SEGMENT_COLORS[idx%len(SEGMENT_COLORS)],
                         width=3,corner_radius=0).pack(side="left",fill="y")
            # Miniatura
            seg_start = points[idx]
            thumb_lbl = ctk.CTkLabel(row, text="", fg_color=BG_INPUT,
                                      width=36, height=28, corner_radius=3)
            thumb_lbl.pack(side="left", padx=(4,4), pady=3)
            thumb_lbl.bind("<Button-1>", lambda e,t=seg_start: self._seek_to(t))
            if self.video_path and self.ffmpeg_path:
                threading.Thread(target=self._load_thumb,
                                 args=(thumb_lbl, seg_start), daemon=True).start()
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(info,text=lbl,font=ctk.CTkFont(size=10,weight="bold"),
                         text_color=TEXT_PRIMARY,anchor="w").pack(anchor="w")
            ctk.CTkLabel(info,text=f"{format_duration(td)}  ~{mb:.0f}MB",
                         font=ctk.CTkFont(size=9,family="Courier"),
                         text_color=DANGER if over else TEXT_SEC).pack(anchor="w")
            ctk.CTkButton(row,text="▶",width=26,height=26,
                          fg_color=BG_CARD,border_width=1,border_color=BORDER_LIGHT,
                          text_color=TEXT_SEC,hover_color=BG_ELEVATED,
                          font=ctk.CTkFont(size=9),
                          command=lambda p=pn: self._export_single_part(p)
                          ).pack(side="right",padx=6)

    def _load_thumb(self, label, time_sec):
        try:
            tmp = tempfile.mktemp(suffix=".png")
            if extract_frame(self.video_path, time_sec, tmp, self.ffmpeg_path):
                img = Image.open(tmp)
                img.thumbnail((36,28))
                photo = ctk.CTkImage(light_image=img, dark_image=img, size=(36,28))
                self.after(0, lambda: label.configure(image=photo, text=""))
                label._thumb_image = photo
                try: os.unlink(tmp)
                except: pass
        except: pass

    def _seek_to(self, time_sec):
        if self._vlc and self._vlc._ok:
            self._vlc.set_time(time_sec)
            self._player_time = time_sec
            self._playhead_sec = time_sec
            self.time_lbl.configure(text=seconds_to_str(time_sec))
            self.player_var.set(time_sec / max(self._vlc.get_duration(),1) * 100)
            self._tl_draw()
            self._toast(f"Reproductor → {seconds_to_str(time_sec)}", "info")

    # ── Línea de tiempo ───────────────────────────────────────────────────────
    def _tl_sec_to_x(self, sec, canvas_w, duration):
        if duration <= 0: return 0
        visible = duration / self._zoom
        frac = (sec - self._tl_offset) / visible
        return int(frac * canvas_w)

    def _tl_x_to_sec(self, x, canvas_w, duration):
        if duration <= 0: return 0
        visible = duration / self._zoom
        return max(0, min(self._tl_offset + (x / canvas_w) * visible, duration))

    def _tl_clamp_offset(self, duration):
        visible = duration / self._zoom
        self._tl_offset = max(0, min(self._tl_offset, duration - visible))

    def _tl_reset_zoom(self):
        self._zoom = 1.0
        self._tl_offset = 0.0
        self._zoom_lbl.configure(text="1.0x")
        self._tl_draw()

    def _tl_scroll_zoom(self, event):
        duration = self.video_info.get("duration", 0)
        if duration <= 0: return
        w = self.tl_canvas.winfo_width() or 800
        # Centro del zoom = posición del cursor
        sec_at_cursor = self._tl_x_to_sec(event.x, w, duration)
        factor = 1.15 if event.delta > 0 else 1/1.15
        self._zoom = max(1.0, min(self._zoom * factor, 50.0))
        # Mantener el punto bajo el cursor fijo
        visible = duration / self._zoom
        self._tl_offset = sec_at_cursor - (event.x / w) * visible
        self._tl_clamp_offset(duration)
        self._zoom_lbl.configure(text=f"{self._zoom:.1f}x")
        self._tl_draw()

    def _tl_click(self, event):
        duration = self.video_info.get("duration", 0)
        if duration <= 0: return
        w = self.tl_canvas.winfo_width() or 800
        cuts = self._get_cuts()
        THRESH = 8
        # ¿Cerca del playhead?
        ph_x = self._tl_sec_to_x(self._playhead_sec, w, duration)
        if abs(event.x - ph_x) <= THRESH:
            self._dragging_playhead = True
            self.tl_canvas.configure(cursor="sb_h_double_arrow")
            return
        # ¿Cerca de un corte?
        for i, cut in enumerate(cuts):
            cx = self._tl_sec_to_x(cut, w, duration)
            if abs(event.x - cx) <= THRESH:
                self._dragging_cut_idx = i
                self.tl_canvas.configure(cursor="sb_h_double_arrow")
                return
        # Clic libre → mover playhead
        sec = self._tl_x_to_sec(event.x, w, duration)
        self._playhead_sec = sec
        self._player_time = sec
        if self._vlc and self._vlc._ok:
            self._vlc.set_time(sec)
            self.player_var.set(sec / duration * 100)
            self.time_lbl.configure(text=seconds_to_str(sec))
        self._tl_draw()

    def _tl_drag(self, event):
        duration = self.video_info.get("duration", 0)
        if duration <= 0: return
        w = self.tl_canvas.winfo_width() or 800
        sec = self._tl_x_to_sec(event.x, w, duration)
        if self._dragging_playhead:
            self._playhead_sec = sec
            self._player_time = sec
            self._drag_cursor_x = event.x
            if self._vlc and self._vlc._ok:
                self._vlc.set_time(sec)
                d = self._vlc.get_duration()
                remaining = d - sec if d > 0 else 0
                self.player_var.set(sec / max(d,1) * 100)
                self.time_lbl.configure(
                    text=f"{seconds_to_str(sec)} / -{seconds_to_str(remaining)}")
            self._tl_draw()
        elif self._dragging_cut_idx is not None:
            self._drag_cursor_x = event.x
            if self._dragging_cut_idx < len(self.cuts_entries):
                sorted_entries = sorted(self.cuts_entries,
                    key=lambda e: parse_time(e.get().strip()) or 0)
                if self._dragging_cut_idx < len(sorted_entries):
                    entry = sorted_entries[self._dragging_cut_idx]
                    entry.delete(0,"end")
                    entry.insert(0, seconds_to_str(round(sec,2)))
            self._on_cuts_changed()

    def _tl_release(self, event):
        was_dragging_cut = self._dragging_cut_idx is not None
        release_x = event.x
        self._dragging_playhead = False
        self._dragging_cut_idx = None
        self._drag_cursor_x = -1
        self.tl_canvas.configure(cursor="crosshair")
        # Mostrar miniatura del frame al soltar si estaba arrastrando corte
        if was_dragging_cut and self.video_path and self.ffmpeg_path:
            duration = self.video_info.get("duration", 0)
            w = self.tl_canvas.winfo_width() or 800
            sec = self._tl_x_to_sec(release_x, w, duration)
            self._show_hover_thumb(release_x, sec)
        self._tl_draw()

    def _tl_double_click(self, event):
        duration = self.video_info.get("duration", 0)
        if duration <= 0: return
        w = self.tl_canvas.winfo_width() or 800
        sec = self._tl_x_to_sec(event.x, w, duration)
        self._add_cut()
        if self.cuts_entries:
            self.cuts_entries[-1].delete(0,"end")
            self.cuts_entries[-1].insert(0, seconds_to_str(round(sec,2)))
        self._on_cuts_changed()
        self._toast(f"Corte en {seconds_to_str(sec)}", "info")

    def _tl_hover(self, event):
        self._tl_hover_sec = self._tl_x_to_sec(
            event.x,
            self.tl_canvas.winfo_width() or 800,
            self.video_info.get("duration", 0))
        duration = self.video_info.get("duration", 0)
        cuts = self._get_cuts()
        w = self.tl_canvas.winfo_width() or 800
        THRESH = 8
        ph_x = self._tl_sec_to_x(self._playhead_sec, w, duration)
        near = abs(event.x - ph_x) <= THRESH or any(
            abs(event.x - self._tl_sec_to_x(c, w, duration)) <= THRESH for c in cuts)
        self.tl_canvas.configure(cursor="sb_h_double_arrow" if near else "crosshair")
        self._tl_draw()

    def _tl_draw(self):
        if not hasattr(self, "tl_canvas"): return
        c = self.tl_canvas
        w = c.winfo_width() or 800
        h = c.winfo_height() or TL_H
        if w < 10 or h < 10: return

        duration = self.video_info.get("duration", 0)

        # Fondo
        c.create_rectangle(0, 0, w, h, fill=BG_TL, outline="")

        if duration <= 0:
            c.create_text(w//2, h//2,
                          text="Carga un video para ver la línea de tiempo  ·  Doble clic = nuevo corte",
                          fill=TEXT_MUTED, font=("Courier", 13))
            return

        # Zonas verticales (sin miniaturas)
        ruler_y1, ruler_y2 = 0, TL_RULER_H
        wave_y1,  wave_y2  = TL_RULER_H, TL_RULER_H+TL_WAVE_H
        seg_y1,   seg_y2   = wave_y2, wave_y2+TL_SEG_H

        # ── Regla de tiempo ───────────────────────────────────────────────────
        c.create_rectangle(0, ruler_y1, w, ruler_y2, fill="#1a1612", outline="")
        visible = duration / self._zoom
        # Calcular intervalo de ticks legible
        raw_interval = visible / 10
        nice = [0.5,1,2,5,10,15,30,60,120,300,600]
        interval = next((n for n in nice if n >= raw_interval), nice[-1])
        start_t = (self._tl_offset // interval) * interval
        t = start_t
        while t <= self._tl_offset + visible + interval:
            x = self._tl_sec_to_x(t, w, duration)
            if 0 <= x <= w:
                c.create_line(x, ruler_y2-10, x, ruler_y2, fill=TEXT_MUTED, width=1)
                mins = int(t)//60; secs = int(t)%60
                label = f"{mins}:{secs:02d}"
                c.create_text(x+4, ruler_y1+12, text=label,
                               fill=TEXT_SEC, font=("Courier", 12), anchor="w")
            t += interval

        # ── Onda de audio ─────────────────────────────────────────────────────
        c.create_rectangle(0, wave_y1, w, wave_y2, fill="#0e1a0e", outline="")
        wave_center = (wave_y1+wave_y2)//2
        wave_half = (wave_y2-wave_y1)//2 - 2
        if self._waveform_data:
            total_s = len(self._waveform_data)
            start_idx = int(self._tl_offset / duration * total_s)
            end_idx   = int((self._tl_offset+visible) / duration * total_s)
            end_idx   = min(end_idx+1, total_s)
            visible_s = self._waveform_data[start_idx:end_idx]
            if visible_s:
                for px in range(w):
                    si = int(px/w * len(visible_s))
                    val = visible_s[si] if si < len(visible_s) else 0
                    bar = max(1, int(val * wave_half))
                    c.create_line(px, wave_center-bar, px, wave_center+bar,
                                  fill="#2a6e2a", width=1)
        else:
            c.create_line(0, wave_center, w, wave_center, fill="#1a3a1a", width=1)
            c.create_text(w//2, wave_center,
                          text="Generando onda de audio...", fill=TEXT_MUTED,
                          font=("Courier", 12))

        # ── Segmentos coloreados ───────────────────────────────────────────────
        c.create_rectangle(0, seg_y1, w, seg_y2, fill="#0a0e14", outline="")
        cuts = self._get_cuts()
        points = [0.0]+cuts+[duration]
        segs = [(points[i],points[i+1]) for i in range(len(points)-1)]
        for idx,(s,e) in enumerate(segs):
            x1 = self._tl_sec_to_x(s, w, duration)
            x2 = self._tl_sec_to_x(e, w, duration)
            x1 = max(0,x1); x2 = min(w,x2)
            if x2 <= x1: continue
            col = SEGMENT_COLORS[idx%len(SEGMENT_COLORS)]
            c.create_rectangle(x1+1, seg_y1+2, x2-1, seg_y2-2,
                                fill=col, outline="", stipple="")
            lbl = "FINAL" if idx==len(segs)-1 else f"P{idx+1}"
            if x2-x1 > 30:
                c.create_text((x1+x2)//2, (seg_y1+seg_y2)//2,
                               text=lbl, fill="#fff", font=("Courier", 12, "bold"))

        # ── Marcadores de corte ────────────────────────────────────────────────
        for i, cut in enumerate(cuts):
            x = self._tl_sec_to_x(cut, w, duration)
            if x < 0 or x > w: continue
            # Línea blanca
            c.create_line(x, ruler_y2, x, seg_y2, fill="#ffffff", width=2)
            # Handle triangular superior
            c.create_polygon(x-7, ruler_y2, x+7, ruler_y2, x, ruler_y2+10,
                             fill="#ffffff", outline=BG_TL)
            # Etiqueta de tiempo
            t_str = seconds_to_str(cut)
            tx = min(max(x-22, 2), w-72)
            c.create_rectangle(tx-2, ruler_y1+1, tx+68, ruler_y1+18,
                                fill="#1a1612", outline="")
            c.create_text(tx, ruler_y1+9, text=t_str, fill=ACCENT_DIM,
                           font=("Courier", 12), anchor="w")

        # ── Playhead blanco ────────────────────────────────────────────────────
        ph_x = self._tl_sec_to_x(self._playhead_sec, w, duration)
        if 0 <= ph_x <= w:
            # Línea vertical blanca
            c.create_line(ph_x, 0, ph_x, h, fill="#ffffff", width=2)
            # Cabeza triangular superior
            c.create_polygon(ph_x-8, 0, ph_x+8, 0, ph_x, 14,
                             fill="#ffffff", outline="")
            # Tiempo del playhead
            t_str = seconds_to_str(self._playhead_sec)
            tx = min(max(ph_x-26, 2), w-80)
            c.create_rectangle(tx-2, 2, tx+76, 18,
                                fill="#ffffff", outline="")
            c.create_text(tx, 10, text=t_str,
                           fill="#000000", font=("Courier", 12, "bold"), anchor="w")

        # ── Indicador de arrastre en tiempo real ──────────────────────────────
        if self._drag_cursor_x >= 0 and self._dragging_cut_idx is not None:
            c.create_line(self._drag_cursor_x, 0, self._drag_cursor_x, h,
                          fill="#ffdd88", width=2, dash=(4,2))
            drag_sec = self._tl_x_to_sec(self._drag_cursor_x, w, duration)
            c.create_rectangle(self._drag_cursor_x-34, 0, self._drag_cursor_x+56, 18,
                               fill="#ffdd88", outline="")
            c.create_text(self._drag_cursor_x-32, 9, text=seconds_to_str(drag_sec),
                          fill="#000000", font=("Courier",12,"bold"), anchor="w")

        # ── Tiempo en hover ────────────────────────────────────────────────────
        if hasattr(self,"_tl_hover_sec") and self._tl_hover_sec >= 0:
            hx = self._tl_sec_to_x(self._tl_hover_sec, w, duration)
            if 0 <= hx <= w:
                c.create_line(hx, ruler_y2, hx, seg_y2,
                              fill="#555544", width=1, dash=(2,3))

        # ── Bordes entre zonas ────────────────────────────────────────────────
        for y in [ruler_y2, wave_y2, seg_y2]:
            c.create_line(0, y, w, y, fill=BORDER, width=1)

    def _show_hover_thumb(self, x, sec):
        """Muestra miniatura del frame al soltar el marcador."""
        if not self.video_path or not self.ffmpeg_path: return
        def load():
            try:
                tmp = tempfile.mktemp(suffix=".jpg")
                flags = subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
                cmd = [self.ffmpeg_path, "-y", "-ss", str(sec),
                       "-i", self.video_path,
                       "-frames:v","1","-vf","scale=120:-1","-q:v","4", tmp]
                subprocess.run(cmd, capture_output=True, timeout=5, creationflags=flags)
                if os.path.isfile(tmp):
                    img = Image.open(tmp).convert("RGB")
                    img.thumbnail((120, 80))
                    photo = ImageTk.PhotoImage(img)
                    self.after(0, lambda: self._draw_hover_thumb(x, photo, sec))
                    try: os.unlink(tmp)
                    except: pass
            except: pass
        threading.Thread(target=load, daemon=True).start()

    def _draw_hover_thumb(self, x, photo, sec):
        """Dibuja la miniatura sobre la línea de tiempo."""
        if not hasattr(self,"tl_canvas"): return
        c = self.tl_canvas
        w = c.winfo_width() or 800
        tx = min(max(x - 60, 0), w - 125)
        c.delete("hover_thumb")
        c.create_rectangle(tx-2, TL_RULER_H+2, tx+122, TL_RULER_H+88,
                           fill=BG_TL, outline=ACCENT_DIM, tags="hover_thumb")
        c.create_image(tx, TL_RULER_H+4, image=photo, anchor="nw", tags="hover_thumb")
        c.create_text(tx+60, TL_RULER_H+74, text=seconds_to_str(sec),
                     fill=ACCENT_DIM, font=("Courier",8), tags="hover_thumb")
        self._hover_thumb_photo = photo
        # Auto-borrar después de 2 segundos
        self.after(2000, lambda: c.delete("hover_thumb") if hasattr(self,"tl_canvas") else None)

    # ── Generación de assets en background ───────────────────────────────────
    def _generate_waveform(self):
        if not self.video_path or not self.ffmpeg_path: return
        self._waveform_data = []
        try:
            cmd = [self.ffmpeg_path, "-y", "-i", self.video_path,
                   "-ac","1","-ar","8000","-f","s16le","-"]
            flags = subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
            result = subprocess.run(cmd, capture_output=True, timeout=60,
                                    creationflags=flags)
            if result.returncode==0 and result.stdout:
                raw = result.stdout
                n = len(raw)//2
                samples = struct.unpack(f"{n}h", raw[:n*2])
                chunk = max(1, n//800)
                waveform = []
                for i in range(0, n, chunk):
                    cd = samples[i:i+chunk]
                    if cd: waveform.append(max(abs(s) for s in cd)/32768.0)
                self._waveform_data = waveform
                self.after(0, self._tl_draw)
        except: pass

    # ── Proceso btn y log ─────────────────────────────────────────────────────
    def _refresh_process_btn(self):
        if not hasattr(self,"process_btn"): return
        ok = (bool(self.video_path) and
              parse_time(self.intro_entry.get()) is not None and
              len(self._get_cuts()) > 0)
        if ok:
            self.process_btn.configure(fg_color=SUCCESS, hover_color="#16a34a",
                                        text_color=BG_ROOT, text="✔  LISTO PARA PROCESAR")
        else:
            self.process_btn.configure(fg_color=ACCENT, hover_color=ACCENT_DIM,
                                        text_color=BG_ROOT, text="▶  PROCESAR VIDEO")

    def _clear_log(self):
        if hasattr(self,"log_box"):
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0","end")
            self.log_box.configure(state="disabled")

    # ── Tab 1: Texto ──────────────────────────────────────────────────────────
    def _build_tab_texto(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)
        left = self._card(parent)
        left.grid(row=0, column=0, sticky="nsew", padx=(8,4), pady=8)
        scroll = ctk.CTkScrollableFrame(left, fg_color="transparent",
                                         scrollbar_button_color=BORDER)
        scroll.pack(fill="both", expand=True, padx=1, pady=1)
        self._sec(scroll,"PRESET")
        preset_row = ctk.CTkFrame(scroll, fg_color="transparent")
        preset_row.pack(fill="x", padx=14, pady=(0,8))
        self.preset_var = ctk.StringVar(value=self.settings.get("text_preset_active","Por defecto"))
        self.preset_menu = ctk.CTkOptionMenu(preset_row, variable=self.preset_var,
                                              values=list(self.presets.keys()),
                                              command=self._load_preset,
                                              fg_color=BG_ELEVATED, button_color=ACCENT,
                                              button_hover_color=ACCENT_DIM,
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
        self._sec(scroll,"CONTROLES")
        self.text_controls = {}
        for key, lbl, mn, mx, default in [
            ("font_size","Tamaño fuente",20,250,80),
            ("outline_width","Grosor contorno",0,30,6),
            ("position_y_pct","Posición vertical %",5,95,15),
            ("opacity_pct","Opacidad %",10,100,100),
        ]:
            r = ctk.CTkFrame(scroll, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=(5,0))
            ctk.CTkLabel(r, text=lbl, font=ctk.CTkFont(size=11),
                         text_color=TEXT_SEC, anchor="w").pack(side="left")
            vl = ctk.CTkLabel(r, text=str(default),
                               font=ctk.CTkFont(size=11, family="Courier"),
                               text_color=ACCENT_DIM, width=34, anchor="e")
            vl.pack(side="right")
            sl = ctk.CTkSlider(scroll, from_=mn, to=mx, number_of_steps=mx-mn,
                                progress_color=ACCENT, button_color=ACCENT,
                                button_hover_color=ACCENT_DIM, fg_color=BG_INPUT, height=12)
            sl.set(default)
            sl.pack(fill="x", padx=14, pady=(2,0))
            sl.configure(command=lambda v,k=key,vl=vl: self._on_slider(k,v,vl))
            self.text_controls[key] = {"slider":sl,"label":vl}
        self._sec(scroll,"COLORES")
        cr = ctk.CTkFrame(scroll, fg_color="transparent")
        cr.pack(fill="x", padx=14, pady=(0,8))
        self.text_color_btn = ctk.CTkButton(cr, text="● Color texto",
                                             width=120, height=32,
                                             fg_color=BG_ELEVATED, border_width=1,
                                             border_color=BORDER,
                                             text_color=TEXT_DEFAULTS["color"],
                                             hover_color=BG_CARD, font=ctk.CTkFont(size=11),
                                             command=lambda: self._pick_color("color"))
        self.text_color_btn.pack(side="left", padx=(0,6))
        self.outline_color_btn = ctk.CTkButton(cr, text="● Contorno",
                                                width=100, height=32,
                                                fg_color=BG_ELEVATED, border_width=1,
                                                border_color=BORDER,
                                                text_color=TEXT_DEFAULTS["outline_color"],
                                                hover_color=BG_CARD, font=ctk.CTkFont(size=11),
                                                command=lambda: self._pick_color("outline_color"))
        self.outline_color_btn.pack(side="left")
        right = self._card(parent)
        right.grid(row=0, column=1, sticky="nsew", padx=(4,8), pady=8)
        self._sec(right,"VISTA PREVIA EN TIEMPO REAL")
        self.text_preview = ctk.CTkLabel(right, text="", fg_color=BG_INPUT, corner_radius=8)
        self.text_preview.pack(fill="both", expand=True, padx=14, pady=(0,14))
        self._update_preview()

    # ── Tab 3: Historial ──────────────────────────────────────────────────────
    def _build_tab_historial(self, parent):
        card = self._card(parent)
        card.pack(fill="both", expand=True, padx=8, pady=8)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14,4))
        self._sec(header,"HISTORIAL DE VIDEOS")
        ctk.CTkButton(header, text="🗑  Borrar todo", width=100, height=26,
                      fg_color="transparent", border_width=1, border_color="#5a2a2a",
                      text_color=DANGER, hover_color="#2b0d0d", font=ctk.CTkFont(size=10),
                      command=self._clear_all_history).pack(side="right")
        self.history_scroll = ctk.CTkScrollableFrame(card, fg_color="transparent",
                                                      scrollbar_button_color=BORDER)
        self.history_scroll.pack(fill="both", expand=True, padx=14, pady=(0,14))
        self._refresh_history_list()

    def _refresh_history_list(self):
        if not hasattr(self,"history_scroll"): return
        for w in self.history_scroll.winfo_children(): w.destroy()
        if not self.history:
            ctk.CTkLabel(self.history_scroll, text="Sin historial todavía.",
                         text_color=TEXT_MUTED, font=ctk.CTkFont(size=12)).pack(pady=30)
            return
        for he in self.history:
            row = ctk.CTkFrame(self.history_scroll, fg_color=BG_ELEVATED,
                               corner_radius=8, border_width=1, border_color=BORDER)
            row.pack(fill="x", pady=4)
            ctk.CTkFrame(row, fg_color=ACCENT, width=3, corner_radius=0
                         ).pack(side="left", fill="y")
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="both", expand=True, padx=12, pady=10)
            ctk.CTkLabel(info, text=he["name"][:40],
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=TEXT_PRIMARY, anchor="w").pack(anchor="w")
            ctk.CTkLabel(info,
                         text=f"{he['date']}  ·  {he['parts']} partes  ·  {he['duration']}",
                         font=ctk.CTkFont(size=10), text_color=TEXT_MUTED,
                         anchor="w").pack(anchor="w")
            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=8)
            ctk.CTkButton(btns, text="Cargar →", width=75, height=28,
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=BG_ROOT,
                          font=ctk.CTkFont(size=10),
                          command=lambda p=he["path"]: [self._load_video(p), self._switch_tab(0)]
                          ).pack(pady=(0,4))
            ctk.CTkButton(btns, text="✕", width=75, height=24,
                          fg_color="transparent", border_width=1, border_color="#5a2a2a",
                          text_color=DANGER, hover_color="#2b0d0d", font=ctk.CTkFont(size=10),
                          command=lambda h=he: self._delete_history_entry(h)).pack()

    def _clear_all_history(self):
        if messagebox.askyesno("Borrar historial","¿Borrar todo el historial?",icon="warning"):
            self.history = []
            save_history(self.history)
            self._refresh_history_list()
            self._toast("Historial borrado","info")

    def _delete_history_entry(self, entry):
        self.history = [h for h in self.history if h["path"]!=entry["path"]]
        save_history(self.history, self.settings.get("history_max",5))
        self._refresh_history_list()
        self._toast("Eliminado del historial","info")

    # ── Helpers UI ────────────────────────────────────────────────────────────
    def _card(self, parent):
        return ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=10,
                            border_width=1, border_color=BORDER)

    def _sec(self, parent, text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(10,4))
        ctk.CTkLabel(row, text=text, font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=TEXT_MUTED).pack(side="left")
        ctk.CTkFrame(row, fg_color=BORDER, height=1, corner_radius=0
                     ).pack(side="left", fill="x", expand=True, padx=(8,0), pady=5)

    def _entry(self, parent, placeholder="", width=180):
        return ctk.CTkEntry(parent, placeholder_text=placeholder, width=width,
                            fg_color=BG_INPUT, border_color=BORDER_LIGHT,
                            border_width=1, text_color=TEXT_PRIMARY,
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

    # ── Texto ─────────────────────────────────────────────────────────────────
    def _on_slider(self, key, value, label):
        label.configure(text=str(int(value)))
        self._update_preview()

    def _pick_color(self, target):
        current = self._text_color if target=="color" else self._outline_color
        color = colorchooser.askcolor(color=current, title="Elegir color")[1]
        if color:
            if target=="color":
                self._text_color=color; self.text_color_btn.configure(text_color=color)
            else:
                self._outline_color=color; self.outline_color_btn.configure(text_color=color)
            self._update_preview()

    def _update_preview(self):
        try:
            w,h=420,200
            img=Image.new("RGB",(w,h),color="#0a0806")
            draw=ImageDraw.Draw(img)
            fs=int(self.text_controls["font_size"]["slider"].get())
            ow=int(self.text_controls["outline_width"]["slider"].get())
            py=int(self.text_controls["position_y_pct"]["slider"].get())
            try: font=ImageFont.truetype(self.anton_path,fs) if self.anton_path else ImageFont.load_default()
            except: font=ImageFont.load_default()
            text="PARTE 1"
            bbox=draw.textbbox((0,0),text,font=font)
            tw,th=bbox[2]-bbox[0],bbox[3]-bbox[1]
            x=(w-tw)//2; y=max(4,int(h*py/100)-th//2)
            for dx in range(-ow,ow+1):
                for dy in range(-ow,ow+1):
                    if dx*dx+dy*dy<=ow*ow:
                        draw.text((x+dx,y+dy),text,font=font,fill=self._outline_color)
            draw.text((x,y),text,font=font,fill=self._text_color)
            photo=ctk.CTkImage(light_image=img,dark_image=img,size=(w,h))
            self.text_preview.configure(image=photo,text="")
            self.text_preview._image=photo
        except: pass

    def _get_text_cfg(self):
        return {
            "font_size":int(self.text_controls["font_size"]["slider"].get()),
            "color":self._text_color,
            "outline_color":self._outline_color,
            "outline_width":int(self.text_controls["outline_width"]["slider"].get()),
            "opacity":self.text_controls["opacity_pct"]["slider"].get()/100.0,
            "position_y":self.text_controls["position_y_pct"]["slider"].get()/100.0,
        }

    def _load_preset(self, name):
        p=self.presets.get(name,TEXT_DEFAULTS)
        self.text_controls["font_size"]["slider"].set(p.get("font_size",80))
        self.text_controls["outline_width"]["slider"].set(p.get("outline_width",6))
        self.text_controls["position_y_pct"]["slider"].set(int(p.get("position_y",0.15)*100))
        self.text_controls["opacity_pct"]["slider"].set(int(p.get("opacity",1.0)*100))
        self._text_color=p.get("color","#FFFFFF")
        self._outline_color=p.get("outline_color","#000000")
        self.text_color_btn.configure(text_color=self._text_color)
        self.outline_color_btn.configure(text_color=self._outline_color)
        for v in self.text_controls.values():
            v["label"].configure(text=str(int(v["slider"].get())))
        self._update_preview()

    def _save_preset(self):
        d=ctk.CTkInputDialog(text="Nombre del preset:",title="Guardar preset")
        name=d.get_input()
        if name and name.strip() and name.strip()!="Por defecto":
            self.presets[name.strip()]=self._get_text_cfg()
            save_presets(self.presets)
            self.preset_menu.configure(values=list(self.presets.keys()))
            self.preset_var.set(name.strip())
            self._toast(f"Preset '{name.strip()}' guardado","success")

    def _delete_preset(self):
        name=self.preset_var.get()
        if name=="Por defecto":
            self._toast("No puedes borrar el preset por defecto","warning"); return
        if name in self.presets:
            del self.presets[name]
            save_presets(self.presets)
            self.preset_menu.configure(values=list(self.presets.keys()))
            self.preset_var.set("Por defecto")
            self._load_preset("Por defecto")
            self._toast("Preset eliminado","info")

    # ── Exportación ───────────────────────────────────────────────────────────
    def _start_export(self):
        if not self.video_path:
            self._toast("Selecciona un video primero","error"); self._switch_tab(0); return
        intro_sec=parse_time(self.intro_entry.get())
        if intro_sec is None:
            self._toast("Configura la duración de la intro primero","error"); self._switch_tab(0); return
        cuts=self._get_cuts()
        if not cuts:
            self._toast("Agrega al menos un corte","error"); self._switch_tab(0); return
        duration=self.video_info.get("duration",0)
        if duration<=0:
            self._toast("No se pudo leer la duración del video","error"); return
        errors=validate_cuts(cuts,duration,intro_sec,30)
        if errors:
            msg="Problemas detectados:\n\n"+"\n".join(f"• {e}" for e in errors)
            if not messagebox.askyesno("Validación",msg+"\n\n¿Continuar?",icon="warning"): return
        total=len(cuts)+1
        durs=get_segment_durations(cuts,duration)
        lines=[f"Video: {os.path.basename(self.video_path)}",
               f"Partes: {total}  |  Intro: {format_duration(intro_sec)}",
               f"Preset: {self.speed_var.get()}",""]
        for i,d in enumerate(durs):
            lbl="Parte Final" if i+1==total else f"Parte {i+1}"
            lines.append(f"  {lbl}: {format_duration(intro_sec+d)}")
        if not messagebox.askyesno("Confirmar exportación","\n".join(lines)+"\n\n¿Comenzar?"): return
        out_dir=self.settings.get("output_dir",r"C:\Videos_Trabajo")
        vname=Path(self.video_path).stem
        out=Path(out_dir)/f"{vname}_partes"
        if out.exists():
            choice=messagebox.askyesnocancel("Carpeta existente",f"Ya existe:\n{out}\n\n¿Sobreescribir?")
            if choice is None: return
            if not choice:
                import shutil; shutil.rmtree(out)
        out.mkdir(parents=True,exist_ok=True)
        if self._vlc and self._vlc.is_playing(): self._vlc.pause()
        self.is_exporting=True
        self.export_start_time=time.time()
        self.engine.reset_cancel()
        self.export_results=[]
        self.log_entries=[f"Inicio: {datetime.now()}",f"Video: {self.video_path}",
                           f"Partes: {total}"]
        threading.Thread(target=self._export_thread,
                         args=(cuts,intro_sec,duration,out,total),daemon=True).start()

    def _export_thread(self,cuts,intro_sec,duration,out_folder,total):
        text_cfg=self._get_text_cfg()
        speed=self.speed_var.get()
        points=[0.0]+cuts+[duration]
        for idx in range(total):
            if self.engine.is_cancelled(): break
            pn=idx+1; is_last=pn==total
            seg_start=points[idx]; seg_end=points[idx+1]
            label="parte_final" if is_last else f"parte_{pn}"
            vname=Path(self.video_path).stem
            out_path=str(out_folder/f"{vname}_{label}.mp4")
            self._log(f"\n── Parte {pn}/{total} ──")
            self.after(0,lambda p=pn,t=total:
                       self.progress_lbl.configure(text=f"Exportando parte {p} de {t}..."))
            def on_prog(pct,spd,eta,pn=pn,tt=total):
                overall=((pn-1)+pct/100)/tt
                self.after(0,lambda:[
                    self.progress_bar.set(overall),
                    self.speed_lbl.configure(text=f"Velocidad: {spd}"),
                    self.eta_lbl.configure(text=f"ETA: {eta}"),
                ])
            result=self.engine.export_part(
                video_path=self.video_path,intro_end_sec=intro_sec,
                segment_start_sec=seg_start,segment_end_sec=seg_end,
                output_path=out_path,part_number=pn,total_parts=total,
                is_last_part=is_last,text_config=text_cfg,
                anton_font_path=self.anton_path or "",speed_preset=speed,
                on_progress=on_prog,on_log=self._log)
            self.export_results.append({"part":pn,"label":label,**result})
            if not result["success"]:
                err=result.get("error","Error desconocido")
                self._log(f"ERROR: {err}")
                self.after(0,lambda e=err,p=pn: self._on_error(p,e)); return
            sz=format_size(result.get("size_bytes",0))
            self._log(f"✓ Parte {pn} — {sz}")
            self.after(0,lambda s=sz,p=pn:
                       self.progress_lbl.configure(text=f"✓ Parte {p} — {s}"))
        self.engine.cleanup_temp(str(out_folder))
        write_log(str(out_folder),self.log_entries)
        if not self.engine.is_cancelled():
            self.after(0,lambda: self._on_complete(out_folder))
        else:
            self.after(0,self._on_cancelled)

    def _on_complete(self,out_folder):
        self.is_exporting=False
        if hasattr(self,"process_btn"): self.process_btn.configure(state="normal")
        if hasattr(self,"cancel_btn"): self.cancel_btn.configure(state="disabled")
        elapsed=time.time()-(self.export_start_time or time.time())
        mins=int(elapsed//60); secs=int(elapsed%60)
        time_str=f"{mins}m {secs:02d}s"
        try:
            import winsound; winsound.MessageBeep(winsound.MB_OK)
        except: pass
        self._toast(f"¡Listo en {time_str}!","success")
        self._add_to_history(out_folder)
        self._show_summary_panel(out_folder, time_str)
        self._refresh_process_btn()

    def _on_error(self,pn,error):
        self.is_exporting=False
        self.process_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        friendly=self._friendly_error(error)
        self._toast(f"Error parte {pn}: {friendly}","error")
        messagebox.showerror(f"Error en parte {pn}",f"{friendly}\n\nDetalle:\n{error[:300]}")
        self._refresh_process_btn()

    def _on_cancelled(self):
        self.is_exporting=False
        self.process_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.progress_lbl.configure(text="Exportación cancelada")
        self._toast("Exportación cancelada","warning")
        self._refresh_process_btn()

    def _cancel_export(self):
        if messagebox.askyesno("Cancelar","¿Cancelar la exportación?"):
            self.engine.cancel()

    def _friendly_error(self,error):
        e=error.lower()
        if "no such file" in e or "not found" in e: return "No se encontró el archivo."
        if "permission" in e or "access" in e: return "Sin permiso en la carpeta de salida."
        if "codec" in e or "encoder" in e: return "Error de codificación con FFmpeg."
        if "font" in e: return "No se encontró la fuente Anton."
        if "space" in e or "disk" in e: return "Espacio insuficiente en disco."
        return "Error durante la exportación. Revisa el log."

    def _export_single_part(self, part_num):
        if not self.video_path:
            self._toast("Selecciona un video primero","error"); return
        intro_sec=parse_time(self.intro_entry.get())
        if intro_sec is None:
            self._toast("Configura la intro primero","error"); return
        cuts=self._get_cuts()
        if not cuts:
            self._toast("Agrega al menos un corte","error"); return
        duration=self.video_info.get("duration",0)
        points=[0.0]+cuts+[duration]
        total=len(points)-1
        if part_num>total: return
        seg_start=points[part_num-1]; seg_end=points[part_num]
        is_last=part_num==total
        label="parte_final" if is_last else f"parte_{part_num}"
        out_dir=self.settings.get("output_dir",r"C:\Videos_Trabajo")
        vname=Path(self.video_path).stem
        out_folder=Path(out_dir)/f"{vname}_partes"
        out_folder.mkdir(parents=True,exist_ok=True)
        out_path=str(out_folder/f"{vname}_{label}.mp4")
        if not messagebox.askyesno("Exportar parte",
            f"¿Exportar solo '{label}'?\n\nDestino: {out_path}"): return
        self.is_exporting=True
        self.process_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.engine.reset_cancel()
        self.export_start_time=time.time()
        self._clear_log()
        self._switch_tab(2)
        def run():
            result=self.engine.export_part(
                video_path=self.video_path,intro_end_sec=intro_sec,
                segment_start_sec=seg_start,segment_end_sec=seg_end,
                output_path=out_path,part_number=part_num,total_parts=total,
                is_last_part=is_last,text_config=self._get_text_cfg(),
                anton_font_path=self.anton_path or "",
                speed_preset=self.speed_var.get(),
                on_progress=lambda pct,spd,eta: self.after(0,lambda:[
                    self.progress_bar.set(pct/100),
                    self.speed_lbl.configure(text=f"Velocidad: {spd}"),
                    self.eta_lbl.configure(text=f"ETA: {eta}"),
                ]),
                on_log=self._log)
            self.after(0,lambda: self._on_single_done(result,out_path,label))
        threading.Thread(target=run,daemon=True).start()

    def _on_single_done(self,result,out_path,label):
        self.is_exporting=False
        self.process_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self._refresh_process_btn()
        if result["success"]:
            sz=format_size(result.get("size_bytes",0))
            self.progress_bar.set(1.0)
            self.progress_lbl.configure(text=f"✅ {label} exportada — {sz}")
            self._toast(f"✅ {label} — {sz}","success")
            try:
                import winsound; winsound.MessageBeep(winsound.MB_OK)
            except: pass
        else:
            err=self._friendly_error(result.get("error",""))
            self._toast(f"Error: {err}","error")

    def _rename(self,result,out_folder):
        d=ctk.CTkInputDialog(text="Nuevo nombre:",title="Renombrar")
        name=d.get_input()
        if name and name.strip():
            vname=Path(self.video_path).stem
            old=out_folder/f"{vname}_{result['label']}.mp4"
            new=out_folder/f"{name.strip()}.mp4"
            try:
                old.rename(new); result["label"]=name.strip()
                self._toast(f"Renombrado a '{name.strip()}'","success")
            except Exception as e:
                messagebox.showerror("Error",str(e))

    def _add_to_history(self,out_folder):
        entry={"path":self.video_path,"name":os.path.basename(self.video_path),
               "date":datetime.now().strftime("%d/%m/%Y %H:%M"),
               "parts":len(self.export_results),
               "duration":format_duration(self.video_info.get("duration",0))}
        self.history=[entry]+[h for h in self.history if h["path"]!=self.video_path]
        max_h=self.settings.get("history_max",5)
        self.history=self.history[:max_h]
        save_history(self.history,max_h)
        self._refresh_history_list()

    # ── Reset ─────────────────────────────────────────────────────────────────
    def _reset_all(self):
        if self.is_exporting:
            self._toast("Cancela la exportación antes","warning"); return
        if self._vlc: self._vlc.stop()
        if self._player_job: self.after_cancel(self._player_job); self._player_job=None
        self.video_path=None; self.video_info={}
        self._waveform_data=[]; self._zoom=1.0; self._tl_offset=0.0; self._playhead_sec=0.0
        self.drop_label.configure(text="Arrastra el video aquí",text_color=TEXT_MUTED,
                                   font=ctk.CTkFont(size=11))
        for k in self.info_labels: self.info_labels[k].configure(text="—")
        self.vlc_placeholder.place(relx=0.5,rely=0.5,anchor="center")
        self.vlc_placeholder.configure(text="Sin video")
        self.intro_entry.delete(0,"end")
        for e in self.cuts_entries: e.master.destroy()
        self.cuts_entries.clear()
        self._add_cut()
        self.progress_bar.set(0)
        self.progress_lbl.configure(text="En espera")
        self.speed_lbl.configure(text=""); self.eta_lbl.configure(text="")
        self._clear_log()
        self._player_time=0.0
        self.play_btn.configure(text="▶")
        self.time_lbl.configure(text="0:00.00")
        self.player_var.set(0)
        self._tl_draw()
        self._refresh_process_btn()
        self._switch_tab(0)

    # ── Log ───────────────────────────────────────────────────────────────────
    def _log(self, msg):
        self.log_entries.append(msg)
        self.after(0,lambda m=msg: self._append_log(m))

    def _append_log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end",msg+"\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ── Atajos ────────────────────────────────────────────────────────────────
    def _apply_shortcuts(self):
        self.bind("<space>",    lambda e: self._toggle_play())
        self.bind("<Control-a>",lambda e: self._add_cut())
        self.bind("<Control-r>",lambda e: self._reset_all())
        self.bind("<Control-o>",lambda e: self._browse_video())
        self.bind("<Return>",   lambda e: self._start_export())
        for i in range(len(TAB_NAMES)):
            self.bind(f"<Control-Key-{i+1}>",lambda e,i=i: self._switch_tab(i))
