# src/endstone_landclaim/landclaimui.py
# Strict Endstone-friendly. No future annotations.

from typing import Dict, Any, List, Optional, Tuple
import json, math

from endstone import Player
from endstone.form import ActionForm, Label, MessageForm, ModalForm, TextInput

# Reuse the buy-land UI (Money + buttons)
try:
    from .landclaim_modify import ModifyUI          # preferred (newer filename)
except ModuleNotFoundError:
    from .landclaim_modifyui import ModifyUI        # fallback (older filename)

# Rank-aware basemate manager
from .basemangment import BaseManagement

# Use shared helpers for dimension + index bump
try:
    from .checks import (
        player_dim_key as _player_dim_key,
        normalize_dim_key as _normalize_dim_key,
        bump_claims_version as _bump_version,
    )
except Exception:
    _player_dim_key = None
    _normalize_dim_key = None

    def _bump_version(_plugin, delta: int = 1):
        try:
            cur = int(getattr(_plugin, "_claims_version", 0))
            setattr(_plugin, "_claims_version", cur + int(delta))
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Robust modal parsing (handles Endstone variants)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from endstone.form import ModalFormResponse  # some builds pass this
except Exception:
    class ModalFormResponse:  # type: ignore
        form_values: list | None = None
        response: str | None = None
        pass


