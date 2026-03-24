# Slicer by Claude v1.0.0 — Instrucciones de instalación y compilación

## Requisitos del sistema
- Windows 10 / 11
- Python 3.10 o superior
- FFmpeg instalado y en el PATH
- Fuente Anton instalada en Windows

---

## 1. Instalar Python
Descarga desde: https://www.python.org/downloads/
Marca "Add Python to PATH" durante la instalación.

---

## 2. Instalar FFmpeg
1. Descarga desde: https://ffmpeg.org/download.html  (builds de gyan.dev recomendados)
2. Extrae el .zip en C:\ffmpeg
3. Agrega C:\ffmpeg\bin al PATH de Windows:
   - Busca "Variables de entorno" en el menú Inicio
   - Edita la variable "Path" del sistema
   - Agrega: C:\ffmpeg\bin

Verifica con: ffmpeg -version (en CMD)

---

## 3. Instalar fuente Anton
1. Descarga desde: https://fonts.google.com/specimen/Anton
2. Extrae el .zip
3. Haz doble clic en Anton-Regular.ttf → "Instalar"

---

## 4. Instalar dependencias Python
Abre CMD en la carpeta del proyecto y ejecuta:

    pip install -r requirements.txt

---

## 5. Ejecutar el programa
    python main.py

---

## 6. Generar el .exe (opcional)
Para crear un ejecutable que puedes abrir con doble clic:

    pip install pyinstaller
    pyinstaller --onefile --windowed --name "Slicer by Claude" --icon=assets/icon.ico main.py

El .exe se generará en la carpeta `dist/`.

Nota: el .exe no incluye FFmpeg — debe seguir instalado en el sistema.

---

## Atajos de teclado
| Atajo         | Acción                          |
|---------------|---------------------------------|
| Enter         | Iniciar exportación             |
| Espacio       | Play / Pausa del reproductor    |
| Ctrl + A      | Agregar nuevo corte             |
| Ctrl + R      | Resetear / nuevo video          |
| Ctrl + O      | Abrir explorador de archivos    |

---

## Estructura del proyecto
    slicer_by_claude/
    ├── main.py                  ← Punto de entrada
    ├── requirements.txt
    ├── README.md
    ├── core/
    │   ├── config.py            ← Configuración central
    │   ├── utils.py             ← Utilidades de tiempo y validación
    │   └── engine.py            ← Motor FFmpeg
    └── ui/
        ├── setup_screen.py      ← Pantalla de verificación de dependencias
        └── main_window.py       ← Ventana principal

---

## Carpeta de salida
Los videos exportados se guardan en:
    C:\Videos_Trabajo\NombreDelVideo_partes\

Cada carpeta incluye:
- parte_1.mp4, parte_2.mp4 ... parte_final.mp4
- slicer_log.txt (registro de la sesión)
