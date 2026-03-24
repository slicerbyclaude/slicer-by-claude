"""
Slicer by Claude - Motor de procesamiento FFmpeg
"""
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional
from datetime import datetime

from core.config import (
    VIDEO_CODEC, VIDEO_BITRATE, VIDEO_FPS,
    AUDIO_CODEC, AUDIO_BITRATE, LOG_FILENAME,
)
LOG_FILENAME = "slicer_log.txt"
from core.utils import seconds_to_ffmpeg, format_size


# ─── Detección de FFmpeg ────────────────────────────────────────────────────

def find_ffmpeg() -> Optional[str]:
    """Busca ffmpeg en PATH y rutas comunes de Windows."""
    # 1. En PATH
    path = shutil.which("ffmpeg")
    if path:
        return path
    # 2. Rutas comunes de Windows
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ffmpeg", "bin", "ffmpeg.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def find_ffprobe() -> Optional[str]:
    """Busca ffprobe (viene con ffmpeg)."""
    path = shutil.which("ffprobe")
    if path:
        return path
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        probe = Path(ffmpeg).parent / "ffprobe.exe"
        if probe.exists():
            return str(probe)
    return None


def check_anton_font() -> Optional[str]:
    """Busca la fuente Anton en Windows."""
    font_dirs = [
        r"C:\Windows\Fonts",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
    ]
    for d in font_dirs:
        for name in ["Anton-Regular.ttf", "Anton.ttf"]:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None


# ─── Información del video ───────────────────────────────────────────────────

