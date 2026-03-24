"""
Slicer by Claude v1.0.0
========================
Punto de entrada principal.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import customtkinter as ctk
from core.config import APP_NAME, load_settings, save_settings
from ui.setup_screen import SetupScreen
from ui.main_window import SlicerApp


def main():
    settings = load_settings()
    first_run = not settings.get("setup_done", False)

    if first_run:
        # Mostrar pantalla de setup primero
        check_root = ctk.CTk()
        check_root.withdraw()

        result_holder = {"ready": False, "deps": {}}

        def on_ready(dep_results):
            result_holder["ready"] = True
            result_holder["deps"] = dep_results
            settings["setup_done"] = True
            save_settings(settings)
            check_root.quit()

        def on_abort():
            check_root.quit()

        SetupScreen(check_root, on_ready=on_ready, on_abort=on_abort)
        check_root.mainloop()
        check_root.destroy()

        if not result_holder["ready"]:
            sys.exit(0)

        dep_results = result_holder["deps"]
    else:
        dep_results = {}

    # Abrir ventana principal
    app = SlicerApp(dep_results)
    app.mainloop()


if __name__ == "__main__":
    main()
