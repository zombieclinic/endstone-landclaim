from __future__ import annotations
from endstone import Player
from endstone.form import ActionForm, ModalForm, TextInput
from .shared import settings, set_setting, online_players, player_name, parse_modal_values

class AdminManagerUI:
    def __init__(self, plugin, back_fn=None):
        self.plugin = plugin
        self._back = back_fn or (lambda p: None)

    def open(self, p: Player):
        s = settings(self.plugin)
        admins = list(s.get("admins", []))
        content = "§7Admins bypass claim protections (but still see popups)."
        if admins:
            content += "\n§7Current: §e" + ", ".join(admins[:24]) + ("…" if len(admins) > 24 else "")
        f = ActionForm(title="§lAdmin Manager", content=content)
        f.add_button("Add admin (from online)")  # 0
        f.add_button("Add admin (type name)")    # 1
        f.add_button("Remove admin")             # 2
        f.add_button("Back")                     # 3

        def pick(pl, idx):
            if idx == 0:
                names = [player_name(x) for x in online_players(self.plugin)]
                if not names:
                    pl.send_message("§7No players online.")
                    return self.open(pl)
                g = ActionForm(title="§lOnline Players", content="Pick a player to add")
                for n in names: g.add_button(n)
                g.add_button("Back")
                def on_pick(pp, ii):
                    if ii is None or ii < 0 or ii >= len(names):
                        return self.open(pp)
                    nm = names[ii]
                    self._add_admin(nm)
                    pp.send_message(f"§aAdded admin: §e{nm}")
                    self.open(pp)
                g.on_submit = on_pick
                return pl.send_form(g)

            if idx == 1:
                m = ModalForm(title="Add Admin", submit_button="Add")
                m.add_control(TextInput("Player name", placeholder="Exact name", default_value=""))
                def on_submit(pp, data):
                    vals = parse_modal_values(data)
                    nm = str((vals or [""])[-1]).strip()
                    if not nm:
                        return self.open(pp)
                    self._add_admin(nm)
                    pp.send_message(f"§aAdded admin: §e{nm}")
                    return self.open(pp)
                m.on_submit = on_submit
                return pl.send_form(m)

            if idx == 2:
                admins2 = list(settings(self.plugin).get("admins", []))
                if not admins2:
                    pl.send_message("§7No admins to remove.")
                    return self.open(pl)
                g = ActionForm(title="§lRemove Admin", content="Pick a name to remove")
                for n in admins2: g.add_button(n)
                g.add_button("Back")
                def on_pick(pp, ii):
                    if ii is None or ii < 0 or ii >= len(admins2):
                        return self.open(pp)
                    nm = admins2[ii]
                    self._remove_admin(nm)
                    pp.send_message(f"§aRemoved admin: §e{nm}")
                    return self.open(pp)
                g.on_submit = on_pick
                return pl.send_form(g)

            if idx == 3:
                return self._back(pl)
        f.on_submit = pick
        p.send_form(f)

    def _add_admin(self, name: str):
        s = settings(self.plugin)
        admins = list(s.get("admins", []))
        if name not in admins:
            admins.append(name)
            set_setting(self.plugin, "admins", admins)

    def _remove_admin(self, name: str):
        s = settings(self.plugin)
        admins = [x for x in s.get("admins", []) if x != name]
        set_setting(self.plugin, "admins", admins)
