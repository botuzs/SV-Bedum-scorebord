import json
import logging
import socket 
import qrcode
import io 
import base64 
import os 
import sys
import threading
import subprocess
import secrets 
from flask import Flask, render_template, abort, request, redirect, url_for, session, Response, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
import scraper

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
# ... (rest van je variabelen)

# --- Configuratie ---
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
LOGO_FOLDER = os.path.join('static', 'clublogos')
app.config['SECRET_KEY'] = 'svbedum_zeer_geheim_wachtwoord_123' 
socketio = SocketIO(app, async_mode='threading')

WEDSTRIJDEN_DB = {}
SERVER_IP = "0.0.0.0"
ADMIN_WACHTWOORD = "svbedum"   # Voor volledig beheer (instellingen, teams, etc.)
KIOSK_WACHTWOORD = "bar123"
SETTINGS_FILE = 'settings.json'

# --- Globale Objecten ---
main_kiosk_window = None
SPONSOR_VAST = None
SPONSOR_ROTEREND = []
HOOFDSPONSOR = None
BALSPONSOREN = []
UPLOAD_FOLDER = os.path.join('static', 'sponsors') # We gooien alles in één map
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

HUIDIGE_ACTIEVE_WEDSTRIJD_ID = None # <-- DEZE REGEL IS NIEUW

# --- Standaard Thema Instellingen (AANGEPAST VOOR BANNER LAYOUT) ---
DEFAULT_SETTINGS = {
    "background_color": "#4a148c", # Paars
    "timer_color": "#000000",      # Zwart (op witte balk)
    "timer_size": 4.0,             # in vw
    "score_color": "#FFFFFF",      # Wit
    "score_size": 10.0,            # in vw
    "logo_size": 25,               # in vh (vertical height)
    "sponsor_bar_height": 14,      # in vh
    "banner_color": "#FFFFFF",     # Algemene banner kleur
    "top_banner_width": 40,        # in %
    "bottom_banner_width": 60      # in %
}

# --- Instellingen Functies (ongewijzigd) ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e: logging.error(f"Kon settings.json niet laden: {e}")
    return {}

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
    """Laadt sponsors en instellingen."""
    global SPONSOR_ROTEREND, HOOFDSPONSOR, BALSPONSOREN, STANDAARD_THUIS_LOGO
    
    instellingen = load_settings()
    theme = instellingen.get('theme', {})
    
    # 1. Laad specifieke keuzes uit settings
    HOOFDSPONSOR = theme.get('hoofdsponsor_file')
    BALSPONSOREN = theme.get('balsponsor_files', [])
    STANDAARD_THUIS_LOGO = theme.get('standaard_thuis_logo')

    # 2. Vul de lijst voor de balk (SPONSOR_ROTEREND)
    # We gebruiken hier de BALSPONSOREN lijst als die er is, 
    # anders scannen we de map als fallback.
    SPONSOR_ROTEREND = []
    
    if BALSPONSOREN:
        # Als er balsponsoren zijn geselecteerd, gebruik die
        SPONSOR_ROTEREND = BALSPONSOREN
    else:
        # Fallback: scan de map als er niets is geselecteerd
        sponsor_base_path = os.path.join('static', 'sponsors')
        if os.path.exists(sponsor_base_path):
            for root, dirs, files in os.walk(sponsor_base_path):
                for f in files:
                    if f.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                        path = os.path.relpath(os.path.join(root, f), 'static').replace("\\", "/")
                        SPONSOR_ROTEREND.append(path)

    logging.info(f"Assets geladen. Std Thuis Logo: {STANDAARD_THUIS_LOGO}")

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
    socketio.emit('forceer_nieuwe_wedstrijd', {'id': wedstrijd_id})
    
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

    # 2. Direct doorsturen (geen keuze meer nodig, want admin heeft al gekozen)
    return redirect(url_for('control_panel', wedstrijd_id=wedstrijd_id))

# --- In app.py ---

