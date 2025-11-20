from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, Set
import json

# ─────────────────────────────────────────────────────────────────────────────
# Settings + persistence
# ─────────────────────────────────────────────────────────────────────────────

def settings(plugin) -> Dict[str, Any]:
    st = plugin.data.get("settings")
    if not isinstance(st, dict):
        st = {}
        plugin.data["settings"] = st
    return st


def set_setting(plugin, key: str, value):
    st = settings(plugin)
    st[key] = value
    plugin.data["settings"] = st
    # Best-effort: save wherever possible
    try:
        adm = getattr(plugin, "admin", None)
        if adm and hasattr(adm, "_save"):
            adm.data = adm.data or {}
            adm.data.setdefault("settings", {}).update({key: value})
            adm._save()
    except Exception:
        pass
    for meth in (
        "write_json",
        "save_config",
        "save_players",
        "_save_players",
        "_save_claims",
    ):
        fn = getattr(plugin, meth, None)
        try:
            if meth == "write_json":
                fn("admin_config.json", st)
            elif callable(fn):
                fn()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Modal parsing (robust across forks)
# ─────────────────────────────────────────────────────────────────────────────

def parse_modal_values(payload) -> List[Any]:
    try:
        if isinstance(payload, list):
            return payload

        if hasattr(payload, "form_values") and payload.form_values is not None:
            return payload.form_values

        if hasattr(payload, "response") and isinstance(payload.response, str):
            arr = json.loads(payload.response or "[]")
            return arr if isinstance(arr, list) else []

        if isinstance(payload, dict):
            vals = (
                payload.get("formValues")
                or payload.get("values")
                or payload.get("form_values")
            )
            if vals is not None:
                return vals
            if isinstance(payload.get("response"), str):
                arr = json.loads(payload["response"] or "[]")
                return arr if isinstance(arr, list) else []

        if isinstance(payload, str):
            arr = json.loads(payload or "[]")
            return arr if isinstance(arr, list) else []
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Players + server utilities
# ─────────────────────────────────────────────────────────────────────────────

def players_store(plugin) -> Dict[str, Any]:
    return plugin.data.setdefault("players", {})


def online_players(plugin) -> List[Any]:
    out = []
    for path in [
        ("server", "get_online_players"),
        ("server", "online_players"),
        ("get_server",),
    ]:
        cur = plugin
        ok = True
        for seg in path:
            cur = getattr(cur, seg, None)
            if cur is None:
                ok = False
                break
            if callable(cur) and seg.startswith("get_"):
                cur = cur()
        if not ok:
            continue
        try:
            lst = cur() if callable(cur) else cur
            if lst:
                out = list(lst)
            if out:
                break
        except Exception:
            pass
    return list(out or [])


def player_name(pl) -> str:
    try:
        return str(
            getattr(pl, "name", None)
            or getattr(pl, "get_name", lambda: "")()
            or "player"
        )
    except Exception:
        return "player"


# ─────────────────────────────────────────────────────────────────────────────
# Inventory helpers (portable across forks)
# ─────────────────────────────────────────────────────────────────────────────

def get_inventory(pl):
    for attr in ("inventory", "get_inventory"):
        try:
            inv = getattr(pl, attr)
            inv = inv() if callable(inv) else inv
            if inv:
                return inv
        except Exception:
            pass
    return None


def get_ender(pl):
    for attr in ("ender_chest", "get_ender_chest", "enderchest", "get_enderchest"):
        try:
            ed = getattr(pl, attr)
            ed = ed() if callable(ed) else ed
            if ed:
                return ed
        except Exception:
            pass
    return None


def inv_size(inv):
    for attr in ("size", "get_size"):
        try:
            v = getattr(inv, attr)
            return int(v() if callable(v) else v)
        except Exception:
            pass
    return 36


def get_item_from_slot(inv, slot):
    for name in ("get_item", "getItem"):
        if hasattr(inv, name):
            try:
                return getattr(inv, name)(slot)
            except Exception:
                pass
    for arr_name in ("items", "contents"):
        if hasattr(inv, arr_name):
            try:
                arr = getattr(inv, arr_name)
                if isinstance(arr, (list, tuple)) and 0 <= slot < len(arr):
                    return arr[slot]
            except Exception:
                pass
    return None


def set_item_in_slot(inv, slot, item):
    for name in ("set_item", "setItem"):
        if hasattr(inv, name):
            try:
                getattr(inv, name)(slot, item)
                return True
            except Exception:
                pass
    if item is None and hasattr(inv, "clear"):
        try:
            inv.clear(slot)
            return True
        except Exception:
            pass
    return False


