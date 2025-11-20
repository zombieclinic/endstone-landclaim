# src/endstone_landclaim/basemangment.py
# Strict Endstone-friendly. No future annotations.

from typing import Dict, Any, List, Optional, Callable
import json

from endstone.form import ActionForm, ModalForm, Label, TextInput, MessageForm
from endstone import Player
from endstone.level import Location  # correct import for native teleport


# ─────────────────────────────────────────────────────────────────────────────
# Modal parsing helpers (handle Endstone variants consistently)
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

def _get_modal_values(resp: ModalFormResponse | dict | str | None) -> list | None:
    if resp is None:
        return None
    if isinstance(resp, ModalFormResponse):
        if resp.form_values is not None: return resp.form_values
        if resp.response is not None:    return _parse_modal_values_str(resp.response)
        return None
    if isinstance(resp, dict):
        vals = resp.get("formValues") or resp.get("values") or resp.get("form_values")
        if vals is not None: return vals
        if isinstance(resp.get("response"), str):
            return _parse_modal_values_str(resp["response"])
        return None
    if isinstance(resp, str):
        return _parse_modal_values_str(resp)
    return None

def _read_last_text(resp) -> str:
    """Return the last modal field as plain text (robust to variants)."""
    vals = _get_modal_values(resp) or []
    v = vals[-1] if vals else ""
    # common cases are already string; some forks wrap in list etc.
    if isinstance(v, str):
        return v.strip()
    try:
        if isinstance(v, list) and v and isinstance(v[0], str):
            return v[0].strip()
    except Exception:
        pass
    try:
        return str(v).strip()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# dimension helpers
# ─────────────────────────────────────────────────────────────────────────────
def _norm_dim_key(raw: str) -> str:
    s = (raw or "").strip().lower()
    if "nether" in s or "hell" in s:
        return "nether"
    if "end" in s:
        return "the_end"
    return "overworld"

def _resolve_dimension(plugin, desired_key: str, fallback_from_player: Optional[Player] = None):
    key = _norm_dim_key(desired_key)

    level_names = {
        "overworld": ("overworld", "world", "Overworld"),
        "nether": ("nether", "the_nether", "Nether"),
        "the_end": ("the_end", "end", "TheEnd", "End"),
    }.get(key, (key,))

    srv = getattr(plugin, "server", None)
    if srv:
        # Try server.get_level(name)
        for lname in level_names:
            try:
                get_level = getattr(srv, "get_level", None) or getattr(srv, "getLevel", None)
                level = get_level(lname) if callable(get_level) else None
                if level:
                    dim = getattr(level, "dimension", level)
                    if dim:
                        return dim
            except Exception:
                pass

        # Try server.get_dimension(name/id)
        for probe in (key, {"overworld": 0, "nether": -1, "the_end": 1}.get(key, 0)):
            try:
                for meth in ("get_dimension", "getDimension", "dimension_by_id", "get_dimension_by_id"):
                    fn = getattr(srv, meth, None)
                    if callable(fn):
                        dim = fn(probe)
                        if dim:
                            return dim
            except Exception:
                pass

    # Numeric fallback
    try:
        id_map = {"overworld": 0, "nether": -1, "the_end": 1}
        return id_map.get(key, 0)
    except Exception:
        pass

    # Player's current dimension as last resort
    try:
        if fallback_from_player:
            return getattr(fallback_from_player.location, "dimension", None)
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# storage helpers
# ─────────────────────────────────────────────────────────────────────────────
def _players_root(plugin) -> Dict[str, Any]:
    return (plugin.data or {}).setdefault("players", {})

def _claims_map(plugin, owner: str) -> Dict[str, Any]:
    return _players_root(plugin).setdefault(owner, {}).setdefault("claims", {})

def _get_claim(plugin, owner: str, claim_key: str) -> Optional[Dict[str, Any]]:
    try:
        return _claims_map(plugin, owner).get(claim_key)
    except Exception:
        return None

