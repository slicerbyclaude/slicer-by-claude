"""
Slicer by Claude - Pantalla de bienvenida v1.5.0
Paleta marrón/blanco actualizada
"""
import webbrowser
import customtkinter as ctk
from core.engine import find_ffmpeg, find_ffprobe, check_anton_font
from core.config import APP_NAME, APP_VERSION

# Paleta marrón/blanco
BG_ROOT      = "#1c1610"
BG_PANEL     = "#232018"
BG_CARD      = "#2a2418"
BG_ELEVATED  = "#302a1e"
BG_INPUT     = "#161210"
BORDER       = "#3d3528"
ACCENT       = "#ffffff"
ACCENT_DIM   = "#d4c8b4"
TEXT_PRIMARY = "#ffffff"
TEXT_SEC     = "#c8bca8"
TEXT_MUTED   = "#7a6a55"
SUCCESS      = "#4ade80"
WARNING      = "#fbbf24"
DANGER       = "#f87171"

DEPS = [
    {
        "key": "ffmpeg",
        "name": "FFmpeg",
        "desc": "Motor de procesamiento de video — requerido",
        "check": find_ffmpeg,
        "required": True,
        "url": "https://ffmpeg.org/download.html",
        "install_hint": "Descarga la versión Windows, descomprime y agrega la carpeta bin al PATH.",
    },
    {
        "key": "anton",
        "name": "Fuente Anton",
        "desc": "Fuente para el texto PARTE X — requerida",
        "check": check_anton_font,
        "required": True,
        "url": "https://fonts.google.com/specimen/Anton",
        "install_hint": "Descarga, extrae el .ttf y haz doble clic → Instalar.",
    },
    {
        "key": "customtkinter",
        "name": "CustomTkinter",
        "desc": "Librería de interfaz gráfica",
        "check": lambda: __import__("customtkinter") and "ok",
        "required": False,
        "url": "https://github.com/TomSchimansky/CustomTkinter",
        "install_hint": "Ejecuta: pip install customtkinter",
    },
    {
        "key": "pillow",
        "name": "Pillow",
        "desc": "Procesamiento de imágenes y miniaturas",
        "check": lambda: __import__("PIL") and "ok",
        "required": False,
        "url": "https://python-pillow.org",
        "install_hint": "Ejecuta: pip install Pillow",
    },
]


class SetupScreen(ctk.CTkToplevel):
    def __init__(self, parent, on_ready: callable, on_abort: callable):
        super().__init__(parent)
        self.on_ready = on_ready
        self.on_abort = on_abort
        self.results = {}
        self.title(f"{APP_NAME} — Verificación de dependencias")
        self.geometry("620x560")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=BG_ROOT)
        self.protocol("WM_DELETE_WINDOW", self._abort)
        self._build_ui()
        self.after(300, self._run_checks)

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkFrame(header, fg_color=ACCENT, height=2, corner_radius=0).pack(fill="x", side="top")
        ctk.CTkLabel(header, text="S",
                     font=ctk.CTkFont(size=28, weight="bold", family="Georgia"),
                     text_color=ACCENT).pack(pady=(16, 2))
        ctk.CTkLabel(header, text=APP_NAME,
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TEXT_PRIMARY).pack()
        ctk.CTkLabel(header, text=f"v{APP_VERSION} — Verificando dependencias...",
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(pady=(2, 14))

        # Lista de dependencias
        self.deps_frame = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                                  scrollbar_button_color=BORDER, height=300)
        self.deps_frame.pack(fill="both", expand=True, padx=20, pady=10)
        self.dep_rows = {}
        for dep in DEPS:
            row = self._build_dep_row(self.deps_frame, dep)
            self.dep_rows[dep["key"]] = row

        # Botones
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)
        self.btn_continue = ctk.CTkButton(
            btn_frame, text="Continuar →", state="disabled",
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            text_color=BG_ROOT, font=ctk.CTkFont(size=12, weight="bold"),
            command=self._continue)
        self.btn_continue.pack(side="right", padx=4)
        ctk.CTkButton(btn_frame, text="Cancelar",
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT_MUTED, hover_color=BG_ELEVATED,
                      command=self._abort).pack(side="right", padx=4)

    def _build_dep_row(self, parent, dep: dict) -> dict:
        frame = ctk.CTkFrame(parent, fg_color=BG_ELEVATED, corner_radius=8,
                              border_width=1, border_color=BORDER)
        frame.pack(fill="x", pady=4)
        left = ctk.CTkFrame(frame, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=12, pady=10)
        status_lbl = ctk.CTkLabel(left, text="⏳", font=ctk.CTkFont(size=18),
                                   width=28, anchor="w")
        status_lbl.pack(side="left", padx=(0, 8))
        info = ctk.CTkFrame(left, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text=dep["name"],
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_PRIMARY, anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=dep["desc"],
                     font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
                     anchor="w").pack(anchor="w")
        hint_lbl = ctk.CTkLabel(frame, text="",
                                 font=ctk.CTkFont(size=11),
                                 text_color=WARNING, anchor="w", wraplength=380)
        hint_lbl.pack(fill="x", padx=12, pady=(0, 6))
        btn_dl = ctk.CTkButton(frame, text="Descargar →", width=100, height=28,
                                fg_color=ACCENT, hover_color=ACCENT_DIM,
                                text_color=BG_ROOT, font=ctk.CTkFont(size=11),
                                command=lambda u=dep["url"]: webbrowser.open(u))
        return {"frame": frame, "status": status_lbl, "hint": hint_lbl, "btn": btn_dl, "dep": dep}

    def _run_checks(self):
        missing_required = False
        for dep in DEPS:
            key = dep["key"]
            row = self.dep_rows[key]
            try:
                result = dep["check"]()
                found = bool(result)
            except Exception:
                found = False
            self.results[key] = found
            if found:
                row["status"].configure(text="✅", text_color=SUCCESS)
                row["hint"].configure(text="")
            else:
                if dep["required"]:
                    row["status"].configure(text="❌", text_color=DANGER)
                    missing_required = True
                else:
                    row["status"].configure(text="⚠️", text_color=WARNING)
                row["hint"].configure(text=dep["install_hint"])
                row["btn"].pack(anchor="e", padx=12, pady=(0, 8))
        if not missing_required:
            self.btn_continue.configure(state="normal")
        else:
            self.btn_continue.configure(text="Faltan dependencias requeridas", state="disabled")

    def _continue(self):
        self.grab_release()
        self.destroy()
        self.on_ready(self.results)

    def _abort(self):
        self.grab_release()
        self.destroy()
        self.on_abort()