def add_item(inv, item):
    for name in ("add_item", "addItem"):
        if hasattr(inv, name):
            try:
                getattr(inv, name)(item)
                return True
            except Exception:
                pass
    size = inv_size(inv)
    for i in range(size):
        if not get_item_from_slot(inv, i):
            if set_item_in_slot(inv, i, item):
                return True
    return False


def is_air(stack):
    try:
        t = getattr(stack, "type", None) or getattr(stack, "material", None)
        tid = getattr(t, "id", None) or getattr(t, "name", None)
        return tid in (None, "minecraft:air", "air") or getattr(
            stack, "amount", 1
        ) <= 0
    except Exception:
        return True


def item_display_name(stack):
    try:
        meta = getattr(stack, "item_meta", None)
        if meta:
            dn = getattr(meta, "display_name", None) or getattr(meta, "name", None)
            if dn:
                return str(dn)
    except Exception:
        pass
    cn = getattr(stack, "custom_name", None)
    if cn:
        return str(cn)
    t = getattr(stack, "type", None) or getattr(stack, "material", None)
    if t:
        for attr in ("id", "name", "key", "identifier"):
            v = getattr(t, attr, None)
            if v:
                return str(v)
    for attr in ("type_id", "id", "identifier", "namespace_id"):
        v = getattr(stack, attr, None)
        if v:
            return str(v)
    try:
        return str(stack)
    except Exception:
        return "unknown_item"


def get_hand_stack(inv):
    try:
        s = getattr(inv, "item_in_main_hand", None)
        if s:
            return s, ("write_mainhand", None)
    except Exception:
        pass
    slot_index = getattr(inv, "held_item_slot", 0)
    try:
        s = get_item_from_slot(inv, slot_index)
        return s, ("slot", slot_index)
    except Exception:
        return None, ("slot", 0)


def write_hand_stack(inv, stack, where):
    kind, idx = where
    try:
        if kind == "write_mainhand":
            inv.item_in_main_hand = stack
            return True
        if kind == "slot":
            return set_item_in_slot(inv, int(idx or 0), stack)
    except Exception:
        pass
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Item identity + meta helpers
# ─────────────────────────────────────────────────────────────────────────────

def item_identifier(stack) -> Optional[str]:
    t = getattr(stack, "type", None) or getattr(stack, "material", None)
    for attr in ("identifier", "id", "name", "key", "namespace_id"):
        if t is not None:
            v = getattr(t, attr, None)
            if v and isinstance(v, str):
                ident = v.strip()
                if ident and ":" not in ident:
                    ident = f"minecraft:{ident}"
                return ident
    for attr in ("identifier", "namespace_id", "type_id", "id", "name"):
        v = getattr(stack, attr, None)
        if v and isinstance(v, str):
            ident = v.strip()
            if ident and ":" not in ident:
                ident = f"minecraft:{ident}"
            return ident
    return None


