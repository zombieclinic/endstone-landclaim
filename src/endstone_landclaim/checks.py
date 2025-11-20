# src/endstone_landclaim/checks.py
# Strict Endstone-friendly. No future annotations.

from typing import Dict, List, Tuple, Optional, Any

# ── math helpers ─────────────────────────────────────────────────────────────
def dist2d(ax: float, az: float, bx: float, bz: float) -> float:
    return ((ax - bx) ** 2 + (az - bz) ** 2) ** 0.5


# ── settings/roles ──────────────────────────────────────────────────────────
def _settings(plugin) -> dict:
    """
    Prefer admin.settings if present, then plugin.data.settings, then plugin.settings.
    Merges where possible instead of picking only one.
    """
    merged: Dict[str, Any] = {}

    # plugin.data.settings
    try:
        d = getattr(plugin, "data", {}) or {}
        s = d.get("settings", {}) or {}
        if isinstance(s, dict):
            merged.update(s)
    except Exception:
        pass

    # admin.data.settings (override plugin.data.settings)
    try:
        adm = getattr(plugin, "admin", None)
        if adm and getattr(adm, "data", None):
            s = adm.data.get("settings", {}) or {}
            if isinstance(s, dict):
                merged.update(s)
    except Exception:
        pass

    # plugin.settings (last override)
    try:
        s = getattr(plugin, "settings", {}) or {}
        if isinstance(s, dict):
            merged.update(s)
    except Exception:
        pass

    return merged


def get_setting_int(plugin, key: str, default: int = 0) -> int:
    s = _settings(plugin)
    try:
        return int(float(str(s.get(key, default))))
    except Exception:
        return default


# ── spawn / dimension helpers (per dimension with legacy fallback) ───────────
def _norm_dim_str(s: str) -> str:
    s = (s or "").lower()
    if "nether" in s:
        return "nether"
    if "end" in s:
        return "end"
    return "overworld"


def normalize_dim_key(dim_obj_or_name) -> str:
    """
    Normalize a dimension object/name/int to: overworld | nether | end
    """
    try:
        nm = getattr(dim_obj_or_name, "name", None)
        if nm:
            return _norm_dim_str(str(nm))
    except Exception:
        pass
    if isinstance(dim_obj_or_name, str):
        return _norm_dim_str(dim_obj_or_name)
    try:
        iv = int(dim_obj_or_name)
        if iv == 0:
            return "overworld"
        if iv in (1, -1):
            return "nether"
        if iv in (2,):
            return "end"
    except Exception:
        pass
    return "overworld"


def player_dim_key(player) -> str:
    try:
        loc = getattr(player, "location", None)
        if loc is not None:
            dim = getattr(loc, "dimension", None)
            if dim is not None:
                return normalize_dim_key(dim)
            lvl = getattr(loc, "level", None)
            if lvl is not None:
                return normalize_dim_key(getattr(lvl, "name", None))
    except Exception:
        pass
    return "overworld"


def entity_dim_key(ent) -> str:
    try:
        loc = getattr(ent, "location", None)
        if loc is not None:
            dim = getattr(loc, "dimension", None)
            if dim is not None:
                return normalize_dim_key(dim)
            lvl = getattr(loc, "level", None)
            if lvl is not None:
                return normalize_dim_key(getattr(lvl, "name", None))
    except Exception:
        pass
    return "overworld"


def claim_dim_key(claim: dict) -> str:
    try:
        return normalize_dim_key((claim or {}).get("dim", "overworld"))
    except Exception:
        return "overworld"


def same_dim(a, b) -> bool:
    return normalize_dim_key(a) == normalize_dim_key(b)


