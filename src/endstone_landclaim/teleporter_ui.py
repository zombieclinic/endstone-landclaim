# src/endstone_landclaim/teleporter_ui.py
# Strict Endstone-friendly. No future annotations.

from typing import List, Dict, Optional, Tuple, Any
import random

from endstone import Player
from endstone.form import ActionForm, MessageForm

try:
    from endstone.scoreboard import Criteria  # type: ignore
except Exception:
    Criteria = None  # type: ignore

from . import checks  # for is_admin(), player_dim_key, etc.

MONEY_OBJ = "Money"
SNAP_RANGE = 2


class TeleporterUI:
    """
    Teleporter / economy logic.

    Settings used (edited via TPSettingsUI):

      - economy_tpCommunityCost  # Spawn, Random, Community list
      - economy_tpPrivateCost    # Base teleports (My/Base)
      - economy_tpPlayerCost     # TP request cost (charged on accept)

    Optional:
      - economy_adminFreeTP      # 1 = admins free, 0 = admins pay (default)
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self._requests: Dict[str, str] = {}
        self._base_owner_ctx: Dict[str, str] = {}
        self._money_warned: bool = False

    # ======================================================================
    # Settings helpers
    # ======================================================================

    def _settings(self) -> Dict[str, Any]:
        try:
            return dict(self.plugin.data.get("settings", {}))
        except Exception:
            return {}

    def _num_setting(self, key: str, default: int) -> int:
        try:
            v = int(float(str(self._settings().get(key, default))))
            return max(0, v)
        except Exception:
            return default

    def _spawn_cost(self) -> int:
        """
        Spawn cost == Community cost.
        """
        return self._num_setting("economy_tpCommunityCost", 0)

    def _admin_free_tp(self) -> bool:
        """
        economy_adminFreeTP == 1 → admins FREE.
        Default 0 → admins PAY like everyone else.
        """
        try:
            v = int(float(str(self._settings().get("economy_adminFreeTP", 0))))
            return v != 0
        except Exception:
            return False

    def _cur_currency_name(self) -> str:
        """
        Get display name for the currency (UI only).
        """
        try:
            if hasattr(checks, "currency_name"):
                nm = checks.currency_name(self.plugin)  # type: ignore[attr-defined]
                nm = str(nm).strip()
                if nm:
                    return nm
        except Exception:
            pass

        s = self._settings()
        nm = str(
            s.get("currency_name")
            or s.get("economy_currencyName")
            or "Currency"
        ).strip()
        return nm or "Currency"

    # ======================================================================
    # Script-event entry (block trigger)
    # ======================================================================

    def open_from_block_trigger(self, p: Player) -> None:
        lvl, x, y, z = self._block_below(p)
        pos_key = self._pos_key(lvl, x, y, z)

        store   = self._load_tp_store()
        claimed = store.get("claimed", {}) or {}
        owners  = store.get("owners", {}) or {}

        me   = self._name(p)
        mine = owners.get(me)

        snap_key, snap_owner = self._nearest_claimed_block(
            store, lvl, x, y, z, prefer_owner=me, radius=SNAP_RANGE
        )
        if snap_key:
            pos_key = snap_key

        if mine and self._pos_within(pos_key, mine, SNAP_RANGE):
            pos_key = mine
            at_owner = me
        else:
            at_owner = claimed.get(pos_key) if pos_key in claimed else snap_owner

        self._base_owner_ctx[me] = me

        if not at_owner:
            if mine and not self._pos_within(pos_key, mine, SNAP_RANGE):
                return self._confirm_move_block(
                    p, store, old_key=mine, new_key=pos_key, coords=(lvl, x, y, z)
                )
            if not mine:
                return self._confirm_claim_block(
                    p, store, pos_key=pos_key, coords=(lvl, x, y, z)
                )
            self._base_owner_ctx[me] = me
            return self.open_main(p)

        if at_owner == me:
            self._base_owner_ctx[me] = me
            return self.open_main(p)

        if checks.is_admin(self.plugin, me) or self._is_basemate_of(at_owner, me):
            self._base_owner_ctx[me] = at_owner
            return self.open_main(p)

        m = MessageForm(
            title="Teleporter",
            content=f"This teleporter block is claimed by §e{at_owner}§r.\nAsk them for permission.",
            button1="Ok",
            button2="Back",
        )
        p.send_form(m)
        return

    # ======================================================================
    # Community teleporter (ALL eligible bases)
    # ======================================================================

    def open_community_teleport(self, p: Player) -> None:
        viewer = self._name(p)
        pairs = self._collect_bases_for_player(viewer)
        if not pairs:
            self._msg(p, "§7No eligible bases found (yours or where you’re a basemate).")
            return

        cost_comm = self._num_setting("economy_tpCommunityCost", 1)
        cur = self._cur_currency_name()

        def _key(row):
            owner, base = row
            own = 0 if str(owner).lower() == viewer.lower() else 1
            nm = str(base.get("name") or base.get("id") or "base")
            return (own, str(owner).lower(), nm.lower())

        pairs.sort(key=_key)

        lines = [
            "Select a base to teleport to.",
            f"§7This costs §e{cost_comm} {cur}§7.",
        ]
        f = ActionForm(title="§lCommunity Teleport", content="\n".join(lines))

        order: List[Tuple[str, Dict[str, Any]]] = []
        for owner, base in pairs:
            nm = str(base.get("name") or base.get("id") or "base")
            dk = str(base.get("dim", "overworld"))
            x, y, z = int(base.get("x", 0)), int(base.get("y", 64)), int(base.get("z", 0))
            prefix = "My base" if str(owner).lower() == viewer.lower() else f"{owner}'s base"
            f.add_button(f"{prefix}: {nm} §7({x},{y},{z}) §8[{dk}]")
            order.append((owner, base))
        f.add_button("Close")

        def pick(pl: Player, idx: int):
            if idx is None or idx < 0 or idx >= len(order):
                return
            owner, base = order[idx]
            self._confirm_community_tp(pl, owner, base, cost_comm)

        f.on_submit = pick
        p.send_form(f)

    def _confirm_community_tp(self, p: Player, owner: str,
                              base: Dict[str, Any], cost_comm: int) -> None:
        nm = str(base.get("name") or base.get("id") or "base")
        dk = str(base.get("dim", "overworld"))
        x, y, z = int(base.get("x", 0)), int(base.get("y", 64)), int(base.get("z", 0))
        txt_owner = "your" if str(owner).lower() == self._name(p).lower() else f"{owner}'s"
        cur = self._cur_currency_name()
        mf = MessageForm(
            title="Confirm Teleport",
            content=(f"Teleport to {txt_owner} base §f{nm}§r at "
                     f"§b({x} {y} {z})§r in §b{dk}§r?\n\n"
                     f"§7This will cost §e{cost_comm} {cur}§7."),
            button1=f"Teleport ({cost_comm} {cur})",
            button2="Cancel"
        )

        def done(pl: Player, idx: int):
            if idx != 0:
                return
            if not self._charge(pl, cost_comm, f"Community TP → {nm}"):
                return
            self._teleport_to_claim(pl, base)
            self._msg(pl, f"§aTeleported to §f{nm}§a.")
        mf.on_submit = done
        p.send_form(mf)

    def _collect_bases_for_player(self, viewer_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        out: List[Tuple[str, Dict[str, Any]]] = []
        try:
            players = self.plugin.data.get("players", {}) or {}
        except Exception:
            players = {}
        viewer_l = str(viewer_name).lower()

        for owner, rec in (players or {}).items():
            claims = (rec or {}).get("claims", {}) or {}
            for c in claims.values():
                if not isinstance(c, dict):
                    continue
                if str(owner).lower() == viewer_l:
                    out.append((owner, c))
                    continue
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

    # ======================================================================
    # Main Teleporter menu
    # ======================================================================

    def open_main(self, p: Player) -> None:
        # Costs (all from your tp_settings.py keys)
        cost_spawn   = self._spawn_cost()                               # Community
        cost_base    = self._num_setting("economy_tpPrivateCost", 0)    # Private
        cost_random  = self._spawn_cost()                               # Community
        cost_player  = self._num_setting("economy_tpPlayerCost", 0)     # Player
        cost_comm    = self._num_setting("economy_tpCommunityCost", 1)  # Community list
        cur = self._cur_currency_name()

        viewer = self._name(p)
        base_owner = self._base_owner_ctx.get(viewer, viewer)

        pending = self._requests.get(getattr(p, "name", ""), None)
        body_lines = []
        if pending:
            body_lines.append(f"§ePending TP request from §f{pending}")
        else:
            body_lines.append("§7No pending teleport requests.")
        body_lines += [
            "",
            f"§7Costs — Spawn: §e{cost_spawn} {cur}§7, "
            f"Base: §e{cost_base} {cur}§7, "
            f"Random: §e{cost_random} {cur}§7, "
            f"To Player: §e{cost_player} {cur}§7.",
            f"§8Bases shown: §7{base_owner}"
        ]

        f = ActionForm(title="Teleporter", content="\n".join(body_lines))
        f.add_button("TP to Spawn")  # 0
        if base_owner == viewer:
            f.add_button("TP to My Base")       # 1
        else:
            f.add_button(f"TP to {base_owner}'s Base")  # 1
        f.add_button("TP to Player (request)") # 2
        f.add_button("Accept TP Request")      # 3
        f.add_button("Random TP")              # 4
        f.add_button("Community Bases")        # 5
        f.add_button("Close")                  # 6

        def on_submit(pl: Player, idx: int):
            if idx == 0:
                return self._confirm_tp_spawn(pl, cost_spawn)
            if idx == 1:
                return self._choose_base(pl, cost_base)
            if idx == 2:
                return self._tp_to_player_menu(pl, cost_player)
            if idx == 3:
                return self._handle_requests(pl, cost_player)
            if idx == 4:
                return self._confirm_random_tp(pl, cost_random)
            if idx == 5:
                return self.open_community_teleport(pl)
            try:
                self._base_owner_ctx.pop(self._name(pl), None)
            except Exception:
                pass
        f.on_submit = on_submit
        p.send_form(f)

    # ======================================================================
    # Claim / Move / Storage
    # ======================================================================

    def _confirm_claim_block(self, p: Player, store: Dict[str, Any],
                             pos_key: str, coords: Tuple[str, int, int, int]):
        lvl, x, y, z = coords
        mf = MessageForm(
            title="Claim Teleporter",
            content=f"Claim this block at §b{x} {y} {z}§r as your teleporter?",
            button1="Claim",
            button2="Cancel",
        )

        def on_submit(pl, which):
            if which != 0:
                return self.open_main(pl)
            self._claim_block(pl, store, pos_key)
            self._msg(pl, "§aTeleporter registered.")
            return self.open_main(pl)
        mf.on_submit = on_submit
        p.send_form(mf)

    def _confirm_move_block(self, p: Player, store: Dict[str, Any],
                            old_key: str, new_key: str,
                            coords: Tuple[str, int, int, int]):
        lvl, x, y, z = coords
        mf = MessageForm(
            title="Move Teleporter",
            content=(f"You already have a teleporter.\nMove it to §b{x} {y} {z}§r?\n"
                     f"Your old block will be unclaimed."),
            button1="Move",
            button2="Cancel",
        )

        def on_submit(pl: Player, which):
            if which != 0:
                return self.open_main(pl)
            self._move_block(pl, store, old_key, new_key)
            self._msg(pl, "§aTeleporter moved.")
            return self.open_main(pl)
        mf.on_submit = on_submit
        p.send_form(mf)

    def _tp_store_path(self) -> str:
        return "teleporters.json"

    def _load_tp_store(self) -> Dict[str, Any]:
        try:
            data = self.plugin.read_json(self._tp_store_path())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_tp_store(self, data: Dict[str, Any]) -> None:
        try:
            self.plugin.write_json(self._tp_store_path(), data)
        except Exception:
            pass

    def _claim_block(self, p: Player, store: Dict[str, Any], pos_key: str):
        claimed = store.setdefault("claimed", {})
        owners  = store.setdefault("owners", {})
        me = self._name(p)
        old = owners.get(me)
        if old and claimed.get(old) == me:
            try:
                del claimed[old]
            except Exception:
                pass
        claimed[pos_key] = me
        owners[me] = pos_key
        self._save_tp_store(store)

    def _move_block(self, p: Player, store: Dict[str, Any],
                    old_key: str, new_key: str):
        claimed = store.setdefault("claimed", {})
        owners  = store.setdefault("owners", {})
        me = self._name(p)
        if claimed.get(old_key) == me:
            try:
                del claimed[old_key]
            except Exception:
                pass
        claimed[new_key] = me
        owners[me] = new_key
        self._save_tp_store(store)

    # ---- coords helpers ---------------------------------------------------

    def _block_below(self, p: Player) -> Tuple[str, int, int, int]:
        loc = p.location
        lvl = getattr(getattr(loc, "level", None), "name", None) or getattr(
            p.level, "name", "world"
        )
        return (str(lvl), int(loc.x), int(loc.y) - 1, int(loc.z))

    def _pos_key(self, level_name: str, x: int, y: int, z: int) -> str:
        return f"{level_name}:{x},{y},{z}"

    def _parse_pos_key(self, key: str) -> Tuple[Optional[str], Optional[int],
                                                Optional[int], Optional[int]]:
        try:
            level_name, rest = key.split(":", 1)
            x, y, z = rest.split(",", 2)
            return level_name, int(x), int(y), int(z)
        except Exception:
            return None, None, None, None

    # ---- snapping helpers -------------------------------------------------

    def _chebyshev_dist(self, a: Tuple[int, int, int],
                        b: Tuple[int, int, int]) -> int:
        ax, ay, az = a
        bx, by, bz = b
        dx = ax - bx
        dy = ay - by
        dz = az - bz
        if dz < 0:
            dz = -dz
        if dx < 0:
            dx = -dx
        if dy < 0:
            dy = -dy
        return max(dx, dy, dz)

    def _nearest_claimed_block(self, store: Dict[str, Any], level_name: str,
                               x: int, y: int, z: int,
                               prefer_owner: Optional[str] = None,
                               radius: int = SNAP_RANGE) -> Tuple[Optional[str], Optional[str]]:
        claimed: Dict[str, str] = (store.get("claimed") or {})
        if not claimed:
            return (None, None)

        best_key = None
        best_owner = None
        best_score = 10 ** 9

        for key, owner in claimed.items():
            lvl, cx, cy, cz = self._parse_pos_key(key)
            if lvl != level_name or cx is None:
                continue
            d = self._chebyshev_dist((x, y, z), (cx, cy, cz))
            if d <= radius:
                bias = -1 if (prefer_owner and owner == prefer_owner) else 0
                score = d * 10 + (0 if owner == prefer_owner else 5) + bias
                if score < best_score:
                    best_score = score
                    best_key = key
                    best_owner = owner

        return (best_key, best_owner)

    def _pos_within(self, key_a: str, key_b: str, within: int) -> bool:
        lvl_a, ax, ay, az = self._parse_pos_key(key_a)
        lvl_b, bx, by, bz = self._parse_pos_key(key_b)
        if lvl_a is None or lvl_b is None or lvl_a != lvl_b:
            return False
        return self._chebyshev_dist((ax, ay, az), (bx, by, bz)) <= within

    # ---- dimension helpers ------------------------------------------------

    def _cur_dim_key(self, p: Player) -> str:
        try:
            if hasattr(checks, "player_dim_key"):
                dk = checks.player_dim_key(p)
                if dk:
                    return self._norm_dim_key(dk)
        except Exception:
            pass
        try:
            loc = p.location
            dim = getattr(loc, "dimension", None)
            if isinstance(dim, int):
                return "overworld" if dim in (0,) else ("nether" if dim in (1, -1) else "the_end")
            name = (
                str(getattr(dim, "name", ""))
                or str(getattr(getattr(loc, "level", None), "name", ""))
            ).lower()
            if "nether" in name:
                return "nether"
            if "end" in name:
                return "the_end"
            return "overworld"
        except Exception:
            return "overworld"

    def _norm_dim_key(self, dk: str) -> str:
        d = (dk or "overworld").lower()
        if "nether" in d:
            return "nether"
        if "end" in d:
            return "the_end"
        return "overworld"

    def _exec_dim_candidates(self, dk: str) -> List[str]:
        d = self._norm_dim_key(dk)
        if d == "nether":
            return ["nether", "minecraft:nether", "the_nether"]
        if d == "the_end":
            return ["the_end", "minecraft:the_end", "end"]
        return ["overworld", "minecraft:overworld"]

    def _exec_dim_name(self, dk: str) -> str:
        return self._exec_dim_candidates(dk)[0]

    # ======================================================================
    # Spawn
    # ======================================================================

    def _confirm_tp_spawn(self, p: Player, _cost_from_caller: int) -> None:
        """
        Always recompute from _spawn_cost() so everything uses Community price.
        """
        cost = self._spawn_cost()
        cur = self._cur_currency_name()
        mf = MessageForm(
            title="Teleport to Spawn",
            content=f"Teleport to spawn?\n§7Cost: §e{cost} {cur}",
            button1="Yes",
            button2="No"
        )

        def on_submit(pl: Player, which: int):
            if which != 0:
                return
            if not self._charge(pl, cost, "TP to Spawn"):
                return
            self._tp_to_spawn(pl)
            self._msg(pl, "§aTeleported to spawn.")
        mf.on_submit = on_submit
        p.send_form(mf)

    def _tp_to_spawn(self, p: Player) -> None:
        def _parse_xyz(raw, default=(0.0, 64.0, 0.0)):
            try:
                s = str(raw or "").replace("|", " ").replace(",", " ")
                parts = [t for t in s.split() if t]
                if len(parts) >= 3:
                    return float(parts[0]), float(parts[1]), float(parts[2])
                if len(parts) == 2:
                    return float(parts[0]), 64.0, float(parts[1])
            except Exception:
                pass
            return default

        x, y, z = 0.0, 64.0, 0.0
        try:
            s = dict(self.plugin.data.get("settings", {}))
        except Exception:
            s = {}

        try:
            spawns = s.get("spawns") or {}
            ow = spawns.get("overworld") or {}
            pos = ow.get("pos")
            if pos:
                x, y, z = _parse_xyz(pos, (x, y, z))
        except Exception:
            pass

        if (x, y, z) == (0.0, 64.0, 0.0):
            try:
                legacy = s.get("worldspawn")
                if legacy:
                    x, y, z = _parse_xyz(legacy, (x, y, z))
            except Exception:
                pass

        self._teleport(p, (x, y, z), dim_key="overworld")

    # ======================================================================
    # TP to Base (uses Private cost)
    # ======================================================================

    def _choose_base(self, p: Player, cost: int) -> None:
        viewer = self._name(p)
        base_owner = self._base_owner_ctx.get(viewer, viewer)
        bases = self._owned_bases_of(base_owner)
        if not bases:
            self._msg(p, "§cNo bases found for " + base_owner + ".")
            return
        label_owner = "your" if base_owner == viewer else f"{base_owner}'s"
        cur = self._cur_currency_name()
        f = ActionForm(
            title="Your Bases",
            content=f"Pick a base to teleport to ({label_owner}).\n"
                    f"§7Cost per TP: §e{cost} {cur}"
        )
        for base in bases:
            nm = base.get("name") or base.get("id") or "base"
            coords = f"({int(base.get('x',0))}, {int(base.get('y',64))}, {int(base.get('z',0))})"
            dk = str(base.get("dim", "overworld"))
            f.add_button(f"{nm} §7{coords} §8[{dk}]")
        f.add_button("Back")

        def on_submit(pl: Player, idx: int):
            if idx is None or idx < 0 or idx >= len(bases):
                return
            base = bases[idx]
            self._confirm_tp_base(pl, base, cost)
        f.on_submit = on_submit
        p.send_form(f)

    def _confirm_tp_base(self, p: Player, base: Dict[str, Any], cost: int) -> None:
        nm = base.get("name") or base.get("id") or "base"
        cur = self._cur_currency_name()
        mf = MessageForm(
            title="Teleport to Base",
            content=f"Teleport to §f{nm}§r?\n§7Cost: §e{cost} {cur}",
            button1="Yes",
            button2="No"
        )

        def on_submit(pl: Player, which: int):
            if which != 0:
                return
            if not self._charge(pl, cost, f"TP to {nm}"):
                return
            self._teleport_to_claim(pl, base)
            self._msg(pl, f"§aTeleported to §f{nm}§a.")
            try:
                self._base_owner_ctx.pop(self._name(pl), None)
            except Exception:
                pass
        mf.on_submit = on_submit
        p.send_form(mf)

    def _teleport_to_claim(self, p: Player, base: Dict[str, Any]) -> None:
        x = float(base.get("x", 0.0))
        y = float(base.get("y", 64.0))
        z = float(base.get("z", 0.0))
        target_dim = self._norm_dim_key(str(base.get("dim", "overworld")))
        if target_dim != self._cur_dim_key(p):
            self._teleport(p, (x, y, z), dim_key=target_dim)
            return
        self._teleport(p, (x, y, z))

    # ======================================================================
    # TP to Player (request) / Random TP
    # ======================================================================

    def _tp_to_player_menu(self, p: Player, cost: int) -> None:
        names = [n for n in self._online_names() if n != p.name]
        if not names:
            self._msg(p, "§7No other players online.")
            return
        cur = self._cur_currency_name()
        f = ActionForm(
            title="TP to Player",
            content=f"Select a player to request a teleport.\n"
                    f"§7Cost (on accept): §e{cost} {cur}"
        )
        for n in names:
            f.add_button(n)
        f.add_button("Back")

        def on_submit(pl: Player, idx: int):
            if idx is None or idx < 0 or idx >= len(names):
                return
            target_name = names[idx]
            conf = MessageForm(
                title="Send TP Request",
                content=(f"Send a TP request to §f{target_name}§r?\n"
                         f"§7If they accept, you will be charged: §e{cost} {cur}"),
                button1="Send",
                button2="Cancel"
            )

            def after_send(ppa: Player, which: int):
                if which != 0:
                    return
                self._requests[target_name] = p.name
                self._msg(
                    p,
                    f"§aRequest sent to §f{target_name}§a. "
                    f"§7(You will be charged if they accept.)"
                )
                tgt = self._find_online_by_name(target_name)
                if tgt:
                    self._msg(
                        tgt,
                        f"§e{p.name} wants to teleport to you. "
                        f"Open Teleporter → Accept TP Request."
                    )
            conf.on_submit = after_send
            p.send_form(conf)

        f.on_submit = on_submit
        p.send_form(f)

    def _handle_requests(self, p: Player, cost: int) -> None:
        req = self._requests.get(p.name)
        if not req:
            self._msg(p, "§7No teleport requests.")
            return
        requester = self._find_online_by_name(req)
        cur = self._cur_currency_name()
        content = (
            f"§f{req}§r wants to TP to you.\n"
            f"§7They will be charged §e{cost} {cur}§7 if you accept."
        )
        mf = MessageForm(
            title="Teleport Request",
            content=content,
            button1="Accept",
            button2="Decline"
        )

        def on_submit(pl: Player, which: int):
            self._requests.pop(p.name, None)
            if which != 0:
                self._msg(pl, f"§cRequest from {req} declined.")
                if requester:
                    self._msg(requester, f"§cYour TP request to {p.name} was declined.")
                return
            if not requester:
                self._msg(pl, "§cRequester is no longer online.")
                return
            if not self._charge(requester, cost, f"TP to {p.name}"):
                self._msg(pl, f"§c{req} couldn’t afford the teleport.")
                self._msg(requester, "§cTeleport cancelled — insufficient funds.")
                return
            self._teleport_to_player(requester, p)
            self._msg(pl, f"§a{req} teleported to you.")
            self._msg(requester, f"§aTeleported to §f{p.name}§a.")
        mf.on_submit = on_submit
        p.send_form(mf)

    def _confirm_random_tp(self, p: Player, cost: int) -> None:
        cur = self._cur_currency_name()
        mf = MessageForm(
            title="Random Teleport",
            content=(f"Teleport to a random spot (±25,000) at y=300 "
                     f"with Slow Falling?\n§7Cost: §e{cost} {cur}"),
            button1="Yes",
            button2="No"
        )

        def on_submit(pl: Player, which: int):
            if which != 0:
                return
            if not self._charge(pl, cost, "Random TP"):
                return
            x = random.randint(-25000, 25000)
            z = random.randint(-25000, 25000)
            y = 300.0
            self._apply_slow_fall(pl, 30)
            self._teleport(pl, (float(x), y, float(z)))
            self._msg(pl, f"§aRandom teleported to §f({x}, {int(y)}, {z})§a.")
        mf.on_submit = on_submit
        p.send_form(mf)

    # ======================================================================
    # Helpers: bases / mates
    # ======================================================================

    def _is_basemate_of(self, owner_name: str, mate_name: str) -> bool:
        try:
            players = self.plugin.data.get("players", {}) or {}
            owner_l = str(owner_name).lower()
            actual_owner_key = None
            for k in players.keys():
                try:
                    if str(k).lower() == owner_l:
                        actual_owner_key = k
                        break
                except Exception:
                    continue
            if actual_owner_key is None:
                return False

            prec = players.get(actual_owner_key, {}) or {}
            claims = prec.get("claims", {}) or {}
            mlow = str(mate_name).lower()
            for c in claims.values():
                if not isinstance(c, dict):
                    continue
                mates = c.get("mates") or []
                if isinstance(mates, dict):
                    mates = list(mates.keys())
                mates = [str(m).lower() for m in mates]
                if mlow in mates:
                    return True
        except Exception:
            pass
        return False

    def _owned_bases_of(self, owner_name: str) -> List[Dict[str, Any]]:
        try:
            players = self.plugin.data.get("players", {}) or {}
            target_key = None
            ol = str(owner_name).lower()
            for k in players.keys():
                try:
                    if str(k).lower() == ol:
                        target_key = k
                        break
                except Exception:
                    continue
            if target_key is None:
                return []
            rec = players.get(target_key, {}) or {}
            claims = rec.get("claims") or {}
            out: List[Dict[str, Any]] = []
            for c in claims.values():
                if isinstance(c, dict):
                    out.append(c)
            return out
        except Exception:
            return []

    # ======================================================================
    # Helpers: forms & messaging
    # ======================================================================

    def _msg(self, p: Player, text: str) -> None:
        for fn in (lambda: p.send_message(text), lambda: p.send_popup(text)):
            try:
                fn()
                return
            except Exception:
                continue

    # ======================================================================
    # Console helpers (quotes-safe)
    # ======================================================================

    def _dispatch_console(self, cmd: str) -> bool:
        try:
            cs = getattr(self.plugin.server, "command_sender", None) \
                 or getattr(self.plugin.server, "console_sender", None)
        except Exception:
            cs = None
        try:
            return bool(self.plugin.server.dispatch_command(cs, cmd))
        except Exception:
            return False

    def _name_for_selector(self, p: Player) -> str:
        return str(getattr(p, "name", "")).replace('"', r'\"')

    # ======================================================================
    # Teleport helpers
    # ======================================================================

    def _teleport(self, p, xyz, dim_key: Optional[str] = None):
        x, y, z = map(float, xyz)

        if dim_key is not None:
            want = self._norm_dim_key(dim_key)
            if want != self._cur_dim_key(p):
                n = self._name_for_selector(p)
                for exec_dim in self._exec_dim_candidates(want):
                    for core in (
                        f'execute in {exec_dim} run tp @s {int(x)} {int(y)} {int(z)}',
                        f'execute in {exec_dim} run teleport @s {int(x)} {int(y)} {int(z)}',
                    ):
                        if self._dispatch_console(
                            f'execute as @a[name="{n}"] at @s run {core}'
                        ):
                            return
                        if self._dispatch_console(core.replace("@s", f'@a[name="{n}"]')):
                            return

        try:
            from endstone.level import Location
            cur = p.location
            target_dim = getattr(cur, "dimension", None)
            if dim_key is not None:
                dk = self._norm_dim_key(dim_key)
                for did in (
                    {"overworld": 0, "nether": 1, "the_end": 2}.get(dk, None),
                    {"overworld": 0, "nether": -1, "the_end": 1}.get(dk, None),
                ):
                    if did is not None:
                        try:
                            loc = Location(
                                did,
                                x,
                                y,
                                z,
                                pitch=getattr(cur, "pitch", 0.0),
                                yaw=getattr(cur, "yaw", 0.0),
                            )
                            p.teleport(loc)
                            return
                        except Exception:
                            pass
            loc = Location(
                target_dim,
                x,
                y,
                z,
                pitch=getattr(cur, "pitch", 0.0),
                yaw=getattr(cur, "yaw", 0.0),
            )
            p.teleport(loc)
            return
        except Exception:
            pass

        n = self._name_for_selector(p)
        for core in (
            f"tp @s {int(x)} {int(y)} {int(z)}",
            f"teleport @s {int(x)} {int(y)} {int(z)}",
        ):
            if self._dispatch_console(
                f'execute as @a[name="{n}"] at @s run {core}'
            ):
                return

        self._msg(p, "§cTeleport failed — server blocked all TP methods.")

    def _teleport_to_player(self, who: Player, to: Player) -> None:
        try:
            loc = to.location
            self._teleport(who, (float(loc.x), float(loc.y), float(loc.z)))
        except Exception:
            pass

    # ======================================================================
    # Scoreboard economy helpers
    # ======================================================================

    def _objective(self, p: Player):
        try:
            return p.scoreboard.get_objective(MONEY_OBJ)
        except Exception:
            pass
        try:
            anyp = self._any_player()
            if anyp:
                return anyp.scoreboard.get_objective(MONEY_OBJ)
        except Exception:
            pass
        return None

    def _warn_missing_money_once(self):
        if not self._money_warned:
            self._money_warned = True
            try:
                self.plugin.logger.warning(
                    "[TeleporterUI] Money scoreboard objective not found."
                )
            except Exception:
                pass

    def _ensure_objective(self, name: str = MONEY_OBJ) -> None:
        return  # we assume Money already exists

    def _get_money(self, p: Player) -> Optional[int]:
        try:
            obj = self._objective(p)
            if obj is not None:
                sc = obj.get_score(p)
                if getattr(sc, "is_score_set", True):
                    return int(sc.value)
        except Exception:
            pass
        try:
            obj = self._objective(p)
            if obj is not None:
                sc = obj.get_score(self._name(p))
                if getattr(sc, "is_score_set", True):
                    return int(sc.value)
        except Exception:
            pass
        self._warn_missing_money_once()
        return None

    def _set_money(self, p: Player, value: int) -> bool:
        v = max(0, int(value))
        try:
            obj = self._objective(p)
            if obj is None:
                self._warn_missing_money_once()
                return False
            sc = obj.get_score(p)
            sc.value = v
            return True
        except Exception:
            pass
        try:
            n = self._name_for_selector(p)
            return self._dispatch_console(
                f'scoreboard players set @a[name="{n}"] {MONEY_OBJ} {v}'
            )
        except Exception:
            return False

    def _add_money(self, p: Player, delta: int) -> bool:
        try:
            obj = self._objective(p)
            if obj is None:
                self._warn_missing_money_once()
                return False
            sc = obj.get_score(p)
            sc.value = int(sc.value) + int(delta)
            return True
        except Exception:
            pass
        try:
            n = self._name_for_selector(p)
            return self._dispatch_console(
                f'scoreboard players add @a[name="{n}"] {MONEY_OBJ} {int(delta)}'
            )
        except Exception:
            return False

    def _charge(self, p: Player, amount: int, label: str) -> bool:
        # Admin free toggle (now OFF by default)
        if self._admin_free_tp():
            try:
                if checks.is_admin(self.plugin, self._name(p)):
                    return True
            except Exception:
                pass

        cost = max(0, int(amount or 0))
        if cost <= 0:
            return True

        bal = self._get_money(p)
        if bal is None:
            self._msg(
                p,
                f"§cEconomy not available ({MONEY_OBJ} scoreboard could not be read).",
            )
            return False
        if bal < cost:
            self._msg(
                p,
                f"§cNot enough {self._cur_currency_name()}."
                f" Need §e{cost}§c, you have §e{bal}§c.",
            )
            return False

        if self._add_money(p, -cost):
            self._msg(
                p,
                f"§aPaid §e{cost}§a {self._cur_currency_name()} for {label}. "
                f"New balance: §e{bal - cost}§a.",
            )
            return True

        self._msg(p, "§cPayment failed.")
        return False

    # ======================================================================
    # Effects & players helpers
    # ======================================================================

    def _apply_slow_fall(self, p, seconds: int = 30) -> bool:
        secs = max(1, int(seconds or 30))
        try:
            n = self._name_for_selector(p)
            for core in (
                f"effect give @s slow_falling {secs} 0 true",
                f"effect @s slow_falling {secs} 0 true",
            ):
                if self._dispatch_console(
                    f'execute as @a[name="{n}"] at @s run {core}'
                ):
                    return True
        except Exception:
            pass
        for applier in (
            lambda: p.add_effect(
                "minecraft:slow_falling", duration=secs * 20, amplifier=0
            ),
            lambda: p.add_status_effect("slow_falling", secs * 20, 0),
        ):
            try:
                applier()
                return True
            except Exception:
                continue
        return False

    def _online_names(self) -> List[str]:
        for meth in ("get_players", "get_online_players"):
            m = getattr(self.plugin.server, meth, None)
            if callable(m):
                try:
                    return [
                        str(getattr(p, "name", ""))
                        for p in (m() or [])
                        if getattr(p, "name", None)
                    ]
                except Exception:
                    pass
        for attr in ("players", "online_players"):
            if hasattr(self.plugin.server, attr):
                try:
                    return [
                        str(getattr(p, "name", ""))
                        for p in (getattr(self.plugin.server, attr) or [])
                        if getattr(p, "name", None)
                    ]
                except Exception:
                    pass
        return []

    def _find_online_by_name(self, name: str) -> Optional[Player]:
        for pl in self._all_players():
            if getattr(pl, "name", "").lower() == str(name).lower():
                return pl
        return None

    def _all_players(self) -> List[Player]:
        for meth in ("get_players", "get_online_players"):
            m = getattr(self.plugin.server, meth, None)
            if callable(m):
                try:
                    return list(m())
                except Exception:
                    pass
        for attr in ("players", "online_players"):
            if hasattr(self.plugin.server, attr):
                try:
                    v = getattr(self.plugin.server, attr)
                    if isinstance(v, (list, tuple, set)):
                        return list(v)
                except Exception:
                    pass
        return []

    def _any_player(self) -> Optional[Player]:
        pls = self._all_players()
        return pls[0] if pls else None

    def _name(self, p: Player) -> str:
        try:
            nm = getattr(p, "name", None)
            if nm:
                return str(nm)
        except Exception:
            pass
        return "@s"
