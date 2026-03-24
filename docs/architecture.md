# Architektur

## Uebersicht

OpenELO besteht aus zwei getrennten Anwendungsbereichen:

- `server/`: Webplattform fuer Nutzer, Engines, Approvals, Clients und Admin-Funktionen
- `client/`: lokaler Agent fuer Heartbeats, Hardware-Erkennung und Job-Ausfuehrung

## Warum diese Struktur?

- Server und Client koennen getrennt gelesen, gestartet und erweitert werden.
- Die Root-Ebene bleibt uebersichtlich.
- Jede Datei hat eine klare Aufgabe.
- Die Plattform laeuft lokal direkt aus dem Source-Code.

## Server

Der Server nutzt:

- FastAPI fuer Web und JSON-API
- Jinja2-Templates fuer die HTML-Seiten
- SQLAlchemy fuer das Datenmodell
- SQLite lokal ohne Docker
- PostgreSQL in Docker Compose

Zusaetzlich modelliert der Server:

- `OpeningBook` fuer hochgeladene Books
- `RatingList` fuer feste Kombinationen aus Time-Control, SMP, Hash und Book
- Match-Jobs mit eingebetteten Lauf-Settings
- mehrere `GameRecord`-Eintraege pro Match fuer mehrere PGNs
- Client-Kapazitaeten mit `max_threads` und `max_hash_mb`
- ein einfacher Scheduler, der mehrere Match-Jobs passend zu den freien Ressourcen auf einen Client claimt

## Client

Der Client ist ein einfacher Python-Agent:

- liest eine lokale Konfigurationsdatei
- authentifiziert sich mit einem Client-Token
- registriert oder aktualisiert den lokalen Client
- sendet Heartbeats
- holt Jobs vom Server
- kann ein Book fuer einen Match-Job herunterladen
- fuehrt Jobs lokal aus

## Design-Regeln

- einfache Namen
- kleine Dateien
- eine Klasse pro Datei
- keine grossen Utility-Sammeldateien
- kein unnnoetiger Magie-Layer

## Naechster Refactor

Die vereinfachte Zielarchitektur fuer Client, Job-Schnittstellen und Datenmodell steht in:

- `docs/client-server-simplification.md`
