# OpenELO

OpenELO ist ein klar getrenntes Monorepo mit zwei Hauptbausteinen:

- `server/` fuer die Webplattform, API, Datenbanklogik und die Weboberflaeche
- `client/` fuer den lokal ausfuehrbaren Source-Code-Agenten

Die Plattform ist bewusst einfach gehalten:

- einfache Sprache in Code und Texten
- kleine, klar getrennte Dateien
- keine komplizierten Framework-Tricks
- Rollen, Ownership und Approval serverseitig
- responsive Weboberflaeche
- lokale Entwicklung direkt aus dem Source-Code
- Rating-Listen mit festen Match-Settings
- Opening-Books als eigene Admin-Ressource

## Struktur

```text
OpenELO/
├── client/
├── server/
├── .env.example
├── docker-compose.yml
└── README.md
```

## Schnellstart

### 1. Server lokal starten

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Der Server startet standardmaessig mit einer lokalen SQLite-Datei unter `server/data/openeelo.db`.

### 2. Server per Docker Compose starten

```bash
docker compose up --build
```

Dann laeuft die Plattform unter [http://localhost:8000](http://localhost:8000).

In Docker nutzt der Server PostgreSQL. Lokal ohne Docker nutzt der Server SQLite, damit der Einstieg einfach bleibt.

### 3. Client lokal starten

```bash
cd client
python3 app/main.py --help
```

Der Client ist absichtlich kein kompiliertes Binary. Man cloned das Projekt und startet den Agenten direkt aus dem Quellcode.

## Kernideen

- kombinierbare Rollen: `admin`, `tester`, `engine_owner`
- normale Web-Accounts fuer Nutzer
- Client-Authentifizierung ueber Client-Tokens
- Engines mit Ownern und Maintainern
- Versionen, Rezepte und Kompatibilitaetsregeln
- Rating-Listen mit Time-Control, SMP, Hash und optionalem Book
- Books koennen hochgeladen und Match-Jobs mitgegeben werden
- Clients melden `max_threads` und `max_hash` an den Server
- der Server kann mehrere Match-Jobs parallel auf einen Client legen, wenn Threads und Hash reichen
- Approval fuer Engine-Owner, Engines und Versionen
- Admin-Bereich fuer Queue, Rollen, Logs und Systemstatus
- oeffentliche Bereiche fuer Engines, Versionen, Rating-Listen und Books

## Oeffentlicher Ablauf

- `Engines` zeigt such- und filterbare Engines
- ein Klick auf eine Engine zeigt freigegebene Versionen
- ein Klick auf eine Version zeigt Matchups, Resultate und PGN-Downloads
- `Rating-Listen` zeigen die festen Settings und das Ranking pro Liste

## Weitere Hinweise

- [Server README](/Users/marceggers/GitHub/OpenELO/server/README.md)
- [Client README](/Users/marceggers/GitHub/OpenELO/client/README.md)
