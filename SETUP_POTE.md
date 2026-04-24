# Setup PC B — Instructions pour Claude

Ce fichier est destiné au Claude local qui tourne sur le PC du pote (PC B).
Il contient tout ce qu'il faut faire pour que la sync FL Studio fonctionne.

---

## Ce que fait ce projet

Synchronisation en temps réel entre deux FL Studio via internet :
- **PLAY / STOP** bidirectionnel (instantané)
- **BPM** exact bidirectionnel via script FL Studio
- **Arrangement .flp** : quand PC A fait Ctrl+S → PC B reçoit et FL Studio se recharge automatiquement

---

## Étape 1 — loopMIDI

Installer loopMIDI : https://www.tobias-erichsen.de/software/loopmidi.html

Créer exactement ces deux ports virtuels :
- `FL In`
- `FL Out`

Laisser loopMIDI ouvert en arrière-plan (cocher "autostart" dans le tray).

---

## Étape 2 — Script FL Studio

Copier le fichier `fl_studio_script/device_flsync.py` du repo vers :
```
C:\Users\[TON_USERNAME]\Documents\Image-Line\FL Studio\Settings\Hardware\FL SYNC\device_flsync.py
```

Créer le dossier `FL SYNC` s'il n'existe pas (avec un espace, pas "FLSync").

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
- Controller type = **FL SYNC**
- Port = **1**

### External sync (en bas) :
- Sélectionner **FL In**

### Après config :
- Cliquer **Update MIDI scripts**
- La console FL Studio doit afficher : `FLSync: chargé ✓` puis `FLSync: BPM → XXX`

---

## Étape 4 — Dépendances Python

```
pip install mido python-rtmidi websockets pywin32
```

`pywin32` est nécessaire pour que le dialog de sauvegarde FL Studio soit auto-cliqué.
Sans lui ça marche quand même (fallback clavier) mais moins fiable.

---

## Étape 5 — bridge_pote.py

Ouvrir `bridge_pote.py` et adapter ces lignes :

```python
SERVER = "ws://176.159.207.97:8080"  # IP publique de PC A — ne pas changer

# Où sauvegarder le projet reçu de PC A (FL Studio l'ouvrira automatiquement)
FLP_RECEIVED = r"C:\Users\[TON_USERNAME]\Desktop\flsync_received.flp"

# Ton propre projet à envoyer vers PC A (laisser vide si tu envoies pas)
FLP_PATH = r""  # ex: r"C:\Users\[TON_USERNAME]\Documents\projects\mon_projet.flp"
```

Pour vérifier les noms exacts des ports MIDI :
```
python -c "import mido; print('IN:', mido.get_input_names()); print('OUT:', mido.get_output_names())"
```

Les ports `FL In 0`, `FL In 1`, `FL Out 1`, `FL Out 2` doivent apparaître.
Si les noms sont différents, adapter `MIDI_IN`, `SCRIPT_MIDI_IN`, `MIDI_OUT` dans le script.

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

## Comment fonctionne la sync .flp (arrangement)

Quand PC A fait **Ctrl+S** dans FL Studio :
1. `bridge.py` détecte le changement de fichier
2. Envoie le .flp via WebSocket
3. `bridge_pote.py` reçoit et sauvegarde dans `FLP_RECEIVED`
4. Si FL Studio **est stoppé** → ouvre automatiquement le fichier, auto-clique "Non" sur le dialog de sauvegarde → FL Studio recharge sans action manuelle
5. Si FL Studio **joue** → attend le prochain stop, puis applique

Pour que ça marche dans les deux sens, PC B doit aussi renseigner `FLP_PATH` avec son projet,
et PC A doit renseigner `FLP_RECEIVED` dans `bridge.py`.

---

## Dépannage

**"unknown port"** → les noms de ports ne correspondent pas.
Lancer la commande mido de l'étape 5 pour voir les vrais noms.

**"Script FLSync actif ✓" n'apparaît pas** → vérifier Port = 1 sur FL In (input) ET Port = 1 sur FL Out (output) dans MIDI Settings. Redémarrer FL Studio.

**Le BPM ne sync pas** → vérifier que "Send master sync" est coché sur FL Out.

**FL Studio ne se recharge pas automatiquement** → vérifier que `pywin32` est installé (`pip install pywin32`).
Si le dialog "Enregistrer ?" reste ouvert, appuyer manuellement sur "Non".
