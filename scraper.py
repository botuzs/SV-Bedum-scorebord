import time
import json
import os
import logging
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO)

PROGRAMMA_URL = 'https://svbedum.nl/programma/'
JSON_BESTAND = 'wedstrijden.json'
LOGO_DIR = os.path.join('static', 'clublogos')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
}

def download_logo(url, bestandsnaam):
    lokaal_pad = os.path.join(LOGO_DIR, bestandsnaam)
    try:
        logging.info(f"Logo downloaden: {url} -> {lokaal_pad}")
        img_data = requests.get(url, headers=HEADERS).content
        with open(lokaal_pad, 'wb') as f: f.write(img_data)
        
        # Verwerking (Rond maken)
        img = Image.open(lokaal_pad).convert("RGBA")
        width, height = img.size
        is_white = False
        if width > 10 and height > 10:
            corners = [img.getpixel((0,0)), img.getpixel((width-1,0)), img.getpixel((0,height-1)), img.getpixel((width-1,height-1))]
            white_px = sum(1 for r,g,b,a in corners if a==255 and r>235 and g>235 and b>235)
            if white_px >= 3: is_white = True
        
        if is_white:
            new_size = int(max(width, height) * 1.15)
            new_img = Image.new("RGBA", (new_size, new_size), (255, 255, 255, 255))
            new_img.paste(img, ((new_size-width)//2, (new_size-height)//2), img)
            mask = Image.new("L", (new_size, new_size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, new_size, new_size), fill=255)
            final_img = Image.new("RGBA", (new_size, new_size), (0, 0, 0, 0))
            final_img.paste(new_img, (0, 0), mask)
            final_img.save(lokaal_pad, "PNG")
            
    except Exception as e:
        logging.error(f"Fout logo {url}: {e}")
        return None
    return f"clublogos/{bestandsnaam}".replace("\\", "/")

def get_veld1_wedstrijden(timeout_seconds=10):
    logging.info(f"Start scraper op {PROGRAMMA_URL} (Timeout: {timeout_seconds}s)...")
    os.makedirs(LOGO_DIR, exist_ok=True)
    
    # 1. Laad bestaande data om overschrijven te voorkomen
    bestaande_data = {}
    if os.path.exists(JSON_BESTAND):
        try:
            with open(JSON_BESTAND, 'r', encoding='utf-8') as f:
                oude_lijst = json.load(f)
                for w in oude_lijst:
                    bestaande_data[w['id']] = w
        except: pass

    wedstrijden = []
    gevonden_ids = set()

    # Selenium deel
    driver = None
    html_content = ""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless"); chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--disable-gpu"); chrome_options.add_argument("--no-sandbox")
        s = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=s, options=chrome_options)
        driver.get(PROGRAMMA_URL)
        WebDriverWait(driver, timeout_seconds).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Veld 1')]")))
        html_content = driver.page_source
    except Exception as e:
        logging.error(f"Selenium fout: {e}")
        return []
    finally:
        if driver: driver.quit()

    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 6: continue
            if 'veld 1' not in cells[4].get_text(strip=True).lower(): continue
            if 'sv bedum' not in cells[2].get_text(strip=True).lower(): continue
            if 'afgelast' in cells[5].get_text(strip=True).lower(): continue

            try:
                datum = cells[0].get_text(strip=True)
                tijd = cells[1].get_text(strip=True)
                starttijd = f"{datum} {tijd}"
                thuis = cells[2].get_text(strip=True)
                uit = cells[3].get_text(strip=True)
                
                wid = hash(f"{starttijd}-{thuis}-{uit}")
                wid_str = str(wid)
                if wid in gevonden_ids: continue
                gevonden_ids.add(wid)

                # Check of we deze al kennen, zo ja: behoud custom velden
                bestaande_match = bestaande_data.get(wid_str, {})
                thuis_logo = bestaande_match.get('thuis_logo_lokaal') # BEHOUD DIT
                
                # Uit logo proberen te vinden als we die nog niet hebben
                uit_logo = bestaande_match.get('uit_logo_lokaal')
                if not uit_logo:
                    img_tag = cells[3].find('img')
                    if img_tag and img_tag.get('src'):
                        try:
                            code = img_tag.get('src').split('clubcode=')[-1]
                            uit_logo = download_logo(img_tag.get('src'), f"{code}.png")
                        except: pass

                wedstrijden.append({
                    "id": wid_str, 
                    "tijd": starttijd, 
                    "thuis": thuis, 
                    "uit": uit,
                    "uit_logo_lokaal": uit_logo, 
                    "thuis_logo_lokaal": thuis_logo, # Nu veiliggesteld
                    "scoreThuis": 0, "scoreUit": 0, "status": "Nog niet begonnen"
                })
            except: pass
            
        if wedstrijden:
            wedstrijden.sort(key=lambda x: x['tijd'])
            with open(JSON_BESTAND, 'w', encoding='utf-8') as f:
                json.dump(wedstrijden, f, indent=4)
            logging.info(f"Scraper klaar: {len(wedstrijden)} wedstrijden (data samengevoegd).")
            
        return wedstrijden
    except Exception as e:
        logging.error(f"Parse fout: {e}")
        return []

if __name__ == "__main__":
    get_veld1_wedstrijden(15)