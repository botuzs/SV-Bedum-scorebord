import json
import logging
import socket
import qrcode
import io
import base64
import os
import sys
import time
import threading
import subprocess
import secrets
from flask import Flask, render_template, abort, request, redirect, url_for, session, Response, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import scraper
import uuid  # <--- VOEG DEZE REGEL TOE

import requests
import shutil
import zipfile

# --- PADEN CONFIGURATIE (CRUCIAAL VOOR .EXE) ---
def get_base_path():
    """Geeft de map waar de .exe staat (of het script)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_internal_path():
    """Geeft de map waar de interne bestanden (templates) staan (in _MEI folder)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

BASE_PATH = get_base_path()         # Hier slaan we dingen op (settings, uploads)
INTERNAL_PATH = get_internal_path() # Hier halen we templates vandaan

# --- MAP VOORBEIDING ---
# Zorg dat de mappen extern bestaan, anders crasht hij bij opslaan
os.makedirs(os.path.join(BASE_PATH, 'static', 'clublogos'), exist_ok=True)
os.makedirs(os.path.join(BASE_PATH, 'static', 'sponsors'), exist_ok=True)

# --- FLASK INIT ---
# We vertellen Flask: "Zoek templates intern, maar static files EXTERN (naast de exe)"
app = Flask(__name__, 
            template_folder=os.path.join(INTERNAL_PATH, 'templates'),
            static_folder=os.path.join(BASE_PATH, 'static'))

logging.basicConfig(level=logging.INFO)

# --- CONFIGURATIE ---
LOGO_FOLDER = os.path.join(BASE_PATH, 'static', 'clublogos') # Absoluut pad
UPLOAD_FOLDER = os.path.join(BASE_PATH, 'static', 'sponsors') # Absoluut pad
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'svbedum_zeer_geheim_wachtwoord_123' 

# Pas de bestandsnamen aan naar absolute paden
SETTINGS_FILE = os.path.join(BASE_PATH, 'settings.json')
WEDSTRIJDEN_FILE = os.path.join(BASE_PATH, 'wedstrijden.json')

socketio = SocketIO(app, async_mode='threading')

WEDSTRIJDEN_DB = {}
WEDSTRIJD_TOKENS = {} # Token opslag
SERVER_IP = "0.0.0.0"
ADMIN_WACHTWOORD = "Svbedum@!#!"   # Voor volledig beheer (instellingen, teams, etc.)
KIOSK_WACHTWOORD = "bar123"


PLAYERS_FILE = os.path.join(BASE_PATH, 'spelers.json')
PLAYERS_FOLDER = os.path.join(BASE_PATH, 'static', 'players')
os.makedirs(PLAYERS_FOLDER, exist_ok=True)

SPELERS_DB = [] # Wordt geladen bij start
ACTIVE_LINEUP = {"players": [], "index": -1} # Huidige status opstelling


# --- Globale Objecten ---
main_kiosk_window = None
SPONSOR_VAST = None
SPONSOR_ROTEREND = []
HOOFDSPONSOR = None
BALSPONSOREN = []
STANDAARD_THUIS_LOGO = None

HUIDIGE_ACTIEVE_WEDSTRIJD_ID = None # <-- DEZE REGEL IS NIEUW

# --- Standaard Thema Instellingen (AANGEPAST VOOR BANNER LAYOUT) ---
# --- Standaard Thema Instellingen ---
DEFAULT_SETTINGS = {
    "background_color": "#4a148c",
    "timer_color": "#000000",
    "timer_size": 4.0,
    "score_color": "#FFFFFF",
    "score_size": 10.0,
    "logo_size": 25,
    "top_bar_height": 10,
    
    # Sponsor instellingen (Tussen timer en score)
    "top_sponsor_height": 15,
    "top_sponsor_size": 80,
    
    "banner_color": "#FFFFFF",
    "top_banner_width": 40,
    "bottom_banner_width": 60,
    "sponsor_bar_height": 10,

    # Layout Spacing
    "score_padding": 2,
    "vertical_spacing": 1,
    "border_radius": 3,
    
    # Speler Weergave
    "player_overlay_bg": "#000000",
    "player_overlay_opacity": 0.95,
    "player_card_width": 90,
    "player_img_height": 80,
    "player_nr_size": 12,
    "player_nr_color": "#ffcc00",
    "player_name_size": 5,
    "player_name_color": "#ffffff"
}

# --- Instellingen Functies (ongewijzigd) ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e: logging.error(f"Kon settings.json niet laden: {e}")
    return {}


def load_players():
    global SPELERS_DB
    if os.path.exists(PLAYERS_FILE):
        try:
            with open(PLAYERS_FILE, 'r') as f:
                SPELERS_DB = json.load(f)
                # Sorteer op rugnummer (optioneel)
                SPELERS_DB.sort(key=lambda x: int(x.get('rugnummer', 0)))
        except Exception as e: logging.error(f"Fout laden spelers: {e}")
    else:
        SPELERS_DB = []

def save_players():
    try:
        with open(PLAYERS_FILE, 'w') as f:
            json.dump(SPELERS_DB, f, indent=4)
    except Exception as e: logging.error(f"Fout opslaan spelers: {e}")


