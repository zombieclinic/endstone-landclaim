# src/endstone_landclaim/adminmenu/adminui.py
# Strict Endstone-friendly. No future annotations.

from typing import Optional
from endstone import Player
from endstone.form import ActionForm

from .spawn_settings import SpawnSettingsUI
from .landclaim_rules import LandclaimRulesUI
from .admin_manager import AdminManagerUI
from .view_players import ViewPlayersUI
from .item_editor import ItemEditorUI
from .commands_settings import CommandsSettingsUI   # ← existing
from .currency_settings import CurrencySettingsUI   # ← NEW

try:
    from .tp_settings import TPSettingsUI
except Exception:
    TPSettingsUI = None


class AdminUI:
    def __init__(self, plugin):
        self.plugin = plugin
        back = lambda p: self.open_root(p)

        # Core sections (these UIs accept back_fn)
        self.spawn_ui   = SpawnSettingsUI(plugin, back_fn=back)
        self.rules_ui   = LandclaimRulesUI(plugin, back_fn=back)
        self.admins_ui  = AdminManagerUI(plugin, back_fn=back)
        self.cmds_ui    = CommandsSettingsUI(plugin, back_fn=back)
        self.players_ui = ViewPlayersUI(plugin, back_fn=back)
        self.items_ui   = ItemEditorUI(plugin, back_fn=back)
        self.curr_ui    = CurrencySettingsUI(plugin, back_fn=back)   # ← NEW

        # Teleport Settings (constructor can vary across your files)
        self.tp_ui = None
        if TPSettingsUI:
            try:
                self.tp_ui = TPSettingsUI(plugin, back_fn=back)
            except TypeError:
                try:
                    self.tp_ui = TPSettingsUI(plugin)
                    for attr in ("set_back", "set_back_fn", "set_back_func", "set_back_callback"):
                        if hasattr(self.tp_ui, attr):
                            try: getattr(self.tp_ui, attr)(back)
                            except Exception: pass
                    if not hasattr(self.tp_ui, "back_fn"):
                        try: setattr(self.tp_ui, "back_fn", back)
                        except Exception: pass
                except Exception:
                    self.tp_ui = None

    # keep both names for compatibility
    def open(self, p: Player) -> None:
        self.open_root(p)

    def open_root(self, p: Player) -> None:
        f = ActionForm(title="§lAdmin", content="Pick a section")

        # Button order (stable indices)
        f.add_button("Spawn Settings")      # 0
        f.add_button("Landclaim Rules")     # 1
        f.add_button("Admin Manager")       # 2
        f.add_button("Command Settings")    # 3
        f.add_button("View Players")        # 4
        f.add_button("Item Editor")         # 5
        f.add_button("Currency Settings")   # 6  ← NEW

        has_tp = bool(self.tp_ui)
        if has_tp:
            f.add_button("Teleport Settings")  # 7
            close_idx = 8
        else:
            close_idx = 7
        f.add_button("Close")               # close_idx

        def pick(a: Player, idx: Optional[int]):
            if idx is None:
                return
            if idx == 0: return self.spawn_ui.open(a)
            if idx == 1: return self.rules_ui.open(a)
            if idx == 2: return self.admins_ui.open(a)
            if idx == 3: return self.cmds_ui.open(a)
            if idx == 4: return self.players_ui.open(a)
            if idx == 5: return self.items_ui.open(a)
            if idx == 6: return self.curr_ui.open(a)      # ← NEW
            if has_tp and idx == 7:
                try:
                    return self.tp_ui.open(a)
                except TypeError:
                    try:
                        return self.tp_ui.open(a, back_fn=lambda p: self.open_root(p))
                    except Exception:
                        pass
            # Close -> nothing
        f.on_submit = pick
        p.send_form(f)


# Back-compat alias
AdminMenu = AdminUI
