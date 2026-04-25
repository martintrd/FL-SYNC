# Setup PC B — Instructions pour Claude

Ce fichier est destiné au Claude local sur le PC du pote (PC B).
Suis chaque étape dans l'ordre.

---

## Ce que fait ce projet

Synchronisation en temps réel entre deux FL Studio via internet :
- **PLAY / STOP** bidirectionnel instantané
- **BPM** exact bidirectionnel via script FL Studio
- **Projet .flp** : sync automatique à la sauvegarde + **merge 3-voies** si les deux ont édité en même temps
- **Samples audio** : transfert automatique quand un nouveau fichier apparaît dans le dossier partagé

---

## Étape 1 — Dossiers à créer

Crée ces deux dossiers sur le Bureau du pote (ou un autre endroit, mais **note les chemins exacts**) :

```
C:\Users\[USERNAME_POTE]\Desktop\FL-SYNC-SHARE   ← projets .flp
C:\Users\[USERNAME_POTE]\Desktop\FL-SAMPLES       ← samples audio
```

---

## Étape 2 — loopMIDI

Installer : https://www.tobias-erichsen.de/software/loopmidi.html

Créer exactement ces deux ports virtuels :
- `FL In`
- `FL Out`

Laisser loopMIDI ouvert (cocher "autostart" dans le tray).

---

## Étape 3 — Script FL Studio

Copier `fl_studio_script/device_flsync.py` du repo vers :
```
C:\Users\[USERNAME_POTE]\Documents\Image-Line\FL Studio\Settings\Hardware\FL SYNC\device_flsync.py
```
Créer le dossier `FL SYNC` (avec un espace) s'il n'existe pas.

---

## Étape 4 — Config FL Studio (F10 → MIDI Settings)

**Section Output :**
- Sélectionner **FL Out** → Port = **1** → cocher **Send master sync** → MIDI clock

**Section Input :**
- Sélectionner **FL In** → Enable → Controller type = **FL SYNC** → Port = **1**

**External sync (en bas) :** sélectionner **FL In**

Cliquer **Update MIDI scripts** → la console FL Studio doit afficher :
```
FLSync: chargé ✓
FLSync: BPM → 140.0
```

---

## Étape 5 — Dépendances Python

```
pip install mido python-rtmidi websockets pywin32 pyflp
```

- `pywin32` → auto-dismiss du dialog "Enregistrer ?" quand FL Studio recharge
- `pyflp` → merge 3-voies des projets en cas d'édition simultanée

---

## Étape 6 — bridge_pote.py

Ouvrir `bridge_pote.py` et adapter ces lignes :

```python
SERVER = "ws://176.159.207.97:8080"   # IP de PC A — ne pas changer

FLP_SYNC_DIR     = r"C:\Users\[USERNAME_POTE]\Desktop\FL-SYNC-SHARE"
SAMPLES_SYNC_DIR = r"C:\Users\[USERNAME_POTE]\Desktop\FL-SAMPLES"
```

Pour vérifier les noms exacts des ports MIDI :
```
python -c "import mido; print('IN:', mido.get_input_names()); print('OUT:', mido.get_output_names())"
```
Les ports `FL In 0`, `FL In 1`, `FL Out 1`, `FL Out 2` doivent apparaître.
Si les noms diffèrent, adapter `MIDI_IN`, `SCRIPT_MIDI_IN`, `MIDI_OUT` dans bridge_pote.py.

---

## Étape 7 — Lancement

PC A lance `server.js` + `bridge.py`. PC B lance uniquement :
```
python -u bridge_pote.py
```

Terminal attendu :
```
Surveillance projet   : C:\...\FL-SYNC-SHARE
Surveillance samples  : C:\...\FL-SAMPLES
Écoute script sur FL In 0...
Écoute MIDI FL Out 1...
Connecté au serveur ✓
Script FLSync actif ✓
BPM : 140.0
```

---

## Workflow projets .flp

**Pour envoyer un projet :**
1. Dans FL Studio : **File → Save as** → enregistre dans `FL-SYNC-SHARE\`
2. Chaque **Ctrl+S** suivant envoie automatiquement au pote
3. Le pote reçoit → FL Studio recharge automatiquement à l'arrêt du playback

**Pour les samples :**
1. Mets tes samples dans `FL-SAMPLES\`
2. Dans FL Studio, configure ce dossier comme source de samples (Options → File → Browse extra search folders)
3. Dès qu'un fichier apparaît dans ce dossier, il est transféré automatiquement

---

## Merge automatique en cas d'édition simultanée

Si les deux PCs sauvegardent en même temps :
- Le système détecte le conflit
- Tente un **merge 3-voies** : identifie les channels/patterns ajoutés par chacun et les combine
- Si le merge réussit → fichier mergé rechargé automatiquement dans FL Studio
- Si le merge échoue → le projet remote est appliqué + **ton travail est sauvé** dans `projet_backup_local.flp` avec un message dans le terminal expliquant ce que tu avais ajouté

---

## Dépannage

**"unknown port"** → lancer la commande mido de l'étape 6, adapter les noms de ports dans bridge_pote.py.

**"Script FLSync actif ✓" n'apparaît pas** → vérifier Port = 1 sur FL In ET FL Out dans MIDI Settings, redémarrer FL Studio.

**FL Studio ne recharge pas automatiquement** → vérifier que `pywin32` est installé.

**Merge échoue souvent** → vérifier que `pyflp` est installé (`pip install pyflp`).
