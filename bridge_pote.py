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

SERVER = "ws://176.159.207.97:8080"
MY_ID = "pc_b"
MIDI_IN = "FL Out 1"
MIDI_OUT = "FL In 1"

FLP_PATH     = r""
FLP_RECEIVED = r"C:\Users\pote\Desktop\received_project.flp"

apply_until       = 0.0
clock_slave_until = 0.0
flp_slave_until   = 0.0

current_generated_bpm = None
clock_task    = None
midi_out_port = None

event_queue = asyncio.Queue()

async def run_clock_generator():
    global current_generated_bpm
    while True:
        bpm = current_generated_bpm
        if bpm is None:
            break
        midi_out_port.send(mido.Message.from_bytes([0xF8]))
        await asyncio.sleep(60.0 / (bpm * 24))

async def websocket_handler():
    global apply_until, clock_slave_until, flp_slave_until
    global current_generated_bpm, clock_task
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
                            payload = {"op": "FLP", "data": msg[1], "from": MY_ID}
                            print(f"\nProjet envoyé ✓")
                        else:
                            payload = {"op": msg, "from": MY_ID}
                            print(f"\nEnvoyé : {msg}")
                        await ws.send(json.dumps(payload))

                async def receiver():
                    global apply_until, clock_slave_until, flp_slave_until
                    global current_generated_bpm, clock_task
                    async for raw in ws:
                        event = json.loads(raw)
                        if event.get("from") == MY_ID:
                            continue
                        op = event.get("op")
                        if op == "FLP":
                            flp_slave_until = time.time() + 5.0
                            data = base64.b64decode(event["data"])
                            with open(FLP_RECEIVED, "wb") as f:
                                f.write(data)
                            print(f"\nProjet reçu → {FLP_RECEIVED}")
                        elif op == "BPM":
                            bpm = event["bpm"]
                            print(f"\nReçu BPM : {bpm} — génération clock MIDI")
                            clock_slave_until = time.time() + 3.0
                            current_generated_bpm = bpm
                            if clock_task is None or clock_task.done():
                                clock_task = asyncio.create_task(run_clock_generator())
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

def midi_listener(loop):
    last    = None
    bpm_msb = None

    with mido.open_input(MIDI_IN) as port:
        print(f"Écoute MIDI {MIDI_IN}...")
        for msg in port:
            if msg.type == "control_change" and msg.channel == 0:
                if msg.control == 0 and msg.value == 1:
                    print("Script FLSync actif ✓")
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
                continue

            if msg.type == "clock":
                continue

            if time.time() < apply_until:
                continue
            if msg.type == "start" and last != "start":
                print("PLAY détecté !")
                asyncio.run_coroutine_threadsafe(event_queue.put("PLAY"), loop)
                last = "start"
            elif msg.type == "stop" and last != "stop":
                print("STOP détecté !")
                asyncio.run_coroutine_threadsafe(event_queue.put("STOP"), loop)
                last = "stop"

def flp_watcher(loop):
    if not FLP_PATH:
        return
    last_mtime = 0
    print(f"Surveillance projet : {FLP_PATH}")
    while True:
        time.sleep(1)
        if time.time() < flp_slave_until:
            try:
                last_mtime = os.path.getmtime(FLP_PATH)
            except Exception:
                pass
            continue
        try:
            mtime = os.path.getmtime(FLP_PATH)
            if last_mtime != 0 and mtime != last_mtime:
                last_mtime = mtime
                time.sleep(0.3)
                with open(FLP_PATH, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                asyncio.run_coroutine_threadsafe(event_queue.put(("FLP", data)), loop)
            else:
                last_mtime = mtime
        except Exception:
            pass

async def main():
    global midi_out_port
    midi_out_port = mido.open_output(MIDI_OUT)
    loop = asyncio.get_event_loop()
    threading.Thread(target=flp_watcher,   args=(loop,), daemon=True).start()
    threading.Thread(target=midi_listener, args=(loop,), daemon=True).start()
    try:
        await websocket_handler()
    finally:
        midi_out_port.close()

asyncio.run(main())