def _parse_modal_values_str(s: str) -> list:
    try:
        data = json.loads(s or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _get_modal_values(resp: "ModalFormResponse | dict | str | None") -> List[Any] | None:
    if resp is None:
        return None
    if isinstance(resp, ModalFormResponse):
        if resp.form_values is not None:
            return list(resp.form_values)
        if resp.response is not None:
            return _parse_modal_values_str(resp.response)
        return None
    if isinstance(resp, dict):
        vals = resp.get("formValues") or resp.get("values") or resp.get("form_values")
        if vals is not None:
            return list(vals)
        if isinstance(resp.get("response"), str):
            return _parse_modal_values_str(resp["response"])
        return None
    if isinstance(resp, str):
        return _parse_modal_values_str(resp)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Settings helpers (prefer live Admin settings when present)
# ─────────────────────────────────────────────────────────────────────────────
def _settings(plugin) -> dict:
    out = dict(getattr(plugin, "data", {}).get("settings", {}))
    try:
        adm = getattr(plugin, "admin", None)
        if adm and getattr(adm, "data", None):
            out.update(adm.data.get("settings", adm.data) or {})
    except Exception:
        pass
    return out


def _admin_caps(plugin) -> Tuple[int, int, int, int]:
    s = _settings(plugin)
    fb = int(s.get("lc_first_base_radius_cap", 500))
    ob = int(s.get("lc_other_base_radius_cap", 250))
    buf = int(s.get("lc_min_distance_between_bases", 200))
    max_bases = int(s.get("lc_max_bases", 3))
    return fb, ob, buf, max_bases


def _currency_name(plugin) -> str:
    """Text name only (UI). Scoreboard is always 'Money'."""
    try:
        s = _settings(plugin)
        return str(s.get("currency_name", "Currency"))
    except Exception:
        return "Currency"


# ─────────────────────────────────────────────────────────────────────────────
# Dimension helpers (Bedrock-safe)
# ─────────────────────────────────────────────────────────────────────────────
def _dim_key_of_player(p: Player) -> str:
    """Normalize player's current dimension to: overworld | nether | end (Bedrock-safe)."""
    if _player_dim_key:
        try:
            return _player_dim_key(p)
        except Exception:
            pass
    # Local robust fallback
    try:
        loc = p.location
        dim = getattr(loc, "dimension", None)

        # Numeric IDs (Bedrock/BDS): 0=overworld, 1=nether, 2=end (some forks use -1 for nether)
        if isinstance(dim, int):
            if dim == 0:
                return "overworld"
            if dim in (1, -1):
                return "nether"
            if dim == 2:
                return "end"

        # Enum / object with name
        try:
            dname = str(getattr(dim, "name", "")).lower()
            if "overworld" in dname:
                return "overworld"
            if "nether" in dname:
                return "nether"
            if "the_end" in dname or dname == "end":
                return "end"
        except Exception:
            pass

        # Level name fallback
        lvl = getattr(loc, "level", None)
        lname = str(getattr(lvl, "name", "")).lower()
        if "overworld" in lname:
            return "overworld"
        if "nether" in lname:
            return "nether"
        if "the_end" in lname or lname == "end":
            return "end"
    except Exception:
        pass
    return "overworld"


def _dim_of_claim(c: Dict[str, Any]) -> str:
    """Canonicalize stored claim dim to overworld|nether|end."""
    if _normalize_dim_key:
        try:
            return _normalize_dim_key(c.get("dim", "overworld"))
        except Exception:
            pass
    try:
        d = c.get("dim", "overworld")
        if isinstance(d, int):
            if d == 0:
                return "overworld"
            if d in (1, -1):
                return "nether"
            if d == 2:
                return "end"
        d = str(d).lower()
        if d in ("the_end", "end", "2"):
            return "end"
        if d in ("nether", "1", "-1"):
            return "nether"
        if d in ("overworld", "0"):
            return "overworld"
    except Exception:
        pass
    return "overworld"


# ─────────────────────────────────────────────────────────────────────────────
# Player/Claim helpers + migrations (defaults for new fields)
# ─────────────────────────────────────────────────────────────────────────────
def _players(plugin) -> dict:
    try:
        data = getattr(plugin, "data", {})
        if isinstance(data, dict):
            return data.setdefault("players", {})
        return {}
    except Exception:
        return {}


def _all_claims(plugin) -> List[Tuple[str, str, dict]]:
    """[(owner, claim_id, claim_dict), ...]"""
    arr: List[Tuple[str, str, dict]] = []
    for owner, prec in _players(plugin).items():
        claims = ((prec or {}).get("claims", {}) or {})
        for cid, c in claims.items():
            if isinstance(c, dict):
                if "id" not in c:
                    try:
                        c["id"] = cid
                    except Exception:
                        pass
                arr.append((owner, cid, c))
    return arr


def _ensure_defaults_on_claim(c: dict, cur_buf: int):
    if "buffer_rule" not in c:
        c["buffer_rule"] = int(cur_buf)
    flags = c.setdefault("flags", {})
    flags.setdefault("allow_build", True)
    flags.setdefault("allow_interact", True)
    flags.setdefault("allow_kill_passive", True)
    c.setdefault("mates", [])  # BaseManagement can normalize list -> dict
    c.setdefault("dim", "overworld")


def _ensure_defaults_on_all(plugin):
    _, _, cur_buf, _ = _admin_caps(plugin)
    changed = False
    for owner, prec in _players(plugin).items():
        claims = prec.get("claims", {}) or {}
        for _, c in claims.items():
            before = json.dumps(c, sort_keys=True, default=str)
            _ensure_defaults_on_claim(c, cur_buf)
            if json.dumps(c, sort_keys=True, default=str) != before:
                changed = True
    if changed:
        _persist_claims(plugin, bump=True)


def _inside(c: Dict[str, Any], x: int, z: int, dim_here: str) -> bool:
    if _dim_of_claim(c) != dim_here:
        return False
    cx, cz = int(c.get("x", 0)), int(c.get("z", 0))
    r = int(c.get("radius", 0))
    dx, dz = x - cx, z - cz
    return dx * dx + dz * dz <= r * r


def _find_any_claim_at(plugin, x: int, z: int, dim_here: str) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
    """Return (owner, claim_id, claim) for whichever claim contains (x,z) in dim."""
    for owner, cid, c in _all_claims(plugin):
        if _inside(c, x, z, dim_here):
            return owner, cid, c
    return None, None, None


def _mates_rank_of(claim: dict, name: str) -> int:
    """Return 0 or 1 for this player's basemate rank inside claim."""
    mates = claim.get("mates", [])
    nm = (name or "").lower()
    try:
        if isinstance(mates, dict):
            for k, v in list(mates.items()):
                if isinstance(k, str) and k.lower() == nm:
                    try:
                        return 1 if int(v) >= 1 else 0
                    except Exception:
                        return 0
            return 0
        # legacy list -> rank 0 by default (member, not manager)
        for k in mates:
            try:
                if str(k).lower() == nm:
                    return 0
            except Exception:
                pass
        return 0
    except Exception:
        return 0


def _collect_bases_for_player(plugin, viewer_name: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Shared helper: all bases the viewer owns OR is a basemate on.
    Used by Teleporter-style community lists and the basemate-bases tab.
    """
    out: List[Tuple[str, Dict[str, Any]]] = []
    try:
        players = _players(plugin)
    except Exception:
        players = {}
    viewer_l = str(viewer_name).lower()

    for owner, rec in (players or {}).items():
        claims = (rec or {}).get("claims", {}) or {}
        for c in claims.values():
            if not isinstance(c, dict):
                continue
            # Own bases always count
            if str(owner).lower() == viewer_l:
                out.append((owner, c))
                continue
            # Basemate membership
            mates = c.get("mates", [])
            try:
                if isinstance(mates, dict):
                    keys = {str(k).lower() for k in mates.keys()}
                    if viewer_l in keys:
                        out.append((owner, c))
                        continue
                else:
                    if any(str(m).lower() == viewer_l for m in mates):
                        out.append((owner, c))
                        continue
            except Exception:
                continue
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Spawn spacing rules (dimension-aware)
# ─────────────────────────────────────────────────────────────────────────────
def _spawn_cfg(plugin, dim_key: str) -> Optional[Tuple[int, int, int]]:
    """
    Try dimension-specific spawn first:
      • worldspawn_overworld / _nether / _end
      • spawn_protection_radius_overworld / _nether / _end
    Fall back:
      • overworld -> worldspawn, spawn_protection_radius
      • others -> None (no blocking unless keys are present)
    """
    s = _settings(plugin)
    dk = (dim_key or "overworld").lower()

    # Which keys to probe for this dimension
    ws_keys: List[str] = []
    rad_keys: List[str] = []
    if dk == "overworld":
        ws_keys = ["worldspawn_overworld", "worldspawn"]
        rad_keys = ["spawn_protection_radius_overworld", "spawn_protection_radius"]
    elif dk == "nether":
        ws_keys = ["worldspawn_nether"]
        rad_keys = ["spawn_protection_radius_nether"]
    elif dk == "end":
        ws_keys = ["worldspawn_end", "worldspawn_the_end"]
        rad_keys = ["spawn_protection_radius_end", "spawn_protection_radius_the_end"]

    ws = None
    for k in ws_keys:
        v = s.get(k)
        if isinstance(v, str) and v.strip():
            ws = v.strip()
            break

    if ws is None:
        # only fallback to legacy on overworld
        if dk != "overworld":
            return None
        ws = str(s.get("worldspawn", "")).strip()
        if not ws:
            return None

    parts = ws.split()
    if len(parts) != 3:
        return None

    try:
        sx, sy, sz = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
    except Exception:
        return None

    radius = None
    for rk in rad_keys:
        try:
            rv = s.get(rk, None)
            if rv is not None:
                radius = int(float(str(rv)))
                break
        except Exception:
            continue
    if radius is None:
        # default if missing
        try:
            radius = int(float(str(s.get("spawn_protection_radius", 0))))
        except Exception:
            radius = 0

    return (sx, sz, max(0, int(radius)))


def _spawn_blocked(plugin, x: int, z: int, r: int, dim_here: str) -> bool:
    cfg = _spawn_cfg(plugin, dim_here)
    if not cfg:
        # No configured spawn for this dimension -> no block
        return False
    sx, sz, min_from_spawn = cfg
    d = math.hypot(x - sx, z - sz)
    return d < (r + min_from_spawn)


# ─────────────────────────────────────────────────────────────────────────────
# Inter-claim spacing rules
# ─────────────────────────────────────────────────────────────────────────────
def _conflicts_with_bases(
    plugin,
    owner: str,
    x: int,
    z: int,
    r: int,
    dim_here: str,
    ignore_same_center: Optional[Tuple[int, int]] = None,
) -> List[Dict[str, Any]]:
    _, _, cur_buf, _ = _admin_caps(plugin)
    offenders: List[Dict[str, Any]] = []
    for other_owner, _cid, c in _all_claims(plugin):
        try:
            cdim = _dim_of_claim(c)
            if cdim != dim_here:
                continue
            cx, cz = int(c.get("x", 0)), int(c.get("z", 0))
            if ignore_same_center and (cx, cz) == ignore_same_center:
                continue
            r_other = int(c.get("radius", 0))
            other_buf = int(c.get("buffer_rule", cur_buf))
        except Exception:
            continue
        d = math.hypot(x - cx, z - cz)
        needed = r + r_other + max(cur_buf, other_buf)
        if d < needed and other_owner != owner:
            offenders.append({"owner": other_owner, "cx": cx, "cz": cz, "dim": cdim})
    # dedupe
    seen = set()
    out = []
    for info in offenders:
        key = (info["owner"], info["cx"], info["cz"], info["dim"])
        if key not in seen:
            out.append(info)
            seen.add(key)
    return out


def _compute_new_claim_cap(plugin, owner: str, x: int, z: int, admin_cap: int, dim_here: str) -> int:
    """
    Used only when creating a NEW base.

    Here we *do* respect spacing rules so a brand new base can't be
    created overlapping someone else.
    """
    best = 0
    r = 50
    while r <= admin_cap:
        if _spawn_blocked(plugin, x, z, r, dim_here):
            return 0
        if _conflicts_with_bases(plugin, owner, x, z, r, dim_here):
            break
        best = r
        r += 50
    return best


def _max_radius_for_existing_claim(
    plugin,
    owner: str,
    claim: Dict[str, Any],
    rules_cap: int,
) -> int:
    """
    For an EXISTING base: walk upwards in +50 steps and find the
    maximum radius allowed here, respecting:

      - rules_cap
      - spawn spacing
      - distance to other bases (ignoring this base's own center)
    """
    try:
        x = int(claim.get("x", 0))
        z = int(claim.get("z", 0))
        dim_here = _dim_of_claim(claim)
        cur_r = int(claim.get("radius", 0))
    except Exception:
        return int(claim.get("radius", 0) or 0)

    best = cur_r
    step = 50

    while True:
        cand = best + step
        if cand > rules_cap:
            break
        if _spawn_blocked(plugin, x, z, cand, dim_here):
            break
        offenders = _conflicts_with_bases(
            plugin,
            owner,
            x,
            z,
            cand,
            dim_here,
            ignore_same_center=(x, z),
        )
        if offenders:
            break
        best = cand

    return best


# ─────────────────────────────────────────────────────────────────────────────
# Persistence helper (centralizes bump + save)
# ─────────────────────────────────────────────────────────────────────────────
def _persist_claims(plugin, bump: bool = True):
    if bump:
        _bump_version(plugin, 1)
    # Prefer the plugin's own saver if available
    for meth in ("_save_claims", "save_players", "_save_players", "save_config"):
        fn = getattr(plugin, meth, None)
        if callable(fn):
            try:
                fn()
                return
            except Exception:
                pass
    # Last-resort write — try to persist at least players block
    try:
        data = getattr(plugin, "data", {})
        players = data.get("players", {})
        base = getattr(plugin, "data_folder", None) or getattr(plugin, "data_path", None)
        if base:
            import os

            os.makedirs(base, exist_ok=True)
            with open(os.path.join(base, "claims.json"), "w", encoding="utf-8") as f:
                json.dump({"players": players}, f, indent=2)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────────────
class LandClaimUI:
    def __init__(self, plugin):
        self.plugin = plugin
        self._modify_ui = ModifyUI(plugin)
        self._bm = BaseManagement(plugin)  # rank-aware basemate manager

    # ---------- Teleporter shortcuts ----------
    def _tp_spawn_shortcut(self, p: Player):
        tp = getattr(self.plugin, "teleporter", None)
        if not tp:
            try:
                p.send_message("§cTeleporter system not available.")
            except Exception:
                pass
            return
        cost = tp._num_setting("economy_tpSpawnCost", 0)
        tp._confirm_tp_spawn(p, cost)

    def _tp_request_shortcut(self, p: Player):
        tp = getattr(self.plugin, "teleporter", None)
        if not tp:
            try:
                p.send_message("§cTeleporter system not available.")
            except Exception:
                pass
            return
        cost = tp._num_setting("economy_tpPlayerCost", 0)
        tp._tp_to_player_menu(p, cost)

    def _tp_accept_shortcut(self, p: Player):
        tp = getattr(self.plugin, "teleporter", None)
        if not tp:
            try:
                p.send_message("§cTeleporter system not available.")
            except Exception:
                pass
            return
        cost = tp._num_setting("economy_tpPlayerCost", 0)
        tp._handle_requests(p, cost)

    # Basemate bases (new tab) ----------
    def _basemate_bases(self, p: Player):
        """
        Lists all bases where this player is a basemate (but not the owner),
        and teleports using the Community TP cost from TeleporterUI.
        """
        viewer = getattr(p, "name", "")
        if not viewer:
            return

        tp = getattr(self.plugin, "teleporter", None)
        if not tp:
            try:
                p.send_message("§cTeleporter system not available.")
            except Exception:
                pass
            return

        # Reuse shared collector but filter out own bases
        all_pairs = _collect_bases_for_player(self.plugin, viewer)
        viewer_l = viewer.lower()
        pairs: List[Tuple[str, Dict[str, Any]]] = [
            (owner, base)
            for (owner, base) in all_pairs
            if str(owner).lower() != viewer_l
        ]

        if not pairs:
            try:
                p.send_message("§7You are not a basemate on any bases.")
            except Exception:
                pass
            return

        # Pricing: use community cost + currency name
        try:
            cost_comm = tp._num_setting("economy_tpCommunityCost", 1)
        except Exception:
            cost_comm = 1
        cur_name = _currency_name(self.plugin)

        # Sort by owner then base name
        def _key(row):
            owner, base = row
            nm = str(base.get("name") or base.get("id") or "base")
            return (str(owner).lower(), nm.lower())

        pairs.sort(key=_key)

        lines = [
            "§lBasemate Bases",
            "",
            "§7These are bases you have been added to as a basemate.",
            f"§7Teleporting to any of these costs §e{cost_comm} {cur_name}§7.",
            "",
        ]
        f = ActionForm(title="§lBasemate Bases", content="\n".join(lines))

        order: List[Tuple[str, Dict[str, Any]]] = []
        for owner, base in pairs:
            nm = str(base.get("name") or base.get("id") or "base")
            dk = str(base.get("dim", "overworld"))
            x, y, z = int(base.get("x", 0)), int(base.get("y", 64)), int(base.get("z", 0))
            f.add_button(f"{owner}'s base: {nm} §7({x},{y},{z}) §8[{dk}]")
            order.append((owner, base))
        f.add_button("Back")

        def pick(pl: Player, idx: Optional[int]):
            if idx is None or idx < 0:
                return self.open_main(pl)
            if idx >= len(order):
                return self.open_main(pl)
            owner, base = order[idx]
            # Reuse TeleporterUI flow so it handles charge + teleport
            try:
                tp._confirm_community_tp(pl, owner, base, cost_comm)
            except Exception:
                try:
                    pl.send_message("§cTeleport failed (teleporter error).")
                except Exception:
                    pass

        f.on_submit = pick
        p.send_form(f)

    # Helper: try several method names so we work with your BaseManagement version
    def _open_mate_manager(self, p: Player, owner: str, claim_key: str, back_fn):
        bm = self._bm
        # Try explicit mate methods first
        for name in (
            "open_manage_as_mate",
            "open_manage_for_mate",
            "open_manage_for_claim_as_mate",
            "open_manage_for_claim_mate",
        ):
            fn = getattr(bm, name, None)
            if callable(fn):
                try:
                    return fn(p, owner=owner, claim_key=claim_key, back_fn=back_fn)
                except TypeError:
                    try:
                        return fn(p, owner, claim_key, back_fn)
                    except Exception:
                        pass
        # Fallback: maybe open_manage_for_claim supports as_mate flag
        fn = getattr(bm, "open_manage_for_claim", None)
        if callable(fn):
            try:
                return fn(p, owner=owner, claim_key=claim_key, back_fn=back_fn, as_mate=True)
            except TypeError:
                try:
                    return fn(p, owner, claim_key, back_fn)
                except Exception:
                    pass
        try:
            p.send_message("§cBasemate manager is not available on this build.")
        except Exception:
            pass

    # ---------- entry ----------
    def open_main(self, p: Player):
        _ensure_defaults_on_all(self.plugin)

        players = _players(self.plugin)
        pdata = players.setdefault(p.name, {})
        claims: Dict[str, Any] = dict(pdata.get("claims") or {})
        fb_cap, ob_cap, _buf, max_bases = _admin_caps(self.plugin)

        x, z = int(p.location.x), int(p.location.z)
        dim_here = _dim_key_of_player(p)

        # Own-claim detection
        inside_claim_id: Optional[str] = None
        inside_claim_obj: Optional[Dict[str, Any]] = None
        for cid, c in claims.items():
            if _inside(c, x, z, dim_here):
                inside_claim_id, inside_claim_obj = cid, c
                break

        # Any-claim detection (for basemate manager)
        any_owner, any_cid, any_claim = _find_any_claim_at(self.plugin, x, z, dim_here)
        is_foreign_here = bool(any_owner and any_owner != p.name)
        basemate_rank_here = 0
        if is_foreign_here and any_claim:
            basemate_rank_here = _mates_rank_of(any_claim, p.name)

        at_limit = len(claims) >= max_bases
        is_first = len(claims) == 0
        admin_cap = fb_cap if is_first else ob_cap

        body_lines: List[str] = []
        r_test = 50

        show_new_here: bool
        if inside_claim_obj:
            name = inside_claim_obj.get("name", inside_claim_id)
            cx, cz = int(inside_claim_obj.get("x", 0)), int(inside_claim_obj.get("z", 0))
            body_lines.append("§aYou are inside your base:")
            body_lines.append(f"§b• {name} §7(@ {cx}, {cz}, dim={_dim_of_claim(inside_claim_obj)})")
            show_new_here = False
        else:
            if is_foreign_here and any_claim:
                onm = any_claim.get("name", any_cid)
                body_lines.append(f"§7You are inside base: §e{onm} §7(Owner: §b{any_owner}§7).")
                if basemate_rank_here >= 1:
                    body_lines.append("§aYou have basemate manager privileges here.")
                show_new_here = False
            elif at_limit:
                show_new_here = False
                body_lines.append("§cYou are at your max bases allowed.")
                body_lines.append("§7Remove a base to add another.")
            elif _spawn_blocked(self.plugin, x, z, r_test, dim_here):
                show_new_here = False
                body_lines.append("§cThis location is inside §eSpawn Protection§c for this dimension.")
            else:
                offenders = _conflicts_with_bases(self.plugin, p.name, x, z, r_test, dim_here)
                if offenders:
                    show_new_here = False
                    body_lines.append("§cThis location is NOT claimable:")
                    for info in offenders[:6]:
                        who = info["owner"]
                        cx = info["cx"]
                        cz = info["cz"]
                        dm = info["dim"]
                        body_lines.append(
                            f"§7- Too close to base of: §e{who} §7at §b({cx}, {cz}) §7in §e{dm}"
                        )
                else:
                    show_new_here = True
                    body_lines.append("§aThis location is claimable.")

        if claims:
            body_lines.append("")
            body_lines.append("§eYour bases:")
            for cid, c in claims.items():
                name = c.get("name", cid)
                r = int(c.get("radius", 100))
                dm = _dim_of_claim(c)
                body_lines.append(f"§b• {name} §7(r={r}, dim={dm})")
        else:
            body_lines.append("")
            body_lines.append("§7You have no bases yet.")

        # Teleporter section hint
        tp = getattr(self.plugin, "teleporter", None)
        if tp:
            pending = getattr(tp, "_requests", {}).get(getattr(p, "name", ""), None)
            body_lines.append("")
            body_lines.append("§8Teleport shortcuts:")
            if pending:
                body_lines.append(f"§7• Pending TP request from §e{pending}")
            body_lines.append("§7• Use 'Basemate bases' to TP to bases you’re added on.")

        f = ActionForm(title="§lLand Claim", content="\n".join(body_lines))

        # Build buttons
        buttons: List[Tuple[str, str]] = []  # (label, action)

        if not inside_claim_obj and show_new_here:
            buttons += [
                ("New base here", "new_here"),
                ("My bases", "my_bases"),
                ("Basemate bases", "mate_bases"),
            ]
        else:
            buttons += [
                ("My bases", "my_bases"),
                ("Basemate bases", "mate_bases"),
            ]

        # Basemate manager entry when inside a foreign base with rank=1
        if is_foreign_here and basemate_rank_here >= 1 and any_owner and any_cid:
            buttons.insert(1, ("Manage basemates (this base)", "mate_manage_here"))

        # Teleporter shortcuts
        buttons += [
            ("TP to Spawn", "tp_spawn"),
            ("TP to Player (request)", "tp_request"),
            ("Accept TP Request", "tp_accept"),
            ("Close", "close"),
        ]

        for label, _ in buttons:
            f.add_button(label)

        def pick(pl, idx):
            if idx is None or idx < 0 or idx >= len(buttons):
                return
            action = buttons[idx][1]
            if action == "new_here":
                return self._new_base_flow(pl)
            if action == "my_bases":
                return self._my_bases(pl)
            if action == "mate_bases":
                return self._basemate_bases(pl)
            if action == "tp_spawn":
                return self._tp_spawn_shortcut(pl)
            if action == "tp_request":
                return self._tp_request_shortcut(pl)
            if action == "tp_accept":
                return self._tp_accept_shortcut(pl)
            if action == "mate_manage_here":

                def back_fn(pp: Player):
                    return self.open_main(pp)

                return self._open_mate_manager(pl, any_owner, any_cid, back_fn=back_fn)
            return  # close

        f.on_submit = pick
        p.send_form(f)

    # ---------- my bases ----------
    def _my_bases(self, p: Player):
        claims: Dict[str, Any] = dict(_players(self.plugin).setdefault(p.name, {}).get("claims") or {})
        if not claims:
            p.send_message("§7You have no bases.")
            return
        ids = list(claims.keys())
        f = ActionForm(title="§lMy Bases", content="Pick a base to manage.\n")
        for cid in ids:
            c = claims[cid]
            name = c.get("name", cid)
            r = int(c.get("radius", 100))
            dm = _dim_of_claim(c)
            f.add_button(f"{name} §7(r={r}, dim={dm})")

        def pick(pl, idx):
            if idx is None or idx < 0 or idx >= len(ids):
                return
            cid = ids[idx]
            # refetch claim to ensure latest
            claim = _players(self.plugin).get(pl.name, {}).get("claims", {}).get(cid, {})
            return self._base_menu(pl, cid, claim)

        f.on_submit = pick
        p.send_form(f)

    # ---------- single base menu ----------
    def _base_menu(self, p: Player, claim_id: str, claim: Dict[str, Any]):
        fb_cap, ob_cap, _buf, _max_bases = _admin_caps(self.plugin)
        claims_of_player = _players(self.plugin).get(p.name, {}).get("claims", {}) or {}
        is_first_base = len(claims_of_player) <= 1
        rules_cap = fb_cap if is_first_base else ob_cap

        _ensure_defaults_on_claim(claim, _buf)

        name = claim.get("name", claim_id)
        r = int(claim.get("radius", 100))
        br = int(claim.get("buffer_rule", _buf))
        dm = _dim_of_claim(claim)

        # NEW: actual max radius available here, respecting spacing
        eff_cap = _max_radius_for_existing_claim(self.plugin, p.name, claim, rules_cap)

        body = (
            f"§e{name}\n"
            f"§7Center: §b{int(claim.get('x',0))}, {int(claim.get('z',0))}\n"
            f"§7Radius: §b{r}\n"
            f"§7Buffer between bases (at placement): §b{br}\n"
            f"§7Dimension: §b{dm}\n"
            f"§7Max radius available here: §b{eff_cap}\n"
        )

        # --- Teleport button label uses Community TP price + currency name ---
        tp = getattr(self.plugin, "teleporter", None)
        tp_cost = 0
        cur_name = _currency_name(self.plugin)
        if tp:
            try:
                tp_cost = tp._num_setting("economy_tpCommunityCost", 1)
            except Exception:
                tp_cost = 1
            if tp_cost <= 0:
                tp_label = "Teleport (FREE)"
            else:
                tp_label = f"Teleport ({tp_cost} {cur_name})"
        else:
            tp_label = "Teleport (FREE)"

        f = ActionForm(title="§lManage Base", content=body)
        f.add_button(tp_label)            # 0
        f.add_button("Rename")           # 1
        f.add_button("Modify land size") # 2
        f.add_button("Security settings")# 3
        f.add_button("Manage basemates") # 4  # owner flow
        f.add_button("Delete base")      # 5
        f.add_button("Back")             # 6

        def back_to_menu(pp: Player):
            fresh = _players(self.plugin).get(pp.name, {}).get("claims", {}).get(claim_id, claim)
            return self._base_menu(pp, claim_id, fresh)

        def pick(pl, idx):
            if idx == 0:
                # --- Teleport using the same Community TP price / charge flow ---
                tp = getattr(self.plugin, "teleporter", None)
                if tp:
                    try:
                        if tp_cost > 0:
                            # Reuse TeleporterUI confirmation + payment
                            tp._confirm_community_tp(pl, pl.name, claim, tp_cost)
                            return
                        # Free: just teleport directly
                        tp._teleport_to_claim(pl, claim)
                        pl.send_message(f"§aTeleported to base §e{claim.get('name', claim_id)}§a.")
                        return
                    except Exception:
                        pass

                # Fallback: raw /tp if Teleporter system is missing
                c = claim
                x = int(c.get("x", pl.location.x))
                y = int(c.get("y", pl.location.y))
                z = int(c.get("z", pl.location.z))
                try:
                    pl.perform_command(f"tp {x} {y} {z}")
                    pl.send_message(f"§aTeleported to base §e{c.get('name', claim_id)}§a.")
                except Exception:
                    pl.send_message("§cTeleport failed.")
                return

            if idx == 1:
                return self._rename(pl, claim_id, claim)
            if idx == 2:
                # Pass rules cap into ModifyUI; ModifyUI will clamp by spacing.
                return self._modify_ui.open(
                    pl,
                    claim_id,
                    claim,
                    rules_cap,
                    self._save_claims,
                    self.open_main,
                )
            if idx == 3:
                return self._security(pl, claim_id, claim)
            if idx == 4:
                # Owner management path
                return self._bm.open_manage_for_claim(pl, owner=pl.name, claim_key=claim_id, back_fn=back_to_menu)
            if idx == 5:
                return self._delete_base(pl, claim_id, claim)
            return self._my_bases(pl)

        f.on_submit = pick
        p.send_form(f)

    # ---------- security ----------
    def _security(self, p: Player, claim_id: str, claim: Dict[str, Any]):
        # Read current state via normalized resolver, then derive security booleans
        _, _, _buf, _ = _admin_caps(self.plugin)
        flags = claim.setdefault("flags", {})
        from .checks import claim_flags  # normalized: returns allow_* booleans

        allow_build, allow_interact, allow_kill = claim_flags(claim)

        # We expose “Security (ON = blocked)” → security = not allow
        sec_build = not allow_build
        sec_interact = not allow_interact
        sec_kill = not allow_kill

        def onoff(v: bool) -> str:
            return "§aON§r" if v else "§cOFF§r"

        body = [
            "§lSecurity (ON = random players BLOCKED)",
            f"§7Break/place: {onoff(sec_build)}",
            f"§7Interact:    {onoff(sec_interact)}",
            f"§7Kill passive: {onoff(sec_kill)}",
            "",
            "§8(Admins and basemates always bypass.)",
        ]
        f = ActionForm(title="§lSecurity", content="\n".join(body))
        f.add_button("Toggle break/place")  # 0
        f.add_button("Toggle interact")  # 1
        f.add_button("Toggle kill passive")  # 2
        f.add_button("Back")  # 3

        def _apply(sec_b=None, sec_i=None, sec_k=None):
            # Write BOTH styles so all runtimes stay in sync
            if sec_b is not None:
                flags["security_build"] = bool(sec_b)
                flags["allow_build"] = not bool(sec_b)
            if sec_i is not None:
                flags["security_interact"] = bool(sec_i)
                flags["allow_interact"] = not bool(sec_i)
            if sec_k is not None:
                flags["security_kill_passive"] = bool(sec_k)
                flags["allow_kill_passive"] = not bool(sec_k)
            self._save_claims()  # bumps version + persists

        def pick(pl, idx):
            nonlocal sec_build, sec_interact, sec_kill
            if idx == 0:
                sec_build = not sec_build
                _apply(sec_b=sec_build)
                try:
                    pl.send_message(f"§aBreak/place security is now {'ON' if sec_build else 'OFF'}.")
                except Exception:
                    pass
                return self._security(pl, claim_id, claim)
            if idx == 1:
                sec_interact = not sec_interact
                _apply(sec_i=sec_interact)
                try:
                    pl.send_message(f"§aInteract security is now {'ON' if sec_interact else 'OFF'}.")
                except Exception:
                    pass
                return self._security(pl, claim_id, claim)
            if idx == 2:
                sec_kill = not sec_kill
                _apply(sec_k=sec_kill)
                try:
                    pl.send_message(f"§aKill-passive security is now {'ON' if sec_kill else 'OFF'}.")
                except Exception:
                    pass
                return self._security(pl, claim_id, claim)
            return self._base_menu(pl, claim_id, claim)

        f.on_submit = pick
        p.send_form(f)

    # ---------- rename / delete ----------
    def _rename(self, p: Player, claim_id: str, claim: Dict[str, Any]):
        f = ModalForm(title="Rename Base", submit_button="Save")
        f.add_control(TextInput("New name", placeholder=claim_id, default_value=claim.get("name", "")))

        def on_submit(pl, data):
            vals = _get_modal_values(data)
            if not vals:
                return self._base_menu(pl, claim_id, claim)
            name = str(vals[-1] or "").strip()[:32] or claim_id
            claim["name"] = name
            self._save_claims()
            pl.send_message(f"§aRenamed to §e{name}")
            return self._base_menu(pl, claim_id, claim)

        f.on_submit = on_submit
        p.send_form(f)

    def _delete_base(self, p: Player, claim_id: str, claim: Dict[str, Any]):
        m = MessageForm(
            title="Delete Base",
            content=f"Delete §e{claim.get('name', claim_id)}§r? This cannot be undone.",
            button1="Delete",
            button2="Cancel",
        )

        def on_submit(pl, idx):
            if idx == 0:
                rec = _players(self.plugin).setdefault(pl.name, {})
                claims = rec.setdefault("claims", {})
                if claim_id in claims:
                    del claims[claim_id]
                    self._save_claims()
                    pl.send_message("§aBase deleted.")
                return self.open_main(pl)
            return self._base_menu(pl, claim_id, claim)

        m.on_submit = on_submit
        p.send_form(m)

    # ---------- new base flow ----------
    def _new_base_flow(self, p: Player):
        fb_cap, ob_cap, cur_buf, max_bases = _admin_caps(self.plugin)
        rec = _players(self.plugin).setdefault(p.name, {})
        claims_of_player = rec.get("claims", {}) or {}
        if len(claims_of_player) >= max_bases:
            p.send_message("§cYou are at your max bases allowed. Remove a base to add another.")
            return self.open_main(p)

        admin_cap = fb_cap if len(claims_of_player) == 0 else ob_cap
        x, z = int(p.location.x), int(p.location.z)
        dim_here = _dim_key_of_player(p)
        cap = _compute_new_claim_cap(self.plugin, p.name, x, z, admin_cap, dim_here)
        return self._prompt_radius(p, x, z, cap, cur_buf, dim_here)

    def _prompt_radius(self, p: Player, x: int, z: int, max_r: int, buffer_to_stamp: int, dim_here: str):
        if max_r <= 0:
            p.send_message("§cYou cannot claim at this location.")
            return self.open_main(p)

        free_cap_text = min(500, int(max_r))
        f = ModalForm(title="Claim Radius", submit_button="Save")
        f.add_control(
            Label(
                f"Enter radius (1..{max_r}) — first claim is free (≤ {free_cap_text}).\n§7Dimension: §e{dim_here}"
            )
        )
        f.add_control(TextInput("Blocks", placeholder=str(max_r), default_value=str(max_r)))

        def on_submit(pl, data):
            vals = _get_modal_values(data)
            if not vals:
                return self.open_main(pl)
            raw = str(vals[-1]).strip()
            try:
                r = max(1, min(int(float(raw)), int(max_r)))
            except Exception:
                m = MessageForm(
                    title="Invalid number",
                    content="Please enter a number like 200.",
                    button1="OK",
                    button2="Back",
                )
                m.on_submit = lambda _pl, _i: self._prompt_radius(_pl, x, z, max_r, buffer_to_stamp, dim_here)
                return pl.send_form(m)

            if _spawn_blocked(self.plugin, x, z, r, dim_here):
                pl.send_message("§cCannot create: §7too close to spawn for this dimension.")
                return self.open_main(pl)
            offenders = _conflicts_with_bases(self.plugin, pl.name, x, z, r, dim_here)
            if offenders:
                detail = ", ".join(
                    [f"{i['owner']} @ ({i['cx']},{i['cz']}) in {i['dim']}" for i in offenders[:4]]
                )
                pl.send_message("§cCannot create: §7too close to other base(s): §e" + detail)
                return self.open_main(pl)

            rec = _players(self.plugin).setdefault(pl.name, {})
            claims = rec.setdefault("claims", {})
            base_num = 1
            while f"base_{base_num}" in claims:
                base_num += 1
            cid = f"base_{base_num}"
            claims[cid] = {
                "id": cid,
                "name": cid,
                "x": int(x),
                "y": int(p.location.y),
                "z": int(z),
                "radius": int(r),
                "buffer_rule": int(buffer_to_stamp),
                "flags": {
                    "security_build": True,
                    "security_interact": True,
                    "security_kill_passive": True,
                    "allow_build": False,
                    "allow_interact": False,
                    "allow_kill_passive": False,
                },
                "mates": [],  # BaseManagement will normalize if needed
                "dim": dim_here,
            }
            self._save_claims()
            try:
                pl.send_popup(f"§aBase created with radius §e{r} §7(dim={dim_here})")
            except Exception:
                pass
            return self.open_main(pl)

        f.on_submit = on_submit
        p.send_form(f)

    # ---------- persistence ----------
    def _save_claims(self):
        _persist_claims(self.plugin, bump=True)
