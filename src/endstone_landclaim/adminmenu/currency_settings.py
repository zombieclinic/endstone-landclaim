# src/endstone_landclaim/adminmenu/currency_settings.py
# Strict Endstone-friendly. No future annotations.

from typing import Any, Dict, List
from endstone import Player
from endstone.form import ActionForm, ModalForm, Label, TextInput


def _settings(plugin) -> Dict[str, Any]:
    try:
        return dict(plugin.data.get("settings", {}))
    except Exception:
        return {}


def _set_setting(plugin, key: str, value: Any) -> None:
    try:
        d = dict(plugin.data)
    except Exception:
        d = {}
    s = dict(d.get("settings", {}))
    s[key] = value
    d["settings"] = s
    try:
        plugin.data = d
    except Exception:
        pass

    # best-effort save; plugin can implement any of these
    for m in ("save_data", "save", "persist", "write_data", "write_json"):
        fn = getattr(plugin, m, None)
        if callable(fn):
            try:
                fn()
                break
            except Exception:
                continue


def _parse_modal_values(data: Any) -> List[Any]:
    if isinstance(data, list):
        return list(data)
    try:
        import json
        v = json.loads(data) if isinstance(data, str) else []
        return v if isinstance(v, list) else []
    except Exception:
        return []


class CurrencySettingsUI:
    """
    Admin → Currency settings (name only).

    Saves in settings:
      - currency_name : str   (default "Currency")

    Teleporter / Land-claim UIs can read this and display the name instead of a
    hard-coded "ZCoins" (e.g., "Mana", "Credits", etc.). No economy logic,
    no scoreboards, no webhooks.
    """

    def __init__(self, plugin, back_fn=None):
        self.plugin = plugin
        self._back = back_fn or (lambda p: None)

    def open(self, p: Player) -> None:
        s = _settings(self.plugin)
        name = str(s.get("currency_name", "Currency"))

        lines = [
            "§lCurrency Settings",
            "",
            f"§7Current name: §e{name}",
            "",
            "§8This name is shown in Teleporter / Land-claim menus.",
        ]
        f = ActionForm(title="§lCurrency", content="\n".join(lines))
        f.add_button("Set currency name")  # 0
        f.add_button("Back")               # 1

        def pick(pl: Player, idx: int):
            if idx == 0:
                return self._set_name(pl, name)
            return self._back(pl)

        f.on_submit = pick
        p.send_form(f)

    # ---- name ----
    def _set_name(self, p: Player, current: str) -> None:
        m = ModalForm(title="Currency Name", submit_button="Save")
        m.add_control(Label("Shown in menus and confirmations (e.g., Mana, Credits)."))
        m.add_control(TextInput("Name", default_value=current or "Currency"))

        def on_submit(pp: Player, data):
            vals = _parse_modal_values(data) or []
            nm = str((vals or [""])[-1]).strip() or current or "Currency"

            _set_setting(self.plugin, "currency_name", nm)

            try:
                pp.send_message(f"§aCurrency name set to §e{nm}§a.")
            except Exception:
                pass

            self.open(pp)

        m.on_submit = on_submit
        p.send_form(m)