def _spawn_cfg_for_dim(plugin, dim_key: str) -> Dict[str, Any]:
    """
    Returns {"center": (x, y, z) or None, "radius": int} for the given dim_key.

    Uses:
      worldspawn_<dim>, spawn_protection_radius_<dim>
    with legacy fallback to:
      worldspawn, spawn_protection_radius
    """
    s = _settings(plugin)
    dk = normalize_dim_key(dim_key)

    ws_key = f"worldspawn_{dk}"
    rad_key = f"spawn_protection_radius_{dk}"

    spawn_s = str(s.get(ws_key, "")).strip()
    try:
        radius = int(float(str(s.get(rad_key, 0))))
    except Exception:
        radius = 0

    # Legacy fallback if per-dim keys are missing
    if not spawn_s:
        spawn_s = str(s.get("worldspawn", "")).strip()
    if radius <= 0:
        try:
            radius = int(float(str(s.get("spawn_protection_radius", 0))))
        except Exception:
            radius = 0

    center = None
    if spawn_s:
        parts = [p for p in spawn_s.split() if p]
        try:
            if len(parts) >= 3:
                cx = float(parts[0])
                cy = float(parts[1])
                cz = float(parts[2])
                center = (cx, cy, cz)
        except Exception:
            center = None

    return {"center": center, "radius": max(0, int(radius))}


def _inside_spawn(plugin, x: float, z: float, dim_key: str) -> bool:
    cfg = _spawn_cfg_for_dim(plugin, dim_key)
    center = cfg["center"]
    r = cfg["radius"]
    if not center or r <= 0:
        return False
    cx, _cy, cz = center
    return dist2d(float(x), float(z), float(cx), float(cz)) <= float(r)


# ── NEW: spawn_config / spawn_cfg_2d used by Protection ─────────────────────
def spawn_config(plugin, dim_key: str) -> Tuple[int, int, int, str]:
    """
    Unified spawn config for a dimension.

    Returns (sx, sz, radius, label), where:
      • sx, sz: center X/Z (int)
      • radius: protection radius (int)
      • label: human name ("Overworld Spawn", "Nether Spawn", "The End Spawn")
    """
    dk = normalize_dim_key(dim_key)
    labels = {
        "overworld": "Overworld Spawn",
        "nether": "Nether Spawn",
        "end": "The End Spawn",
    }
    cfg = _spawn_cfg_for_dim(plugin, dk)
    center = cfg.get("center") or (0.0, 64.0, 0.0)
    radius = int(cfg.get("radius", 0))
    sx = int(center[0])
    sz = int(center[2])
    name = labels.get(dk, "Spawn")
    return sx, sz, radius, name


def spawn_cfg_2d(plugin, dim_key: str) -> Tuple[int, int, int]:
    """
    Convenience wrapper when only (sx, sz, radius) are needed.
    """
    sx, sz, r, _ = spawn_config(plugin, dim_key)
    return sx, sz, r


def spawn_security_flags(plugin, dim_key: str) -> Tuple[bool, bool, bool]:
    """
    Treat spawn like a "virtual base" and return:
      (allow_build, allow_interact, allow_kill_passive)

    Security flags stored as:
      spawn_security_<dim>_build
      spawn_security_<dim>_interact
      spawn_security_<dim>_kill_passive

    True = security ON = block that action → allow = not security.
    """
    s = _settings(plugin)
    dk = normalize_dim_key(dim_key)

    sec_build = bool(s.get(f"spawn_security_{dk}_build", False))
    sec_interact = bool(s.get(f"spawn_security_{dk}_interact", False))
    sec_kill = bool(s.get(f"spawn_security_{dk}_kill_passive", False))

    allow_build = not sec_build
    allow_interact = not sec_interact
    allow_kill = not sec_kill
    return allow_build, allow_interact, allow_kill


