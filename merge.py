"""
Merge 3-voies de projets FL Studio.
Stratégie :
  - Utilise pyflp pour compter channels/patterns dans base, local, remote
  - Trouve le type d'event FLP qui sert de séparateur de channel (heuristique)
  - Extrait les blocs "nouveaux" de remote et les injecte dans local
  - Fallback : applique remote + sauvegarde local en backup
"""

import os
import shutil
import struct


# ── Parser/serializer FLP brut ────────────────────────────────────────────────

def _read_flp(path):
    """Lit un .flp et retourne (header_meta, events_list, raw_events_bytes)."""
    with open(path, 'rb') as f:
        data = f.read()
    assert data[:4] == b'FLhd', f"Pas un .flp : {path}"
    hdr_size  = struct.unpack_from('<I', data, 4)[0]
    fmt, n_ch, ppq = struct.unpack_from('<HHH', data, 8)
    dt_off    = 8 + hdr_size
    assert data[dt_off:dt_off+4] == b'FLdt'
    dt_size   = struct.unpack_from('<I', data, dt_off+4)[0]
    ev_bytes  = data[dt_off+8:dt_off+8+dt_size]
    return (fmt, n_ch, ppq), _parse_events(ev_bytes), ev_bytes

def _parse_events(data):
    """Décode le flux d'events FLP en liste de (type, bytes_data)."""
    evts = []
    i = 0
    while i < len(data):
        t = data[i]; i += 1
        if t < 64:
            evts.append((t, data[i:i+1])); i += 1
        elif t < 128:
            evts.append((t, data[i:i+2])); i += 2
        elif t < 192:
            evts.append((t, data[i:i+4])); i += 4
        else:                           # variable-length
            size = shift = 0
            while i < len(data):
                b = data[i]; i += 1
                size |= (b & 0x7F) << shift; shift += 7
                if not (b & 0x80): break
            evts.append((t, data[i:i+size])); i += size
    return evts

def _serialize_event(t, d):
    if t < 64:   return bytes([t]) + d[:1]
    if t < 128:  return bytes([t]) + d[:2]
    if t < 192:  return bytes([t]) + d[:4]
    # variable-length
    size = len(d); sb = b''
    while True:
        b = size & 0x7F; size >>= 7
        if size: b |= 0x80
        sb += bytes([b])
        if not size: break
    return bytes([t]) + sb + d

def _serialize_events(evts):
    return b''.join(_serialize_event(t, d) for t, d in evts)

def _build_flp(fmt, n_ch, ppq, events_bytes):
    hdr = struct.pack('<HHH', fmt, n_ch, ppq)
    return (b'FLhd' + struct.pack('<I', 6) + hdr +
            b'FLdt' + struct.pack('<I', len(events_bytes)) + events_bytes)


# ── Détection du séparateur de channels ──────────────────────────────────────

def _find_separator(evts, expected_count):
    """
    Trouve le type d'event qui apparaît exactement expected_count fois.
    C'est l'event séparateur de channel dans ce fichier.
    """
    counts = {}
    for t, _ in evts:
        counts[t] = counts.get(t, 0) + 1
    candidates = [t for t, c in counts.items() if c == expected_count]
    # Préfère les types dans les ranges "dword" ou "text" (128-255)
    for t in sorted(candidates, reverse=True):
        if t >= 64:
            return t
    return candidates[0] if candidates else None


# ── Merge 3-voies ─────────────────────────────────────────────────────────────

