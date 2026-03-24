"""
Slicer by Claude - Utilidades de tiempo y validación
"""
import re
from typing import Optional


def parse_time(time_str: str) -> Optional[float]:
    """
    Convierte MM:SS.cc a segundos float.
    Acepta: 4:19.23 | 4:19 | 0:15.30 | 15:40.23
    Retorna None si el formato es inválido.
    """
    time_str = time_str.strip()
    pattern = r'^(\d+):(\d{1,2})(?:\.(\d{1,3}))?$'
    m = re.match(pattern, time_str)
    if not m:
        return None
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    if seconds >= 60:
        return None
    centesimas_str = m.group(3) or "0"
    # Normalizar a milisegundos
    centesimas_str = centesimas_str.ljust(3, "0")[:3]
    milliseconds = int(centesimas_str)
    return minutes * 60 + seconds + milliseconds / 1000.0


def seconds_to_str(seconds: float) -> str:
    """Convierte segundos a MM:SS.cc legible."""
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}:{secs:05.2f}"


def seconds_to_ffmpeg(seconds: float) -> str:
    """Convierte segundos al formato HH:MM:SS.mmm para FFmpeg."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def format_duration(seconds: float) -> str:
    """Formato legible de duración: 4m 19s."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}m {s:02d}s"


def format_size(bytes_val: int) -> str:
    """Formato legible de tamaño de archivo."""
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024*1024):.1f} MB"
    else:
        return f"{bytes_val / (1024*1024*1024):.2f} GB"


def validate_cuts(cuts_sec: list[float], video_duration: float,
                  intro_duration: float, min_gap: float = 30.0) -> list[str]:
    """
    Valida la lista de cortes. Retorna lista de mensajes de error (vacía = OK).
    """
    errors = []
    if not cuts_sec:
        return errors

    # Orden correcto
    for i in range(1, len(cuts_sec)):
        if cuts_sec[i] <= cuts_sec[i - 1]:
            errors.append(
                f"El corte {i+1} ({seconds_to_str(cuts_sec[i])}) debe ser "
                f"mayor que el corte {i} ({seconds_to_str(cuts_sec[i-1])})."
            )

    # Dentro del rango del video
    for i, c in enumerate(cuts_sec):
        if c >= video_duration:
            errors.append(
                f"El corte {i+1} ({seconds_to_str(c)}) supera la duración "
                f"del video ({seconds_to_str(video_duration)})."
            )

    # Cortes demasiado cercanos
    all_points = [0.0] + cuts_sec + [video_duration]
    for i in range(1, len(all_points)):
        gap = all_points[i] - all_points[i - 1]
        if gap < min_gap and gap > 0:
            errors.append(
                f"El segmento {i} dura solo {format_duration(gap)} "
                f"(mínimo recomendado: {int(min_gap)}s)."
            )

    # Intro mayor que el segmento más corto
    if intro_duration > 0:
        all_points2 = [0.0] + cuts_sec + [video_duration]
        for i in range(1, len(all_points2)):
            seg_dur = all_points2[i] - all_points2[i - 1]
            if intro_duration >= seg_dur:
                errors.append(
                    f"La intro ({format_duration(intro_duration)}) es más larga "
                    f"que el segmento {i} ({format_duration(seg_dur)})."
                )
                break

    return errors


def estimate_segment_size_mb(duration_sec: float, bitrate_kbps: int = 3000) -> float:
    """Estima el tamaño de un segmento en MB basado en bitrate."""
    return (bitrate_kbps * duration_sec) / (8 * 1024)


def get_segment_durations(cuts_sec: list[float], video_duration: float) -> list[float]:
    """Retorna la duración de cada segmento de contenido (sin intro)."""
    points = [0.0] + cuts_sec + [video_duration]
    return [points[i+1] - points[i] for i in range(len(points)-1)]