# ── FREE-BUILD AREAS (3D boxes inside spawn) ────────────────────────────────
def _spawn_free_areas_cfg(plugin) -> Dict[str, List[Tuple[int, int, int, int, int, int]]]:
    """
    Returns:
      { dim_key: [ (x1,y1,z1,x2,y2,z2), ... ], ... }

    Uses:
      settings["spawn_free_areas"] = {
        "<dim>": [ { "a":[x1,y1,z1], "b":[x2,y2,z2] }, ... ]
      }

    Also imports legacy:
      spawn_free_area_<dim> = "x1 y1 z1 x2 y2 z2" or "x1 z1 x2 z2"
    """
    s = _settings(plugin)
    out: Dict[str, List[Tuple[int, int, int, int, int, int]]] = {}

    root = s.get("spawn_free_areas", {})
    if isinstance(root, dict):
        for raw_dim, areas in root.items():
            dk = normalize_dim_key(raw_dim)
            lst: List[Tuple[int, int, int, int, int, int]] = out.setdefault(dk, [])
            if not isinstance(areas, list):
                continue
            for it in areas:
                try:
                    a = it.get("a", [])
                    b = it.get("b", [])
                    if not isinstance(a, list) or not isinstance(b, list):
                        continue
                    if len(a) < 3 or len(b) < 3:
                        continue
                    ax, ay, az = int(a[0]), int(a[1]), int(a[2])
                    bx, by, bz = int(b[0]), int(b[1]), int(b[2])
                    lst.append((ax, ay, az, bx, by, bz))
                except Exception:
                    continue

    # Legacy keys: spawn_free_area_<dim>
    for dim_hint in ("overworld", "nether", "end"):
        key = f"spawn_free_area_{dim_hint}"
        val = s.get(key)
        if not val:
            continue
        dk = normalize_dim_key(dim_hint)
        lst = out.setdefault(dk, [])
        try:
            parts = str(val).replace(",", " ").split()
            nums = [int(float(x)) for x in parts if x]
            if len(nums) >= 6:
                x1, y1, z1, x2, y2, z2 = nums[:6]
            elif len(nums) >= 4:
                x1, z1, x2, z2 = nums[:4]
                y1, y2 = -64, 320
            else:
                continue
            lst.append((x1, y1, z1, x2, y2, z2))
        except Exception:
            continue

    return out


def inside_spawn_free_area(plugin, x: int, y: int, z: int, dim_key: str) -> bool:
    """
    Returns True if (x,y,z) is inside ANY configured free-build area
    for the given dimension.
    """
    dk = normalize_dim_key(dim_key)
    cfg = _spawn_free_areas_cfg(plugin)
    areas = cfg.get(dk, [])
    if not areas:
        return False
    for ax, ay, az, bx, by, bz in areas:
        minx, maxx = sorted((ax, bx))
        miny, maxy = sorted((ay, by))
        minz, maxz = sorted((az, bz))
        if (minx <= x <= maxx) and (miny <= y <= maxy) and (minz <= z <= maxz):
            return True
    return False


def spawn_free_area_name_at(plugin, x: int, y: int, z: int, dim_key: str):
    """
    Return (area_id, area_name) for the FIRST free-build box containing (x,y,z)
    in the given dimension, or (None, None) if none.

    Uses the same settings block as inside_spawn_free_area, but keeps names:
      settings["spawn_free_areas"] = {
        "<dim>": [
          { "name": "Player Store Area", "a":[x1,y1,z1], "b":[x2,y2,z2] },
          ...
        ]
      }

    If 'name' is missing, falls back to 'Free Area #N'.
    """
    dk = normalize_dim_key(dim_key)
    s = _settings(plugin)

    root = s.get("spawn_free_areas", {}) or {}
    areas = root.get(dk, []) or []
    if not isinstance(areas, list):
        return None, None

    for idx, it in enumerate(areas):
        try:
            a = it.get("a", [])
            b = it.get("b", [])
            if not isinstance(a, list) or not isinstance(b, list):
                continue
            if len(a) < 3 or len(b) < 3:
                continue
            ax, ay, az = int(a[0]), int(a[1]), int(a[2])
            bx, by, bz = int(b[0]), int(b[1]), int(b[2])

            minx, maxx = (ax if ax <= bx else bx), (bx if bx >= ax else ax)
            miny, maxy = (ay if ay <= by else by), (by if by >= ay else ay)
            minz, maxz = (az if az <= bz else bz), (bz if bz >= az else az)

            if (minx <= x <= maxx) and (miny <= y <= y <= maxy) and (minz <= z <= maxz):
                nm = str(it.get("name", "") or "").strip()
                area_id = "%s:%d" % (dk, idx)
                area_name = nm or ("Free Area %d" % (idx + 1))
                return area_id, area_name
        except Exception:
            continue

    return None, None


