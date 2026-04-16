"""
SV Bedum - Sponsor Beheer Server
Draait op poort 4000. Biedt een webinterface om sponsorlogo's
te uploaden, bij te snijden en te activeren.
Het scorebord haalt actieve sponsoren op via de API.
"""

import json
import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify, abort
from werkzeug.utils import secure_filename
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
DATA_FILE = os.path.join(BASE_DIR, 'data.json')

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Max 16MB

# --- Data opslag ---

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"sponsors": []}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- Webpagina ---

@app.route('/')
def index():
    data = load_data()
    return render_template('index.html', sponsors=data['sponsors'])

# --- Upload + Bijsnijden ---

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    if not file or file.filename == '':
        return redirect(url_for('index'))

    if not file.filename.lower().endswith('.png'):
        return redirect(url_for('index'))

    # Genereer unieke bestandsnaam
    naam = request.form.get('naam', '').strip()
    file_id = str(uuid.uuid4())[:8]
    filename = secure_filename(f"{file_id}_{naam or 'sponsor'}.png")
    temp_path = os.path.join(UPLOAD_DIR, f"temp_{filename}")
    final_path = os.path.join(UPLOAD_DIR, filename)

    file.save(temp_path)

    # Bijsnijden met crop parameters van de frontend
    try:
        img = Image.open(temp_path).convert('RGBA')

        crop_x = int(float(request.form.get('crop_x', 0)))
        crop_y = int(float(request.form.get('crop_y', 0)))
        crop_w = int(float(request.form.get('crop_w', 0)))
        crop_h = int(float(request.form.get('crop_h', 0)))

        if crop_w > 0 and crop_h > 0:
            img = img.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))

        # Resize naar standaard hoogte (200px) met behoud van aspect ratio
        target_h = 200
        ratio = target_h / img.height
        target_w = int(img.width * ratio)
        img = img.resize((target_w, target_h), Image.LANCZOS)

        # Sla op als PNG met transparantie
        img.save(final_path, 'PNG')
    except Exception as e:
        print(f"Fout bij verwerken: {e}")
        # Fallback: gewoon opslaan zonder crop
        if os.path.exists(temp_path):
            os.rename(temp_path, final_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    # Toevoegen aan data
    data = load_data()
    data['sponsors'].append({
        'filename': filename,
        'naam': naam or filename,
        'actief': False
    })
    save_data(data)

    return redirect(url_for('index'))

# --- Activeren / Deactiveren ---

@app.route('/toggle/<filename>')
def toggle(filename):
    data = load_data()
    for s in data['sponsors']:
        if s['filename'] == filename:
            s['actief'] = not s['actief']
            break
    save_data(data)
    return redirect(url_for('index'))

# --- Verwijderen ---

@app.route('/delete/<filename>')
def delete(filename):
    data = load_data()
    data['sponsors'] = [s for s in data['sponsors'] if s['filename'] != filename]
    save_data(data)

    filepath = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    return redirect(url_for('index'))

# --- API (voor het scorebord) ---

@app.route('/api/sponsors')
def api_sponsors():
    """Geeft alle actieve sponsoren terug. Het scorebord gebruikt dit."""
    data = load_data()
    actieve = [s for s in data['sponsors'] if s.get('actief')]
    result = []
    for s in actieve:
        result.append({
            'filename': s['filename'],
            'naam': s.get('naam', s['filename']),
            'url': f"/api/image/{s['filename']}"
        })
    return jsonify({'sponsors': result})

@app.route('/api/image/<filename>')
def api_image(filename):
    """Serveert een sponsor afbeelding."""
    safe = secure_filename(filename)
    if not os.path.exists(os.path.join(UPLOAD_DIR, safe)):
        abort(404)
    return send_from_directory(UPLOAD_DIR, safe, mimetype='image/png')

# --- Start ---

if __name__ == '__main__':
    print("=" * 50)
    print("  SV Bedum - Sponsor Beheer Server")
    print("  Open: http://localhost:4000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=4000, debug=False)
