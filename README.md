# SV Bedum Scorebord v2

Een digitaal scorebord voor SV Bedum, gebouwd met Python/Flask en bedienbaar via elke browser in het netwerk. De applicatie draait als een lokale webserver en toont live scores, speleropstellingen en sponsoren op het scorebord.

---

## Downloaden & Starten

Download de nieuwste release: [**SVBedumScorebord.exe**](https://github.com/botuzs/SV-Bedum-scorebord/releases/latest)

1. Zet de `.exe` in een lege map (bijv. `C:\Scorebord\`)
2. Dubbelklik op `SVBedumScorebord.exe`
3. Het scorebord opent automatisch in een kioskmodus venster
4. Het beheerpaneel is bereikbaar via `http://<ip-adres>:5000/admin`

> Bij de eerste start worden `settings.json`, `wedstrijden.json` en de `static/` map automatisch aangemaakt naast de exe.

---

## Wachtwoorden

| Rol | Wachtwoord |
|-----|-----------|
| Admin (volledig beheer) | `Svbedum@!#!` |
| Kiosk / Bar | `bar123` |

---

## Functies

- **Live scorebord** — doelpunten bijhouden per wedstrijd met automatische updates via WebSockets
- **Meerdere wedstrijden** — beheer meerdere velden/wedstrijden tegelijk
- **Speleropstelling** — toon de naam van de volgende speler op het scorebord
- **Sponsoren** — roterende sponsorbanners op het scorebord
- **Clublogo's** — automatisch ophalen van logo's via de KNVB scraper
- **QR-code** — automatisch gegenereerde QR-code om het scorebord te openen op mobiel
- **Kioskmodus** — volledig scherm weergave zonder browserbalken

---

## Beheerpaneel

Ga naar `http://<ip-adres>:5000/admin` in een browser op hetzelfde netwerk.

| Pagina | URL |
|--------|-----|
| Admin dashboard | `/admin` |
| Wedstrijden beheren | `/admin/wedstrijden` |
| Spelers beheren | `/admin/spelers` |
| Sponsoren beheren | `/admin/sponsors` |
| Instellingen | `/admin/instellingen` |

---

## Bouwen vanuit broncode

### Vereisten

```
pip install -r requirements.txt
```

### Starten (ontwikkeling)

```bash
python app.py
```

### Bouwen naar .exe

```bash
pyinstaller SVBedumScorebord.spec
```

De `.exe` verschijnt in de `dist/` map.

---

## Bekende beperkingen

- Wedstrijden worden opgeslagen in een lokale `wedstrijden.json` (geen database).
- Sponsoren kunnen niet handmatig verwijderd worden via de interface.
- Bij het opnieuw synchroniseren van sponsoren wordt de map niet eerst leeggemaakt.

---

## Licentie

Intern gebruik SV Bedum. Niet bedoeld voor publieke verspreiding.
