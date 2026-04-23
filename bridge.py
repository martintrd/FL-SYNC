import sys
sys.stdout.reconfigure(encoding='utf-8')
import mido
import asyncio
import websockets
import json
import threading
import time

SERVER = "ws://localhost:8080"
MY_ID = "pc_a"
MIDI_IN = "FL Out 1"
MIDI_OUT = "FL In 1"

apply_until = 0.0       # bloque PLAY/STOP reçus depuis FL (anti-boucle)
clock_slave_until = 0.0 # bloque envoi BPM quand on reçoit le BPM du pote

current_generated_bpm = None
clock_task = None
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
    global apply_until, clock_slave_until, current_generated_bpm, clock_task
    while True:
        try:
            async with websockets.connect(SERVER) as ws:
                print("Connecté au serveur ✓")

                async def sender():
                    while True:
                        msg = await event_queue.get()
                        if isinstance(msg, tuple) and msg[0] == "BPM":
                            payload = {"op": "BPM", "bpm": msg[1], "from": MY_ID}
                            print(f"Envoyé BPM : {msg[1]}")
                        else:
                            payload = {"op": msg, "from": MY_ID}
                            print(f"Envoyé : {msg}")
                        await ws.send(json.dumps(payload))

                async def receiver():
                    global apply_until, clock_slave_until, current_generated_bpm, clock_task
                    async for raw in ws:
                        event = json.loads(raw)
                        if event.get("from") == MY_ID:
                            continue
                        op = event.get("op")
                        if op == "BPM":
                            bpm = event["bpm"]
                            print(f"Reçu BPM : {bpm} — génération clock MIDI")
                            clock_slave_until = time.time() + 3.0
                            current_generated_bpm = bpm
                            if clock_task is None or clock_task.done():
                                clock_task = asyncio.create_task(run_clock_generator())
                        elif op in ("PLAY", "STOP"):
                            print(f"Reçu : {op} — blocage MIDI 1s")
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
    last = None
    last_bpm_sent = None
    last_bpm_time = 0.0
    last_bpm_display = 0.0
    clock_intervals = []
    last_clock_time = None

    with mido.open_input(MIDI_IN) as port:
        print(f"Écoute {MIDI_IN}...")
        for msg in port:
            if msg.type == "clock":
                if time.time() < clock_slave_until:
                    continue
                now = time.time()
                if last_clock_time is not None:
                    interval = now - last_clock_time
                    if 0.001 < interval < 0.5:
                        clock_intervals.append(interval)
                        if len(clock_intervals) > 96:
                            clock_intervals = clock_intervals[-96:]
                        if len(clock_intervals) >= 48:
                            mean = sum(clock_intervals) / len(clock_intervals)
                            bpm = round(60.0 / (mean * 24), 1)
                            if now - last_bpm_display >= 1.0:
                                print(f"\rBPM : {bpm}    ", end="", flush=True)
                                last_bpm_display = now
                            changed = last_bpm_sent is None or abs(bpm - last_bpm_sent) >= 0.5
                            throttled = now - last_bpm_time >= 1.0
                            if changed and throttled:
                                last_bpm_sent = bpm
                                last_bpm_time = now
                                asyncio.run_coroutine_threadsafe(
                                    event_queue.put(("BPM", bpm)), loop
                                )
                last_clock_time = now
                continue

            if time.time() < apply_until:
                print(f"[bloqué] {msg.type} ignoré (anti-boucle)")
                continue
            if msg.type == "start" and last != "start":
                print("PLAY détecté !")
                asyncio.run_coroutine_threadsafe(event_queue.put("PLAY"), loop)
                last = "start"
            elif msg.type == "stop" and last != "stop":
                print("STOP détecté !")
                asyncio.run_coroutine_threadsafe(event_queue.put("STOP"), loop)
                last = "stop"

async def main():
    global midi_out_port
    midi_out_port = mido.open_output(MIDI_OUT)
    loop = asyncio.get_event_loop()
    thread = threading.Thread(target=midi_listener, args=(loop,), daemon=True)
    thread.start()
    try:
        await websocket_handler()
    finally:
        midi_out_port.close()

asyncio.run(main())
