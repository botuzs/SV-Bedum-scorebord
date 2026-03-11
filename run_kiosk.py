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
    
    # 1. Laad de wedstrijd data & assets
    app.laad_wedstrijden_van_json()
    app.laad_assets()
    
    # 2. Vind het IP (nodig voor de QR-codes)
    app.get_local_ip()
    
    # 3. Start de server in een aparte thread
    t = threading.Thread(target=start_server_thread)
    t.daemon = True 
    t.start()
    
    logging.info("Wachten op serverstart (3s)...")
    time.sleep(3) # Geef de server even de tijd om op te starten

    # 4. Laad instellingen en detecteer monitor
    instellingen = app.load_settings()
    monitor_width, monitor_height = 1920, 1080 # Defaults
    # LAAD HET THEMA OM DE ACHTERGRONDKLEUR TE KRIJGEN
    theme = {**app.DEFAULT_SETTINGS, **instellingen.get('theme', {})}
    startup_bg_color = theme.get('background_color', '#000000') # Pak de opgeslagen kleur
    
    try:
        monitor = webview.screens[0]
        monitor_width = monitor.width
        monitor_height = monitor.height
        
        # SLA MONITORGROOTTE OP voor de admin-pagina
        if (instellingen.get('monitor_width') != monitor_width or 
            instellingen.get('monitor_height') != monitor_height):
            logging.info(f"Nieuwe monitorgrootte gedetecteerd: {monitor_width}x{monitor_height}. Opslaan...")
            instellingen['monitor_width'] = monitor_width
            instellingen['monitor_height'] = monitor_height
            app.save_settings(instellingen)
        
    except Exception as e:
        logging.warning(f"Kon schermgrootte niet detecteren: {e}")
        monitor_width = instellingen.get('monitor_width', 1920)
        monitor_height = instellingen.get('monitor_height', 1080)


    # 5. Bepaal venstergrootte (opgeslagen of default)
    initial_x = instellingen.get('x', 0)
    initial_y = instellingen.get('y', 0)
    initial_width = instellingen.get('width', monitor_width) # Default volledige breedte
    initial_height = instellingen.get('height', monitor_height // 6) # Default 1/6e hoogte
    
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
            transparent=False,             # <-- CRUCIAAL (1/2)
            background_color=startup_bg_color  # <-- CRUCIAAL (2/2)
        )
        # 7. REGISTREER het venster bij de server
        app.register_main_window(main_window)
        
        # 8. Start de GUI
        webview.start(debug=False, private_mode=True)
        
    except Exception as e:
        logging.error(f"Kon webview venster niet starten: {e}")
        sys.exit()