# src/endstone_landclaim/adminmenu/tp_settings.py
# Strict Endstone-friendly. No future annotations.

from typing import Optional, List, Dict, Tuple, Any
from endstone import Player
from endstone.form import ActionForm, ModalForm, Label, TextInput

from .shared import settings, set_setting, parse_modal_values


class TPSettingsUI:
    """
    Teleporter / Economy settings editor + admin tools.

    Keys:
      - economy_tpCommunityCost   # Spawn, Random, Community list, basemates bases
      - economy_tpPrivateCost     # Base teleports (your / base-owner bases)
      - economy_tpPlayerCost      # TP request cost (charged on accept)

    Admin tools share the same teleporters.json used by TeleporterUI.
    """

    def __init__(self, plugin, back_fn=None):
        self.plugin = plugin
        self._back = back_fn or (lambda p: None)

    # ======================================================================
    #                       MAIN SETTINGS MENU
    # ======================================================================

    def open(self, p: Player) -> None:
        s = settings(self.plugin)
        community = int(float(str(s.get("economy_tpCommunityCost", 0))))
        private   = int(float(str(s.get("economy_tpPrivateCost",   0))))
        player    = int(float(str(s.get("economy_tpPlayerCost",    0))))

        body = [
            "§lTeleporter / Economy Settings",
            f"§7Community TP cost (Spawn/Random/Community): §e{community}",
            f"§7Private TP cost (Base teleports):          §e{private}",
            f"§7Player request cost (TP ask → accept):     §e{player}",
            "",
            "§8Admin tools are at the bottom."
        ]

        f = ActionForm(title="§lTeleport Settings", content="\n".join(body))
        f.add_button("Edit Prices (Community / Private / Player)")  # 0
        f.add_button("View Players' Teleporters")                   # 1
        f.add_button("Back")                                        # 2

        def pick(pl: Player, idx: Optional[int]):
            if idx == 0:
                return self._edit_prices(pl, community, private, player)
            if idx == 1:
                return self._view_players(pl)
            return self._back(pl)

        f.on_submit = pick
        p.send_form(f)

    # ---------- price editor (three fields) ----------
    def _edit_prices(self, p: Player, community: int, private: int, player: int) -> None:
        m = ModalForm(title="Teleport Prices", submit_button="Save")
        m.add_control(Label("Enter non-negative integers."))
        m.add_control(TextInput(
            "Community TP cost (Spawn/Random/Community list)",
            default_value=str(community)
        ))
        m.add_control(TextInput(
            "Private TP cost (Base teleports)",
            default_value=str(private)
        ))
        m.add_control(TextInput(
            "Player request cost (TP ask → accept)",
            default_value=str(player)
        ))

        def on_submit(pp: Player, data):
            vals = parse_modal_values(data) or []

            # We expect [label, community, private, player]
            try:
                com = max(0, int(float(str(vals[-3]))))
            except Exception:
                com = community
            try:
                prv = max(0, int(float(str(vals[-2]))))
            except Exception:
                prv = private
            try:
                ply = max(0, int(float(str(vals[-1]))))
            except Exception:
                ply = player

            set_setting(self.plugin, "economy_tpCommunityCost", com)
            set_setting(self.plugin, "economy_tpPrivateCost",   prv)
            set_setting(self.plugin, "economy_tpPlayerCost",    ply)

            try:
                pp.send_message("§aSaved teleport prices.")
            except Exception:
                pass
            self.open(pp)

        m.on_submit = on_submit
        p.send_form(m)

    # ======================================================================
    #                     ADMIN: VIEW / EDIT OWNERS
    # ======================================================================

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

    def _parse_pos_key(self, key: str) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[int]]:
        try:
            level_name, rest = key.split(":", 1)
            x, y, z = rest.split(",", 2)
            return level_name, int(x), int(y), int(z)
        except Exception:
            return None, None, None, None

    def _fmt_pos(self, key: str) -> str:
        lvl, x, y, z = self._parse_pos_key(key)
        if lvl is None:
            return key or "?"
        return f"{lvl}: {x} {y} {z}"

    def _online_names(self) -> List[str]:
        sv = getattr(self.plugin, "server", None)
        if not sv:
            return []
        for meth in ("get_players", "get_online_players"):
            fn = getattr(sv, meth, None)
            if callable(fn):
                try:
                    return [
                        str(getattr(p, "name", ""))
                        for p in (fn() or [])
                        if getattr(p, "name", None)
                    ]
                except Exception:
                    pass
        for attr in ("players", "online_players"):
            try:
                arr = getattr(sv, attr, None)
                if isinstance(arr, (list, tuple, set)):
                    return [
                        str(getattr(p, "name", ""))
                        for p in arr
                        if getattr(p, "name", None)
                    ]
            except Exception:
                pass
        return []

    def _find_owner_key(self, owners: Dict[str, str], name: str) -> Optional[str]:
        nl = str(name).lower()
        for k in owners.keys():
            try:
                if str(k).lower() == nl:
                    return k
            except Exception:
                continue
        return None

    def _reassign_owner(self, store: Dict[str, Any], pos_key: str, new_owner: str) -> None:
        claimed = store.setdefault("claimed", {})
        owners  = store.setdefault("owners", {})

        old_owner = claimed.get(pos_key)
        if old_owner:
            try:
                if owners.get(old_owner) == pos_key:
                    del owners[old_owner]
            except Exception:
                pass

        existing_key_name = self._find_owner_key(owners, new_owner)
        if existing_key_name is None:
            existing_key_name = new_owner

        prev_pos = owners.get(existing_key_name)
        if prev_pos and prev_pos != pos_key:
            try:
                if claimed.get(prev_pos):
                    del claimed[prev_pos]
            except Exception:
                pass

        claimed[pos_key] = existing_key_name
        owners[existing_key_name] = pos_key

        self._save_tp_store(store)
        try:
            self.plugin.logger.info(
                f"[TPSettingsUI] Reassigned teleporter {pos_key} -> "
                f"{existing_key_name} (from {old_owner})"
            )
        except Exception:
            pass

    def _remove_owner(self, store: Dict[str, Any], pos_key: str) -> None:
        claimed = store.setdefault("claimed", {})
        owners  = store.setdefault("owners", {})
        old_owner = claimed.get(pos_key)
        try:
            if old_owner and owners.get(old_owner) == pos_key:
                del owners[old_owner]
        except Exception:
            pass
        try:
            if pos_key in claimed:
                del claimed[pos_key]
        except Exception:
            pass
        self._save_tp_store(store)

    def _view_players(self, p: Player) -> None:
        store = self._load_tp_store()
        owners: Dict[str, str] = store.get("owners", {}) or {}
        if not owners:
            f = ActionForm(
                title="§lPlayers' Teleporters",
                content="§7No teleporters are registered."
            )
            f.add_button("Back")

            def back(pl, _):
                self.open(pl)

            f.on_submit = back
            return p.send_form(f)

        rows: List[Tuple[str, str]] = []
        try:
            for owner, key in owners.items():
                rows.append((str(owner), str(key)))
        except Exception:
            pass
        rows.sort(key=lambda t: t[0].lower())

        lines = ["§lPlayers' Teleporters", ""]
        show = rows[:16]
        for owner, key in show:
            lines.append(f"§e{owner}§7 → §b{self._fmt_pos(key)}")
        if len(rows) > len(show):
            lines.append(f"§8… and {len(rows) - len(show)} more")

        f = ActionForm(title="§lPlayers' Teleporters", content="\n".join(lines))
        for owner, _ in rows:
            f.add_button(owner)
        f.add_button("Back")

        def pick(pl: Player, idx: Optional[int]):
            if idx is None or idx < 0:
                return self.open(pl)
            if idx >= len(rows):
                return self.open(pl)
            owner, key = rows[idx]
            return self._owner_detail(pl, owner, key)

        f.on_submit = pick
        p.send_form(f)

    def _owner_detail(self, p: Player, owner: str, pos_key: str) -> None:
        content = [
            "§lTeleporter Owner",
            f"§7Owner: §e{owner}",
            f"§7Block: §b{self._fmt_pos(pos_key)}",
            "",
            "§7Pick an action:",
        ]
        from endstone.form import (
            ActionForm as _AF,
            ModalForm as _MF,
            Label as _LB,
            TextInput as _TI,
            MessageForm as _MSG,
        )

        f = _AF(title="§lTeleporter Details", content="\n".join(content))
        f.add_button("Change owner (pick online)")  # 0
        f.add_button("Change owner (type name)")    # 1
        f.add_button("Remove owner")                # 2
        f.add_button("Back")                        # 3

        def pick(pl: Player, idx: Optional[int]):
            if idx == 0:
                return self._change_owner_pick_online(pl, pos_key)
            if idx == 1:
                return self._change_owner_type(pl, pos_key)
            if idx == 2:
                return self._confirm_remove(pl, owner, pos_key)
            return self._view_players(pl)

        f.on_submit = pick
        p.send_form(f)

    def _change_owner_pick_online(self, p: Player, pos_key: str) -> None:
        names = [n for n in self._online_names()]
        if not names:
            try:
                p.send_message("§7No players online.")
            except Exception:
                pass
            return self._owner_detail_from_key(p, pos_key)

        f = ActionForm(
            title="§lPick New Owner",
            content="Choose a player to assign this teleporter to."
        )
        for n in names:
            f.add_button(n)
        f.add_button("Back")

        def pick(pl: Player, idx: Optional[int]):
            if idx is None or idx < 0 or idx >= len(names):
                return self._owner_detail_from_key(pl, pos_key)
            new_owner = names[idx]
            self._apply_change_owner(pl, pos_key, new_owner)

        f.on_submit = pick
        p.send_form(f)

    def _change_owner_type(self, p: Player, pos_key: str) -> None:
        m = ModalForm(title="Type New Owner", submit_button="Assign")
        m.add_control(Label(
            "Enter an exact player name. If they already have a teleporter, "
            "their old one will be unclaimed."
        ))
        m.add_control(TextInput("Player name", placeholder="Player123", default_value=""))

        def on_submit(pl: Player, data):
            vals = parse_modal_values(data) or []
            new_owner = str((vals or [""])[-1]).strip()
            if not new_owner:
                try:
                    pl.send_message("§cName required.")
                except Exception:
                    pass
                return self._owner_detail_from_key(pl, pos_key)
            self._apply_change_owner(pl, pos_key, new_owner)

        m.on_submit = on_submit
        p.send_form(m)

    def _apply_change_owner(self, p: Player, pos_key: str, new_owner: str) -> None:
        store = self._load_tp_store()
        self._reassign_owner(store, pos_key, new_owner)
        try:
            p.send_message(
                f"§aAssigned {self._fmt_pos(pos_key)} to §e{new_owner}§a."
            )
        except Exception:
            pass
        self._owner_detail_from_key(p, pos_key)

    def _confirm_remove(self, p: Player, owner: str, pos_key: str) -> None:
        m = ModalForm(title="Remove Owner", submit_button="Remove")
        m.add_control(Label(
            f"This will unclaim §b{self._fmt_pos(pos_key)}§r from §e{owner}§r."
        ))
        m.add_control(Label("Are you sure? (Only the saved owner entry is removed.)"))

        def on_submit(pl: Player, _data):
            store = self._load_tp_store()
            self._remove_owner(store, pos_key)
            try:
                pl.send_message("§aTeleporter owner removed.")
            except Exception:
                pass
            self._view_players(pl)

        m.on_submit = on_submit
        p.send_form(m)

    def _owner_detail_from_key(self, p: Player, pos_key: str) -> None:
        store = self._load_tp_store()
        owner = (store.get("claimed", {}) or {}).get(pos_key)
        if not owner:
            return self._view_players(p)
        return self._owner_detail(p, owner, pos_key)
