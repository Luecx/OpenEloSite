# Scripts

Kleine Admin- und Seed-Helfer fuer lokale Anpassungen.

Beispiele:

```bash
python3 -B scripts/add_dummy_users.py
python3 -B scripts/add_dummy_users.py --count 50
python3 -B scripts/add_dummy_users.py --count 50 --prefix testuser --password dummy123 --roles tester
python3 -B scripts/add_dummy_engines.py --count 50
```

Aktuell vorhanden:

- `add_dummy_users.py`: legt Dummy-User mit fortlaufenden Namen an
- `add_dummy_engines.py`: legt viele Dummy-Engines mit Versionen und einfachen Linux-Artefakten an