def get_video_info(video_path: str, ffprobe: str) -> dict:
    """Extrae metadatos del video usando ffprobe."""
    cmd = [
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        import json
        data = json.loads(result.stdout)
        info = {
            "duration": 0.0, "width": 0, "height": 0,
            "fps": 0.0, "video_codec": "", "audio_codec": "",
            "is_hevc": False, "is_1080p": False, "size_bytes": 0,
        }
        info["size_bytes"] = int(data.get("format", {}).get("size", 0))
        info["duration"] = float(data.get("format", {}).get("duration", 0))
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = stream.get("width", 0)
                info["height"] = stream.get("height", 0)
                info["video_codec"] = stream.get("codec_name", "")
                info["is_hevc"] = stream.get("codec_name", "") in ("hevc", "h265")
                info["is_1080p"] = stream.get("height", 0) == 1080
                fps_str = stream.get("r_frame_rate", "0/1")
                try:
                    num, den = fps_str.split("/")
                    info["fps"] = round(int(num) / int(den), 2)
                except Exception:
                    info["fps"] = 0.0
            elif stream.get("codec_type") == "audio":
                info["audio_codec"] = stream.get("codec_name", "").upper()
        return info
    except Exception as e:
        return {"error": str(e)}


def extract_frame(video_path: str, time_sec: float, output_path: str, ffmpeg: str) -> bool:
    """Extrae un frame del video en el tiempo dado."""
    cmd = [
        ffmpeg, "-y", "-ss", seconds_to_ffmpeg(time_sec),
        "-i", video_path, "-frames:v", "1",
        "-vf", "scale=480:-1", output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        return os.path.isfile(output_path)
    except Exception:
        return False


# ─── Motor de exportación ────────────────────────────────────────────────────

class ExportEngine:
    def __init__(self):
        self.ffmpeg = find_ffmpeg()
        self.ffprobe = find_ffprobe()
        self._cancel_event = threading.Event()
        self._current_proc: Optional[subprocess.Popen] = None

    def cancel(self):
        self._cancel_event.set()
        if self._current_proc:
            try:
                self._current_proc.terminate()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def reset_cancel(self):
        self._cancel_event.clear()

    def _run_ffmpeg(self, cmd: list, duration_sec: float,
                    on_progress: Callable[[float, float, str], None]) -> bool:
        """
        Ejecuta un comando FFmpeg y parsea el progreso.
        on_progress(percent, speed, eta_str)
        """
        try:
            self._current_proc = subprocess.Popen(
                cmd, stderr=subprocess.PIPE, universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
            speed_pattern = re.compile(r"speed=\s*([\d.]+)x")

            for line in self._current_proc.stderr:
                if self.is_cancelled():
                    return False
                t_match = time_pattern.search(line)
                s_match = speed_pattern.search(line)
                if t_match and duration_sec > 0:
                    h, m, s = t_match.groups()
                    elapsed = int(h)*3600 + int(m)*60 + float(s)
                    percent = min(elapsed / duration_sec * 100, 99.9)
                    speed = float(s_match.group(1)) if s_match else 0.0
                    if speed > 0:
                        remaining = (duration_sec - elapsed) / speed
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        eta = f"{mins}m {secs:02d}s"
                    else:
                        eta = "calculando..."
                    speed_str = f"{speed:.1f}x" if speed > 0 else "..."
                    on_progress(percent, speed_str, eta)

            self._current_proc.wait()
            return self._current_proc.returncode == 0
        except Exception as e:
            raise RuntimeError(f"Error ejecutando FFmpeg: {e}")

    def export_part(
        self,
        video_path: str,
        intro_end_sec: float,
        segment_start_sec: float,
        segment_end_sec: float,
        output_path: str,
        part_number: int,
        total_parts: int,
        is_last_part: bool,
        text_config: dict,
        anton_font_path: str,
        speed_preset: str,
        on_progress: Callable,
        on_log: Callable,
    ) -> dict:
        """
        Exporta una parte completa:
        intro (con texto PARTE X) + contenido del segmento [+ outro si es última parte]
        """
        if self.is_cancelled():
            return {"success": False, "error": "Cancelado por el usuario"}

        temp_dir = Path(output_path).parent / "_temp"
        temp_dir.mkdir(exist_ok=True)

        part_label = "PARTE FINAL" if (is_last_part and part_number == total_parts) else f"PARTE {part_number}"

        try:
            # ── 1. Extraer intro con texto superpuesto ──────────────────────
            intro_path = str(temp_dir / f"intro_{part_number}.mp4")
            on_log(f"[Parte {part_number}] Extrayendo intro...")

            # Construir filtro de texto para FFmpeg
            font_path_escaped = anton_font_path.replace("\\", "/").replace(":", "\\:")
            tc = text_config
            font_size = tc.get("font_size", 80)
            color_hex = tc.get("color", "#FFFFFF").lstrip("#")
            outline_hex = tc.get("outline_color", "#000000").lstrip("#")
            outline_w = tc.get("outline_width", 6)
            opacity = int(tc.get("opacity", 1.0) * 255)
            pos_y_frac = tc.get("position_y", 0.15)

            # Color con alpha para FFmpeg drawtext
            text_color = f"#{color_hex}{opacity:02X}"
            border_color = f"#{outline_hex}FF"

            drawtext_filter = (
                f"drawtext=fontfile='{font_path_escaped}':"
                f"text='{part_label}':"
                f"fontsize={font_size}:"
                f"fontcolor={text_color}:"
                f"borderw={outline_w}:"
                f"bordercolor={border_color}:"
                f"x=(w-text_w)/2:"
                f"y=h*{pos_y_frac}"
            )

            # Detectar orientación para escalar a 1080p correctamente
            # Si es vertical (9:16) → 1080x1920, si es horizontal → 1920x1080
            scale_filter = "scale='if(gt(iw,ih),1920,1080)':'if(gt(iw,ih),1080,1920)':flags=lanczos"

            drawtext_with_scale = f"{scale_filter},{drawtext_filter}"

            cmd_intro = [
                self.ffmpeg, "-y",
                "-ss", "0", "-to", seconds_to_ffmpeg(intro_end_sec),
                "-i", video_path,
                "-vf", drawtext_with_scale,
                "-c:v", VIDEO_CODEC, "-b:v", VIDEO_BITRATE,
                "-r", str(VIDEO_FPS),
                "-preset", speed_preset,
                "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE,
                intro_path
            ]

            intro_duration = intro_end_sec
            total_duration = (segment_end_sec - segment_start_sec) + intro_duration

            def prog_intro(pct, spd, eta):
                real_pct = pct * (intro_duration / total_duration)
                on_progress(real_pct, spd, eta)

            ok = self._run_ffmpeg(cmd_intro, intro_duration, prog_intro)
            if not ok or self.is_cancelled():
                raise RuntimeError("Falló la extracción de la intro.")

            # ── 2. Extraer contenido del segmento ──────────────────────────
            content_path = str(temp_dir / f"content_{part_number}.mp4")
            on_log(f"[Parte {part_number}] Extrayendo contenido...")

            cmd_content = [
                self.ffmpeg, "-y",
                "-ss", seconds_to_ffmpeg(segment_start_sec if segment_start_sec > intro_end_sec else intro_end_sec),
                "-to", seconds_to_ffmpeg(segment_end_sec),
                "-i", video_path,
                "-vf", scale_filter,
                "-c:v", VIDEO_CODEC, "-b:v", VIDEO_BITRATE,
                "-r", str(VIDEO_FPS),
                "-preset", speed_preset,
                "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE,
                content_path
            ]

            content_duration = segment_end_sec - segment_start_sec

            def prog_content(pct, spd, eta):
                real_pct = (intro_duration / total_duration * 100) + pct * (content_duration / total_duration)
                on_progress(min(real_pct, 98.0), spd, eta)

            ok = self._run_ffmpeg(cmd_content, content_duration, prog_content)
            if not ok or self.is_cancelled():
                raise RuntimeError("Falló la extracción del contenido.")

            # ── 3. Concatenar con ffmpeg concat ─────────────────────────────
            on_log(f"[Parte {part_number}] Uniendo segmentos...")
            concat_list = str(temp_dir / f"concat_{part_number}.txt")
            with open(concat_list, "w") as f:
                f.write(f"file '{intro_path}'\n")
                f.write(f"file '{content_path}'\n")

            cmd_concat = [
                self.ffmpeg, "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                output_path
            ]
            result = subprocess.run(
                cmd_concat, capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            if result.returncode != 0:
                raise RuntimeError(f"Error al concatenar: {result.stderr.decode()}")

            on_progress(100.0, "✓", "0s")

            # Tamaño del archivo generado
            size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
            return {"success": True, "size_bytes": size, "output": output_path}

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            # Limpiar temporales de esta parte
            for tmp in [
                temp_dir / f"intro_{part_number}.mp4",
                temp_dir / f"content_{part_number}.mp4",
                temp_dir / f"concat_{part_number}.txt",
            ]:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass

    def cleanup_temp(self, output_dir: str):
        temp = Path(output_dir) / "_temp"
        try:
            if temp.exists():
                import shutil as sh
                sh.rmtree(temp, ignore_errors=True)
        except Exception:
            pass


# ─── Logger ──────────────────────────────────────────────────────────────────

def write_log(output_dir: str, entries: list[str]):
    log_path = Path(output_dir) / LOG_FILENAME
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"Sesión: {timestamp}\n")
        f.write(f"{'='*60}\n")
        for entry in entries:
            f.write(entry + "\n")
