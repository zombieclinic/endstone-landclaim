from __future__ import annotations
from endstone import Player
from endstone.form import ActionForm, ModalForm, Label, TextInput

from .shared import (
    get_inventory, get_hand_stack, write_hand_stack, is_air, item_display_name,
    set_lore, rename_item, parse_modal_values,
    item_identifier, empty_slots, find_new_stack_after_give,
    get_damage, set_damage,
    copy_basic_meta, ensure_keep_on
)

# ── Enchant helpers using Endstone ItemMeta ────────────────────────────────
def read_enchants(stack) -> dict[str, int]:
    try:
        meta = stack.item_meta
        return dict(meta.enchants or {})
    except Exception:
        return {}

def write_enchants(stack, enchants: dict[str, int], *, force: bool = True) -> bool:
    try:
        meta = stack.item_meta
        try:
            meta.remove_enchants()
        except Exception:
            pass
        for ench_id, lvl in (enchants or {}).items():
            meta.add_enchant(str(ench_id), max(1, int(lvl)), force)
        stack.set_item_meta(meta)
        return True
    except Exception:
        return False

def add_enchant_any_level(stack, ench_id: str, level: int, *, force: bool = True) -> bool:
    try:
        meta = stack.item_meta
        ok = meta.add_enchant(str(ench_id), max(1, int(level)), force)
        if not ok:
            return False
        stack.set_item_meta(meta)
        return True
    except Exception:
        return False