def sync_met_master():
    """
    Gooit alle lokale data (afbeeldingen en JSON) weg en haalt
    een verse kopie op van de Raspberry Pi (Master).
    """
    logging.info("--- START SYNCHRONISATIE MET MASTER ---")

    # 1. Haal master IP op
    instellingen = load_settings()
    master_ip = instellingen.get("master_ip", "")
    master_port = instellingen.get("master_port", 5000)
    api_url = f"http://{master_ip}:{master_port}/api/export"

    # 2. EERST proberen te downloaden, pas DAARNA lokale data wissen
    try:
        logging.info(f"Downloaden van nieuwe data via {api_url}...")
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()

        # Download gelukt! Nu pas lokale data wissen
        mappen_om_te_legen = [
            os.path.join(BASE_PATH, 'static', 'clublogos'),
            os.path.join(BASE_PATH, 'static', 'players'),
            os.path.join(BASE_PATH, 'static', 'sponsors')
        ]
        for map_pad in mappen_om_te_legen:
            if os.path.exists(map_pad):
                shutil.rmtree(map_pad, ignore_errors=True)
            os.makedirs(map_pad, exist_ok=True)

        bestanden_om_te_verwijderen = ['wedstrijden.json', 'spelers.json', 'sponsoren.json']
        for bestand in bestanden_om_te_verwijderen:
            pad = os.path.join(BASE_PATH, bestand)
            if os.path.exists(pad):
                try:
                    os.remove(pad)
                except Exception as e:
                    logging.warning(f"Kon {bestand} niet verwijderen: {e}")

        # ZIP uitpakken
        zip_pad = os.path.join(BASE_PATH, 'sync.zip')
        with open(zip_pad, 'wb') as f:
            f.write(response.content)

        logging.info("Data uitpakken...")
        with zipfile.ZipFile(zip_pad, 'r') as zip_ref:
            zip_ref.extractall(BASE_PATH)

        os.remove(zip_pad)

        # Herstel lokale instellingen (master_ip, thema, venster positie)
        # zodat de ZIP van de master deze niet overschrijft.
        save_settings(instellingen)
        logging.info("Lokale instellingen hersteld na sync.")
        logging.info("--- SYNCHRONISATIE SUCCESVOL ---")

    except requests.exceptions.RequestException as e:
        logging.warning(f"Synchronisatie overgeslagen: Master (IP: {master_ip}) niet bereikbaar. Lokale data behouden. ({e})")
    except Exception as e:
        logging.error(f"Fout tijdens uitpakken van synchronisatie-data: {e}")

    # Haal sponsors apart op (overschrijft wat de ZIP eventueel al heeft geplaatst)
    sync_sponsors_van_master(master_ip, master_port)


def sync_sponsors_van_master(master_ip, master_port=5000):
    """Leegt de lokale sponsors map en downloadt alle PNG's van de master."""
    if not master_ip:
        logging.info("Sponsor sync overgeslagen: geen master IP.")
        return
    base_url = f"http://{master_ip}:{master_port}"
    try:
        logging.info(f"Sponsors ophalen van {base_url} ...")
        resp = requests.get(f"{base_url}/api/sponsors", timeout=10)
        resp.raise_for_status()
        sponsors = resp.json().get('sponsors', [])

        # Verwijder alleen bestanden (niet de map zelf, om toegangsproblemen te voorkomen)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        for bestand in os.listdir(UPLOAD_FOLDER):
            pad = os.path.join(UPLOAD_FOLDER, bestand)
            if os.path.isfile(pad):
                try:
                    os.remove(pad)
                except Exception as e:
                    logging.warning(f"Kon {bestand} niet verwijderen: {e}")

        for s in sponsors:
            img_url = f"{base_url}{s['url']}"
            img_resp = requests.get(img_url, timeout=10)
            img_resp.raise_for_status()
            with open(os.path.join(UPLOAD_FOLDER, s['filename']), 'wb') as f:
                f.write(img_resp.content)

        logging.info(f"Sponsors gesynchroniseerd: {len(sponsors)} bestanden.")
    except requests.exceptions.RequestException as e:
        logging.warning(f"Sponsor sync mislukt: master niet bereikbaar. Lokale sponsors bewaard. ({e})")
    except Exception as e:
        logging.error(f"Fout tijdens sponsor sync: {e}")

# Voeg load_players() ook toe aan de startup, bijv. onder laad_assets()
# (Roep dit handmatig aan of zet het onderin bij `if __name__ == ...`)
load_players()

def haal_externe_sponsoren_op():
    """Haalt actieve sponsoren op van de sponsor server (PI/ander apparaat)."""
    try:
        instellingen = load_settings()
        sponsor_ip = instellingen.get('sponsor_server_ip', '')
        sponsor_port = instellingen.get('sponsor_server_port', 4000)

        if not sponsor_ip:
            logging.info("Geen sponsor server IP ingesteld, externe sponsoren overgeslagen.")
            return []

        url = f"http://{sponsor_ip}:{sponsor_port}/api/sponsors"
        logging.info(f"Sponsoren ophalen van {url}...")
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()

        data = resp.json()
        sponsoren = data.get('sponsors', [])

        # Download de afbeeldingen lokaal zodat het display ze kan tonen
        lokale_bestanden = []
        for s in sponsoren:
            image_url = f"http://{sponsor_ip}:{sponsor_port}{s['url']}"
            lokaal_pad = os.path.join(BASE_PATH, 'static', 'sponsors', f"ext_{s['filename']}")
            try:
                img_resp = requests.get(image_url, timeout=5)
                img_resp.raise_for_status()
                with open(lokaal_pad, 'wb') as f:
                    f.write(img_resp.content)
                lokale_bestanden.append(f"ext_{s['filename']}")
            except Exception as e:
                logging.warning(f"Kon sponsor afbeelding niet downloaden: {s['filename']}: {e}")

        logging.info(f"Externe sponsoren opgehaald: {len(lokale_bestanden)}")
        return lokale_bestanden

    except requests.exceptions.RequestException as e:
        logging.warning(f"Sponsor server niet bereikbaar: {e}")
        return []
    except Exception as e:
        logging.error(f"Fout bij ophalen externe sponsoren: {e}")
        return []

def get_actieve_sponsoren():
    """
    Geeft alle sponsors terug die in de sponsors map staan (SPONSOR_ROTEREND).
    """
    resultaat = list(SPONSOR_ROTEREND)

    return resultaat

def save_settings(data):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e: logging.error(f"Kon settings.json niet opslaan: {e}")

# --- Registratie Functies (ongewijzigd) ---
def register_main_window(window):
    global main_kiosk_window
    main_kiosk_window = window
    logging.info("Hoofdvenster (Kiosk) geregistreerd in server.")

def laad_wedstrijden_van_json():
    global WEDSTRIJDEN_DB
    try:
        # Gebruik nu de variabele met het absolute pad!
        with open(WEDSTRIJDEN_FILE, 'r', encoding='utf-8') as f:
            wedstrijden_lijst = json.load(f)
            WEDSTRIJDEN_DB = {w['id']: w for w in wedstrijden_lijst}
            logging.info(f"Succesvol {len(WEDSTRIJDEN_DB)} wedstrijden geladen.")
    except Exception as e: logging.error(f"Fout bij laden JSON: {e}")

