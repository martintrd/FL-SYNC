# Setup PC B — Instructions pour Claude

Ce fichier est destiné au Claude local qui tourne sur le PC du pote (PC B).
Il contient tout ce qu'il faut faire pour que la sync FL Studio fonctionne.

---

## Ce que fait ce projet

Synchronisation en temps réel entre deux FL Studio via internet :
- PLAY / STOP bidirectionnel
- BPM exact bidirectionnel (via script FL Studio)
- Sync de projet .flp à la sauvegarde (optionnel)

Architecture :
```
FL Studio B → loopMIDI → bridge_pote.py → WebSocket → server.js (PC A) → bridge.py → FL Studio A
```

---

## Étape 1 — loopMIDI

Installer loopMIDI : https://www.tobias-erichsen.de/software/loopmidi.html

Créer exactement ces deux ports virtuels :
- `FL In`
- `FL Out`

Laisser loopMIDI ouvert en arrière-plan.

---

## Étape 2 — Script FL Studio

Copier le fichier `fl_studio_script/device_flsync.py` vers :
```
C:\Users\[TON_USERNAME]\Documents\Image-Line\FL Studio\Settings\Hardware\FL SYNC\device_flsync.py
```

Le dossier `FL SYNC` est à créer s'il n'existe pas.

---

## Étape 3 — Config FL Studio (F10 → MIDI Settings)

### Section Output :
- Sélectionner **FL Out**
- Port = **1**
- Cocher **Send master sync**
- Synchronization type = **MIDI clock**

### Section Input :
- Sélectionner **FL In**
- Cocher **Enable**
- Controller type = **FL SYNC** (le script qu'on vient d'installer)
- Port = **1**

### External sync (en bas) :
- Sélectionner **FL In**

### Après config :
- Cliquer **Update MIDI scripts**
- La console FL Studio doit afficher : `FLSync: chargé ✓`

---

## Étape 4 — bridge_pote.py

Ouvrir `bridge_pote.py` et vérifier / adapter ces lignes :

```python
SERVER = "ws://176.159.207.97:8080"  # IP publique du PC A — ne pas changer
MY_ID  = "pc_b"
MIDI_IN        = "FL Out 1"   # nom exact du port loopMIDI (vérifier avec mido)
SCRIPT_MIDI_IN = "FL In 0"    # idem
MIDI_OUT       = "FL In 1"    # idem
FLP_RECEIVED   = r"C:\Users\[TON_USERNAME]\Desktop\received_project.flp"
```

Pour vérifier les noms exacts des ports MIDI disponibles, lancer :
```
python -c "import mido; print('IN:', mido.get_input_names()); print('OUT:', mido.get_output_names())"
```

Les ports `FL In 0`, `FL In 1`, `FL Out 1`, `FL Out 2` doivent apparaître.

---

## Étape 5 — Dépendances Python

```
pip install mido python-rtmidi websockets
```

---

## Étape 6 — Lancement

PC A lance `server.js` et `bridge.py`.
PC B lance seulement :
```
python -u bridge_pote.py
```

Le terminal doit afficher :
```
Écoute script sur FL In 0...
Écoute MIDI FL Out 1...
Connecté au serveur ✓
Script FLSync actif ✓
BPM : 140.0
```

---

## Vérification

- Appuyer play sur FL Studio A → FL Studio B démarre aussi
- Changer le BPM sur FL Studio A → FL Studio B se met à jour
- Idem dans l'autre sens depuis FL Studio B

---

## Dépannage

**"unknown port"** → les noms de ports dans bridge_pote.py ne correspondent pas.
Lancer la commande mido de l'étape 4 pour voir les vrais noms.

**Rien ne se passe au play** → vérifier que "Send master sync" est coché sur FL Out dans FL Studio.

**"Script FLSync actif ✓" n'apparaît pas** → vérifier le Controller type = "FL SYNC" dans les MIDI settings et recliquer "Update MIDI scripts". Redémarrer FL Studio si nécessaire.

**BPM ne se sync pas** → vérifier Port = 1 sur FL In (input) ET sur FL Out (output) dans FL Studio MIDI Settings.
