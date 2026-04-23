# FL SYNC — Sync play/pause entre deux FL Studio via internet

## Architecture
```
FL Studio A → loopMIDI → bridge.py → server.js → bridge_pote.py → loopMIDI → FL Studio B
                                          ↑
FL Studio B → loopMIDI → bridge_pote.py ─┘
```

## Fichiers clés
- `server.js` — serveur WebSocket central (port 8080)
- `bridge.py` — PC A : écoute + envoie + reçoit (MY_ID="pc_a", MIDI_IN="FL Out 1", MIDI_OUT="FL In 0")
- `bridge_pote.py` — PC B : idem (MY_ID="pc_b", MIDI_IN="FL Out 2", MIDI_OUT="FL In 0", SERVER=IP publique PC A)

## Anti-boucle
`apply_until` (timestamp) bloque l'écoute MIDI 1 seconde après avoir appliqué un event reçu.
Sans ça : FL Studio rejoue un STOP+START quand il reçoit une commande MIDI → boucle infinie.

## Lancement
**PC A (3 terminaux) :**
```
node server.js
python bridge.py
```
**PC B (1 terminal) :**
```
python bridge_pote.py
```

## loopMIDI
- PC A : ports `test 0`, `FL In 0`, `FL Out 1`
- PC B : ports `FL In 0`, `FL Out 2`

## FL Studio config
- Output → port FL Out → "Send master sync" coché
- Input → port FL In → Enable + External sync + MIDI clock

## État
- Sync play/pause deux sens : en cours de test (fix boucle via bridge.py unifié)
- Sync BPM : pas encore fait
- Sync patterns .flp : pas encore fait
