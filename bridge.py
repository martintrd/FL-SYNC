import sys
sys.stdout.reconfigure(encoding='utf-8')
import asyncio
import websockets
import json
import threading
import base64
import hashlib
import os
import re
import shutil
import time
import ctypes

# ── Config (peut aussi être dans config.json) ─────────────────────────────────

_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
if os.path.exists(_CFG_FILE):
    with open(_CFG_FILE) as f:
        _cfg = json.load(f)
else:
    _cfg = {}

SERVER           = _cfg.get("SERVER",           "ws://localhost:8080")
MY_ID            = _cfg.get("MY_ID",            "pc_a")
FLP_SYNC_DIR     = _cfg.get("FLP_SYNC_DIR",     r"C:\Users\flyxe\Desktop\FL-SYNC-SHARE")
SAMPLES_SYNC_DIR = _cfg.get("SAMPLES_SYNC_DIR", r"C:\Users\flyxe\Desktop\FL-SAMPLES")
SAMPLES_MAX_MB   = _cfg.get("SAMPLES_MAX_MB",   30)

_BASE_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".flp_bases")
_sent_samples = set()
_base_hashes  = {}
flp_slave_until = 0.0

event_queue = asyncio.Queue()

# ── Utilitaires ───────────────────────────────────────────────────────────────

def _md5(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

def _dismiss_save_dialog():
    deadline = time.time() + 8.0
    while time.time() < deadline:
        try:
            import win32gui, win32con, win32api
            clicked = [False]
            def _btn(hwnd, _):
                txt = win32gui.GetWindowText(hwnd).strip().lower().replace('&', '')
                if txt in ('no', 'non', "don't save", 'ne pas enregistrer'):
                    win32api.PostMessage(hwnd, win32con.BM_CLICK, 0, 0)
                    clicked[0] = True; return False
                return True
            def _win(hwnd, _):
                if clicked[0]: return False
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == '#32770':
                    try: win32gui.EnumChildWindows(hwnd, _btn, None)
                    except: pass
                return True
            win32gui.EnumWindows(_win, None)
            if clicked[0]: return
        except ImportError:
            time.sleep(0.5)
            u = ctypes.windll.user32
            u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x4E, 0, 0, 0)
            u.keybd_event(0x4E, 0, 2, 0); u.keybd_event(0x12, 0, 2, 0)
            return
        time.sleep(0.15)

def _open_flp(path):
    print(f"\nOuverture FL Studio : {path}")
    threading.Thread(target=_dismiss_save_dialog, daemon=True).start()
    ctypes.windll.shell32.ShellExecuteW(None, "open", path, None, None, 1)

# ── Collecte samples depuis le .flp ──────────────────────────────────────────

def _collect_flp_samples(flp_path, loop=None):
    if not SAMPLES_SYNC_DIR:
        return
    try:
        with open(flp_path, "rb") as f:
            data = f.read()
        drive_pat = re.compile(r"[A-Za-z]:\\")
        paths = set()
        for ext in ["wav", "mp3", "flac", "ogg", "aiff", "aif", "w64"]:
            needle = ("." + ext).encode("utf-16-le")
            pos = 0
            while True:
                idx = data.find(needle, pos)
                if idx == -1: break
                j = idx
                while j >= 2:
                    if j >= 4 and data[j-4] == 0 and data[j-3] == 0: break
                    j -= 2
                chunk = data[j:idx + len(needle)]
                try:
                    raw = chunk.decode("utf-16-le", errors="ignore").strip(chr(0))
                    m = drive_pat.search(raw)
                    if m: paths.add(raw[m.start():])
                except: pass
                pos = idx + 1
        os.makedirs(SAMPLES_SYNC_DIR, exist_ok=True)
        for sp in paths:
            if not os.path.isfile(sp): continue
            if os.path.getsize(sp) > SAMPLES_MAX_MB * 1024 * 1024: continue
            if os.path.abspath(sp).startswith(os.path.abspath(SAMPLES_SYNC_DIR)): continue
            fname = os.path.basename(sp)
            dest  = os.path.join(SAMPLES_SYNC_DIR, fname)
            if not os.path.exists(dest):
                shutil.copy2(sp, dest)
                print(f"\nSample collecté : {fname}")
            if loop and dest not in _sent_samples:
                _sent_samples.add(dest)
                rel = os.path.relpath(dest, SAMPLES_SYNC_DIR)
                with open(dest, 'rb') as f:
                    enc = base64.b64encode(f.read()).decode()
                asyncio.run_coroutine_threadsafe(
                    event_queue.put(("SAMPLE", enc, rel)), loop)
                print(f"\nEnvoi sample : {rel}")
    except Exception as e:
        print(f"\nCollect samples: {e}")

# ── WebSocket ─────────────────────────────────────────────────────────────────

