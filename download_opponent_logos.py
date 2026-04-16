import requests
import os
import json
import logging
import re
from PIL import Image, ImageDraw
import io

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# --- CONFIGURATIE ---
CLIENT_ID = "4BOXhXAvFq"
SPORTLINK_BASE = "https://data.sportlink.com"
SV_BEDUM_ID = "PJSY23I"  # De officiële Sportlink code voor SV Bedum
LOGO_DIR = os.path.join('static', 'clublogos')
LOGO_API_BASE = "https://logoapi.voetbal.nl/logo.php?clubcode="

def sanitize_filename(name):
    """Maakt een naam veilig voor gebruik als bestandsnaam."""
    name = name.replace(' ', '_')
    return re.sub(r'(?u)[^-\w.]', '', name)

def process_logo(img_data, target_path):
    """Maakt het logo mooi rond en voegt een witte achtergrond toe indien nodig (vrijstaand maken)."""
    try:
        img = Image.open(io.BytesIO(img_data)).convert("RGBA")
        width, height = img.size
        
        # Maak een witte cirkel achtergrond
        new_size = int(max(width, height) * 1.1)
        background = Image.new("RGBA", (new_size, new_size), (255, 255, 255, 255))
        
        # Plak het logo in het midden
        offset = ((new_size - width) // 2, (new_size - height) // 2)
        background.paste(img, offset, img)
        
        # Maak het rond
        mask = Image.new("L", (new_size, new_size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, new_size, new_size), fill=255)
        
        final = Image.new("RGBA", (new_size, new_size), (0, 0, 0, 0))
        final.paste(background, (0, 0), mask)
        
        final.save(target_path, "PNG")
        return True
    except Exception as e:
        logging.error(f"Fout bij verwerken logo: {e}")
        return False

def sanitize_club_name(name):
    """Verwijdert team-specifieke toevoegingen om de pure clubnaam over te houden."""
    # Verwijder aanduidingen zoals 1, 2, 3, JO15-1, MO17, 35+, 45+, VR, etc.
    # We splitsen op spaties en kijken naar patronen
    parts = name.split(' ')
    clean_parts = []
    
    # Lijst met patronen die we willen negeren/stoppen
    stop_patterns = [
        r'^\d+$',          # Alleen getallen (1, 2, 3...)
        r'^JO\d+',         # JO15, JO9...
        r'^MO\d+',         # MO17, MO13...
        r'^\d+\+',         # 35+, 45+...
        r'^VR\d*',         # VR, VR1, VR30+...
        r'^G-?team$',      # G-team
        r'^Zat$',          # Zat
        r'^Zon$'           # Zon
    ]
    
    for part in parts:
        is_team_part = False
        for pattern in stop_patterns:
            if re.search(pattern, part, re.IGNORECASE):
                is_team_part = True
                break
        
        if is_team_part:
            break # Stop zodra we een team-aanduiding tegenkomen
        clean_parts.append(part)
    
    clean_name = ' '.join(clean_parts).strip()
    # Verwijder eventuele resterende komma's of punten aan het eind
    clean_name = re.sub(r'[,.]+$', '', clean_name)
    return clean_name

def download_logos():
    if not os.path.exists(LOGO_DIR):
        os.makedirs(LOGO_DIR)

    # 1. Programma ophalen
    url = f"{SPORTLINK_BASE}/programma"
    params = {
        'client_id': CLIENT_ID,
        'verenigingcode': SV_BEDUM_ID,
        'aantaldagen': 200 # Nu 200 dagen
    }

    try:
        logging.info("Programma ophalen van Sportlink (200 dagen)...")
        response = requests.get(url, params=params)
        response.raise_for_status()
        matches = response.json()
        
        if not isinstance(matches, list):
            logging.error("Onverwacht API resultaat (geen lijst)")
            return

        opponents = {} # Code -> Schone Naam mapping
        processed_names = set() # Om dubbele namen (verschillende codes) te voorkomen

        for match in matches:
            # Check wie de tegenstander is
            t_name_raw = match.get('thuisteam', '')
            t_code = match.get('thuisteamclubrelatiecode', '')
            u_name_raw = match.get('uitteam', '')
            u_code = match.get('uitteamclubrelatiecode', '')

            # Verwerk thuisclub als het niet SV Bedum is
            if t_code and t_code != SV_BEDUM_ID:
                clean_name = sanitize_club_name(t_name_raw)
                if clean_name not in processed_names:
                    opponents[t_code] = clean_name
                    processed_names.add(clean_name)
            
            # Verwerk uitclub als het niet SV Bedum is
            if u_code and u_code != SV_BEDUM_ID:
                clean_name = sanitize_club_name(u_name_raw)
                if clean_name not in processed_names:
                    opponents[u_code] = clean_name
                    processed_names.add(clean_name)

        logging.info(f"{len(opponents)} unieke clubnamen gevonden in programma.")

        # 2. Logo's downloaden
        for code, name in opponents.items():
            safe_name = sanitize_filename(name)
            target_path = os.path.join(LOGO_DIR, f"{safe_name}.png")
            
            if os.path.exists(target_path):
                logging.info(f"Overslaan: {name} (bestaat al)")
                continue

            logging.info(f"Logo downloaden voor: {name} ({code})...")
            logo_url = f"{LOGO_API_BASE}{code}"
            
            try:
                logo_resp = requests.get(logo_url, timeout=10)
                if logo_resp.status_code == 200:
                    if process_logo(logo_resp.content, target_path):
                        logging.info(f"Succes: {target_path} opgeslagen.")
                    else:
                        logging.warning(f"Logo verwerking mislukt voor {name}")
                else:
                    logging.warning(f"Geen logo gevonden voor {name} (Status {logo_resp.status_code})")
            except Exception as e:
                logging.error(f"Netwerkfout bij {name}: {e}")

    except Exception as e:
        logging.error(f"Fout bij ophalen programma: {e}")

if __name__ == "__main__":
    download_logos()
