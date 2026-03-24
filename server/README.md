# OpenELO Server

Der Server enthaelt:

- Weboberflaeche
- Authentifizierung
- Rollen und Rechte
- Engines, Versionen und Rezepte
- Rating-Listen und Opening-Books
- Client-Verwaltung
- einfache Kapazitaetsplanung pro Client
- Approval-Workflows
- Admin-Bereich
- JSON-API fuer den Client

## Lokal starten

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

## Wichtige Umgebungsvariablen

- `OPENELO_DATABASE_URL`
- `OPENELO_SECRET_KEY`
- `OPENELO_DEFAULT_ADMIN_EMAIL`
- `OPENELO_DEFAULT_ADMIN_PASSWORD`
- `OPENELO_DEFAULT_ADMIN_USERNAME`

## Startverhalten

Beim Start:

- werden Tabellen angelegt
- Standardrollen angelegt
- ein Default-Admin erzeugt, falls noch kein Admin existiert

## Lokale Datenbank

Ohne gesetzte Datenbank-URL nutzt der Server:

```text
sqlite:///./data/openeelo.db
```

## Docker

Der Dockerfile installiert die Abhaengigkeiten und startet Uvicorn.

## Hinweise

- Rating-Listen definieren Time-Control, Spiele pro Auftrag, SMP, Hash und optional ein Book.
- Clients melden `max_threads` und `max_hash` und koennen mehrere Jobs parallel bekommen.
- Books werden zentral vom Server gespeichert und bei Bedarf vom Client heruntergeladen.
- Eine Engine-Version besteht aus Install-Skript plus `executable_path`.
- Der Client setzt beim Ausfuehren einer Version `OPENELO_ENGINE_DIR` auf den Zielordner der jeweiligen Engine im Container.
