import webview
import threading
import sys
import logging
import app # Importeert app.py als een module
import time
import os
import sys

def get_base_path():
    """ Krijgt het pad naar de app-map, werkt voor .py en .exe """
    if getattr(sys, 'frozen', False):
        # We draaien als .exe, het pad is de map van de .exe
        return os.path.dirname(sys.executable)
    else:
        # We draaien als .py, het pad is de map van het script
        return os.path.dirname(os.path.abspath(__file__))

BASE_PATH = get_base_path()

def start_server_thread():
    """Start de Flask/SocketIO server in een aparte thread."""
    logging.info("Flask server starten op achtergrond thread...")
    try:
        app.start_server_func()
    except Exception as e:
        logging.error(f"Server kon niet starten: {e}")
        try: webview.windows[0].destroy()
        except Exception: pass
        sys.exit()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logging.info("--- Kiosk Modus Starten ---")
    
    # 1. Trigger de synchronisatie en laad de data
    app.initialize_app()
    
    # 2. Start de server in een aparte thread
    t = threading.Thread(target=start_server_thread)
    t.daemon = True 
    t.start()
    
    logging.info("Wachten op serverstart (3s)...")
    time.sleep(3) 

    # 3. Laad instellingen
    instellingen = app.load_settings()
    monitor_width, monitor_height = 1920, 1080 # Defaults
    
    theme = {**app.DEFAULT_SETTINGS, **instellingen.get('theme', {})}
    startup_bg_color = theme.get('background_color', '#000000')
    
    try:
        monitor = webview.screens[0]
        monitor_width = monitor.width
        monitor_height = monitor.height
        logging.info(f"Monitor gedetecteerd: {monitor_width}x{monitor_height}.")
    except Exception as e:
        logging.warning(f"Kon schermgrootte niet detecteren: {e}")
        monitor_width = instellingen.get('monitor_width', 1920)
        monitor_height = instellingen.get('monitor_height', 1080)

    # 5. Bepaal venstergrootte
    initial_x = instellingen.get('x', 0)
    initial_y = instellingen.get('y', 0)
    initial_width = instellingen.get('width', monitor_width)
    initial_height = instellingen.get('height', monitor_height // 6)
    
    logging.info(f"Venster openen op ({initial_x},{initial_y}) met grootte ({initial_width}x{initial_height})")

    # 6. Maak het Kiosk-venster aan
    try:
        main_window = webview.create_window(
            'SV Bedum Scorebord',
            'http://127.0.0.1:5000/display', 
            width=initial_width,
            height=initial_height,
            x=initial_x,
            y=initial_y,
            resizable=False,
            fullscreen=False,
            frameless=True,
            on_top=True,
            transparent=False,
            background_color=startup_bg_color
        )
        
        # 7. REGISTREER het venster bij de server
        app.register_main_window(main_window)

        def force_window_refresh():
            """Wacht 5 seconden en pas dan de grootte/positie nogmaals hard toe vanuit de JSON."""
            time.sleep(5)
            try:
                # Laad de instellingen opnieuw voor de zekerheid
                settings = app.load_settings()
                fx = settings.get('x', initial_x)
                fy = settings.get('y', initial_y)
                fw = settings.get('width', initial_width)
                fh = settings.get('height', initial_height)
                logging.info(f"FORCEREN: Venster herstellen naar {fw}x{fh} op ({fx},{fy})")
                main_window.move(fx, fy)
                main_window.resize(fw, fh)
            except Exception as e:
                logging.error(f"Kon venster niet forceren: {e}")

        # Start de fix thread
        threading.Thread(target=force_window_refresh, daemon=True).start()

        # 8. Start de GUI
        webview.start(debug=False, private_mode=True)
        
    except Exception as e:
        logging.error(f"Kon webview venster niet starten: {e}")
        sys.exit()
