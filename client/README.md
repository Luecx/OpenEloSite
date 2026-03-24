# OpenELO Client

Der Client wird direkt ueber CLI-Argumente gestartet. Es gibt keine lokale JSON-Config mehr.

## Start

```bash
python3 app/main.py \
  --server http://localhost:8000 \
  --access-key YOUR_CLIENT_TOKEN \
  --threads 16 \
  --hash 512 \
  --workdir ./workspace
```

Optionale Argumente:

- `--machine-name`
- `--machine-key`
- `--poll-interval`
- `--heartbeat-interval`

## Workspace

Der Client verwendet im Workdir genau diese Struktur:

- `workspace/books/`
- `workspace/engine1/`
- `workspace/engine2/`
- `workspace/fast-chess/` nur falls `fastchess` oder `fast-chess` nicht im `PATH` gefunden wird

Vor jedem Job wird das Workspace bereinigt. Erhalten bleiben nur:

- `workspace/books/`
- `workspace/fast-chess/`

## Setup

Beim Start prueft der Client:

1. `fastchess` oder `fast-chess` ist im `PATH`.
2. Falls nicht: `fast-chess` wird nach `workspace/fast-chess/` geclont, per `git pull --ff-only` aktualisiert und mit `make -j` gebaut.

## Job-Ablauf

Ein Job liefert:

- Time-Control
- Opening-Book
- Engine 1 und Engine 2
- Artifact je Engine
- `threads_per_engine`
- `hash_per_engine`
- `num_games`
- `seed`

Der Client:

1. laedt das Book nach `workspace/books/`, falls Hash oder Datei fehlen
2. leert `workspace/engine1/` und `workspace/engine2/`
3. laedt beide Engine-Binaries direkt vom Server
4. startet `fast-chess` mit `concurrency = floor(max_threads / threads_per_engine)`
5. sendet W-D-L, PGN und Laufzeit an den Server zurueck

Waerend des gesamten Laufs sendet der Client Heartbeats an den Server.