# ── admin helpers ───────────────────────────────────────────────────────────
def is_admin(plugin, player_name: str) -> bool:
    if not player_name:
        return False
    try:
        name_norm = str(player_name).strip().lower()
    except Exception:
        return False

    candidates = []
    try:
        adm = getattr(plugin, "admin", None)
        if adm and getattr(adm, "data", None):
            candidates.append(adm.data.get("admins", []))
            settings_block = adm.data.get("settings", {}) or {}
            candidates.append(settings_block.get("admins", []))
    except Exception:
        pass
    try:
        d = getattr(plugin, "data", {}) or {}
        candidates.append(d.get("admins", []))
        settings_block = d.get("settings", {}) or {}
        candidates.append(settings_block.get("admins", []))
    except Exception:
        pass

    normalized = set()
    for src in candidates:
        try:
            if src is None:
                continue
            if isinstance(src, dict):
                for k in src.keys():
                    normalized.add(str(k).strip().lower())
                continue
            if isinstance(src, str):
                for p in [q.strip() for q in src.split(",") if q.strip()]:
                    normalized.add(p.lower())
                continue
            for it in src:
                if it is None:
                    continue
                normalized.add(str(it).strip().lower())
        except Exception:
            continue

    return name_norm in normalized


# ── player/claim access ─────────────────────────────────────────────────────
def _players(plugin) -> dict:
    return getattr(plugin, "data", {}).setdefault("players", {}) if hasattr(plugin, "data") else {}


# ── perf helpers: tick + version ────────────────────────────────────────────
try:
    from endstone import system as _sysmod
except Exception:
    _sysmod = None


def _cur_tick(plugin) -> int:
    for attr in ("current_tick", "tick_count", "tick"):
        try:
            sv = getattr(plugin, attr, None)
            v = sv() if callable(sv) else sv
            if isinstance(v, int) and v >= 0:
                return v
        except Exception:
            pass
    if _sysmod and hasattr(_sysmod, "current_tick"):
        try:
            return int(_sysmod.current_tick())
        except Exception:
            pass
    try:
        import time
        return int(time.time() * 20.0)
    except Exception:
        return 0


def bump_claims_version(plugin, delta: int = 1) -> None:
    try:
        v = int(getattr(plugin, "_claims_version", 0))
    except Exception:
        v = 0
    try:
        setattr(plugin, "_claims_version", v + int(delta))
    except Exception:
        pass


# ---------- Lightweight spatial index (grid) ----------

def _iter_all_claims(players_dict: dict):
    for owner, rec in (players_dict or {}).items():
        for c in ((rec or {}).get("claims", {}) or {}).values():
            if isinstance(c, dict):
                yield owner, c


def _cell_size(plugin) -> int:
    cs = get_setting_int(plugin, "lc_index_cell_size", 64)
    return max(16, min(256, cs))


