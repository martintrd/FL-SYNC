import sys
sys.stdout.reconfigure(encoding='utf-8')
import mido
import asyncio
import websockets
import json
import threading
import base64
import os
import time
import ctypes

SERVER = "ws://176.159.207.97:8080"
MY_ID = "pc_b"
MIDI_IN        = "FL Out 1"
SCRIPT_MIDI_IN = "FL In 0"
MIDI_OUT       = "FL In 1"

# Dossier partagé : enregistre tes .flp ici ET les fichiers du pote arrivent ici
FLP_SYNC_DIR = r""  # ex: r"C:\FL-SYNC"

apply_until       = 0.0
clock_slave_until = 0.0
flp_slave_until   = 0.0

current_generated_bpm = None
midi_out_port         = None

_fl_playing    = False   # FL Studio en train de jouer ?
_pending_flp   = None    # .flp en attente d'être appliqué

event_queue = asyncio.Queue()

# ── Rechargement FL Studio ────────────────────────────────────────────────────

def _dismiss_save_dialog():
    """Cherche le dialog 'Enregistrer ?' de FL Studio et clique Non/No."""
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
                if clicked[0]:
                    return False
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == '#32770':
                    try:
                        win32gui.EnumChildWindows(hwnd, _check_btn, None)
                    except Exception:
                        pass
                return True

            win32gui.EnumWindows(_check_win, None)
            if clicked[0]:
                print("Dialog dismissé ✓")
                return

        except ImportError:
            # Fallback sans pywin32 : Alt+N (raccourci clavier Non/No)
            time.sleep(0.5)
            u32 = ctypes.windll.user32
            u32.keybd_event(0x12, 0, 0, 0)  # Alt down
            u32.keybd_event(0x4E, 0, 0, 0)  # N down
            u32.keybd_event(0x4E, 0, 2, 0)  # N up
            u32.keybd_event(0x12, 0, 2, 0)  # Alt up
            return

        time.sleep(0.15)

def _open_flp(path):
    """Ouvre un .flp dans FL Studio et auto-dismiss le dialog de sauvegarde."""
    print(f"\nOuverture dans FL Studio : {path}")
    threading.Thread(target=_dismiss_save_dialog, daemon=True).start()
    ctypes.windll.shell32.ShellExecuteW(None, "open", path, None, None, 1)

# ── Clock generator ───────────────────────────────────────────────────────────

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
        remaining = next_t - time.perf_counter()
        if remaining > 0.002:
            time.sleep(remaining - 0.002)
        while time.perf_counter() < next_t:
            pass
        if current_generated_bpm is not None:
            midi_out_port.send(mido.Message.from_bytes([0xF8]))

# ── WebSocket ─────────────────────────────────────────────────────────────────

async def websocket_handler():
    global apply_until, clock_slave_until, flp_slave_until
    global current_generated_bpm, _pending_flp
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
                            print(f"\nEnvoyé : {msg[2]}")
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
                            dest = os.path.join(FLP_SYNC_DIR, filename)
                            data = base64.b64decode(event["data"])
                            with open(dest, "wb") as f:
                                f.write(data)
                            print(f"\nReçu : {filename}")
                            if not _fl_playing:
                                threading.Thread(
                                    target=_open_flp, args=(dest,), daemon=True
                                ).start()
                            else:
                                _pending_flp = dest
                                print("(FL joue → appliqué à l'arrêt)")
                        elif op == "BPM":
                            bpm = event["bpm"]
                            print(f"\nReçu BPM : {bpm}")
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

# ── Script listener ───────────────────────────────────────────────────────────

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

# ── MIDI listener ─────────────────────────────────────────────────────────────

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
                # Applique le .flp en attente maintenant que FL est stoppé
                if _pending_flp:
                    path = _pending_flp
                    _pending_flp = None
                    threading.Thread(target=_open_flp, args=(path,), daemon=True).start()

# ── FLP watcher ───────────────────────────────────────────────────────────────

def flp_watcher(loop):
    if not FLP_SYNC_DIR:
        return
    os.makedirs(FLP_SYNC_DIR, exist_ok=True)
    print(f"Surveillance dossier : {FLP_SYNC_DIR}")
    mtimes = {}
    while True:
        time.sleep(1)
        try:
            flp_files = [
                os.path.join(FLP_SYNC_DIR, f)
                for f in os.listdir(FLP_SYNC_DIR)
                if f.lower().endswith('.flp')
            ]
            for path in flp_files:
                try:
                    mtime = os.path.getmtime(path)
                except Exception:
                    continue
                if time.time() < flp_slave_until:
                    mtimes[path] = mtime
                    continue
                if path in mtimes and mtimes[path] != mtime:
                    mtimes[path] = mtime
                    time.sleep(0.3)
                    with open(path, "rb") as f:
                        data = base64.b64encode(f.read()).decode()
                    name = os.path.basename(path)
                    print(f"\nEnvoi {name}...")
                    asyncio.run_coroutine_threadsafe(
                        event_queue.put(("FLP", data, name)), loop
                    )
                else:
                    mtimes[path] = mtime
        except Exception:
            pass

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    global midi_out_port
    midi_out_port = mido.open_output(MIDI_OUT)
    loop = asyncio.get_event_loop()
    threading.Thread(target=clock_generator_thread, daemon=True).start()
    threading.Thread(target=flp_watcher,     args=(loop,), daemon=True).start()
    threading.Thread(target=script_listener,  args=(loop,), daemon=True).start()
    threading.Thread(target=midi_listener,    args=(loop,), daemon=True).start()
    try:
        await websocket_handler()
    finally:
        midi_out_port.close()

asyncio.run(main())
