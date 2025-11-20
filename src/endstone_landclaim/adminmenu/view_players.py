# endstone_landclaim/adminmenu/view_players.py
from __future__ import annotations
from typing import List, Dict, Tuple, Optional

from endstone import Player
from endstone.form import ActionForm, ModalForm, Label, TextInput, MessageForm

from .shared import (
    players_store, online_players, player_name,
    get_inventory, get_ender, inv_size,
    get_item_from_slot, set_item_in_slot, add_item,
    is_air, item_display_name, parse_modal_values,
)

# Try to use the same helpers your runtime uses for flags + cache bump
try:
    from .. import checks  # type: ignore
except Exception:
    try:
        from . import checks  # type: ignore
    except Exception:
        checks = None  # type: ignore

# Pull in the player Security UI so we can reuse it
try:
    from ..landclaimui import LandClaimUI as _LCUI  # type: ignore
except Exception:
    _LCUI = None  # type: ignore


# ---------- internal helpers ----------
def _safe_bump_version(plugin):
    try:
        if checks and hasattr(checks, "bump_claims_version"):
            checks.bump_claims_version(plugin, 1)
            return
    except Exception:
        pass
    try:
        v = int(getattr(plugin, "_claims_version", 0))
        setattr(plugin, "_claims_version", v + 1)
    except Exception:
        pass


def _all_player_stores(plugin):
    """
    Return up to three dicts that may hold players:
      - admin UI store (players_store)
      - plugin.data['players']
      - plugin.admin.data['players'] (if present)
    """
    stores = []

    # Admin UI store (what this UI normally edits)
    try:
        st = players_store(plugin)
        if isinstance(st, dict):
            stores.append(st)
    except Exception:
        pass

    # Primary plugin store
    try:
        pdata = getattr(plugin, "data", None)
        if isinstance(pdata, dict):
            stores.append(pdata.setdefault("players", {}))
    except Exception:
        pass

    # Admin block store (some builds mirror here)
    try:
        adm = getattr(plugin, "admin", None)
        if adm and isinstance(getattr(adm, "data", None), dict):
            stores.append(adm.data.setdefault("players", {}))
    except Exception:
        pass

    # Dedup by object id but keep order
    seen = set(); out = []
    for s in stores:
        if id(s) not in seen:
            out.append(s); seen.add(id(s))
    return out


def _resolve_owner_key(store: dict, owner_name: str) -> Optional[str]:
    """Return the existing key for this owner (case-insensitive)."""
    try:
        nlow = str(owner_name).lower()
        for k in list(store.keys()):
            try:
                if str(k).lower() == nlow:
                    return k
            except Exception:
                continue
    except Exception:
        pass
    return None


def _match_claim_id_by_coords(claims: dict, base_ref: dict) -> Optional[str]:
    """If the claim id doesn't exist in this store, try to find an equivalent by coords/radius."""
    try:
        bx = int(base_ref.get("x", 0))
        by = int(base_ref.get("y", 64))
        bz = int(base_ref.get("z", 0))
        br = int(base_ref.get("radius", 0))
    except Exception:
        return None
    for cid2, c in (claims or {}).items():
        try:
            if (int(c.get("x", 0)) == bx and
                int(c.get("y", 64)) == by and
                int(c.get("z", 0)) == bz and
                int(c.get("radius", 0)) == br):
                return cid2
        except Exception:
            continue
    return None


def _get_existing_base(store: dict, owner: str, cid: str, base_ref: Optional[dict] = None) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    """
    Return (base_dict, resolved_owner_key, resolved_cid) ONLY if the base already exists
    in the given store. Never creates new owners/claims (prevents desync).
    """
    if not isinstance(store, dict):
        return None, None, None
    ok = _resolve_owner_key(store, owner) or None
    if ok is None:
        return None, None, None
    rec = store.get(ok, {}) or {}
    claims = rec.get("claims", {}) or {}
    if cid in claims:
        return claims[cid], ok, cid
    if base_ref:
        alt = _match_claim_id_by_coords(claims, base_ref)
        if alt and alt in claims:
            return claims[alt], ok, alt
    return None, None, None