async def websocket_handler():
    global flp_slave_until
    while True:
        try:
            async with websockets.connect(SERVER, max_size=50*1024*1024) as ws:
                print("Connecté au serveur ✓")

                async def sender():
                    while True:
                        msg = await event_queue.get()
                        if isinstance(msg, tuple) and msg[0] == "FLP":
                            payload = {"op": "FLP", "data": msg[1], "filename": msg[2], "from": MY_ID}
                            print(f"\nEnvoyé FLP : {msg[2]}")
                        elif isinstance(msg, tuple) and msg[0] == "SAMPLE":
                            payload = {"op": "SAMPLE", "data": msg[1], "rel": msg[2], "from": MY_ID}
                            print(f"\nEnvoyé sample : {msg[2]}")
                        else:
                            continue
                        await ws.send(json.dumps(payload))

                async def receiver():
                    global flp_slave_until
                    async for raw in ws:
                        event = json.loads(raw)
                        if event.get("from") == MY_ID:
                            continue
                        op = event.get("op")
                        if op == "FLP" and FLP_SYNC_DIR:
                            flp_slave_until = time.time() + 5.0
                            os.makedirs(FLP_SYNC_DIR, exist_ok=True)
                            filename   = event.get("filename", "received.flp")
                            dest       = os.path.join(FLP_SYNC_DIR, filename)
                            remote_tmp = dest + ".remote_tmp"
                            with open(remote_tmp, "wb") as f:
                                f.write(base64.b64decode(event["data"]))
                            local_dirty = (
                                os.path.exists(dest) and
                                filename in _base_hashes and
                                _md5(dest) != _base_hashes[filename]
                            )
                            if local_dirty:
                                print(f"\n⚠ CONFLIT {filename} — merge...")
                                from merge import merge_flp, get_base
                                _, msg = merge_flp(get_base(filename, _BASE_DIR),
                                                   dest, remote_tmp, dest)
                                print(f"\n{msg}")
                            else:
                                shutil.copy(remote_tmp, dest)
                                print(f"\nReçu : {filename}")
                            os.remove(remote_tmp)
                            _base_hashes[filename] = _md5(dest)
                            from merge import save_base
                            save_base(dest, _BASE_DIR)
                            threading.Thread(target=_open_flp, args=(dest,), daemon=True).start()
                        elif op == "SAMPLE" and SAMPLES_SYNC_DIR:
                            rel  = event.get("rel", "")
                            dest = os.path.join(SAMPLES_SYNC_DIR, rel)
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            with open(dest, "wb") as f:
                                f.write(base64.b64decode(event["data"]))
                            _sent_samples.add(dest)
                            print(f"\nSample reçu : {rel}")

                await asyncio.gather(sender(), receiver())
        except Exception as e:
            print(f"Déconnecté ({e}) — reconnexion dans 3s...")
            await asyncio.sleep(3)

# ── Watcher FLP + samples ─────────────────────────────────────────────────────

_AUDIO_EXTS    = {'.wav', '.mp3', '.flac', '.ogg', '.aiff', '.aif', '.w64'}
_WATCHER_START = time.time()

def _scan_dir(base_dir, mtimes, loop):
    for root, _, files in os.walk(base_dir):
        for fname in files:
            path = os.path.join(root, fname)
            ext  = os.path.splitext(fname)[1].lower()
            is_flp   = ext == '.flp'
            is_audio = ext in _AUDIO_EXTS
            if not is_flp and not is_audio:
                continue
            try:
                mtime = os.path.getmtime(path)
                size  = os.path.getsize(path)
            except: continue
            rel = os.path.relpath(path, base_dir)
            key = base_dir + "|" + rel
            is_new = key not in mtimes and mtime > _WATCHER_START
            if (key in mtimes and mtimes[key] != mtime) or is_new:
                mtimes[key] = mtime
                if is_flp and time.time() < flp_slave_until and not is_new:
                    continue
                if is_audio and size > SAMPLES_MAX_MB * 1024 * 1024:
                    print(f"\nSample ignoré (>{SAMPLES_MAX_MB}MB) : {rel}")
                    continue
                if is_audio and path in _sent_samples:
                    continue
                time.sleep(0.2)
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                if is_flp:
                    print(f"\nEnvoi FLP : {fname}")
                    from merge import save_base
                    save_base(path, _BASE_DIR)
                    _collect_flp_samples(path, loop)
                    asyncio.run_coroutine_threadsafe(
                        event_queue.put(("FLP", data, fname)), loop)
                else:
                    _sent_samples.add(path)
                    print(f"\nEnvoi sample : {rel}")
                    asyncio.run_coroutine_threadsafe(
                        event_queue.put(("SAMPLE", data, rel)), loop)
            else:
                mtimes[key] = mtime

def flp_watcher(loop):
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
                _scan_dir(FLP_SYNC_DIR, mtimes, loop)
            if SAMPLES_SYNC_DIR and SAMPLES_SYNC_DIR != FLP_SYNC_DIR:
                _scan_dir(SAMPLES_SYNC_DIR, mtimes, loop)
        except: pass

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    loop = asyncio.get_event_loop()
    threading.Thread(target=flp_watcher, args=(loop,), daemon=True).start()
    await websocket_handler()

asyncio.run(main())