def laad_assets():
    """Laadt de sponsoren lijst en logo's opnieuw in het geheugen."""
    global SPONSOR_ROTEREND, STANDAARD_THUIS_LOGO

    instellingen = load_settings()
    theme = instellingen.get('theme', {})

    # Laad ALLE afbeeldingen uit de sponsors map
    sponsors_folder = os.path.join(BASE_PATH, 'static', 'sponsors')
    if os.path.exists(sponsors_folder):
        SPONSOR_ROTEREND = sorted([
            f for f in os.listdir(sponsors_folder)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))
        ])
    else:
        SPONSOR_ROTEREND = []

    STANDAARD_THUIS_LOGO = theme.get('standaard_thuis_logo')
    logging.info(f"Assets herladen. Sponsoren: {len(SPONSOR_ROTEREND)}, Logo: {STANDAARD_THUIS_LOGO}")

def enrich_match_data(wedstrijd):
    """Voegt globale instellingen toe aan het wedstrijd-object voor de socket."""
    if not wedstrijd: return None
    # Maak een kopie zodat we de DB niet vervuilen
    data = wedstrijd.copy()
    # Voeg het huidige standaard logo toe uit de globale variabele
    data['standaard_thuis_logo'] = STANDAARD_THUIS_LOGO
    return data

def get_local_ip():
    global SERVER_IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(('10.255.255.255', 1)); IP = s.getsockname()[0]; SERVER_IP = IP
    except Exception: SERVER_IP = '127.0.0.1'
    finally: s.close()
    logging.info(f"Server IP adres gevonden: {SERVER_IP}")
    return SERVER_IP

def genereer_qr_code(url):
    img = qrcode.make(url); buf = io.BytesIO(); img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- Routes (Webpagina's) (ongewijzigd) ---
# --- ROUTES ---

@app.route('/')
def index():
    """Root verwijst nu direct naar Welcome."""
    return redirect(url_for('welcome_page'))

@app.route('/welcome')
def welcome_page():
    return render_template('welcome.html')

# --- In app.py ---

@app.route('/kiosk-dashboard')
def kiosk_dashboard():
    # MAG ALS: Je Kiosk OF Admin bent
    if not session.get('kiosk_logged_in') and not session.get('admin_logged_in'):
        return redirect(url_for('login_page'))

    wedstrijden_lijst = sorted(WEDSTRIJDEN_DB.values(), key=lambda x: x['tijd'])
    return render_template('index.html', wedstrijden=wedstrijden_lijst)

# --- In app.py ---

@app.route('/admin/generate-qr/<string:wedstrijd_id>')
def generate_secure_qr(wedstrijd_id):
    # MAG ALS: Je Kiosk OF Admin bent
    if not session.get('kiosk_logged_in') and not session.get('admin_logged_in'):
        return abort(403)
    
    # 1. DICTATOR LOGICA: Zet DEZE wedstrijd als de enige actieve
    global HUIDIGE_ACTIEVE_WEDSTRIJD_ID
    HUIDIGE_ACTIEVE_WEDSTRIJD_ID = wedstrijd_id
    
    # 2. Stuur DIRECT het commando naar het scherm (en kick andere gebruikers)
    #    Het bord springt nu alvast op de juiste wedstrijd, nog voordat er gescand is.
    # Voeg dit toe aan de logica waar een wedstrijd gestart wordt
    actieve_logos = get_actieve_sponsoren()
    socketio.emit('update_sponsoren_lijst', {'sponsoren': actieve_logos})    
    # 3. Genereer de token voor de QR (zoals voorheen)
    token = secrets.token_urlsafe(16)
    WEDSTRIJD_TOKENS[wedstrijd_id] = token
    
    instellingen = load_settings()
    theme = {**DEFAULT_SETTINGS, **instellingen.get('theme', {})}
    base = theme.get('tailscale_url', '127.0.0.1').replace('http://', '').replace('https://', '')
    base_url = f"http://{base}:5000" 
    if 'ts.net' in base: base_url = f"http://{base}" 
    
    volledige_url = f"{base_url}/control/{wedstrijd_id}?token={token}"
    qr_base64 = genereer_qr_code(volledige_url)
    
    return {'qr_code': qr_base64, 'url': volledige_url}


@app.route('/control/<string:wedstrijd_id>')
def confirm_wedstrijd(wedstrijd_id):
    wedstrijd = WEDSTRIJDEN_DB.get(wedstrijd_id)
    if not wedstrijd: return abort(404)

    # --- NIEUW: HARD CHECK OP ACTIEVE WEDSTRIJD ---
    # Als de admin deze wedstrijd niet heeft aangezet via de knop,
    # mag je er NIET in, zelfs niet met een geldige token.
    if HUIDIGE_ACTIEVE_WEDSTRIJD_ID != wedstrijd_id:
        return render_template('error.html', message="Deze wedstrijd is niet geactiveerd door de beheerder. Vraag de bar om de wedstrijd te starten.")
    # ----------------------------------------------

    # 1. Authenticatie Check (Sessie of Token)
    session_key = f"auth_{wedstrijd_id}"
    
    if session.get(session_key):
        pass 
    else:
        url_token = request.args.get('token')
        server_token = WEDSTRIJD_TOKENS.get(wedstrijd_id)
        
        if url_token and server_token and url_token == server_token:
            session[session_key] = True
            # Token vernietigen na gebruik (veiligheid)
            WEDSTRIJD_TOKENS.pop(wedstrijd_id, None) 
        else:
             return render_template('error.html', message="Ongeldige of verlopen QR-code.")

    # 2. Doorsturen naar setup pagina (logo kiezen, duur instellen)
    return redirect(url_for('match_setup_page', wedstrijd_id=wedstrijd_id))

# --- MATCH SETUP (Leider configureert na QR scan) ---

@app.route('/match-setup/<string:wedstrijd_id>')
def match_setup_page(wedstrijd_id):
    if HUIDIGE_ACTIEVE_WEDSTRIJD_ID != wedstrijd_id:
        return render_template('error.html', message="Deze wedstrijd is niet geactiveerd door de beheerder.")
    session_key = f"auth_{wedstrijd_id}"
    if not session.get(session_key):
        return render_template('error.html', message="Geen toegang. Scan de QR-code opnieuw.")

    wedstrijd = WEDSTRIJDEN_DB.get(wedstrijd_id)
    if not wedstrijd: return abort(404)

    # Lijst van beschikbare logos
    logos = []
    if os.path.exists(LOGO_FOLDER):
        logos = sorted([f for f in os.listdir(LOGO_FOLDER) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))])

    return render_template('match-setup.html', wedstrijd=wedstrijd, logos=logos)