def _write_flags_all(plugin, owner: str, cid: str, *, base_ref: Optional[dict] = None, **kv):
    """
    Write flags to all likely player stores, but ONLY if the claim already exists there.
    kv can include: allow_build / allow_interact / allow_kill_passive
                    security_build / security_interact / security_kill_passive
    """
    changed = False
    for store in _all_player_stores(plugin):
        try:
            base, ok, real_cid = _get_existing_base(store, owner, cid, base_ref)
            if base is None:
                continue  # don't create new claims/owners accidentally
            flags = base.setdefault("flags", {})
            for k, v in kv.items():
                if flags.get(k) != v:
                    flags[k] = v
                    changed = True
        except Exception:
            continue
    if changed:
        _safe_bump_version(plugin)


def _save_everywhere(plugin):
    # Call any saver the pack exposes
    for meth in ("save_config", "save_players", "_save_players", "_save_claims"):
        fn = getattr(plugin, meth, None)
        try:
            if callable(fn):
                fn()
                return
        except Exception:
            pass


def _main_store_claim(plugin, owner: str, cid: str, base_ref: Optional[dict] = None) -> Tuple[Optional[dict], Optional[str]]:
    """
    Find the claim in the **main plugin store** (plugin.data['players']).
    Returns (claim_dict, resolved_cid_in_main_store).
    """
    pdata = getattr(plugin, "data", {}) or {}
    pmap = pdata.setdefault("players", {})
    ok = _resolve_owner_key(pmap, owner) or owner
    claims = (pmap.get(ok, {}) or {}).get("claims", {}) or {}
    if cid in claims:
        return claims[cid], cid
    if base_ref:
        alt = _match_claim_id_by_coords(claims, base_ref)
        if alt and alt in claims:
            return claims[alt], alt
    return None, None


