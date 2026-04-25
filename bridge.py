import sys
sys.stdout.reconfigure(encoding='utf-8')
import mido
import asyncio
import websockets
import json
import threading
import base64
import os
import shutil
import time
import ctypes

SERVER = "ws://localhost:8080"
MY_ID = "pc_a"
MIDI_IN        = "FL Out 1"
SCRIPT_MIDI_IN = "FL In 0"
MIDI_OUT       = "FL In 1"

# Dossier partagé .flp (même chemin sur les deux PCs)
FLP_SYNC_DIR = r"C:\Users\flyxe\Desktop\FL-SYNC-SHARE"

# Dossier samples (MÊME chemin sur les deux PCs)
SAMPLES_SYNC_DIR = r"C:\Users\flyxe\Desktop\FL-SAMPLES"
SAMPLES_MAX_MB   = 30

# Dossier interne pour stocker les versions de base (pour le merge)
_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".flp_bases")

apply_until     = 0.0
clock_slave_until = 0.0
flp_slave_until   = 0.0

current_generated_bpm = None
midi_out_port         = None

_fl_playing  = False
_pending_flp = None

event_queue = asyncio.Queue()

# ── Rechargement FL Studio ────────────────────────────────────────────────────

def _dismiss_save_dialog():
    deadline = time.time() + 8.0
    while time.time() < deadline:
        try:
            import win32gui, win32con, win32api
            clicked = [False]
            def _check_btn(hwnd, _):
                txt = win32gui.GetWindowText(hwnd).strip().lower().replace('&', '')
                if txt in ('no', 'non', "don't save", 'ne pas enregistrer'):
                    win32api.PostMessage(hwnd, win32con.BM_CLICK, 0, 0)
                    clicked[0] = True
                    return False
                return True
            def _check_win(hwnd, _):
                if clicked[0]: return False
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == '#32770':
                    try: win32gui.EnumChildWindows(hwnd, _check_btn, None)
                    except Exception: pass
                return True
            win32gui.EnumWindows(_check_win, None)
            if clicked[0]:
                print("Dialog dismissé ✓")
                return
        except ImportError:
            time.sleep(0.5)
            u32 = ctypes.windll.user32
            u32.keybd_event(0x12, 0, 0, 0)
            u32.keybd_event(0x4E, 0, 0, 0)
            u32.keybd_event(0x4E, 0, 2, 0)
            u32.keybd_event(0x12, 0, 2, 0)
            return
        time.sleep(0.15)

def _open_flp(path):
    print(f"\nOuverture dans FL Studio : {path}")
    threading.Thread(target=_dismiss_save_dialog, daemon=True).start()
    ctypes.windll.shell32.ShellExecuteW(None, "open", path, None, None, 1)

# ── Clock generator — thread précis avec perf_counter ───────────────────────

def clock_generator_thread():
    next_t = time.perf_counter()
    while True:
        bpm = current_generated_bpm
        if bpm is None:
            time.sleep(0.005)
            next_t = time.perf_counter()
            continue
        interval = 60.0 / (bpm * 24)
        next_t += interval
        # Sleep la majeure partie, busy-wait les 2 dernières ms
        remaining = next_t - time.perf_counter()
        if remaining > 0.002:
            time.sleep(remaining - 0.002)
        while time.perf_counter() < next_t:
            pass
        if current_generated_bpm is not None:
            midi_out_port.send(mido.Message.from_bytes([0xF8]))

# ── WebSocket ────────────────────────────────────────────────────────────────