@app.route('/match-setup/<string:wedstrijd_id>', methods=['POST'])
def match_setup_save(wedstrijd_id):
    if HUIDIGE_ACTIEVE_WEDSTRIJD_ID != wedstrijd_id:
        return render_template('error.html', message="Niet geactiveerd.")
    session_key = f"auth_{wedstrijd_id}"
    if not session.get(session_key):
        return render_template('error.html', message="Geen toegang.")

    wedstrijd = WEDSTRIJDEN_DB.get(wedstrijd_id)
    if not wedstrijd: return abort(404)

    # Logo selectie opslaan
    uit_logo = request.form.get('uit_logo')
    if uit_logo:
        wedstrijd['uit_logo_lokaal'] = f"clublogos/{uit_logo}"

    # Duur per helft opslaan
    duur = request.form.get('duur_per_helft', 45)
    wedstrijd['duur_per_helft'] = int(duur)

    # Naar bestand opslaan
    try:
        with open(WEDSTRIJDEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(WEDSTRIJDEN_DB.values()), f, indent=4)
    except Exception as e:
        logging.error(f"Fout bij opslaan wedstrijd setup: {e}")

    # Stuur display update met nieuw logo
    socketio.emit('score_is_geupdate', enrich_match_data(wedstrijd))

    return redirect(url_for('control_panel', wedstrijd_id=wedstrijd_id))

# --- API Endpoints ---

@app.route('/api/sponsor-list')
def api_sponsor_list():
    """Geeft een JSON lijst van alle sponsor afbeeldingen in de sponsors map."""
    sponsors = []
    if os.path.exists(UPLOAD_FOLDER):
        sponsors = sorted([
            f for f in os.listdir(UPLOAD_FOLDER)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))
        ])
    return {'sponsors': sponsors}

@app.route('/api/clublogos')
def api_clublogos():
    """Geeft een lijst van beschikbare clublogo bestanden."""
    logos = []
    if os.path.exists(LOGO_FOLDER):
        logos = sorted([f for f in os.listdir(LOGO_FOLDER) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))])
    return {'logos': logos}

# --- KIOSK: Snel wedstrijd aanmaken ---

@app.route('/kiosk/create-match', methods=['POST'])
def kiosk_create_match():
    if not session.get('kiosk_logged_in') and not session.get('admin_logged_in'):
        return redirect(url_for('login_page'))

    match_id = str(uuid.uuid4())
    thuis = request.form.get('thuis', 'SV Bedum').strip() or 'SV Bedum'
    uit = request.form.get('uit', 'Tegenstander').strip() or 'Tegenstander'
    is_eerste = request.form.get('eerste_elftal') == 'on'

    match_data = {
        "id": match_id,
        "thuis": thuis,
        "uit": uit,
        "tijd": "",
        "datum": "",
        "scoreThuis": 0,
        "scoreUit": 0,
        "status": "Nog niet begonnen",
        "thuis_logo_lokaal": "clublogos/default_home_logo-sv-bedum.png",
        "uit_logo_lokaal": None,
        "eerste_elftal": is_eerste,
        "duur_per_helft": 45
    }

    WEDSTRIJDEN_DB[match_id] = match_data
    try:
        with open(WEDSTRIJDEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(WEDSTRIJDEN_DB.values()), f, indent=4)
    except Exception as e:
        logging.error(f"Fout bij aanmaken wedstrijd: {e}")

    return redirect(url_for('kiosk_dashboard'))

@app.route('/control_panel/<string:wedstrijd_id>')
def control_panel(wedstrijd_id):
    if HUIDIGE_ACTIEVE_WEDSTRIJD_ID != wedstrijd_id:
        return render_template('error.html', message="...")

    wedstrijd = WEDSTRIJDEN_DB.get(wedstrijd_id)
    if not wedstrijd: return abort(404)
    
    load_players()
    is_eerste = wedstrijd.get('eerste_elftal') or wedstrijd.get('thuis', '').strip() == "SV Bedum 1"
    return render_template('control.html', wedstrijd=wedstrijd, spelers=SPELERS_DB, is_eerste_elftal=is_eerste)

@app.route('/display')
def display_page():
    instellingen = load_settings()
    theme = {**DEFAULT_SETTINGS, **instellingen.get('theme', {})}
    
    # Vaste sponsors altijd, extra sponsors bij eerste elftal
    huidige_sponsors = get_actieve_sponsoren()

    return render_template('display.html', 
        sponsor_lijst=huidige_sponsors,
        standaard_thuis_logo=theme.get('standaard_thuis_logo'),
        theme_json=theme
    )
# --- NIEUWE SPONSOR ADMIN Routes ---


# --- ADMIN WEDSTRIJD BEHEER ---

@app.route('/admin/matches')
def admin_matches_page():
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    # Ververs de data
    laad_wedstrijden_van_json()
    
    edit_id = request.args.get('edit')
    edit_match = WEDSTRIJDEN_DB.get(edit_id)
    lijst = sorted(WEDSTRIJDEN_DB.values(), key=lambda x: x['tijd'])
    
    # Haal scraper timeout op uit settings
    instellingen = load_settings()
    timeout = instellingen.get('theme', {}).get('scraper_timeout', 10)
    
    return render_template('admin-matches.html', wedstrijden=lijst, edit_match=edit_match, scraper_timeout=timeout)

@app.route('/admin/save-match', methods=['POST'])
def admin_save_match():
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    match_id = request.form.get('match_id')
    
    # Bestaande pakken of nieuwe maken
    if match_id and match_id in WEDSTRIJDEN_DB: 
        match_data = WEDSTRIJDEN_DB[match_id]
    else:
        match_id = str(uuid.uuid4())
        match_data = {
            "id": match_id, "scoreThuis": 0, "scoreUit": 0, 
            "status": "Nog niet begonnen", 
            "uit_logo_lokaal": None, 
            "thuis_logo_lokaal": None # <-- Specifiek thuislogo veld
        }
    
    # Velden updaten
    match_data['tijd'] = request.form.get('tijd')
    match_data['thuis'] = request.form.get('thuis')
    match_data['uit'] = request.form.get('uit')
    
    # Zorg dat map bestaat
    os.makedirs(LOGO_FOLDER, exist_ok=True)
    
    # 1. Uit-Logo Upload
    f_uit = request.files.get('uit_logo')
    if f_uit and f_uit.filename != '':
        fname = secure_filename(f"{match_id}_uit_{f_uit.filename}")
        f_uit.save(os.path.join(LOGO_FOLDER, fname))
        match_data['uit_logo_lokaal'] = f"clublogos/{fname}"

    # 2. Thuis-Logo Upload (NIEUW)
    f_thuis = request.files.get('thuis_logo')
    if f_thuis and f_thuis.filename != '':
        fname = secure_filename(f"{match_id}_thuis_{f_thuis.filename}")
        f_thuis.save(os.path.join(LOGO_FOLDER, fname))
        match_data['thuis_logo_lokaal'] = f"clublogos/{fname}"

    # Opslaan
    WEDSTRIJDEN_DB[match_id] = match_data
    try:
        with open(WEDSTRIJDEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(WEDSTRIJDEN_DB.values()), f, indent=4)
    except: pass
    
    return redirect(url_for('admin_matches_page'))