def _cell_of(x: int, z: int, cell: int) -> Tuple[int, int]:
    return (x // cell, z // cell)


def _ensure_index(plugin) -> None:
    players = _players(plugin)
    want_cell = _cell_size(plugin)
    now_tick = _cur_tick(plugin)

    last_tick = getattr(plugin, "_claims_cache_tick", -1)
    if last_tick == now_tick:
        return

    cache = getattr(plugin, "_claims_cache", None)
    want_version = int(getattr(plugin, "_claims_version", 0))

    need_rebuild = True
    if isinstance(cache, dict):
        try:
            if cache.get("version") == want_version and cache.get("cell") == want_cell:
                need_rebuild = False
        except Exception:
            need_rebuild = True

    if not need_rebuild:
        setattr(plugin, "_claims_cache_tick", now_tick)
        return

    grid: Dict[Tuple[int, int], List[Tuple[str, Dict[str, Any]]]] = {}
    flat: List[Tuple[str, Dict[str, Any]]] = []
    try:
        for owner, c in _iter_all_claims(players):
            flat.append((owner, c))
            try:
                cx, cz = int(c.get("x", 0)), int(c.get("z", 0))
                r = abs(int(c.get("radius", 0)))
            except Exception:
                continue
            cell = want_cell
            min_cx, min_cz = _cell_of(cx - r, cz - r, cell)
            max_cx, max_cz = _cell_of(cx + r, cz + r, cell)
            for gx in range(min_cx, max_cx + 1):
                for gz in range(min_cz, max_cz + 1):
                    grid.setdefault((gx, gz), []).append((owner, c))
        plugin._claims_cache = {
            "version": want_version,
            "list": flat,
            "grid": grid,
            "cell": want_cell,
        }
    except Exception:
        plugin._claims_cache = {
            "version": want_version,
            "list": [],
            "grid": {},
            "cell": want_cell,
        }
    setattr(plugin, "_claims_cache_tick", now_tick)


def all_claims(plugin) -> List[Tuple[str, Dict[str, Any]]]:
    _ensure_index(plugin)
    cache = getattr(plugin, "_claims_cache", None)
    if isinstance(cache, dict) and isinstance(cache.get("list"), list):
        return cache["list"]
    out: List[Tuple[str, Dict[str, Any]]] = []
    for owner, rec in _players(plugin).items():
        for c in ((rec or {}).get("claims", {}) or {}).values():
            if isinstance(c, dict):
                out.append((owner, c))
    return out


# ── spacing/preview ─────────────────────────────────────────────────────────
def preview_status(plugin, x: int, z: int, owner_name: str, max_radius_if_claimed: int,
                   all_claims_list: List[Tuple[str, Dict[str, Any]]], admin_bypass: bool = True) -> Dict[str, Any]:
    if admin_bypass and is_admin(plugin, owner_name):
        spr = get_setting_int(plugin, "spawn_protection_radius_overworld", 0)
        return {
            "inside_spawn_protect": False,
            "too_close_spawn_rule": False,
            "too_close_names": [],
            "spr": spr,
            "d_spawn_rule": get_setting_int(plugin, "lc_min_distance_from_spawn", 300),
            "d_players_rule": get_setting_int(plugin, "lc_min_distance_between_bases", 200),
        }

    scfg = _spawn_cfg_for_dim(plugin, "overworld")  # preview used only for overworld spacing
    center = scfg["center"]
    spr = scfg["radius"]
    inside_spawn = bool(center and dist2d(x, z, center[0], center[2]) < spr)

    d_players_rule = get_setting_int(plugin, "lc_min_distance_between_bases", 200)
    d_spawn_rule = get_setting_int(plugin, "lc_min_distance_from_spawn", 300)

    too_close_spawn_rule = False
    if center:
        if dist2d(x, z, center[0], center[2]) - max_radius_if_claimed < d_spawn_rule:
            too_close_spawn_rule = True

    too_close_names: List[str] = []
    for other_owner, claim in all_claims_list:
        cx, cz = int(claim.get("x", 0)), int(claim.get("z", 0))
        cr = int(claim.get("radius", 0))
        edge_gap = dist2d(x, z, cx, cz) - (max_radius_if_claimed + cr)
        if edge_gap < d_players_rule and other_owner != owner_name:
            too_close_names.append(other_owner)

    return {
        "inside_spawn_protect": inside_spawn,
        "too_close_spawn_rule": too_close_spawn_rule,
        "too_close_names": too_close_names,
        "spr": spr,
        "d_spawn_rule": d_spawn_rule,
        "d_players_rule": d_players_rule,
    }


def full_claim_check(plugin, x: int, z: int, chosen_radius: int, owner_name: str,
                     all_claims_list: List[Tuple[str, Dict[str, Any]]], admin_bypass: bool = True) -> Dict[str, Any]:
    if admin_bypass and is_admin(plugin, owner_name):
        scfg = _spawn_cfg_for_dim(plugin, "overworld")
        spr = scfg["radius"]
        return {
            "inside_spawn_protect": False,
            "too_close_spawn_rule": False,
            "conflicts": [],
            "spr": spr,
            "d_spawn_rule": get_setting_int(plugin, "lc_min_distance_from_spawn", 300),
            "d_players_rule": get_setting_int(plugin, "lc_min_distance_between_bases", 200),
        }

    scfg = _spawn_cfg_for_dim(plugin, "overworld")
    center = scfg["center"]
    spr = scfg["radius"]
    inside_spawn = bool(center and dist2d(x, z, center[0], center[2]) < spr)

    d_players_rule = get_setting_int(plugin, "lc_min_distance_between_bases", 200)
    d_spawn_rule = get_setting_int(plugin, "lc_min_distance_from_spawn", 300)

    too_close_spawn_rule = False
    if center:
        if dist2d(x, z, center[0], center[2]) - chosen_radius < d_spawn_rule:
            too_close_spawn_rule = True

    conflicts: List[str] = []
    for other_owner, claim in all_claims_list:
        cx, cz = int(claim.get("x", 0)), int(claim.get("z", 0))
        cr = int(claim.get("radius", 0))
        edge_gap = dist2d(x, z, cx, cz) - (chosen_radius + cr)
        if edge_gap < d_players_rule and other_owner != owner_name:
            conflicts.append(other_owner)

    return {
        "inside_spawn_protect": inside_spawn,
        "too_close_spawn_rule": too_close_spawn_rule,
        "conflicts": conflicts,
        "spr": spr,
        "d_spawn_rule": d_spawn_rule,
        "d_players_rule": d_players_rule,
    }


# ── geometry ────────────────────────────────────────────────────────────────
def point_in_claim(x: int, z: int, claim: dict) -> bool:
    try:
        cx, cz, r = int(claim.get("x", 0)), int(claim.get("z", 0)), int(claim.get("radius", 0))
        return dist2d(x, z, cx, cz) <= r
    except Exception:
        return False


def claim_at(all_claims_list: List[Tuple[str, dict]], x: int, z: int) -> Tuple[Optional[str], Optional[dict]]:
    best = (None, None, 10**12)
    for owner, c in all_claims_list:
        try:
            cx, cz, r = int(c.get("x", 0)), int(c.get("z", 0)), int(c.get("radius", 0))
            d = dist2d(x, z, cx, cz)
            if d <= r and d < best[2]:
                best = (owner, c, d)
        except Exception:
            pass
    return (best[0], best[1]) if best[0] is not None else (None, None)


# Grid-accelerated + dimension-aware owner lookup
def _claim_at_with_grid(plugin, x: int, z: int, dim_key: Optional[str]) -> Tuple[Optional[str], Optional[dict]]:
    _ensure_index(plugin)
    cache = getattr(plugin, "_claims_cache", None)
    if not isinstance(cache, dict):
        return (None, None)

    cell = int(cache.get("cell", 64)) or 64
    grid = cache.get("grid") or {}
    cx, cz = _cell_of(x, z, cell)

    candidates = []
    try:
        for gx in (cx-1, cx, cx+1):
            for gz in (cz-1, cz, cz+1):
                lst = grid.get((gx, gz))
                if lst:
                    candidates.extend(lst)
    except Exception:
        pass

    dim_key = normalize_dim_key(dim_key or "overworld")
    best = (None, None, 10**12)
    for owner, c in candidates:
        try:
            if claim_dim_key(c) != dim_key:
                continue
            px, pz = int(c.get("x", 0)), int(c.get("z", 0))
            r = int(c.get("radius", 0))
            d = dist2d(x, z, px, pz)
            if d <= r and d < best[2]:
                best = (owner, c, d)
        except Exception:
            continue
    return (best[0], best[1]) if best[0] is not None else (None, None)


# ── security helpers ────────────────────────────────────────────────────────
def claim_owner_at(plugin, x: int, z: int, *, player=None, dim_key: Optional[str] = None) -> Tuple[Optional[str], Optional[dict]]:
    dk = dim_key or (player_dim_key(player) if player is not None else "overworld")
    return _claim_at_with_grid(plugin, x, z, dk)


def claim_flags(claim: Optional[dict]) -> Tuple[bool, bool, bool]:
    """
    Normalize claim flags to (allow_build, allow_interact, allow_kill_passive)
    using a single source of truth across:
      - flags.allow_* booleans
      - flags.security_* booleans
      - legacy 'security_build', 'security_interact', 'security_kill_passive'
    """
    if not isinstance(claim, dict):
        return False, False, False

    flags = claim.get("flags", {}) or {}

    # New-style explicit allow_* flags
    allow_build = bool(flags.get("allow_build", False))
    allow_interact = bool(flags.get("allow_interact", False))
    allow_kill = bool(flags.get("allow_kill_passive", False))

    # security_* flags within flags
    sec_build = bool(flags.get("security_build", flags.get("security_place_break", False)))
    sec_interact = bool(flags.get("security_interact", False))
    sec_kill = bool(flags.get("security_kill_passive", False))

    # Legacy root-level security_* keys
    for legacy_key, target in (
        ("security_build", "build"),
        ("security_place_break", "build"),
        ("security_interact", "interact"),
        ("security_kill_passive", "kill"),
    ):
        if legacy_key in claim:
            v = bool(claim.get(legacy_key, False))
            if target == "build":
                sec_build = v
            elif target == "interact":
                sec_interact = v
            elif target == "kill":
                sec_kill = v

    # If explicit allow_* aren't set, derive them from security toggles
    if "allow_build" not in flags:
        allow_build = not sec_build
    if "allow_interact" not in flags:
        allow_interact = not sec_interact
    if "allow_kill_passive" not in flags:
        allow_kill = not sec_kill

    return allow_build, allow_interact, allow_kill


def is_basemate(claim: Optional[dict], player_name: str) -> bool:
    if not isinstance(claim, dict):
        return False
    mates = claim.get("mates") or []
    pl = str(player_name).lower()
    try:
        return any(str(m).lower() == pl for m in mates)
    except Exception:
        return False


def _trusted(plugin, acting_player_name: str, owner_name: Optional[str], claim: Optional[dict]) -> bool:
    if not owner_name or not claim:
        return False
    if is_admin(plugin, acting_player_name):
        return True
    if acting_player_name == owner_name:
        return True
    if is_basemate(claim, acting_player_name):
        return True
    return False


def _spawn_security_allowed(plugin, acting_player_name: str, x: int, z: int,
                            *, dim_key: str, mode: str) -> bool:
    """
    mode: "build" | "interact" | "kill_passive"
    Returns True if action is allowed by spawn security (or security not enabled).
    """
    # Admins always bypass
    if is_admin(plugin, acting_player_name):
        return True

    if not _inside_spawn(plugin, x, z, dim_key):
        return True

    s = _settings(plugin)
    flag_key = f"spawn_security_{dim_key}_{mode}"
    enabled = bool(s.get(flag_key, False))
    if not enabled:
        return True

    # inside spawn AND security enabled AND not admin => blocked
    return False


def can_build_at(plugin, acting_player_name: str, x: int, z: int, *,
                 player=None, dim_key: Optional[str] = None) -> bool:
    dk = dim_key or (player_dim_key(player) if player is not None else "overworld")
    owner, claim = claim_owner_at(plugin, x, z, player=player, dim_key=dk)
    if claim:
        if _trusted(plugin, acting_player_name, owner, claim):
            return True
        allow_build, _, _ = claim_flags(claim)
        return allow_build

    # No claim: apply spawn security
    return _spawn_security_allowed(plugin, acting_player_name, x, z, dim_key=dk, mode="build")


def can_interact_at(plugin, acting_player_name: str, x: int, z: int, *,
                    player=None, dim_key: Optional[str] = None) -> bool:
    dk = dim_key or (player_dim_key(player) if player is not None else "overworld")
    owner, claim = claim_owner_at(plugin, x, z, player=player, dim_key=dk)
    if claim:
        if _trusted(plugin, acting_player_name, owner, claim):
            return True
        _, allow_interact, _ = claim_flags(claim)
        return allow_interact

    # No claim: apply spawn security (interact)
    return _spawn_security_allowed(plugin, acting_player_name, x, z, dim_key=dk, mode="interact")


# ── mob helpers ─────────────────────────────────────────────────────────────
_MONSTER_KEYS = {
    "monster","hostile","undead","arthropod","illager","raider",
    "zombie","husk","drowned","skeleton","stray","creeper","spider",
    "cave_spider","enderman","slime","magma_cube","blaze","guardian",
    "elder_guardian","witch","phantom","wither","warden","shulker",
    "ghast","piglin","hoglin","zoglin","piglin_brute","vindicator",
    "pillager","evoker","ravager",
}

_PASSIVE_HINTS = {
    "cow","chicken","sheep","pig","horse","donkey","mule","llama","camel",
    "mooshroom","rabbit","turtle","bee","cat","wolf","fox","sniffer",
    "villager","iron_golem","snow_golem","parrot","axolotl","salmon","cod",
}


def is_monster(entity) -> bool:
    try:
        fam = getattr(entity, "family", None) or getattr(entity, "families", None)
        if isinstance(fam, str):
            fams = {fam.lower()}
        elif isinstance(fam, (list, set, tuple)):
            fams = {str(x).lower() for x in fam}
        else:
            fams = set()
        if fams & _MONSTER_KEYS:
            return True
    except Exception:
        pass

    for attr in ("typeId","type_id","type","id","identifier","name"):
        try:
            v = getattr(entity, attr, None)
            if not v:
                continue
            s = str(v).lower()
            if any(k in s for k in _MONSTER_KEYS):
                return True
            if any(k in s for k in _PASSIVE_HINTS):
                return False
        except Exception:
            pass

    return False


def can_damage_entity_at(plugin, acting_player_name: str, entity, x: int, z: int, *,
                         player=None, dim_key: Optional[str] = None) -> bool:
    # Players and monsters are always allowed
    try:
        from endstone import Player as _Player
        if isinstance(entity, _Player):
            return True
    except Exception:
        pass
    if is_monster(entity):
        return True

    dk = dim_key or entity_dim_key(entity) or (player_dim_key(player) if player is not None else "overworld")
    owner, claim = claim_owner_at(plugin, x, z, player=player, dim_key=dk)
    if claim:
        if _trusted(plugin, acting_player_name, owner, claim):
            return True
        _, _, allow_kill_passive = claim_flags(claim)
        return allow_kill_passive

    # No claim: apply spawn security for passive mobs
    return _spawn_security_allowed(plugin, acting_player_name, x, z, dim_key=dk, mode="kill_passive")


# ─────────────────────────────────────────────────────────────────────────────
# SpawnEnforcer stub (legacy compatibility; no entity sweeping)
# ─────────────────────────────────────────────────────────────────────────────

class SpawnEnforcer:
    """
    Legacy stub kept so older code that imports/instantiates SpawnEnforcer
    does not break. All spawn entity enforcement has been removed.
    """

    def __init__(self, plugin):
        self.plugin = plugin

    def start(self):
        # No-op
        pass

    def stop(self):
        # No-op
        pass