async def websocket_handler():
    global apply_until, clock_slave_until, flp_slave_until
    global current_generated_bpm
    while True:
        try:
            async with websockets.connect(SERVER, max_size=50*1024*1024) as ws:
                print("Connecté au serveur ✓")

                async def sender():
                    while True:
                        msg = await event_queue.get()
                        if isinstance(msg, tuple) and msg[0] == "BPM":
                            payload = {"op": "BPM", "bpm": msg[1], "from": MY_ID}
                            print(f"\nEnvoyé BPM : {msg[1]}")
                        elif isinstance(msg, tuple) and msg[0] == "FLP":
                            payload = {"op": "FLP", "data": msg[1], "filename": msg[2], "from": MY_ID}
                            print(f"\nEnvoyé FLP : {msg[2]}")
                        elif isinstance(msg, tuple) and msg[0] == "SAMPLE":
                            payload = {"op": "SAMPLE", "data": msg[1], "rel": msg[2], "from": MY_ID}
                            print(f"\nEnvoyé sample : {msg[2]}")
                        else:
                            payload = {"op": msg, "from": MY_ID}
                            print(f"\nEnvoyé : {msg}")
                        await ws.send(json.dumps(payload))

                async def receiver():
                    global apply_until, clock_slave_until, flp_slave_until
                    global current_generated_bpm, _pending_flp
                    async for raw in ws:
                        event = json.loads(raw)
                        if event.get("from") == MY_ID:
                            continue
                        op = event.get("op")
                        if op == "FLP":
                            flp_slave_until = time.time() + 5.0
                            if not FLP_SYNC_DIR:
                                continue
                            os.makedirs(FLP_SYNC_DIR, exist_ok=True)
                            filename = event.get("filename", "received.flp")
                            dest    = os.path.join(FLP_SYNC_DIR, filename)
                            remote_tmp = dest + ".remote_tmp"
                            # Sauvegarde le fichier remote en tmp
                            with open(remote_tmp, "wb") as f:
                                f.write(base64.b64decode(event["data"]))
                            # Détecte si on a des changements locaux depuis la dernière base
                            local_dirty = (
                                os.path.exists(dest) and
                                os.path.exists(os.path.join(_BASE_DIR, filename)) and
                                os.path.getmtime(dest) > os.path.getmtime(
                                    os.path.join(_BASE_DIR, filename)
                                )
                            )
                            if local_dirty:
                                print(f"\n⚠ CONFLIT sur {filename} — merge en cours...")
                                from merge import merge_flp, get_base
                                base_p = get_base(filename, _BASE_DIR)
                                _, msg = merge_flp(base_p, dest, remote_tmp, dest)
                                print(f"\n{msg}")
                            else:
                                shutil.copy(remote_tmp, dest)
                                print(f"\nReçu : {filename}")
                            os.remove(remote_tmp)
                            # Sauvegarde comme nouvelle base
                            from merge import save_base
                            save_base(dest, _BASE_DIR)
                            final_dest = dest
                            if not _fl_playing:
                                threading.Thread(
                                    target=_open_flp, args=(final_dest,), daemon=True
                                ).start()
                            else:
                                _pending_flp = final_dest
                                print("(FL joue → appliqué à l'arrêt)")
                        elif op == "SAMPLE":
                            if SAMPLES_SYNC_DIR:
                                rel = event.get("rel", "")
                                dest = os.path.join(SAMPLES_SYNC_DIR, rel)
                                os.makedirs(os.path.dirname(dest), exist_ok=True)
                                with open(dest, "wb") as f:
                                    f.write(base64.b64decode(event["data"]))
                                print(f"\nSample reçu : {rel}")
                        elif op == "BPM":
                            bpm = event["bpm"]
                            print(f"\nReçu BPM : {bpm} — génération clock MIDI")
                            clock_slave_until = time.time() + 3.0
                            current_generated_bpm = bpm
                        elif op in ("PLAY", "STOP"):
                            print(f"\nReçu : {op} — blocage MIDI 1s")
                            apply_until = time.time() + 1.0
                            if op == "PLAY":
                                midi_out_port.send(mido.Message.from_bytes([0xFA]))
                            else:
                                midi_out_port.send(mido.Message.from_bytes([0xFC]))

                await asyncio.gather(sender(), receiver())
        except Exception as e:
            print(f"Déconnecté ({e}) — reconnexion dans 3s...")
            await asyncio.sleep(3)

# ── Script listener (FL In 0 — CC depuis FLSync via device.midiOutMsg) ───────

def script_listener(loop):
    bpm_msb = None
    with mido.open_input(SCRIPT_MIDI_IN) as port:
        print(f"Écoute script sur {SCRIPT_MIDI_IN}...")
        for msg in port:
            if msg.type != "control_change" or msg.channel != 0:
                continue
            if msg.control == 0 and msg.value == 1:
                print("\nScript FLSync actif ✓")
            elif msg.control == 20:
                bpm_msb = msg.value
            elif msg.control == 21 and bpm_msb is not None:
                bpm_val = (bpm_msb << 7) | msg.value
                bpm = round(bpm_val / 10.0, 1)
                bpm_msb = None
                if time.time() >= clock_slave_until:
                    print(f"\rBPM : {bpm}    ", end="", flush=True)
                    asyncio.run_coroutine_threadsafe(
                        event_queue.put(("BPM", bpm)), loop
                    )

# ── MIDI listener (FL Out 1 — play/stop depuis FL Studio) ────────────────────

def midi_listener(loop):
    global _fl_playing, _pending_flp
    last = None
    with mido.open_input(MIDI_IN) as port:
        print(f"Écoute MIDI {MIDI_IN}...")
        for msg in port:
            if msg.type == "clock":
                continue
            if time.time() < apply_until:
                continue
            if msg.type == "start" and last != "start":
                _fl_playing = True
                print("PLAY détecté !")
                asyncio.run_coroutine_threadsafe(event_queue.put("PLAY"), loop)
                last = "start"
            elif msg.type == "stop" and last != "stop":
                _fl_playing = False
                print("STOP détecté !")
                asyncio.run_coroutine_threadsafe(event_queue.put("STOP"), loop)
                last = "stop"
                if _pending_flp:
                    path, _pending_flp = _pending_flp, None
                    threading.Thread(target=_open_flp, args=(path,), daemon=True).start()