def deep_copy_item(stack):
    # Try clone/copy methods provided by the stack first
    for m in ("clone", "copy", "duplicate"):
        fn = getattr(stack, m, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    # Fallback: Python deepcopy (may not work on native objects)
    try:
        import copy as _cpy
        return _cpy.deepcopy(stack)
    except Exception:
        return None


def get_damage(stack) -> Optional[int]:
    for attr in ("damage", "get_damage", "durability", "get_durability"):
        v = getattr(stack, attr, None)
        try:
            return int(v() if callable(v) else v)
        except Exception:
            pass
    # Sometimes damage sits on meta
    meta = getattr(stack, "item_meta", None)
    if meta:
        for attr in ("damage", "get_damage", "durability", "get_durability"):
            v = getattr(meta, attr, None)
            try:
                return int(v() if callable(v) else v)
            except Exception:
                pass
    return None


def set_damage(stack, dmg: int) -> bool:
    for attr in ("set_damage", "damage", "set_durability", "durability"):
        fn = getattr(stack, attr, None)
        try:
            if callable(fn):
                fn(int(dmg))
                return True
            else:
                setattr(stack, attr, int(dmg))
                return True
        except Exception:
            pass
    # meta path
    meta = getattr(stack, "item_meta", None)
    if meta:
        for attr in ("set_damage", "damage", "set_durability", "durability"):
            fn = getattr(meta, attr, None)
            try:
                if callable(fn):
                    fn(int(dmg))
                else:
                    setattr(meta, attr, int(dmg))
                if hasattr(stack, "set_item_meta"):
                    stack.set_item_meta(meta)
                else:
                    stack.item_meta = meta
                return True
            except Exception:
                pass
    return False


def read_enchants(stack) -> Dict[str, int]:
    # Prefer meta
    meta = getattr(stack, "item_meta", None)
    enc = getattr(meta, "enchantments", None) if meta is not None else None
    if isinstance(enc, dict):
        try:
            return {str(k): int(v) for k, v in enc.items()}
        except Exception:
            pass
    # Fall back to item-level map
    enc2 = getattr(stack, "enchantments", None)
    if isinstance(enc2, dict):
        try:
            return {str(k): int(v) for k, v in enc2.items()}
        except Exception:
            pass
    return {}


def write_enchants(stack, mapping: Dict[str, int]) -> bool:
    # Try via meta map write-through
    meta = getattr(stack, "item_meta", None)
    if meta is not None:
        enc = getattr(meta, "enchantments", None)
        if isinstance(enc, dict):
            try:
                enc.clear()
                for k, v in mapping.items():
                    enc[str(k)] = int(v)
                if hasattr(stack, "set_item_meta"):
                    stack.set_item_meta(meta)
                    return True
                stack.item_meta = meta
                return True
            except Exception:
                pass
    # Try using add/set methods
    ok_any = False
    for k, v in mapping.items():
        try:
            from .shared import add_enchant_any_level  # self import safety
        except Exception:
            # within same module, function exists above; ignore
            pass
        # direct call
        if add_enchant_any_level(stack, str(k), int(v)):
            ok_any = True
    return ok_any


def copy_basic_meta(src, dst) -> None:
    # Name
    try:
        meta = getattr(src, "item_meta", None)
        if meta:
            nm = getattr(meta, "display_name", None) or getattr(meta, "name", None)
            if nm:
                rename_item(dst, str(nm))
    except Exception:
        pass
    # Lore
    try:
        meta = getattr(src, "item_meta", None)
        lr = getattr(meta, "lore", None) if meta else None
        if lr and isinstance(lr, (list, tuple)):
            set_lore(dst, [str(x) for x in lr if x is not None])
    except Exception:
        pass


def has_keep_on_death(stack) -> bool:
    for get_name in ("get_named_tag", "get_nbt"):
        get_tag = getattr(stack, get_name, None)
        if callable(get_tag):
            try:
                tag = get_tag() or {}
                if isinstance(tag, dict) and "minecraft:keep_on_death" in tag:
                    return True
            except Exception:
                pass
    return False


def ensure_keep_on(stack) -> bool:
    if has_keep_on_death(stack):
        return True
    return toggle_keep_on_death(stack, True)


# ─────────────────────────────────────────────────────────────────────────────
# Optional: Super-Enchants bridge
# ─────────────────────────────────────────────────────────────────────────────

def _try_super_enchants(stack, ench_key: str, level: int) -> bool:
    try:
        import endstone_super_enchants as se  # type: ignore
        fn = getattr(se, "set_enchant", None) or getattr(se, "apply_enchant", None)
        if callable(fn):
            return bool(fn(stack, ench_key, int(level)))
    except Exception:
        pass
    return False


def add_enchant_any_level(stack, ench_key: str, level: int) -> bool:
    key = str(ench_key).strip()
    if not key:
        return False
    lvl = int(level)

    if _try_super_enchants(stack, key, lvl):
        return True

    for name in ("add_enchantment", "addEnchantment", "set_enchantment_level"):
        fn = getattr(stack, name, None)
        if callable(fn):
            try:
                fn(key, lvl)
                return True
            except Exception:
                pass

    try:
        meta = getattr(stack, "item_meta", None)
        if meta is not None:
            for name in ("add_enchantment", "addEnchantment", "set_enchant"):
                fn = getattr(meta, name, None)
                if callable(fn):
                    try:
                        fn(key, lvl)
                        if hasattr(stack, "set_item_meta"):
                            stack.set_item_meta(meta)
                        else:
                            stack.item_meta = meta
                        return True
                    except Exception:
                        pass
            enc = getattr(meta, "enchantments", None)
            if isinstance(enc, dict):
                enc[key] = lvl
                if hasattr(stack, "set_item_meta"):
                    stack.set_item_meta(meta)
                    return True
                stack.item_meta = meta
                return True
    except Exception:
        pass

    enc = getattr(stack, "enchantments", None)
    if isinstance(enc, dict):
        try:
            enc[key] = lvl
            return True
        except Exception:
            pass
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Inventory snapshot helpers (to find the new /give item)
# ─────────────────────────────────────────────────────────────────────────────

def empty_slots(inv) -> Set[int]:
    out: Set[int] = set()
    size = inv_size(inv)
    for i in range(size):
        it = get_item_from_slot(inv, i)
        if not it or is_air(it):
            out.add(i)
    return out


def find_new_stack_after_give(inv, before_empty: Set[int], expect_ident: Optional[str] = None):
    size = inv_size(inv)
    # 1) any slot that was empty and is now filled
    for i in range(size):
        if i in before_empty:
            it = get_item_from_slot(inv, i)
            if it and not is_air(it):
                if not expect_ident:
                    return it, i
                # check identifier match if we can
                iid = item_identifier(it)
                if iid == expect_ident:
                    return it, i
    # 2) fallback: scan for a stack with the expected identifier that has keep_on_death
    for i in range(size):
        it = get_item_from_slot(inv, i)
        if it and not is_air(it):
            if expect_ident is None or item_identifier(it) == expect_ident:
                if has_keep_on_death(it):
                    return it, i
    return None, -1


# Reuse earlier helpers in this module:

def set_lore(stack, lore_lines: Optional[List[str]]) -> bool:  # type: ignore[no-redef]
    try:
        meta = getattr(stack, "item_meta", None)
        if meta is not None:
            meta.lore = lore_lines
            if hasattr(stack, "set_item_meta"):
                return bool(stack.set_item_meta(meta))
            stack.item_meta = meta
            return True
    except Exception:
        pass
    try:
        nbt = getattr(stack, "get_named_tag", None)
        if callable(nbt):
            tag = nbt() or {}
            if isinstance(tag, dict):
                tag["display"] = tag.get("display", {})
                tag["display"]["Lore"] = lore_lines or []
                if hasattr(stack, "set_named_tag"):
                    stack.set_named_tag(tag)
                    return True
    except Exception:
        pass
    return False


def rename_item(stack, new_name: str) -> bool:  # type: ignore[no-redef]
    try:
        meta = getattr(stack, "item_meta", None)
        if meta is not None:
            if hasattr(meta, "display_name"):
                meta.display_name = new_name
            elif hasattr(meta, "name"):
                meta.name = new_name
            if hasattr(stack, "set_item_meta"):
                return bool(stack.set_item_meta(meta))
            stack.item_meta = meta
            return True
    except Exception:
        pass
    try:
        if hasattr(stack, "custom_name"):
            stack.custom_name = new_name
            return True
    except Exception:
        pass
    return False


def toggle_keep_on_death(stack, want_on: bool) -> bool:  # type: ignore[no-redef]
    for get_name, set_name in (("get_named_tag", "set_named_tag"), ("get_nbt", "set_nbt")):
        get_tag = getattr(stack, get_name, None)
        set_tag = getattr(stack, set_name, None)
        if callable(get_tag) and callable(set_tag):
            try:
                tag = get_tag() or {}
                if not isinstance(tag, dict):
                    get = getattr(tag, "get", None)
                    tag = (get("") if callable(get) else {}) or {}
                if want_on:
                    tag["minecraft:keep_on_death"] = tag.get(
                        "minecraft:keep_on_death", {}
                    )
                else:
                    if "minecraft:keep_on_death" in tag:
                        del tag["minecraft:keep_on_death"]
                set_tag(tag)
                return True
            except Exception:
                pass
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Currency helpers (name for UI + Money scoreboard for logic)
# ─────────────────────────────────────────────────────────────────────────────

def currency_name(plugin) -> str:
    """
    Display name only: what you set in Currency Settings.
    This is NOT a scoreboard name.
    """
    try:
        st = settings(plugin)
        nm = str(st.get("currency_name", "Currency")).strip()
        return nm or "Currency"
    except Exception:
        return "Currency"


MONEY_OBJ = "Money"


def _ensure_money_objective(server):
    try:
        sb = getattr(server, "scoreboard", None)
        if not sb:
            return None
        obj = sb.get_objective(MONEY_OBJ)
        if obj:
            return obj
        try:
            from endstone.scoreboard import Criteria  # type: ignore
            return sb.add_objective(MONEY_OBJ, MONEY_OBJ, Criteria.DUMMY)
        except Exception:
            return sb.add_objective(MONEY_OBJ, MONEY_OBJ)
    except Exception:
        return None


def get_money(plugin, player) -> int:
    """Read from the Money scoreboard only."""
    try:
        obj = _ensure_money_objective(plugin.server)
        if not obj:
            return 0
        sid = player.scoreboard_identity
        sc = obj.get_score(sid)
        return int(sc) if isinstance(sc, (int, float)) else 0
    except Exception:
        return 0


def add_money(plugin, player, delta: int) -> None:
    """Add to / subtract from the Money scoreboard only."""
    obj = _ensure_money_objective(plugin.server)
    if not obj:
        return
    try:
        sid = player.scoreboard_identity
        sc = obj.get_score(sid)
        cur = int(sc) if isinstance(sc, (int, float)) else 0
        obj.set_score(sid, cur + int(delta))
    except Exception:
        pass
