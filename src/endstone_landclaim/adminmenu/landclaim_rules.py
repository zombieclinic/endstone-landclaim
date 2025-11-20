# src/endstone_landclaim/adminmenu/landclaim_rules.py
# Strict Endstone-friendly. No future annotations.

from __future__ import annotations

from endstone import Player
from endstone.form import ActionForm, ModalForm, Label, TextInput

from .shared import settings, set_setting, parse_modal_values


class LandclaimRulesUI:
    def __init__(self, plugin, back_fn=None):
        self.plugin = plugin
        self._back = back_fn or (lambda p: None)

    def open(self, p: Player):
        s = settings(self.plugin)

        start_fb = int(s.get("lc_start_first_base_radius", 500))
        start_ob = int(s.get("lc_start_other_base_radius", 100))
        fb_max = int(s.get("lc_first_base_radius_cap", 500))
        ob_max = int(s.get("lc_other_base_radius_cap", 250))
        buf = int(s.get("lc_min_distance_between_bases", 200))
        price = int(s.get("land_price_per_50", 1000))
        max_b = int(s.get("lc_max_bases", 3))

        body = [
            "§lLandclaim Rules",
            f"§7Start first base radius: §e{start_fb}",
            f"§7Start other base radius: §e{start_ob}",
            f"§7First base max radius: §e{fb_max}",
            f"§7Other base max radius: §e{ob_max}",
            f"§7Min distance between bases (edge→edge): §e{buf}",
            f"§7Buy land price (per +50): §e{price}",
            f"§7Max bases per player: §e{max_b}",
        ]

        f = ActionForm(title="§lLandclaim Rules", content="\n".join(body))
        f.add_button("Set start first base radius")     # 0
        f.add_button("Set start other base radius")     # 1
        f.add_button("Set max radius for first base")   # 2
        f.add_button("Set max radius for other bases")  # 3
        f.add_button("Set distance between bases")      # 4
        f.add_button("Set buy land price (per +50)")    # 5
        f.add_button("Set max bases per player")        # 6
        f.add_button("Back")                            # 7

        def pick(pl, idx):
            if idx == 0:
                return self._prompt_step50(
                    pl,
                    "Start first base radius",
                    start_fb,
                    lambda v: set_setting(
                        self.plugin, "lc_start_first_base_radius", max(0, v)
                    ),
                )
            if idx == 1:
                return self._prompt_step50(
                    pl,
                    "Start other base radius",
                    start_ob,
                    lambda v: set_setting(
                        self.plugin, "lc_start_other_base_radius", max(0, v)
                    ),
                )
            if idx == 2:
                return self._prompt_step50(
                    pl,
                    "First base max radius",
                    fb_max,
                    lambda v: set_setting(
                        self.plugin, "lc_first_base_radius_cap", max(0, v)
                    ),
                )
            if idx == 3:
                return self._prompt_step50(
                    pl,
                    "Other base max radius",
                    ob_max,
                    lambda v: set_setting(
                        self.plugin, "lc_other_base_radius_cap", max(0, v)
                    ),
                )
            if idx == 4:
                return self._prompt_int(
                    pl,
                    "Distance between bases (edge→edge)",
                    buf,
                    lambda v: set_setting(
                        self.plugin, "lc_min_distance_between_bases", max(0, v)
                    ),
                )
            if idx == 5:
                return self._prompt_int(
                    pl,
                    "Buy land price (per +50)",
                    price,
                    lambda v: set_setting(
                        self.plugin, "land_price_per_50", max(0, v)
                    ),
                )
            if idx == 6:
                return self._prompt_int(
                    pl,
                    "Max bases per player",
                    max_b,
                    lambda v: set_setting(
                        self.plugin, "lc_max_bases", max(0, v)
                    ),
                )
            if idx == 7:
                return self._back(pl)

        f.on_submit = pick
        p.send_form(f)

    # ---- number helpers ----
    def _prompt_int(self, p: Player, title: str, current: int, setter):
        m = ModalForm(title=title, submit_button="Save")
        m.add_control(Label(f"Current: {current}"))
        m.add_control(TextInput("Enter a number", default_value=str(current)))

        def on_submit(admin, data):
            vals = parse_modal_values(data)
            if not vals:
                return self.open(admin)
            try:
                v = int(float(str(vals[-1]).strip()))
            except Exception:
                v = current
            setter(v)
            try:
                admin.send_message("§aSaved.")
            except Exception:
                pass
            self.open(admin)

        m.on_submit = on_submit
        p.send_form(m)

    def _prompt_step50(self, p: Player, title: str, current: int, setter):
        m = ModalForm(title=title, submit_button="Save")
        m.add_control(
            Label(f"Current: {current}\nValue will be rounded to the nearest 50.")
        )
        m.add_control(
            TextInput(
                "Enter radius (multiple of 50 preferred)", default_value=str(current)
            )
        )

        def on_submit(admin, data):
            vals = parse_modal_values(data)
            if not vals:
                return self.open(admin)
            try:
                v = int(float(str(vals[-1]).strip()))
            except Exception:
                v = current
            v = max(0, (v // 50) * 50)
            setter(v)
            try:
                admin.send_message("§aSaved.")
            except Exception:
                pass
            self.open(admin)

        m.on_submit = on_submit
        p.send_form(m)