@app.route('/control_panel/<string:wedstrijd_id>')
def control_panel(wedstrijd_id):
    # 1. HARD CHECK: Is dit wel de wedstrijd die de admin wil zien?
    if HUIDIGE_ACTIEVE_WEDSTRIJD_ID != wedstrijd_id:
        # Nee? Dan sturen we ze weg naar de foutpagina.
        return render_template('error.html', message="Deze wedstrijd is beëindigd of niet actief. De beheerder heeft het scorebord vrijgegeven of een andere wedstrijd gestart.")

    wedstrijd = WEDSTRIJDEN_DB.get(wedstrijd_id)
    if not wedstrijd: return abort(404)
    
    return render_template('control.html', wedstrijd=wedstrijd)

@app.route('/display')
def display_page():
    """Geeft de display pagina."""
    # Geef de variabelen door die we in laad_assets hebben gevuld
    return render_template('display.html', 
        roterende_sponsors_lijst=SPONSOR_ROTEREND,
        hoofdsponsor_pad=HOOFDSPONSOR,
        standaard_thuis_logo=STANDAARD_THUIS_LOGO
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
        with open('wedstrijden.json', 'w', encoding='utf-8') as f: 
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
    """Toont de nieuwe sponsor admin pagina."""
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    # 1. Scan de sponsor map
    try:
        all_files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]
    except FileNotFoundError:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        all_files = []
        
    # 2. Haal huidige selectie op
    instellingen = load_settings()
    theme_settings = instellingen.get('theme', {})
    huidige_hoofdsponsor = theme_settings.get('hoofdsponsor_file')
    huidige_balsponsoren = theme_settings.get('balsponsor_files', [])
    
    return render_template(
        'admin-sponsors.html',
        all_sponsor_files=all_files,
        huidige_hoofdsponsor=huidige_hoofdsponsor,
        huidige_balsponsoren=huidige_balsponsoren
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
    """Slaat de selectie van hoofd- en balsponsoren op."""
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))

    instellingen = load_settings()
    if 'theme' not in instellingen:
        instellingen['theme'] = {}

    # 1. Sla de hoofdsponsor op
    instellingen['theme']['hoofdsponsor_file'] = request.form.get('hoofdsponsor')
    
    # 2. Sla de balsponsoren op (max 2)
    instellingen['theme']['balsponsor_files'] = request.form.getlist('balsponsor')[:2]
    
    save_settings(instellingen)
    
    # Herlaad de assets in de server
    laad_assets() 
    
    return redirect(url_for('admin_sponsors_page'))

@app.route('/admin/upload-home-logo', methods=['POST'])
def admin_upload_home_logo():
    """Uploadt een nieuw standaard thuislogo."""
    if not session.get('admin_logged_in'): return redirect(url_for('login_page'))
    
    f = request.files.get('home_logo')
    if f and f.filename != '':
        # Zorg dat de map bestaat
        os.makedirs('static/clublogos', exist_ok=True)
        
        # Sla bestand op
        filename = secure_filename(f"default_home_{f.filename}")
        filepath = os.path.join('static', 'clublogos', filename)
        f.save(filepath)
        
        # Update settings.json
        instellingen = load_settings()
        if 'theme' not in instellingen: instellingen['theme'] = {}
        
        # Let op: path opslaan relatief aan static
        instellingen['theme']['standaard_thuis_logo'] = f"clublogos/{filename}"
        save_settings(instellingen)
        
        # Herlaad assets direct
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
            height: 10vh;
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
        # NIEUW: Geef een groter bereik voor de sliders
        monitor_width_extended=monitor_width + 100,
        monitor_height_extended=monitor_height + 100,
        window_data=window_data,
        theme_data=theme_data
    )
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
        logging.info("Thema update ontvangen en opgeslagen in settings.json")
        instellingen = load_settings()
        instellingen['theme'] = data 
        save_settings(instellingen)
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
    """Ontvangt de checkbox-status van de control pagina."""
    is_actief = data.get('active', False)
    logging.info(f"Balsponsoren ingesteld op: {is_actief}")
    
    # Stuur de status door naar het display
    emit('update_sponsor_visibility', {'active': is_actief}, broadcast=True)

# --- Server Start Functie ---
def start_server_func():
    logging.info(f"Server start op http://{SERVER_IP}:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)