class ViewPlayersUI:
    """
    View Players menu:
      • Online players' inventories
      • All players' bases
           -> Teleport / Rename / Set radius / Security / Basemates / Change ownership / Remove
    """
    def __init__(self, plugin, back_fn=None):
        self.plugin = plugin
        self._back = back_fn or (lambda p: None)

    # ──────────────────────────────────────────────────────────────────────
    # Entry
    # ──────────────────────────────────────────────────────────────────────
    def open(self, p: Player):
        f = ActionForm(title="§lView Players", content="Pick a tool")
        f.add_button("Online players' inventories")  # 0
        f.add_button("All players' bases")           # 1
        f.add_button("Back")                         # 2

        def pick(pl, idx):
            if idx == 0: return self._pick_online_player(pl)
            if idx == 1: return self._pick_base_owner(pl)
            return self._back(pl)
        f.on_submit = pick
        p.send_form(f)

    # ──────────────────────────────────────────────────────────────────────
    # ONLINE INVENTORIES FLOW
    # ──────────────────────────────────────────────────────────────────────
    def _pick_online_player(self, p: Player):
        opls = online_players(self.plugin)
        names = [player_name(pl) for pl in opls]

        if not names:
            p.send_message("§7No players online.")
            return self.open(p)

        form = ActionForm(title="§lOnline Players", content="Pick a player")
        for n in names: form.add_button(n)
        form.add_button("Back")

        def on_submit(pl, idx):
            if idx is None or idx < 0 or idx >= len(names):
                return self.open(pl)
            # resolve live object again, avoid stale refs
            target = None
            for live in online_players(self.plugin):
                if player_name(live) == names[idx]:
                    target = live; break
            if not target:
                pl.send_message("§7Player went offline.")
                return self._pick_online_player(pl)
            return self._inspect_online_player(pl, target)
        form.on_submit = on_submit
        p.send_form(form)

    def _inspect_online_player(self, viewer: Player, target: Player):
        tname = player_name(target)
        form = ActionForm(title=f"§lInspect: {tname}", content="Choose an inventory")
        form.add_button("View Inventory")   # 0
        form.add_button("View Ender Chest") # 1
        form.add_button("Back")             # 2

        def pick(pl, idx):
            if idx == 0: return self._open_container(pl, target, which="inv")
            if idx == 1: return self._open_container(pl, target, which="ender")
            return self._pick_online_player(pl)
        form.on_submit = pick
        viewer.send_form(form)

    def _open_container(self, viewer: Player, target: Player, which: str):
        tname = player_name(target)
        if which == "inv":
            inv = get_inventory(target)
            title = "Inventory"
        else:
            inv = get_ender(target)
            title = "Ender Chest"

        if not inv:
            viewer.send_message(f"§cCan't read {title.lower()} on this build.")
            return self._inspect_online_player(viewer, target)

        size = inv_size(inv)
        form = ActionForm(title=f"{title}: {tname}", content=f"{size} slots")
        for i in range(size):
            it = get_item_from_slot(inv, i)
            if not it or is_air(it):
                form.add_button(f"[{i}] — empty —")
            else:
                name = item_display_name(it)
                cnt  = getattr(it, "amount", None) or getattr(it, "count", None) or 1
                form.add_button(f"[{i}] {name} ×{cnt}")
        form.add_button("« Back to Player")  # idx == size

        def pick(pl, idx):
            if idx == size:
                return self._inspect_online_player(pl, target)
            if idx is None or idx < 0 or idx >= size:
                return self._inspect_online_player(pl, target)
            return self._slot_actions(pl, target, inv, idx, title)
        form.on_submit = pick
        viewer.send_form(form)

    def _slot_actions(self, viewer: Player, target: Player, inv, slot_idx: int, title: str):
        it = get_item_from_slot(inv, slot_idx)
        if not it or is_air(it):
            viewer.send_message("§7That slot is empty.")
            return self._open_container(viewer, target, "inv" if title == "Inventory" else "ender")

        name = item_display_name(it)
        cnt  = getattr(it, "amount", None) or getattr(it, "count", None) or 1

        f = ActionForm(title=f"{title} [{slot_idx}]", content=f"§l{name}§r ×{cnt}")
        f.add_button("Take")                # 0
        f.add_button("Copy to me")          # 1
        f.add_button("Remove (clear slot)") # 2
        f.add_button("Back to slots")       # 3
        f.add_button("Back to player")      # 4

        def on_pick(pl, btn_idx):
            if btn_idx == 0:  # Take
                dst = get_inventory(pl)
                if not dst:
                    pl.send_message("§cCan't access your inventory.")
                    return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
                item_now = get_item_from_slot(inv, slot_idx)
                if not item_now or is_air(item_now):
                    pl.send_message("§7Item no longer there.")
                    return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
                if add_item(dst, item_now):
                    set_item_in_slot(inv, slot_idx, None)
                    pl.send_message("§aItem moved to your inventory.")
                else:
                    pl.send_message("§cYour inventory is full.")
                return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")

            if btn_idx == 1:  # Copy
                dst = get_inventory(pl)
                if not dst:
                    pl.send_message("§cCan't access your inventory.")
                    return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
                item_now = get_item_from_slot(inv, slot_idx)
                if not item_now or is_air(item_now):
                    pl.send_message("§7Item no longer there.")
                    return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
                if add_item(dst, item_now):
                    pl.send_message("§aA copy was added to your inventory.")
                else:
                    pl.send_message("§cYour inventory is full.")
                return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")

            if btn_idx == 2:  # Remove
                item_now = get_item_from_slot(inv, slot_idx)
                if not item_now or is_air(item_now):
                    pl.send_message("§7Nothing to remove.")
                else:
                    if set_item_in_slot(inv, slot_idx, None):
                        pl.send_message("§aSlot cleared.")
                    else:
                        pl.send_message("§cFailed to clear that slot on this build.")
                return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")

            if btn_idx == 3:
                return self._open_container(pl, target, "inv" if title == "Inventory" else "ender")
            if btn_idx == 4:
                return self._inspect_online_player(pl, target)
        f.on_submit = on_pick
        viewer.send_form(f)

    # ──────────────────────────────────────────────────────────────────────
    # BASES FLOW (all players with saved claims)
    # ──────────────────────────────────────────────────────────────────────
    def _pick_base_owner(self, p: Player):
        names = sorted([n for n in players_store(self.plugin).keys() if n])
        if not names:
            p.send_message("§7No saved players with bases.")
            return self.open(p)

        f = ActionForm(title="§lPlayers with Bases", content="Pick a player")
        for n in names: f.add_button(n)
        f.add_button("Back")

        def pick(pl, idx):
            if idx is None or idx < 0 or idx >= len(names):
                return self.open(pl)
            return self._list_bases(pl, names[idx])
        f.on_submit = pick
        p.send_form(f)

    def _list_bases(self, p: Player, owner_name: str):
        rec = players_store(self.plugin).get(owner_name, {}) or {}
        claims = rec.get("claims", {}) or {}
        if not claims:
            p.send_message(f"§7No bases for §e{owner_name}.")
            return self._pick_base_owner(p)

        ids = list(claims.keys())
        f = ActionForm(title=f"§l{owner_name}'s Bases", content="Pick a base to manage")
        for cid in ids:
            nm = claims[cid].get("name", cid)
            f.add_button(nm)
        f.add_button("Back")

        def pick(pl, idx):
            if idx is None or idx < 0 or idx >= len(ids):
                return self._pick_base_owner(pl)
            cid = ids[idx]
            return self._base_details(pl, owner_name, cid, claims[cid])
        f.on_submit = pick
        p.send_form(f)

    def _base_details(self, p: Player, owner_name: str, cid: str, base: dict):
        name = base.get("name", cid)
        cx, cy, cz = int(base.get("x", 0)), int(base.get("y", 64)), int(base.get("z", 0))
        r = int(base.get("radius", 0))
        br = int(base.get("buffer_rule", 0))

        # mates list for display only
        mates = [str(m) for m in (base.get("mates") or [])]

        body = [
            f"§lOwner: §e{owner_name}",
            f"§lBase: §e{name} §7(id: {cid})",
            "",
            f"§7Center: §b{cx} {cy} {cz}",
            f"§7Radius: §b{r}",
            f"§7Buffer (at placement): §b{br}",
            "",
            f"§7Basemates: §e{(', '.join(mates) if mates else 'none')}",
        ]

        f = ActionForm(title="§lBase Details", content="\n".join(body))
        f.add_button("Teleport")  # 0
        f.add_button("Rename base")  # 1
        f.add_button("Set radius")  # 2
        f.add_button("Security")  # 3
        f.add_button("Basemates")  # 4
        f.add_button("Change ownership")  # 5
        f.add_button("Remove base")  # 6
        f.add_button("Back")  # 7

        def pick(pl, idx):
            if idx == 0:
                try:
                    pl.perform_command(f"tp {cx} {cy} {cz}")
                    pl.send_message(f"§aTeleported to §e{owner_name}§a/§e{name}")
                except Exception:
                    pl.send_message("§cTeleport failed.")
                return self._base_details(pl, owner_name, cid, base)

            if idx == 1:  # rename
                m = ModalForm(title="Rename Base", submit_button="Save")
                m.add_control(TextInput("New name", placeholder=name, default_value=name))

                def on_submit(pp, data):
                    vals = parse_modal_values(data)
                    new_name = str((vals or [""])[-1]).strip()[:64]
                    if new_name:
                        for store in _all_player_stores(self.plugin):
                            b, ok, real_cid = _get_existing_base(store, owner_name, cid, base)
                            if b is None:
                                continue
                            b["name"] = new_name
                        _safe_bump_version(self.plugin);
                        _save_everywhere(self.plugin)
                        pp.send_message("§aBase renamed.")
                    return self._list_bases(pp, owner_name)

                m.on_submit = on_submit
                return pl.send_form(m)

            if idx == 2:  # set radius
                m = ModalForm(title="Set Radius", submit_button="Save")
                m.add_control(Label(f"Current: {r}"))
                m.add_control(TextInput("Enter new radius", default_value=str(r)))

                def on_submit(pp, data):
                    vals = parse_modal_values(data)
                    if vals:
                        try:
                            nr = int(float(str(vals[-1]).strip()))
                        except Exception:
                            nr = r
                        nr = max(0, nr)
                        for store in _all_player_stores(self.plugin):
                            b, ok, real_cid = _get_existing_base(store, owner_name, cid, base)
                            if b is None:
                                continue
                            b["radius"] = nr
                        _safe_bump_version(self.plugin);
                        _save_everywhere(self.plugin)
                        pp.send_message("§aRadius updated.")
                    # refresh from admin store
                    return self._base_details(pp, owner_name, cid,
                                              players_store(self.plugin)[owner_name]["claims"][cid])

                m.on_submit = on_submit
                return pl.send_form(m)

            if idx == 3:  # security (still opens the real security editor)
                return self._security_menu(pl, owner_name, cid, base_ref=base)

            if idx == 4:  # basemates
                return self._mates_menu(pl, owner_name, cid)

            if idx == 5:  # change ownership
                return self._prompt_change_owner(pl, owner_name, cid, base)

            if idx == 6:  # remove
                mf = MessageForm(
                    title="Delete Base",
                    content=f"Delete §e{name}§r owned by §e{owner_name}§r? This cannot be undone.",
                    button1="Delete",
                    button2="Cancel",
                )

                def on_submit(pp, bidx):
                    if bidx == 0:
                        for store in _all_player_stores(self.plugin):
                            b, ok, real_cid = _get_existing_base(store, owner_name, cid, base)
                            if b is None:
                                continue
                            try:
                                claims = store[ok]["claims"]
                                del claims[real_cid]
                            except Exception:
                                pass
                        _safe_bump_version(self.plugin);
                        _save_everywhere(self.plugin)
                        pp.send_message("§aBase deleted.")
                        return self._list_bases(pp, owner_name)
                    return self._base_details(pp, owner_name, cid, base)

                mf.on_submit = on_submit
                return pl.send_form(mf)

            return self._pick_base_owner(pl)

        f.on_submit = pick
        p.send_form(f)

    # ──────────────────────────────────────────────────────────────────────
    # Security menu: REUSE player Security UI for this base
    # ──────────────────────────────────────────────────────────────────────
    def _security_menu(self, p: Player, owner: str, cid: str, *, base_ref: Optional[dict] = None):
        """
        Open the same Security screen used by players (LandClaimUI._security)
        but targeted at the specified owner's base. The back button returns
        to our admin base details.
        """
        if _LCUI is None:
            # Fallback: old admin security if LandClaimUI isn't importable
            return self._fallback_security_menu(p, owner, cid)

        # Locate the claim in the MAIN plugin store (the one protection reads)
        claim, real_cid = _main_store_claim(self.plugin, owner, cid, base_ref)
        if not isinstance(claim, dict):
            try: p.send_message("§cCan't find that base in the main store.")
            except Exception: pass
            return self._base_details(p, owner, cid, base_ref or {})

        lc = _LCUI(self.plugin)

        # Monkey-patch LandClaimUI._base_menu so Back returns to admin UI
        def _back_to_admin(pp: Player, _claim_id: str = real_cid or cid, _claim: dict = claim):
            # Refresh admin copy for display
            base_admin = players_store(self.plugin).get(owner, {}).get("claims", {}).get(cid, base_ref or claim)
            return self._base_details(pp, owner, cid, base_admin)

        # Replace its _base_menu with our back target
        setattr(lc, "_base_menu", lambda pp, claim_id, claim_dict: _back_to_admin(pp))

        # Open the real Security UI
        return lc._security(p, real_cid or cid, claim)

    # Minimal fallback (kept in case LandClaimUI import fails)
    def _fallback_security_menu(self, p: Player, owner: str, cid: str):
        base = (players_store(self.plugin).get(owner, {}).get("claims", {}).get(cid, {})) or {}
        flags = base.get("flags", {}) or {}
        allow_build = bool(flags.get("allow_build", False))
        allow_interact = bool(flags.get("allow_interact", False))
        allow_kill = bool(flags.get("allow_kill_passive", False))
        sec_build, sec_interact, sec_kill = (not allow_build, not allow_interact, not allow_kill)

        def onoff(v: bool) -> str: return "§aON§r" if v else "§cOFF§r"
        lines = [
            "§lSecurity (ON = random players BLOCKED)",
            f"§7Break/place: {onoff(sec_build)}",
            f"§7Interact:    {onoff(sec_interact)}",
            f"§7Kill passive: {onoff(sec_kill)}",
        ]
        f = ActionForm(title="§lSecurity", content="\n".join(lines))
        f.add_button("Toggle break/place")
        f.add_button("Toggle interact")
        f.add_button("Toggle kill passive")
        f.add_button("Back")

        def pick(pl, idx):
            nonlocal sec_build, sec_interact, sec_kill
            if idx == 0: sec_build = not sec_build
            elif idx == 1: sec_interact = not sec_interact
            elif idx == 2: sec_kill = not sec_kill
            else:
                return self._base_details(pl, owner, cid, base)

            # Write both schemas to all stores
            kv = {
                "security_build": bool(sec_build), "allow_build":    not bool(sec_build),
                "security_interact": bool(sec_interact), "allow_interact": not bool(sec_interact),
                "security_kill_passive": bool(sec_kill), "allow_kill_passive": not bool(sec_kill),
            }
            _write_flags_all(self.plugin, owner, cid, base_ref=base, **kv)
            _save_everywhere(self.plugin)
            return self._fallback_security_menu(pl, owner, cid)

        f.on_submit = pick
        p.send_form(f)

    # ──────────────────────────────────────────────────────────────────────
    # Basemates editor
    # ──────────────────────────────────────────────────────────────────────
    def _mates_menu(self, p: Player, owner: str, cid: str):
        # Use admin store for listing (cosmetic), but writes go to all stores
        rec = players_store(self.plugin).setdefault(owner, {})
        claims = rec.setdefault("claims", {})
        base = claims.setdefault(cid, {})
        mates: List[str] = [str(m) for m in (base.get("mates") or [])]

        content = "Add or remove players who count as basemates (they bypass security)."
        content += "\n§7Current: §e" + (", ".join(mates) if mates else "none")

        f = ActionForm(title="§lBasemates", content=content)
        f.add_button("Add basemate")    # 0
        f.add_button("Remove basemate") # 1
        f.add_button("Back")            # 2

        def pick(pl, idx):
            if idx == 0:
                return self._mates_add_menu(pl, owner, cid)
            if idx == 1:
                return self._mates_remove_menu(pl, owner, cid)
            return self._base_details(pl, owner, cid, base)
        f.on_submit = pick
        p.send_form(f)

    def _mates_add_menu(self, p: Player, owner: str, cid: str):
        f = ActionForm(title="§lAdd Basemate", content="Choose how to add a player")
        f.add_button("Pick from ONLINE players")  # 0
        f.add_button("Type a name manually")      # 1
        f.add_button("Back")                      # 2

        def pick(pl, idx):
            if idx == 0:
                names = [player_name(x) for x in online_players(self.plugin)]
                if not names:
                    pl.send_message("§7No players online.")
                    return self._mates_add_menu(pl, owner, cid)
                g = ActionForm(title="§lOnline Players", content="Pick a player to add")
                for n in names: g.add_button(n)
                g.add_button("Back")
                def on_pick(pp, ii):
                    if ii is None or ii < 0 or ii >= len(names):
                        return self._mates_add_menu(pp, owner, cid)
                    self._add_mate(owner, cid, names[ii], base_ref=players_store(self.plugin)[owner]["claims"][cid])
                    _safe_bump_version(self.plugin); _save_everywhere(self.plugin)
                    try: pp.send_message(f"§aAdded basemate: §e{names[ii]}")
                    except Exception: pass
                    return self._mates_menu(pp, owner, cid)
                g.on_submit = on_pick
                return pl.send_form(g)

            if idx == 1:
                m = ModalForm(title="Add Basemate", submit_button="Add")
                m.add_control(TextInput("Player name", placeholder="Exact name", default_value=""))
                def on_submit(pp, data):
                    vals = parse_modal_values(data) or []
                    nm = str((vals or [""])[-1]).strip()
                    if nm:
                        self._add_mate(owner, cid, nm, base_ref=players_store(self.plugin)[owner]["claims"][cid])
                        _safe_bump_version(self.plugin); _save_everywhere(self.plugin)
                        try: pp.send_message(f"§aAdded basemate: §e{nm}")
                        except Exception: pass
                    return self._mates_menu(pp, owner, cid)
                m.on_submit = on_submit
                return pl.send_form(m)

            return self._mates_menu(pl, owner, cid)
        f.on_submit = pick
        p.send_form(f)

    def _mates_remove_menu(self, p: Player, owner: str, cid: str):
        base = players_store(self.plugin).setdefault(owner, {}).setdefault("claims", {}).setdefault(cid, {})
        mates: List[str] = [str(m) for m in (base.get("mates") or [])]

        if not mates:
            p.send_message("§7No basemates to remove.")
            return self._mates_menu(p, owner, cid)

        f = ActionForm(title="§lRemove Basemate", content="Pick a player to remove")
        for n in mates: f.add_button(n)
        f.add_button("Back")

        def pick(pl, idx):
            if idx is None or idx < 0 or idx >= len(mates):
                return self._mates_menu(pl, owner, cid)
            nm = mates[idx]
            mf = MessageForm(
                title="Remove Basemate",
                content=f"Remove §e{nm}§r from this base?",
                button1="Remove",
                button2="Cancel",
            )
            def on_submit(pp, which):
                if which == 0:
                    self._remove_mate(owner, cid, nm, base_ref=players_store(self.plugin)[owner]["claims"][cid])
                    _safe_bump_version(self.plugin); _save_everywhere(self.plugin)
                    try: pp.send_message(f"§aRemoved basemate: §e{nm}")
                    except Exception: pass
                return self._mates_menu(pp, owner, cid)
            mf.on_submit = on_submit
            return pl.send_form(mf)
        f.on_submit = pick
        p.send_form(f)

    def _add_mate(self, owner: str, cid: str, nm: str, *, base_ref: Optional[dict] = None):
        for store in _all_player_stores(self.plugin):
            b, ok, real_cid = _get_existing_base(store, owner, cid, base_ref)
            if b is None:
                continue
            mates: List[str] = [str(m) for m in (b.get("mates") or [])]
            if not any(str(m).lower() == nm.lower() for m in mates):
                mates.append(nm)
                b["mates"] = mates

    def _remove_mate(self, owner: str, cid: str, nm: str, *, base_ref: Optional[dict] = None):
        for store in _all_player_stores(self.plugin):
            b, ok, real_cid = _get_existing_base(store, owner, cid, base_ref)
            if b is None:
                continue
            mates: List[str] = [str(m) for m in (b.get("mates") or [])]
            b["mates"] = [m for m in mates if str(m).lower() != nm.lower()]

    # ──────────────────────────────────────────────────────────────────────
    # Ownership transfer
    # ──────────────────────────────────────────────────────────────────────
    def _prompt_change_owner(self, p: Player, current_owner: str, cid: str, base: dict):
        name = base.get("name", cid)
        m = ModalForm(title="Change Ownership", submit_button="Transfer")
        m.add_control(Label(f"Current owner: {current_owner}\nBase: {name} (id: {cid})"))
        m.add_control(TextInput("Type NEW owner's name", placeholder="PlayerName"))

        def on_submit(pp, data):
            vals = parse_modal_values(data) or []
            new_owner_raw = str((vals or [""])[-1]).strip()
            if not new_owner_raw:
                pp.send_message("§7No name entered.")
                return self._base_details(pp, current_owner, cid, base)

            new_owner_key, new_cid, ok = self._transfer_claim(current_owner, cid, new_owner_raw)
            if ok:
                pp.send_message(f"§aOwnership transferred to §e{new_owner_key}§a (id: §f{new_cid}§a).")
                return self._list_bases(pp, new_owner_key)
            else:
                pp.send_message("§cTransfer failed.")
                return self._base_details(pp, current_owner, cid, base)

        m.on_submit = on_submit
        p.send_form(m)

    def _transfer_claim(self, old_owner_in: str, cid: str, new_owner_in: str) -> tuple[str, str, bool]:
        stores = _all_player_stores(self.plugin)

        def _resolve_key(name: str, store: dict) -> str | None:
            nlow = str(name).lower()
            for k in list(store.keys()):
                try:
                    if str(k).lower() == nlow:
                        return k
                except Exception:
                    continue
            return None

        # Use the admin store as source of truth for lookup
        src = players_store(self.plugin)
        old_key = _resolve_key(old_owner_in, src) or old_owner_in
        claim = ((src.get(old_key, {}) or {}).get("claims", {}) or {}).get(cid)
        if not isinstance(claim, dict):
            return new_owner_in, cid, False

        # For each store, move/clone claim to new owner (new id if conflict)
        new_ids = {}
        for store in stores:
            ok = _resolve_key(old_key, store) or old_key
            cdata = ((store.get(ok, {}) or {}).get("claims", {}) or {}).get(cid) or claim

            nk = _resolve_key(new_owner_in, store) or new_owner_in
            dst_claims = store.setdefault(nk, {}).setdefault("claims", {})
            nid = cid
            i = 2
            while nid in dst_claims:
                nid = f"{cid}_{i}"; i += 1
            dst_claims[nid] = cdata
            try:
                # remove from old
                oc = store.get(ok, {}).get("claims", {})
                if cid in oc:
                    del oc[cid]
            except Exception:
                pass
            new_ids[nk] = nid

        _safe_bump_version(self.plugin); _save_everywhere(self.plugin)
        nk = list(new_ids.keys())[0]
        return nk, new_ids[nk], True
