# endstone_landclaim/adminmenu/commands_settings.py
# Strict Endstone-friendly. No future annotations.

from typing import Optional
from endstone import Player
from endstone.form import ActionForm

from .shared import set_setting


class CommandsSettingsUI:
    def __init__(self, plugin, back_fn=None):
        self.plugin = plugin
        self._back = back_fn or (lambda p: None)

    def open(self, p: Player) -> None:
        s = dict(self.plugin.data.get("settings", {}))
        # True = admins only (default); False = everyone can use /landclaimui
        admin_only = bool(s.get("cmd_landclaimui_admin_only", True))
        allow_all = not admin_only

        status_color = "§a" if allow_all else "§c"
        status_word = "ON" if allow_all else "OFF"
        status_text = status_color + status_word + "§r"

        if allow_all:
            detail = (
                "§7Status: " + status_text +
                " §7(§aeveryone§7 can use /landclaimui.)"
            )
        else:
            detail = (
                "§7Status: " + status_text +
                " §7(only §eAdmins/OPs§7 can use /landclaimui.)"
            )

        lines = [
            "§7Configure who can use §e/landclaimui§7.",
            detail,
            "",
            "§8Click the button below to toggle."
        ]

        f = ActionForm(
            title="Command Settings",
            content="\n".join(lines),
        )

        # Toggle button: text is green ON or red OFF
        f.add_button(f"Allow everyone: {status_text}")
        f.add_button("Back")

        def on_submit(pp: Player, idx: Optional[int]):
            if idx is None or idx < 0:
                return self._back(pp)

            if idx == 0:
                # Flip the setting
                new_admin_only = not admin_only
                try:
                    set_setting(self.plugin, "cmd_landclaimui_admin_only", new_admin_only)
                except Exception:
                    # Fallback save path
                    self.plugin.data.setdefault("settings", {})["cmd_landclaimui_admin_only"] = new_admin_only
                    try:
                        self.plugin.write_json(
                            "admin_config.json",
                            self.plugin.data["settings"],
                        )
                    except Exception:
                        pass
                try:
                    pp.send_message("§aSaved command settings.")
                except Exception:
                    pass
                # Re-open to refresh colors/text
                return self.open(pp)

            # Back button
            return self._back(pp)

        f.on_submit = on_submit
        p.send_form(f)