def _save(plugin) -> None:
    try:
        plugin._save_claims()
    except Exception:
        try:
            plugin.write_json("claims.json", {"players": plugin.data.get("players", {})})
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# mates <list|dict> ⇄ dict{name: rank} normalization
# ─────────────────────────────────────────────────────────────────────────────
def _mates_to_dict(claim: Dict[str, Any]) -> Dict[str, int]:
    """
    Normalize claim['mates'] to a dict of {name: rank_int}.
    Rank: 0=member, 1=manager
    """
    cur = claim.get("mates")
    out: Dict[str, int] = {}
    if isinstance(cur, dict):
        for k, v in list(cur.items()):
            try:
                nm = str(k).strip()
                if not nm: continue
                out[nm] = 1 if int(v) >= 1 else 0
            except Exception:
                pass
    elif isinstance(cur, (list, tuple, set)):
        for n in cur:
            try:
                nm = str(n).strip()
                if nm: out[nm] = 0
            except Exception:
                pass
    claim["mates"] = out
    return out

def _mates_list(claim: Dict[str, Any]) -> List[str]:
    return sorted(_mates_to_dict(claim).keys(), key=str.lower)

def _rank_of(claim: Dict[str, Any], name: str) -> int:
    return _mates_to_dict(claim).get(str(name), 0)

def _set_rank(claim: Dict[str, Any], name: str, rank: int) -> None:
    m = _mates_to_dict(claim)
    m[str(name)] = 1 if int(rank) >= 1 else 0

def _add_mate(claim: Dict[str, Any], name: str, rank: int = 0) -> bool:
    name = str(name).strip()
    if not name:
        return False
    m = _mates_to_dict(claim)
    if name in m:
        return False
    m[name] = 1 if int(rank) >= 1 else 0
    return True

def _remove_mate(claim: Dict[str, Any], name: str) -> bool:
    m = _mates_to_dict(claim)
    return m.pop(str(name), None) is not None


# ─────────────────────────────────────────────────────────────────────────────
# online players (robust across forks)
# ─────────────────────────────────────────────────────────────────────────────
def _online_names(plugin) -> List[str]:
    srv = getattr(plugin, "server", None)
    names: List[str] = []
    if not srv:
        return names

    candidates = [
        ("get_online_players", True),
        ("get_players", True),
        ("getOnlinePlayers", True),
        ("getPlayers", True),
        ("online_players", False),
        ("players", False),
    ]
    for attr, is_callable in candidates:
        try:
            obj = getattr(srv, attr, None)
            if obj is None:
                continue
            players = obj() if is_callable and callable(obj) else obj
            it = []
            if isinstance(players, dict):
                it = list(players.values())
            elif isinstance(players, (list, tuple, set)):
                it = list(players)
            elif players is not None:
                it = list(players)  # attempt iteration
            for p in it:
                nm = getattr(p, "name", None)
                if nm is None and hasattr(p, "get_name") and callable(getattr(p, "get_name")):
                    nm = p.get_name()
                if nm:
                    s = str(nm).strip()
                    if s and s not in names:
                        names.append(s)
        except Exception:
            continue
    return names