@app.route('/admin/delete-match')
def admin_delete_match():
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    mid = request.args.get('id')
    if mid in WEDSTRIJDEN_DB:
        del WEDSTRIJDEN_DB[mid]
        try:
            with open('wedstrijden.json', 'w', encoding='utf-8') as f: 
                json.dump(list(WEDSTRIJDEN_DB.values()), f, indent=4)
        except: pass
    return redirect(url_for('admin_matches_page'))

@app.route('/admin/run-scraper', methods=['POST'])
def admin_run_scraper():
    """Start de scraper in een thread."""
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    timeout = int(request.form.get('timeout', 10))
    
    # Sla timeout op in settings voor de volgende keer
    instellingen = load_settings()
    if 'theme' not in instellingen: instellingen['theme'] = {}
    instellingen['theme']['scraper_timeout'] = timeout
    save_settings(instellingen)
    
    def run_async():
        logging.info(f"Handmatige scraper start (timeout: {timeout}s)...")
        # Roep de scraper functie aan
        scraper.get_veld1_wedstrijden(timeout)
        # Herlaad de data in het geheugen van de app
        laad_wedstrijden_van_json() 
        logging.info("Handmatige scraper klaar.")

    threading.Thread(target=run_async).start()
    return redirect(url_for('admin_matches_page'))



@app.route('/admin/sponsors')
def admin_sponsors_page():
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    try:
        all_files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]
    except FileNotFoundError:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        all_files = []
        
    instellingen = load_settings()
    # Haal hier de lijst op!
    huidige_selectie = instellingen.get('theme', {}).get('geselecteerde_sponsors', [])
    
    return render_template(
        'admin-sponsors.html',
        all_sponsor_files=all_files,
        huidige_hoofdsponsor=huidige_selectie # Variabele naam hergebruikt in template
    )

@app.route('/admin/upload-sponsor', methods=['POST'])
def upload_sponsor_file():
    """Verwerkt de file upload."""
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    if 'sponsor_file' not in request.files:
        return redirect(url_for('admin_sponsors_page'))
        
    file = request.files['sponsor_file']
    if file.filename == '':
        return redirect(url_for('admin_sponsors_page'))
        
    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
    return redirect(url_for('admin_sponsors_page'))

@app.route('/admin/select-sponsors', methods=['POST'])
def select_sponsor_files():
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))

    instellingen = load_settings()
    if 'theme' not in instellingen: instellingen['theme'] = {}

    # Haal de lijst op uit het formulier
    geselecteerd = request.form.getlist('sponsors')
    
    # Sla op in de JSON structuur
    instellingen['theme']['geselecteerde_sponsors'] = geselecteerd
    
    # Opslaan naar schijf
    save_settings(instellingen)
    
    # CRUCIAAL: Herlaad de assets in de actieve server sessie
    laad_assets()
    
    return redirect(url_for('admin_sponsors_page'))

@app.route('/admin/sync-sponsors', methods=['POST'])
def admin_sync_sponsors():
    if not session.get('admin_logged_in'):
        return {'error': 'Niet ingelogd'}, 403

    instellingen = load_settings()
    master_ip = instellingen.get('master_ip', '')
    master_port = instellingen.get('master_port', 5000)
    if not master_ip:
        return {'ok': False, 'error': 'Geen master IP ingesteld in admin'}, 400

    base_url = f"http://{master_ip}:{master_port}"
    try:
        resp = requests.get(f"{base_url}/api/sponsors", timeout=10)
        resp.raise_for_status()
        sponsors = resp.json().get('sponsors', [])

        # Verwijder alleen bestanden (niet de map zelf, om toegangsproblemen te voorkomen)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        for bestand in os.listdir(UPLOAD_FOLDER):
            pad = os.path.join(UPLOAD_FOLDER, bestand)
            if os.path.isfile(pad):
                try:
                    os.remove(pad)
                except Exception as e:
                    logging.warning(f"Kon {bestand} niet verwijderen: {e}")

        # Download elk bestand
        for s in sponsors:
            img_url = f"{base_url}{s['url']}"
            img_resp = requests.get(img_url, timeout=10)
            img_resp.raise_for_status()
            with open(os.path.join(UPLOAD_FOLDER, s['filename']), 'wb') as f:
                f.write(img_resp.content)

        laad_assets()
        socketio.emit('update_sponsoren_lijst', {'sponsoren': SPONSOR_ROTEREND})
        logging.info(f"Sponsors gesynchroniseerd van {master_ip}:{master_port}: {len(sponsors)} bestanden.")
        return {'ok': True, 'count': len(sponsors)}

    except requests.exceptions.RequestException as e:
        return {'ok': False, 'error': f"Master niet bereikbaar: {e}"}, 503
    except Exception as e:
        return {'ok': False, 'error': str(e)}, 500

@app.route('/admin/save-master-ip', methods=['POST'])
def admin_save_master_ip():
    if not session.get('admin_logged_in'):
        return {'error': 'Niet ingelogd'}, 403
    data = request.get_json()
    instellingen = load_settings()
    instellingen['master_ip'] = data.get('ip', '')
    instellingen['master_port'] = int(data.get('port', 5000))
    save_settings(instellingen)
    return {'ok': True}

@app.route('/admin/save-sponsor-server', methods=['POST'])
def admin_save_sponsor_server():
    if not session.get('admin_logged_in'):
        return {'error': 'Niet ingelogd'}, 403

    data = request.get_json()
    instellingen = load_settings()
    instellingen['sponsor_server_ip'] = data.get('ip', '')
    instellingen['sponsor_server_port'] = int(data.get('port', 4000))
    save_settings(instellingen)
    return {'ok': True}