def merge_flp(base_path, local_path, remote_path, output_path):
    """
    Tente un merge 3-voies de projets FL Studio.
    Retourne (success: bool, message: str).
    """
    try:
        import pyflp
    except ImportError:
        shutil.copy(remote_path, output_path)
        return False, "pyflp manquant — pip install pyflp\n→ Remote appliqué"

    try:
        b_meta, b_evts, _ = _read_flp(base_path) if os.path.exists(base_path) else (None, [], b'')
        l_meta, l_evts, _ = _read_flp(local_path)
        r_meta, r_evts, _ = _read_flp(remote_path)

        # Lecture haut-niveau via pyflp
        b_proj = pyflp.parse(base_path) if os.path.exists(base_path) else None
        l_proj = pyflp.parse(local_path)
        r_proj = pyflp.parse(remote_path)

        b_ch = {c.name for c in (b_proj.channels if b_proj else [])}
        l_ch = {c.name for c in l_proj.channels}
        r_ch = {c.name for c in r_proj.channels}

        l_new = l_ch - b_ch     # local a ajouté ces channels
        r_new = r_ch - b_ch     # remote a ajouté ces channels

        b_pt = {p.name for p in (b_proj.patterns if b_proj else [])}
        l_pt = {p.name for p in l_proj.patterns}
        r_pt = {p.name for p in r_proj.patterns}

        l_pt_new = l_pt - b_pt
        r_pt_new = r_pt - b_pt

        # ── Cas simples ──────────────────────────────────────────────────────
        if not r_new and not r_pt_new:
            shutil.copy(local_path, output_path)
            return True, "Aucun ajout remote → local conservé"

        if not l_new and not l_pt_new:
            shutil.copy(remote_path, output_path)
            return True, "Aucun ajout local → remote appliqué"

        # ── Merge binaire ────────────────────────────────────────────────────
        b_n_ch = b_meta[1] if b_meta else 0
        l_n_ch = l_meta[1]
        r_n_ch = r_meta[1]
        new_ch_count = r_n_ch - b_n_ch   # channels ajoutés par remote

        merged_bytes = None
        if new_ch_count > 0:
            merged_bytes = _binary_merge_channels(
                b_evts, l_evts, r_evts,
                l_meta, r_meta,
                b_n_ch, l_n_ch, r_n_ch, new_ch_count
            )

        if merged_bytes:
            with open(output_path, 'wb') as f:
                f.write(merged_bytes)
            msg = (f"✓ Merge réussi!\n"
                   f"  Local avait ajouté  : {l_new or l_pt_new}\n"
                   f"  Remote avait ajouté : {r_new or r_pt_new}")
            return True, msg

        # ── Fallback : remote + backup local ─────────────────────────────────
        shutil.copy(remote_path, output_path)
        backup = local_path.replace('.flp', '_backup_local.flp')
        shutil.copy(local_path, backup)
        msg = (f"⚠ Merge automatique échoué → remote appliqué\n"
               f"  Ton travail sauvé dans : {os.path.basename(backup)}\n"
               f"  Tu avais ajouté : {l_new | l_pt_new}\n"
               f"  Remote avait ajouté : {r_new | r_pt_new}")
        return False, msg

    except Exception as e:
        shutil.copy(remote_path, output_path)
        return False, f"Erreur merge: {e} → remote appliqué"


def _binary_merge_channels(b_evts, l_evts, r_evts,
                            l_meta, r_meta,
                            b_n_ch, l_n_ch, r_n_ch, new_ch_count):
    """
    Injection binaire des nouveaux channels de remote dans local.
    Heuristique : trouve l'event-type qui apparaît exactement b_n_ch fois
    dans base et (b_n_ch + new_ch_count) fois dans remote = séparateur.
    """
    # 1. Trouver le séparateur dans remote
    sep_type = _find_separator(r_evts, r_n_ch)
    if sep_type is None:
        return None

    # 2. Vérifier cohérence avec base
    b_counts = {}
    for t, _ in b_evts:
        b_counts[t] = b_counts.get(t, 0) + 1
    if b_counts.get(sep_type, 0) != b_n_ch:
        return None

    # 3. Positions des séparateurs dans remote
    sep_pos_remote = [i for i, (t, _) in enumerate(r_evts) if t == sep_type]
    if len(sep_pos_remote) < b_n_ch + new_ch_count:
        return None

    # 4. Extraire le bloc des nouveaux channels de remote
    new_start = sep_pos_remote[b_n_ch]      # 1er séparateur après la base
    new_ch_events = r_evts[new_start:]

    # 5. Trouver le point d'injection dans local
    #    → juste après le dernier channel existant dans local
    sep_pos_local = [i for i, (t, _) in enumerate(l_evts) if t == sep_type]
    if not sep_pos_local:
        return None
    # Injection après le dernier bloc de channel de local
    # = à la position du premier event NON-channel après le dernier séparateur
    inject_at = len(l_evts)  # par défaut : fin
    last_sep = sep_pos_local[-1]
    for i in range(last_sep + 1, len(l_evts)):
        # Heuristique : si on trouve un type d'event qui n'est pas dans les
        # types "normaux" de channels, on s'arrête là
        # Pour l'instant on injecte juste à la fin pour être safe
        pass

    # 6. Construire le stream mergé
    merged_evts = l_evts[:inject_at] + new_ch_events
    merged_data = _serialize_events(merged_evts)

    # 7. Construire le fichier avec le bon channel count
    fmt, _, ppq = l_meta
    return _build_flp(fmt, l_n_ch + new_ch_count, ppq, merged_data)


# ── Suivi de la base ──────────────────────────────────────────────────────────

def save_base(flp_path, base_dir):
    """Sauvegarde une copie du .flp comme version de base."""
    os.makedirs(base_dir, exist_ok=True)
    name = os.path.basename(flp_path)
    base_path = os.path.join(base_dir, name)
    shutil.copy(flp_path, base_path)
    return base_path

def get_base(flp_name, base_dir):
    """Retourne le chemin de la base pour ce fichier, ou None."""
    path = os.path.join(base_dir, flp_name)
    return path if os.path.exists(path) else None
