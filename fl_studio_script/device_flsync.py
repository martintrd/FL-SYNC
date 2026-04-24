# name=FLSync

import device
import transport
import midi

_last_bpm = None
_rec_last = None
_playing  = False

def OnInit():
    print("FLSync: chargé ✓")
    device.midiOutMsg(0xB0 | (0 << 8) | (1 << 16))
    _check_bpm()

def OnRefresh(flags):
    global _playing
    _check_bpm()
    playing = transport.isPlaying()
    if playing != _playing:
        _playing = playing
        val = 1 if playing else 0
        device.midiOutMsg(0xB0 | (10 << 8) | (val << 16))
        print("FLSync:", "PLAY" if playing else "STOP")

def OnUpdateBeatIndicator(value):
    # Poll le BPM exact à chaque beat (pendant le play)
    if value != 0:
        _check_bpm()

def _check_bpm():
    global _rec_last, _last_bpm
    try:
        raw = device.getLinkedValue(midi.REC_Tempo)
        if raw == _rec_last:
            return
        _rec_last = raw
        bpm = round(raw * 512 + 10, 1)
        if bpm != _last_bpm:
            _last_bpm = bpm
            _send_bpm(bpm)
    except Exception:
        pass

def _send_bpm(bpm):
    bpm_val = int(round(bpm * 10))
    msb = (bpm_val >> 7) & 0x7F
    lsb = bpm_val & 0x7F
    device.midiOutMsg(0xB0 | (20 << 8) | (msb << 16))
    device.midiOutMsg(0xB0 | (21 << 8) | (lsb << 16))
    print("FLSync: BPM →", bpm)