class ItemEditorUI:
    def __init__(self, plugin, back_fn=None):
        self.plugin = plugin
        self._back = back_fn or (lambda p: None)

    def open(self, p: Player):
        inv = get_inventory(p)
        if not inv:
            try: p.send_message("§cCan't read your inventory.")
            except Exception: pass
            return self._back(p)

        stack, where = get_hand_stack(inv)
        if not stack or is_air(stack):
            try: p.send_message("§7Hold an item in your main hand first.")
            except Exception: pass
            return self._back(p)

        name = item_display_name(stack)
        cnt  = getattr(stack, "amount", None) or getattr(stack, "count", None) or 1

        f = ActionForm(title="§lItem Editor",
                       content=f"{name} ×{cnt}\n§7(Edits apply to the item in your hand)")
        f.add_button("Edit lore")                           # 0
        f.add_button("Rename")                              # 1
        f.add_button("Give keep-on-death PERFECT copy")     # 2
        f.add_button("Add/Set enchant (any lvl)")           # 3
        f.add_button("Back")                                # 4

        def pick(a, idx):
            if idx == 0:
                return self._edit_lore(a, inv, where)
            if idx == 1:
                return self._rename_item_ui(a, inv, where)
            if idx == 2:
                return self._give_keep_perfect(a, inv, where)
            if idx == 3:
                return self._edit_enchant(a, inv, where)
            if idx == 4:
                return self._back(a)
        f.on_submit = pick
        p.send_form(f)

    # ── Actions ─────────────────────────────────────────────────────────────
    def _edit_lore(self, p, inv, where):
        m = ModalForm(title="Set Lore (hand)", submit_button="Apply")
        m.add_control(Label("Tip: use \\n for a new line"))
        m.add_control(TextInput("Lore text", placeholder="Line 1\\nLine 2", default_value=""))

        def cb(pl, data):
            vals = parse_modal_values(data)
            raw = (vals or [""])[-1]
            text = str(raw or "").replace("\\r\\n", "\n").replace("\\n", "\n")
            lore_lines = [ln for ln in text.split("\n") if ln] if text else None

            stack, _ = get_hand_stack(inv)
            if not stack or is_air(stack):
                pl.send_message("§7No item in hand.")
                return self.open(pl)

            if set_lore(stack, lore_lines) and write_hand_stack(inv, stack, where):
                try: pl.send_popup("§aLore updated.")
                except Exception: pl.send_message("§aLore updated.")
            else:
                pl.send_message("§cFailed to set lore on this build.")
            self.open(pl)

        m.on_submit = cb
        p.send_form(m)

    def _rename_item_ui(self, p, inv, where):
        m = ModalForm(title="Rename (hand)", submit_button="Apply")
        m.add_control(TextInput("New name", placeholder="My Sword", default_value=""))

        def cb(pl, data):
            vals = parse_modal_values(data)
            new_name = str((vals or [""])[-1]).strip()[:64]
            if not new_name:
                return self.open(pl)
            stack, _ = get_hand_stack(inv)
            if not stack or is_air(stack):
                pl.send_message("§7No item in hand.")
                return self.open(pl)
            if rename_item(stack, new_name) and write_hand_stack(inv, stack, where):
                try: pl.send_popup("§aName updated.")
                except Exception: pl.send_message("§aName updated.")
            else:
                pl.send_message("§cFailed to rename on this build.")
            self.open(pl)

        m.on_submit = cb
        p.send_form(m)

    def _give_keep_perfect(self, p: Player, inv, where):
        src, _ = get_hand_stack(inv)
        if not src or is_air(src):
            p.send_message("§7No item in hand.")
            return self.open(p)

        ident = item_identifier(src)
        if not ident:
            p.send_message("§cCouldn't resolve item id for /give.")
            return self.open(p)

        before_empty = empty_slots(inv)

        cmd = f'give @s {ident} 1 0 {{"minecraft:keep_on_death":{{}}}}'
        try:
            if hasattr(p, "perform_command"):
                p.perform_command(cmd)
            else:
                srv = getattr(self.plugin, "server", None)
                if srv and hasattr(srv, "dispatch_command"):
                    srv.dispatch_command(p, cmd)
                else:
                    p.send_message("§7Run: /" + cmd)
                    return self.open(p)
        except Exception:
            p.send_message("§cFailed to run /give on this build.")
            return self.open(p)

        new_stack, new_slot = find_new_stack_after_give(inv, before_empty, ident)
        if not new_stack:
            p.send_message("§eGave keep-on-death item. Couldn’t auto-match stack to copy meta.")
            return self.open(p)

        try:
            copy_basic_meta(src, new_stack)
            enc = read_enchants(src)
            if enc:
                write_enchants(new_stack, enc, force=True)
            dmg = get_damage(src)
            if dmg is not None:
                set_damage(new_stack, dmg)
            ensure_keep_on(new_stack)
            p.send_message("§aPerfect copy created with keep-on-death.")
        except Exception:
            p.send_message("§eGave item, but copying full meta only partially succeeded.")

        return self.open(p)

    def _edit_enchant(self, p, inv, where):
        m = ModalForm(title="Add/Set Enchant", submit_button="Apply")
        m.add_control(Label("Enter a Minecraft enchant key (e.g. minecraft:unbreaking) and level"))
        m.add_control(TextInput("Enchant key", placeholder="minecraft:unbreaking",
                                default_value="minecraft:unbreaking"))
        m.add_control(TextInput("Level", placeholder="10", default_value="10"))

        def cb(pl, data):
            vals = parse_modal_values(data) or []
            if len(vals) < 2:
                return self.open(pl)
            key = str(vals[-2] or "").strip()
            try:
                lvl = int(float(str(vals[-1]).strip()))
            except Exception:
                lvl = 1
            lvl = max(1, lvl)

            stack, _ = get_hand_stack(inv)
            if not stack or is_air(stack):
                pl.send_message("§7No item in hand.")
                return self.open(pl)

            ok = add_enchant_any_level(stack, key, lvl, force=True) and write_hand_stack(inv, stack, where)
            if ok:
                try: pl.send_popup(f"§aEnchant set: §e{key} {lvl}")
                except Exception: pl.send_message(f"§aEnchant set: §e{key} {lvl}")
            else:
                pl.send_message("§cFailed to add enchant on this build.")
            self.open(pl)

        m.on_submit = cb
        p.send_form(m)