@app.route('/admin/test-sponsor-server')
def admin_test_sponsor_server():
    if not session.get('admin_logged_in'):
        return {'error': 'Niet ingelogd'}, 403

    instellingen = load_settings()
    ip = instellingen.get('sponsor_server_ip', '')
    port = instellingen.get('sponsor_server_port', 4000)

    if not ip:
        return {'ok': False, 'error': 'Geen IP ingesteld'}

    try:
        resp = requests.get(f"http://{ip}:{port}/api/sponsors", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        count = len(data.get('sponsors', []))
        return {'ok': True, 'count': count}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.route('/admin/upload-home-logo', methods=['POST'])
def admin_upload_home_logo():
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    f = request.files.get('home_logo')
    if f and f.filename != '':
        os.makedirs(os.path.join(BASE_PATH, 'static', 'clublogos'), exist_ok=True)
        
        filename = secure_filename(f"default_home_{f.filename}")
        # Sla op in de juiste map
        f.save(os.path.join(BASE_PATH, 'static', 'clublogos', filename))
        
        instellingen = load_settings()
        if 'theme' not in instellingen: instellingen['theme'] = {}
        
        # Sla het pad op in de JSON
        instellingen['theme']['standaard_thuis_logo'] = f"clublogos/{filename}"
        save_settings(instellingen)
        
        # CRUCIAAL: Herlaad assets zodat STANDAARD_THUIS_LOGO wordt bijgewerkt
        laad_assets()
        
    return redirect(url_for('admin_page'))

# --- CSS Generator (AANGEPAST: Geen inkepingen/scoops meer) ---
# --- CSS Generator (AANGEPAST VOOR SCORE ROW FIX) ---
@app.route('/theme.css')
def dynamic_theme_css():
    """Genereert het CSS-bestand op basis van settings.json voor de BANNER layout."""
    instellingen = load_settings()
    theme = {**DEFAULT_SETTINGS, **instellingen.get('theme', {})}
    
    # Bepaal de grootte van de 'scoop' (de ronde inkeping)
    scoop_radius = "3vh" 
    
    css = f"""
        /* --- CSS Variabelen (Nodig voor live updates) --- */
        :root {{
            --top-bar-height: {theme['top_bar_height']}vh;
        }}

        body {{
            font-family: Arial, "Helvetica Neue", Helvetica, sans-serif;
            margin: 0;
            overflow: hidden;
            height: 100vh;
            display: flex;
            flex-direction: column;
            background-color: {theme['background_color']};
        }}
        
        .bar-container {{
            width: 100%;
            display: flex;
            justify-content: center;
            position: relative;
            z-index: 2; 
        }}

        /* --- 1. De Bovenste Balk (Timer) --- */
        .top-bar {{
            background-color: {theme['banner_color']};
            width: {theme['top_banner_width']}%;
            min-width: 300px;
            
            /* AANGEPAST: Gebruik nu de CSS variabele voor live updates */
            height: var(--top-bar-height);
            
            display: flex;
            align-items: center;
            justify-content: center;
            box-sizing: border-box;
            position: relative; 
            border-bottom-left-radius: {scoop_radius};
            border-bottom-right-radius: {scoop_radius};
        }}
        .timer {{
            font-size: {theme['timer_size']}vw;
            color: {theme['timer_color']};
            font-weight: bold;
            text-align: center;
            padding: 0 2vw; 
        }}

        /* --- 2. Het Middenstuk (Score & Logos) --- */
        .main-display {{
            background-color: {theme['background_color']};
            flex-grow: 1; 
            padding: 1vw; 
            box-sizing: border-box;
            display: flex; 
            align-items: center; 
            justify-content: center;
            position: relative;
            z-index: 1; 
        }}
        .placeholder {{
            text-align: center; 
            font-size: {theme['score_size'] * 0.4}vw; 
            color: #ccc; 
            width: 100%;
        }}
        #live {{
            display: none; 
            width: 100%;
            height: 100%;
            flex-direction: column; /* Belangrijk voor layout! */
            align-items: center;
            justify-content: center;
        }}
        
        /* --- NIEUWE SCORE-RIJ STIJLEN (Dit fixt de layout!) --- */
        .score-row {{
            display: flex;
            justify-content: center;
            align-items: center;
            width: 100%;
        }}
        .team-logo-container {{
            width: 40%; 
            text-align: center;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .team-logo {{
            max-width: 90%;
            height: {theme['logo_size']}vh;
            object-fit: contain;
        }}
        .score {{
            width: 20%;
            text-align: center;
            font-size: {theme['score_size']}vw;
            font-weight: bold;
            color: {theme['score_color']};
            white-space: nowrap;
            padding: 0 2vw;
        }}
        
        /* De andere rijen verbergen we of stylen we minimaal */
        .timer-row, .teamnaam-row {{
             width: 100%; text-align: center;
        }}

        /* --- 3. De Onderste Balk (Sponsor) --- */
        .bottom-bar {{
            background-color: {theme['banner_color']};
            width: {theme['bottom_banner_width']}%;
            min-width: 300px;
            height: {theme['sponsor_bar_height']}vh;
            display: flex; 
            align-items: center; 
            justify-content: center;
            box-sizing: border-box;
            position: relative;
            border-top-left-radius: {scoop_radius};
            border-top-right-radius: {scoop_radius};
            overflow: hidden;
        }}
        .sponsor-logo {{
            height: {theme['sponsor_bar_height'] - 4}vh;
            width: auto;
            max-width: 30%;
            object-fit: contain;
            margin: 0 1vw;
        }}
    """
    
    return Response(css, mimetype='text/css')

# --- Admin & Login Routes (ongewijzigd) ---
@app.route('/login')
def login_page():
    return render_template('login.html', error=request.args.get('error'))
# --- In app.py, vervang de admin_login_post functie ---

@app.route('/admin-login', methods=['POST'])
def admin_login_post():
    password = request.form.get('password')
    
    # Scenario 1: Hoofdbeheerder
    if password == ADMIN_WACHTWOORD:
        session['admin_logged_in'] = True
        session['kiosk_logged_in'] = True # Admin mag ook bij de kiosk
        return redirect(url_for('admin_page')) # Gaat naar instellingen
        
    # Scenario 2: Barpersoneel
    elif password == KIOSK_WACHTWOORD:
        session['kiosk_logged_in'] = True
        # admin_logged_in blijft False!
        return redirect(url_for('kiosk_dashboard')) # Gaat direct naar QR scherm
        
    # Scenario 3: Fout
    return redirect(url_for('login_page', error=True))

# --- NIEUWE ROUTES VOOR WEDSTRIJD BEHEER EN WELKOM ---


@app.route('/admin')
def admin_page():
    """Toont de admin-pagina, geladen met alle instellingen."""
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    instellingen = load_settings()
    
    monitor_width = instellingen.get('monitor_width', 1920)
    monitor_height = instellingen.get('monitor_height', 1080)
    
    window_data = {
        'current_x': instellingen.get('x', 0),
        'current_y': instellingen.get('y', 0),
        'current_width': instellingen.get('width', monitor_width),
        'current_height': instellingen.get('height', monitor_height // 6)
    }
    
    theme_data = {**DEFAULT_SETTINGS, **instellingen.get('theme', {})}

    return render_template(
        'admin.html',
        monitor_width=monitor_width,
        monitor_height=monitor_height,
        monitor_width_extended=monitor_width + 100,
        monitor_height_extended=monitor_height + 100,
        window_data=window_data,
        theme_data=theme_data,
        master_ip=instellingen.get('master_ip', ''),
        master_port=instellingen.get('master_port', 5000)
    )


@app.route('/admin/players')
def admin_players_page():
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    load_players() # Ververs data
    return render_template('admin-players.html', spelers=SPELERS_DB)

@app.route('/admin/save-player', methods=['POST'])
def admin_save_player():
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    # Gebruikt uuid om een uniek ID te maken voor nieuwe spelers
    speler_id = request.form.get('id')
    if not speler_id or speler_id == "":
        speler_id = str(uuid.uuid4())
        is_new = True
    else:
        is_new = False
    
    # Check of speler al bestaat
    for p in SPELERS_DB:
        if p['id'] == speler_id:
            speler = p
            is_new = False
            break
    
    if is_new:
        speler = {'id': speler_id}
        SPELERS_DB.append(speler)
    
    speler['naam'] = request.form.get('naam')
    speler['rugnummer'] = int(request.form.get('rugnummer', 0))
    
    # Foto's opslaan
    for veld in ['foto_profiel', 'foto_actie']:
        f = request.files.get(veld)
        if f and f.filename != '':
            ext = f.filename.rsplit('.', 1)[1].lower()
            fname = secure_filename(f"{speler_id}_{veld}.{ext}")
            f.save(os.path.join(PLAYERS_FOLDER, fname))
            speler[veld] = f"static/players/{fname}"
            
    save_players()
    return redirect(url_for('admin_players_page'))

@app.route('/admin/delete-player/<string:speler_id>')
def admin_delete_player(speler_id):
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    global SPELERS_DB
    SPELERS_DB = [p for p in SPELERS_DB if p['id'] != speler_id]
    save_players()
    return redirect(url_for('admin_players_page'))


@socketio.on('doelpunt_gevierd')
def handle_doelpunt_gevierd(data):
    if data.get('match_id') != HUIDIGE_ACTIEVE_WEDSTRIJD_ID:
        return

    # Score update
    wedstrijd = WEDSTRIJDEN_DB.get(data.get('match_id'))
    if wedstrijd:
        wedstrijd['scoreThuis'] += 1
        emit('score_is_geupdate', wedstrijd, broadcast=True)

    # Foto logica
    speler_id = data.get('player_id')
    gekozen_speler = next((p for p in SPELERS_DB if p['id'] == speler_id), None)
    
    if gekozen_speler:
        # HIER: Pak expliciet 'foto_actie'.
        gebruikte_foto = gekozen_speler.get('foto_actie') or gekozen_speler.get('foto_profiel')
        
        emit('toon_doelpunt_visual', {
            'foto': gebruikte_foto,  # Dit wordt verstuurd naar de 'toon_doelpunt_visual' functie hierboven
            'naam': gekozen_speler.get('naam'),
            'rugnummer': gekozen_speler.get('rugnummer')
        }, broadcast=True)

@socketio.on('update_score')
def handle_update_score(data):
    # CHECK: Mag dit wel?
    if data.get('id') != HUIDIGE_ACTIEVE_WEDSTRIJD_ID:
        return # Negeer het verzoek volledig
        
    wedstrijd_id = data.get('id'); team = data.get('team'); change = data.get('change')
    wedstrijd = WEDSTRIJDEN_DB.get(wedstrijd_id)
    if not wedstrijd: return 
    
    if team == 'thuis': wedstrijd['scoreThuis'] = max(0, wedstrijd['scoreThuis'] + change)
    elif team == 'uit': wedstrijd['scoreUit'] = max(0, wedstrijd['scoreUit'] + change)
    
    emit('score_is_geupdate', wedstrijd, broadcast=True)

@socketio.on('update_status')
def handle_update_status(data):
    # CHECK: Mag dit wel?
    if data.get('id') != HUIDIGE_ACTIEVE_WEDSTRIJD_ID:
        return # Negeer
        
    wedstrijd_id = data.get('id'); new_status = data.get('status')
    wedstrijd = WEDSTRIJDEN_DB.get(wedstrijd_id)
    if not wedstrijd: return 
    
    wedstrijd['status'] = new_status
    emit('status_is_geupdate', wedstrijd, broadcast=True)

# --- In app.py ---

@socketio.on('client_wakker')
def handle_client_wakker(data):
    wedstrijd_id = data.get('id')
    
    # 1. DICTATOR CHECK: 
    # Als de telefoon niet matcht met wat de ADMIN heeft ingesteld:
    if HUIDIGE_ACTIEVE_WEDSTRIJD_ID != wedstrijd_id:
        logging.warning(f"Poging tot overname geblokkeerd. Huidig: {HUIDIGE_ACTIEVE_WEDSTRIJD_ID}, Poging: {wedstrijd_id}")
        
        # Stuur een signaal naar DEZE telefoon dat hij moet stoppen
        # (We gebruiken request.sid om alleen deze hacker/oude gebruiker te raken)
        emit('wedstrijd_gestopt', room=request.sid)
        return

    # 2. Als we hier zijn, is het de juiste wedstrijd.
    wedstrijd = WEDSTRIJDEN_DB.get(wedstrijd_id)
    if not wedstrijd: return 

    logging.info(f"Bediening verbonden voor actieve wedstrijd: {wedstrijd['thuis']}")
    
    # Stuur status update (zodat de knoppen goed staan)
    emit('status_is_geupdate', wedstrijd, broadcast=True)

@socketio.on('stop_wedstrijd')
def handle_stop_wedstrijd():
    """
    De 'Stop' knop is ingedrukt. Reset het bord.
    """
    global HUIDIGE_ACTIEVE_WEDSTRIJD_ID # <-- NIEUW
    logging.info("Stop knop ontvangen. Scorebord resetten.")
    
    HUIDIGE_ACTIEVE_WEDSTRIJD_ID = None # <-- NIEUW: Maak het bord vrij
    
    # Stuur een 'gestopt' signaal naar het display
    emit('wedstrijd_gestopt', broadcast=True)



@socketio.on('lineup_control')
def handle_lineup_control(data):
    # Check authenticatie (optioneel: session check toevoegen)
    action = data.get('action')
    global ACTIVE_LINEUP
    
    if action == 'start':
        # Haal geselecteerde IDs op en bouw de lijst
        selected_ids = data.get('selected_ids', [])
        # Filter de DB op geselecteerde IDs en sorteer op rugnummer
        ACTIVE_LINEUP['players'] = [p for p in SPELERS_DB if p['id'] in selected_ids]
        ACTIVE_LINEUP['players'].sort(key=lambda x: x.get('rugnummer', 0))
        ACTIVE_LINEUP['index'] = -1 # Startpositie (nog niemand in beeld)
        
        emit('lineup_status', {'active': True, 'state': 'intro'}, broadcast=True)
        
    elif action == 'next':
        if not ACTIVE_LINEUP['players']: return
        
        ACTIVE_LINEUP['index'] += 1
        # Check of we aan het einde zijn
        if ACTIVE_LINEUP['index'] >= len(ACTIVE_LINEUP['players']):
             # Einde bereikt
             emit('lineup_status', {'active': True, 'state': 'finished'}, broadcast=True)
             ACTIVE_LINEUP['index'] = len(ACTIVE_LINEUP['players']) # Cap index
        else:
             p = ACTIVE_LINEUP['players'][ACTIVE_LINEUP['index']]
             emit('lineup_update', p, broadcast=True)

    elif action == 'prev':
        if ACTIVE_LINEUP['index'] > 0:
            ACTIVE_LINEUP['index'] -= 1
            p = ACTIVE_LINEUP['players'][ACTIVE_LINEUP['index']]
            emit('lineup_update', p, broadcast=True)
            
    elif action == 'stop':
        ACTIVE_LINEUP = {"players": [], "index": -1}
        emit('lineup_status', {'active': False}, broadcast=True)


@socketio.on('admin_transform')
def handle_admin_transform(data):
    if not session.get('admin_logged_in'): return 
    if main_kiosk_window:
        try:
            x, y, w, h = int(data.get('x')), int(data.get('y')), int(data.get('width')), int(data.get('height'))
            main_kiosk_window.move(x, y); main_kiosk_window.resize(w, h)
            instellingen = load_settings()
            instellingen.update({'x': x, 'y': y, 'width': w, 'height': h})
            save_settings(instellingen)
        except Exception as e: logging.error(f"Fout bij admin transform: {e}")

@socketio.on('admin_update_theme')
def handle_admin_update_theme(data):
    if not session.get('admin_logged_in'): return
    try:
        logging.info("Thema update ontvangen en doorgestuurd")
        instellingen = load_settings()
        instellingen['theme'] = data 
        save_settings(instellingen)
        
        # NIEUW: Stuur de update direct door naar het scherm!
        emit('theme_update', data, broadcast=True) 
        
    except Exception as e:
        logging.error(f"Fout bij opslaan thema: {e}")
        
@socketio.on('admin_restart')
def handle_admin_restart():
    """Herstart de app (werkt voor zowel script als .exe)."""
    if not session.get('admin_logged_in'): return
    
    logging.warning("ADMIN RESTART: Applicatie wordt herstart...")
    
    def delayed_restart():
        time.sleep(1) 
        try:
            # Check of we als .exe draaien (PyInstaller)
            if getattr(sys, 'frozen', False):
                # Als .exe: start gewoon de exe opnieuw zonder argumenten
                subprocess.Popen([sys.executable])
            else:
                # Als script: start python + het script
                subprocess.Popen([sys.executable] + sys.argv)
                
            # Stop het huidige proces hard
            os._exit(0)
            
        except Exception as e:
            logging.error(f"FATALE FOUT: Kon niet herstarten. {e}")
            
    threading.Thread(target=delayed_restart).start()


@socketio.on('toggle_balsponsors')
def handle_toggle_balsponsors(data):
    """Ontvangt de checkbox-status van de control pagina en stuurt de nieuwe lijst."""
    is_actief = data.get('active', False)
    logging.info(f"Extra sponsoren (eerste elftal) ingesteld op: {is_actief}")

    # Altijd de vaste 2 hoofdsponsoren
    nieuwe_lijst = list(VASTE_SPONSORS)

    # Voeg externe sponsoren toe als het vinkje aan staat
    if is_actief:
        externe = haal_externe_sponsoren_op()
        nieuwe_lijst.extend(externe)

    # Stuur de nieuwe lijst naar ALLE clients (inclusief het display)
    emit('update_sponsoren_lijst', {'sponsoren': nieuwe_lijst}, broadcast=True)

# --- Server Start Functie ---
def start_server_func():
    logging.info(f"Server start op http://{SERVER_IP}:5000")
    # Gebruik eventlet of gevent als je async_mode='threading' hebt, 
    # maar voor nu laten we dit zo voor de compatibiliteit.
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)

# Dit blok voert de synchronisatie uit wanneer de module wordt geladen door run_kiosk.py
# maar START de server nog niet.
def initialize_app():
    try:
        instellingen = load_settings()
        master_ip = instellingen.get('master_ip', '')
        master_port = instellingen.get('master_port', 5000)
        sync_sponsors_van_master(master_ip, master_port)
        laad_wedstrijden_van_json()
        load_players()
        laad_assets()
        get_local_ip()
        logging.info("App initialisatie voltooid.")
    except Exception as e:
        logging.error(f"Fout tijdens initialisatie: {e}")

# Alleen als je direct 'python app.py' draait:
if __name__ == "__main__":
    initialize_app()
    start_server_func()