# ─────────────────────────────────────────────────────────────────────────────
# main UI class
# ─────────────────────────────────────────────────────────────────────────────
class BaseManagement:
    """
    Multi-base management UI with rank-aware basemate management.

    Data:
      plugin.data["players"][owner]["claims"][claim_id] = {
          "id": str, "name": str, "x": int, "y": int, "z": int, "radius": int,
          "dim": "overworld"|"nether"|"the_end",
          "mates": dict[str, int],   # rank: 0|1  (legacy list auto-upgraded)
          "flags": {...}
      }
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self._back: Callable[[Player], None] = lambda p: None

    # Exposed to LandClaimUI to decide if a viewer should see Manage button
    def can_manage(self, owner: str, claim_key: str, viewer_name: str) -> bool:
        claim = _get_claim(self.plugin, str(owner), str(claim_key))
        if not claim:
            return False
        if str(viewer_name) == str(owner):
            return True
        return _mates_to_dict(claim).get(str(viewer_name), 0) == 1

    # Owner’s entry
    def open(self, p: Player) -> None:
        claims = _claims_map(self.plugin, p.name)
        title = "§lYour Bases"
        if not claims:
            f = ActionForm(title=title, content="You don't own any bases yet.")
            f.add_button("Close")
            f.on_submit = lambda pl, _idx: None
            return p.send_form(f)

        content = f"You own §e{len(claims)}§r base(s). Pick one to manage."
        f = ActionForm(title=title, content=content)

        order = []
        for cid, c in claims.items():
            nm = str(c.get("name", cid or "Base"))
            dim = str(c.get("dim", "overworld"))
            f.add_button(f"{nm} §7[{dim}]")
            order.append(cid)
        f.add_button("Close")

        def pick(pl, idx: int):
            if idx < 0 or idx >= len(order):
                return
            if idx == len(order):
                return
            cid = order[idx]
            self._open_base_menu_owner(pl, cid)

        f.on_submit = pick
        p.send_form(f)

    # Open basemate manager for any claim (owner or rank-1 basemate)
    def open_manage_for_claim(self, p: Player, owner: str, claim_key: str,
                              back_fn: Optional[Callable[[Player], None]] = None):
        if back_fn:
            self._back = back_fn
        owner = str(owner); claim_key = str(claim_key)
        claim = _get_claim(self.plugin, owner, claim_key)
        if not claim:
            try: p.send_message("§cClaim not found.")
            except Exception: pass
            return self._back(p)

        viewer = getattr(p, "name", "")
        if self.can_manage(owner, claim_key, viewer):
            return self._open_basemate_hub(p, owner, claim_key)
        return self._open_view_mates(p, owner, claim_key, readonly=True)

    # ── Owner base menu ───────────────────────────────────────────────────────
    def _open_base_menu_owner(self, p: Player, claim_id: str) -> None:
        c = _get_claim(self.plugin, p.name, claim_id)
        if not c:
            try: p.send_message("§cThat base no longer exists.")
            except Exception: pass
            return self.open(p)

        nm = str(c.get("name", claim_id))
        dim = str(c.get("dim", "overworld"))

        f = ActionForm(
            title=f"§lBase Management: §e{nm}",
            content=f"§7Dimension: §b{dim}\nWhat would you like to manage?"
        )
        f.add_button("Rename base")              # 0
        f.add_button("Manage basemates")         # 1
        f.add_button("Security rules")           # 2
        f.add_button("Teleport to this base")    # 3
        f.add_button("Back to list")             # 4

        def pick(pl, idx: int):
            if idx == 0:
                return self._rename(pl, claim_id)
            if idx == 1:
                return self._open_basemate_hub(pl, pl.name, claim_id)
            if idx == 2:
                return self._security(pl, claim_id)
            if idx == 3:
                return self._confirm_tp_base(pl, c)
            return self.open(pl)

        f.on_submit = pick
        p.send_form(f)

    # ── Rename ────────────────────────────────────────────────────────────────
    def _rename(self, p: Player, claim_id: str) -> None:
        c = _get_claim(self.plugin, p.name, claim_id)
        if not c:
            return self.open(p)
        current = str(c.get("name", claim_id))
        f = ModalForm(title="Rename Base", submit_button="Save")
        f.add_control(Label(f"Current name: §e{current}"))
        f.add_control(TextInput("New name", placeholder="My Cozy Base", default_value=current))

        def on_submit(pl, data):
            new_name = _read_last_text(data) or current
            c["name"] = new_name
            _save(self.plugin)
            try: pl.send_popup(f"§aBase renamed to §e{new_name}")
            except Exception: pl.send_message(f"§aBase renamed to §e{new_name}")
            self._open_base_menu_owner(pl, c.get("id", claim_id))

        f.on_submit = on_submit
        p.send_form(f)

    # ── Basemates hub / add / view / member actions ──────────────────────────
    def _open_basemate_hub(self, p: Player, owner: str, claim_key: str):
        claim = _get_claim(self.plugin, owner, claim_key)
        if not claim:
            return self._back(p)

        nm = str(claim.get("name", claim_key))
        x = int(claim.get("x", 0)); y = int(claim.get("y", 64)); z = int(claim.get("z", 0))
        dk = str(claim.get("dim", "overworld"))
        content = f"§7Owner: §e{owner}\n§7Base: §f{nm} §8({x},{y},{z}) [{dk}]"

        f = ActionForm(title="Basemates", content=content)
        f.add_button("Add from online")   # 0
        f.add_button("Add manually")      # 1
        f.add_button("View basemates")    # 2
        f.add_button("Back")              # 3

        def pick(pl, idx: Optional[int]):
            if idx == 0: return self._open_add_from_online(pl, owner, claim_key)
            if idx == 1: return self._open_add_manual(pl, owner, claim_key)
            if idx == 2: return self._open_view_mates(pl, owner, claim_key)
            return self._return_after_manage(pl, owner, claim_key)

        f.on_submit = pick
        p.send_form(f)

    def _open_add_from_online(self, p: Player, owner: str, claim_key: str):
        claim = _get_claim(self.plugin, owner, claim_key)
        if not claim:
            return self._back(p)

        mates = _mates_to_dict(claim)
        used = {k.lower() for k in mates.keys()}
        used.add(owner.lower())

        names = [n for n in _online_names(self.plugin) if n and n.lower() not in used and n != getattr(p, "name", "")]
        names = sorted(list(dict.fromkeys(names)))

        if not names:
            try: p.send_message("§7No eligible players online.")
            except Exception: pass
            return self._open_basemate_hub(p, owner, claim_key)

        f = ActionForm(title="Add basemate", content="Pick an online player to add (as Rank 0).")
        for n in names: f.add_button(n)
        f.add_button("Back")

        def on_pick(pl: Player, idx: Optional[int]):
            if idx is None or idx < 0 or idx >= len(names):
                return self._open_basemate_hub(pl, owner, claim_key)
            target = names[idx]
            self._confirm_add(pl, owner, claim_key, target)

        f.on_submit = on_pick
        p.send_form(f)

    def _open_add_manual(self, p: Player, owner: str, claim_key: str):
        m = ModalForm(title="Add basemate", submit_button="Add")
        m.add_control(TextInput("Player name", placeholder="Exact name", default_value=""))

        def on_submit(pl: Player, data):
            nm = _read_last_text(data)
            # Clean up accidental JSON-like strings or quotes
            try:
                if nm.startswith("[") or nm.startswith("{") or (nm.startswith('"') and nm.endswith('"')):
                    decoded = json.loads(nm)
                    if isinstance(decoded, list) and decoded and isinstance(decoded[0], str):
                        nm = decoded[0].strip()
                    elif isinstance(decoded, str):
                        nm = decoded.strip()
                    else:
                        nm = nm.strip('[]" ').strip()
            except Exception:
                nm = (nm or "").strip('[]" ').strip()

            if not nm:
                return self._open_basemate_hub(pl, owner, claim_key)
            self._confirm_add(pl, owner, claim_key, nm)

        m.on_submit = on_submit
        p.send_form(m)

    def _confirm_add(self, p: Player, owner: str, claim_key: str, target_name: str):
        mf = MessageForm(
            title="Confirm",
            content=f"Add §f{target_name}§r as a basemate (Rank 0)?",
            button1="Add",
            button2="Cancel",
        )
        def done(pl: Player, which: int):
            if which != 0:
                return self._open_basemate_hub(pl, owner, claim_key)
            claim = _get_claim(self.plugin, owner, claim_key)
            if not claim:
                return self._back(pl)
            if target_name.lower() == owner.lower():
                try: pl.send_message("§7Owner is already privileged.")
                except Exception: pass
                return self._open_basemate_hub(pl, owner, claim_key)
            if _add_mate(claim, target_name, rank=0):
                _save(self.plugin)
                try: pl.send_popup(f"§aAdded basemate: §e{target_name} §7(Rank 0).")
                except Exception: pass
            else:
                try: pl.send_message("§7They’re already a basemate.")
                except Exception: pass
            return self._open_basemate_hub(pl, owner, claim_key)
        mf.on_submit = done
        p.send_form(mf)

    def _open_view_mates(self, p: Player, owner: str, claim_key: str, readonly: bool = False):
        claim = _get_claim(self.plugin, owner, claim_key)
        if not claim:
            return self._back(p)
        names = _mates_list(claim)
        nm = str(claim.get("name", claim_key))
        x = int(claim.get("x", 0)); y = int(claim.get("y", 64)); z = int(claim.get("z", 0))
        dk = str(claim.get("dim", "overworld"))

        hdr = f"§7Owner: §e{owner}\n§7Base: §f{nm} §8({x},{y},{z}) [{dk}]"
        content = hdr + ("\n§7Basemates (read-only):" if readonly else "\n§7Tap a name to manage:")
        if not names:
            content = hdr + ("\n§7No basemates yet." if not readonly else "\n§7No basemates.")

        f = ActionForm(title="Basemates", content=content)
        for n in names:
            rk = _rank_of(claim, n)
            f.add_button(f"{n} §8[rank {rk}]")
        f.add_button("Back")

        def pick(pl: Player, idx: Optional[int]):
            if idx is None or idx < 0 or idx >= len(names):
                return (self._open_basemate_hub(pl, owner, claim_key) if not readonly else self._back(pl))
            if readonly:
                return self._back(pl)
            who = names[idx]
            return self._member_actions(pl, owner, claim_key, who)

        f.on_submit = pick
        p.send_form(f)

    def _member_actions(self, p: Player, owner: str, claim_key: str, mate_name: str):
        f = ActionForm(title=f"Basemate: {mate_name}", content="Choose an action")
        f.add_button("Change rank")      # 0
        f.add_button("Remove basemate")  # 1
        f.add_button("Back")             # 2

        def pick(pl: Player, idx: Optional[int]):
            if idx == 0: return self._rank_picker(pl, owner, claim_key, mate_name)
            if idx == 1: return self._confirm_remove(pl, owner, claim_key, mate_name)
            return self._open_view_mates(pl, owner, claim_key)

        f.on_submit = pick
        p.send_form(f)

    def _rank_picker(self, p: Player, owner: str, claim_key: str, mate_name: str):
        claim = _get_claim(self.plugin, owner, claim_key)
        if not claim:
            return self._back(p)
        cur = _rank_of(claim, mate_name)
        f = ActionForm(title=f"Rank for {mate_name}", content=f"Current rank: §e{cur}")
        f.add_button("Rank 0 (member)")    # 0
        f.add_button("Rank 1 (manager)")   # 1
        f.add_button("Back")               # 2

        def pick(pl: Player, idx: Optional[int]):
            if idx not in (0, 1):
                return self._member_actions(pl, owner, claim_key, mate_name)
            new_rk = 0 if idx == 0 else 1
            claim2 = _get_claim(self.plugin, owner, claim_key)
            if claim2:
                _set_rank(claim2, mate_name, new_rk)
                _save(self.plugin)
                try: pl.send_message(f"§aUpdated §f{mate_name}§a to rank §e{new_rk}§a.")
                except Exception: pass
            return self._member_actions(pl, owner, claim_key, mate_name)

        f.on_submit = pick
        p.send_form(f)

    def _confirm_remove(self, p: Player, owner: str, claim_key: str, mate_name: str):
        mf = MessageForm(
            title="Remove basemate",
            content=f"Remove §f{mate_name}§r from this base?",
            button1="Remove",
            button2="Cancel",
        )
        def done(pl: Player, which: int):
            if which != 0:
                return self._member_actions(pl, owner, claim_key, mate_name)
            claim = _get_claim(self.plugin, owner, claim_key)
            if claim and _remove_mate(claim, mate_name):
                _save(self.plugin)
                try: pl.send_message(f"§aRemoved basemate: §e{mate_name}")
                except Exception: pass
            return self._open_view_mates(pl, owner, claim_key)
        mf.on_submit = done
        p.send_form(mf)

    def _return_after_manage(self, p: Player, owner: str, claim_key: str):
        if getattr(p, "name", "") == owner:
            return self._open_base_menu_owner(p, claim_key)
        return self._back(p)

    # ── Security (kept from your version) ─────────────────────────────────────
    def _security(self, p: Player, claim_id: str) -> None:
        c = _get_claim(self.plugin, p.name, claim_id)
        if not c:
            return self.open(p)

        flags = c.setdefault("flags", {})
        flags.setdefault("allow_build", True)
        flags.setdefault("allow_interact", True)
        flags.setdefault("allow_kill_passive", True)

        sec_build_on = not bool(flags.get("allow_build", True))
        sec_interact_on = not bool(flags.get("allow_interact", True))
        sec_kill_on = not bool(flags.get("allow_kill_passive", True))

        def on_off(v: bool) -> str:
            return "§eON" if v else "§7OFF"

        lines = [
            "Choose what non-basemates/non-admins can do in this base:",
            "§7When a security setting is §eON§7, random players are §lblocked§r §7from doing it.",
            "",
            f"• Security: Break/place blocks: {on_off(sec_build_on)}",
            f"• Security: Interact (doors, chests, buttons…): {on_off(sec_interact_on)}",
            f"• Security: Kill passive mobs: {on_off(sec_kill_on)}",
            "",
            "§8(Admins and basemates always bypass these.)",
        ]

        f = ActionForm(title="§lSecurity", content="\n".join(lines))
        f.add_button("Toggle break/place")   # 0
        f.add_button("Toggle interact")      # 1
        f.add_button("Toggle kill passive")  # 2
        f.add_button("Back")                 # 3

        def pick(pl, idx: int):
            if idx == 0:
                flags["allow_build"] = not bool(flags.get("allow_build", True))
                flags["security_build"] = not bool(flags["allow_build"])
            elif idx == 1:
                flags["allow_interact"] = not bool(flags.get("allow_interact", True))
                flags["security_interact"] = not bool(flags["allow_interact"])
            elif idx == 2:
                flags["allow_kill_passive"] = not bool(flags.get("allow_kill_passive", True))
                flags["security_kill_passive"] = not bool(flags["allow_kill_passive"])
            else:
                return self._open_base_menu_owner(pl, claim_id)

            flags.pop("block_build", None)
            flags.pop("block_interact", None)
            flags.pop("block_kill_passive", None)

            _save(self.plugin)
            return self._security(pl, claim_id)

    # ── Teleport helpers (unchanged) ──────────────────────────────────────────
    def _confirm_tp_base(self, p: Player, base: Dict[str, Any]) -> None:
        nm = str(base.get("name", base.get("id", "base")))
        x = float(base.get("x", 0.0))
        y = float(base.get("y", 64.0))
        z = float(base.get("z", 0.0))
        dim_key = str(base.get("dim", "overworld"))

        mf = MessageForm(
            title="Teleport to Base",
            content=f"Teleport to §f{nm}§r at §b({int(x)} {int(y)} {int(z)})§r in §b{dim_key}§r?",
            button1="Yes",
            button2="No"
        )
        def on_submit(pl: Player, which: int):
            if which != 0:
                return self._open_base_menu_owner(pl, base.get("id", ""))
            self._teleport(pl, (x, y, z), dim_key)
            try: pl.send_message(f"§aTeleported to §f{nm}§a.")
            except Exception: pass
            return self._open_base_menu_owner(pl, base.get("id", ""))
        mf.on_submit = on_submit
        p.send_form(mf)

    def _teleport(self, p: Player, xyz, dim_key: Optional[str] = None) -> None:
        x, y, z = map(float, xyz)
        try:
            target_dim = _resolve_dimension(self.plugin, dim_key or "overworld", fallback_from_player=p)
            if target_dim is not None:
                cur = p.location
                loc = Location(target_dim, x, y, z,
                               pitch=getattr(cur, "pitch", 0.0),
                               yaw=getattr(cur, "yaw", 0.0))
                p.teleport(loc)
                return
        except Exception:
            pass
        n = self._name_for_selector(p)
        for core in (f"tp @s {int(x)} {int(y)} {int(z)}",
                     f"teleport @s {int(x)} {int(y)} {int(z)}"):
            if self._dispatch_console(f'execute as @a[name="{n}"] at @s run {core}'):
                return
        try: p.send_message("§cTeleport failed — server blocked all TP methods.")
        except Exception: pass

    def _dispatch_console(self, cmd: str) -> bool:
        try:
            cs = getattr(self.plugin.server, "command_sender", None) \
                 or getattr(self.plugin.server, "console_sender", None)
            return bool(self.plugin.server.dispatch_command(cs, cmd))
        except Exception:
            return False

    def _name_for_selector(self, p: Player) -> str:
        return str(getattr(p, "name", "")).replace('"', r'\"')