# ── Collecte automatique des samples depuis le .flp ──────────────────────────

def _collect_flp_samples(flp_path):
    """Parse le .flp avec pyflp et copie tous les samples dans SAMPLES_SYNC_DIR."""
    if not SAMPLES_SYNC_DIR:
        return
    try:
        import pyflp
        project = pyflp.parse(flp_path)
        for channel in project.channels:
            try:
                sample_path = getattr(channel, 'sample_path', None)
                if not sample_path:
                    continue
                sample_path = str(sample_path)
                if not os.path.isfile(sample_path):
                    continue
                # Déjà dans FL-SAMPLES → rien à faire
                if os.path.abspath(sample_path).startswith(
                        os.path.abspath(SAMPLES_SYNC_DIR)):
                    continue
                fname = os.path.basename(sample_path)
                dest  = os.path.join(SAMPLES_SYNC_DIR, fname)
                if not os.path.exists(dest):
                    os.makedirs(SAMPLES_SYNC_DIR, exist_ok=True)
                    shutil.copy2(sample_path, dest)
                    print(f"\nSample collecté → FL-SAMPLES : {fname}")
            except Exception:
                pass
    except ImportError:
        pass  # pyflp pas installé, on ignore
    except Exception as e:
        print(f"\nCollect samples: {e}")

# ── Sync watcher (.flp + audio dans FLP_SYNC_DIR, samples dans SAMPLES_SYNC_DIR)

_AUDIO_EXTS = {'.wav', '.mp3', '.flac', '.ogg', '.aiff', '.aif', '.w64'}

def _scan_dir(base_dir, mtimes, loop, is_flp_dir=False):
    """Scan un dossier récursivement et envoie les fichiers nouveaux/modifiés."""
    for root, _, files in os.walk(base_dir):
        for fname in files:
            path = os.path.join(root, fname)
            ext  = os.path.splitext(fname)[1].lower()
            is_flp    = ext == '.flp'
            is_audio  = ext in _AUDIO_EXTS
            if not is_flp and not is_audio:
                continue
            try:
                mtime = os.path.getmtime(path)
                size  = os.path.getsize(path)
            except Exception:
                continue
            rel = os.path.relpath(path, base_dir)
            key = base_dir + "|" + rel
            if key in mtimes and mtimes[key] != mtime:
                mtimes[key] = mtime
                if time.time() < flp_slave_until and is_flp_dir and is_flp:
                    continue
                if is_audio and size > SAMPLES_MAX_MB * 1024 * 1024:
                    print(f"\nSample ignoré (>{SAMPLES_MAX_MB}MB) : {rel}")
                    continue
                time.sleep(0.2)
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                if is_flp:
                    print(f"\nEnvoi FLP : {fname}")
                    from merge import save_base
                    save_base(path, _BASE_DIR)
                    # Collecte les samples référencés dans le .flp
                    _collect_flp_samples(path)
                    asyncio.run_coroutine_threadsafe(
                        event_queue.put(("FLP", data, fname)), loop
                    )
                else:
                    print(f"\nEnvoi sample : {rel}")
                    asyncio.run_coroutine_threadsafe(
                        event_queue.put(("SAMPLE", data, rel)), loop
                    )
            else:
                mtimes[key] = mtime

def flp_watcher(loop):
    if not FLP_SYNC_DIR and not SAMPLES_SYNC_DIR:
        return
    if FLP_SYNC_DIR:
        os.makedirs(FLP_SYNC_DIR, exist_ok=True)
        print(f"Surveillance projet : {FLP_SYNC_DIR}")
    if SAMPLES_SYNC_DIR:
        os.makedirs(SAMPLES_SYNC_DIR, exist_ok=True)
        print(f"Surveillance samples : {SAMPLES_SYNC_DIR}")
    mtimes = {}
    while True:
        time.sleep(1)
        try:
            if FLP_SYNC_DIR:
                _scan_dir(FLP_SYNC_DIR, mtimes, loop, is_flp_dir=True)
            if SAMPLES_SYNC_DIR and SAMPLES_SYNC_DIR != FLP_SYNC_DIR:
                _scan_dir(SAMPLES_SYNC_DIR, mtimes, loop, is_flp_dir=False)
        except Exception:
            pass

# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    global midi_out_port
    midi_out_port = mido.open_output(MIDI_OUT)
    loop = asyncio.get_event_loop()
    threading.Thread(target=clock_generator_thread, daemon=True).start()
    threading.Thread(target=flp_watcher,    args=(loop,), daemon=True).start()
    threading.Thread(target=script_listener,  args=(loop,), daemon=True).start()
    threading.Thread(target=midi_listener,    args=(loop,), daemon=True).start()
    try:
        await websocket_handler()
    finally:
        midi_out_port.close()

asyncio.run(main())
