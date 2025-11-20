# src/endstone_landclaim/protection.py
# Strict Endstone-friendly. No future annotations.

from typing import Optional, Tuple

from endstone import Player
from endstone.event import (
    PlayerMoveEvent,
    BlockPlaceEvent,
    BlockBreakEvent,
    PlayerInteractEvent,
)
try:
    from endstone.event import ActorDamageEvent as DamageEvent
except Exception:
    from endstone.event import EntityDamageEvent as DamageEvent

from . import checks


class Protection:
    """
    - Enforces visitor rules inside claims (admins & basemates bypass)
    - Treats spawn like a special base with its own security flags
    - Supports multiple free-build areas near spawn (per dimension)
    - Toasts on entering/leaving claims or spawn (per-dimension)
    - Forces Survival for any NON-ADMIN everywhere
    - Players are NEVER protected from damage by claims (owners can die)
    - EXTRA: Boomstick can only be used in wilderness or in the player's own base
    """

    def __init__(self, plugin):
        self.plugin = plugin
        if not hasattr(self.plugin, "_entered_claim_by_player"):
            self.plugin._entered_claim_by_player = {}

    # ---------- settings & dimension helpers ----------

    def _settings(self) -> dict:
        s = dict(getattr(self.plugin, "data", {}).get("settings", {}))
        try:
            adm = getattr(self.plugin, "admin", None)
            if adm and getattr(adm, "data", None):
                s.update(adm.data.get("settings", adm.data) or {})
        except Exception:
            pass
        return s

    def _dim_key_of_player(self, p: Player) -> str:
        """Normalize to: overworld | nether | end"""
        try:
            return checks.player_dim_key(p)
        except Exception:
            pass
        return "overworld"

    def _spawn_cfg(self, dim_key: str) -> Tuple[int, int, int, str]:
        """
        Use the shared checks.spawn_config helper so spawn behaves
        exactly like the landclaim spacing logic.
        """
        sx, sz, rad, name = checks.spawn_config(self.plugin, dim_key)
        return sx, sz, rad, name

    # ---------- small helpers ----------

    def _is_self_use_item(self, item) -> bool:
        """Return True for food, rockets, potions, ender pearls/eyes, buckets, totems, maps, etc."""
        if not item:
            return False
        name = str(getattr(item, "id", None) or getattr(item, "name", "")).lower()

        # Quick flags some forks expose:
        for attr in ("is_food", "is_consumable", "edible"):
            try:
                if bool(getattr(item, attr, False)):
                    return True
            except Exception:
                pass

        # Name-based whitelist (extend if needed)
        SELF_USE_SUBSTRINGS = (
            "firework", "potion", "suspicious_stew", "milk_bucket", "bucket",
            "ender_pearl", "ender_eye", "chorus_fruit", "golden_apple",
            "bread", "steak", "cooked_", "raw_", "carrot", "beetroot", "potato",
            "rotten_flesh", "cookie", "melon_slice", "sweet_berries", "glow_berries",
            "honey_bottle", "rabbit_stew", "beetroot_soup",
            "totem", "map", "compass", "clock", "spyglass",
        )
        return any(s in name for s in SELF_USE_SUBSTRINGS)

    def _is_boomstick(self, item) -> bool:
        """
        Returns True if the held item looks like the Boomstick.
        We match by id/name and just look for 'boomstick' so you can
        rename it without breaking this.
        """
        if not item:
            return False
        try:
            raw = str(getattr(item, "id", None) or getattr(item, "name", "")).lower()
        except Exception:
            return False
        return "boomstick" in raw

    def _can_use_boomstick_here(self, p: Player) -> bool:
        """
        Boomstick rule:
          - Admins: always allowed.
          - Inside the player's OWN claim: allowed.
          - Wilderness (no claim, outside spawn radius): allowed.
          - Everywhere else: NOT allowed.
            (no Boomstick in spawn, other people's bases, or free-build areas)
        """
        # Admins always allowed
        try:
            name = getattr(p, "name", "")
            if name and checks.is_admin(self.plugin, name):
                return True
        except Exception:
            pass

        # Player's dimension + position
        try:
            loc = p.location
            x, y, z = int(loc.x), int(loc.y), int(loc.z)
        except Exception:
            # If we can't read coords, just fail closed
            return False

        dim_key = self._dim_key_of_player(p)

        # Check if in ANY claim
        owner, claim = self._player_in_claim(p)

        if claim:
            # Only allowed if this is THEIR base (owner only, not basemates)
            try:
                owner_norm = str(owner).strip().lower()
                pname_norm = str(getattr(p, "name", "")).strip().lower()
                return owner_norm and (owner_norm == pname_norm)
            except Exception:
                return False

        # No claim -> check spawn radius. Inside spawn = blocked.
        try:
            sx, sz, spr, _ = self._spawn_cfg(dim_key)
            if spr > 0 and checks.dist2d(x, z, sx, sz) < spr:
                # Inside spawn protection radius => NO boomstick
                return False
        except Exception:
            # If spawn config is broken, treat as no spawn and fall through
            pass

        # Wilderness (no claim, and not in spawn radius) => allowed
        return True

    # ---------- Delegated handlers ----------

    def handle_player_move(self, event: PlayerMoveEvent):
        """
        Lightweight move handler:
          - Enforce Survival for non-admins.
          - Show toasts for per-dimension spawn, claims, and wilderness.
          - Does nothing if the player hasn't changed (int X, int Z, dim) since last check.
        """
        # ---------- guard + survival ----------
        try:
            p: Player = event.player
        except Exception:
            return

        # Enforce Survival (fast path inside)
        try:
            self._force_survival_if_needed(p)
        except Exception:
            pass

        # ---------- skip if not moved a whole block ----------
        try:
            loc = p.location
            cell = (int(loc.x), int(loc.z))
            dim_key = self._dim_key_of_player(p)
            cache = getattr(self.plugin, "_last_move_cell_by_player", None)
            if cache is None:
                cache = {}
                setattr(self.plugin, "_last_move_cell_by_player", cache)
            pid = getattr(p, "name", None) or getattr(p, "pfid", None) or getattr(p, "xuid", None) or id(p)
            last = cache.get(pid)
            now = (cell[0], cell[1], dim_key)
            if last == now:
                return  # same cell & dim → nothing to recompute
            cache[pid] = now
        except Exception:
            # If anything above fails, just continue with the checks.
            pass

        # ---------- toast logic ----------
        try:
            x, z = int(p.location.x), int(p.location.z)
            dim_key = self._dim_key_of_player(p)

            # Per-dimension spawn check
            sx, sz, spr, sname = self._spawn_cfg(dim_key)
            in_spawn = spr > 0 and checks.dist2d(x, z, sx, sz) < spr

            # Dimension-aware claim lookup
            owner, claim = checks.claim_owner_at(self.plugin, x, z, player=p, dim_key=dim_key)

            # Debounce so we only toast on transitions
            key = getattr(p, "name", None) or getattr(p, "pfid", None) or getattr(p, "xuid", None) or id(p)
            prev_marker = self.plugin._entered_claim_by_player.get(key)
            now_marker = None
            title = content = None

            if in_spawn:
                now_marker = f"__SPAWN__|{dim_key}"
                if prev_marker != now_marker:
                    title = f"§l{sname}"
                    content = "§7Welcome!"
            elif claim:
                base_name = str(claim.get("name") or claim.get("id") or "Claim")
                cdim = checks.claim_dim_key(claim)
                now_marker = f"{cdim}|{base_name}"
                if prev_marker != now_marker:
                    title = f"§lEntering §e{base_name}"
                    content = "§7You've entered a protected area!"
            else:
                now_marker = None
                if prev_marker is not None:
                    title = "§lEntering §7Wilderness"
                    content = "§7Unclaimed land."

            self.plugin._entered_claim_by_player[key] = now_marker
            if title:
                self._toast(p, title, content)
        except Exception:
            pass

    def handle_block_place(self, event: BlockPlaceEvent):
        self._guard_build(event, action="place")

    def handle_block_break(self, event: BlockBreakEvent):
        self._guard_build(event, action="break")

    def handle_player_interact(self, event: PlayerInteractEvent):
        """
        - Allows pure self-use (food, rockets, etc.) anywhere.
        - Boomstick is only allowed in wilderness or in the player's own base.
        - For normal interactions with blocks (doors, chests...), we still
          enforce claim/spawn protection as before.
        """
        try:
            p: Player = event.player
        except Exception:
            return

        block = getattr(event, "block", None) or getattr(event, "clicked_block", None)
        item = getattr(event, "item", None)

        # ---------- Boomstick restriction ----------
        if self._is_boomstick(item):
            if not self._can_use_boomstick_here(p):
                self._cancel(event)
                self._warn(p, "You can only use the Boomstick in wilderness or in your own base.")
                return
            # If allowed, we still want normal protections for opening chests etc.
            # So we do NOT return here; we fall through to the normal logic.

        # ---------- Self-use items (eat/drink/etc.) ----------
        # No targeted block => pure "use in air" -> always allowed.
        if not block:
            return

        # Targeting a block, but still allow consumables in hand.
        if self._is_self_use_item(item):
            return

        # ---------- Normal block interaction checks ----------
        if self._deny_if_forbidden(p, "allow_interact"):
            self._cancel(event)
            self._warn(p, "You can't interact here.")

    def handle_actor_damage(self, event: DamageEvent):
        try:
            victim = getattr(event, "actor", None) or getattr(event, "entity", None) or getattr(event, "target", None)
            if victim is None:
                return

            # Players are never protected by claims (owners can die)
            if isinstance(victim, Player):
                return

            attacker = None
            ds = getattr(event, "damage_source", None)
            if ds is not None:
                attacker = getattr(ds, "damaging_actor", None) or getattr(ds, "actor", None)
            if attacker is None:
                attacker = getattr(event, "damager", None) or getattr(event, "attacker", None) or getattr(event, "source", None)

            if attacker is None or not hasattr(attacker, "name"):
                return

            if checks.is_monster(victim):
                return  # monsters always allowed

            p: Player = attacker  # typing
            if self._deny_if_forbidden(p, "block_kill_passive"):
                self._cancel(event)
                self._warn(p, "You can't kill passive mobs here.")
        except Exception:
            pass

    # ---------- Global Survival enforcement ----------

    def _force_survival_if_needed(self, p: Player) -> None:
        """
        Ensure non-admins are in Survival.
        Tries: fast read → native setters → console → player self-command.
        No work if already Survival or if player is an admin.
        """
        try:
            name = getattr(p, "name", "")
            if name and checks.is_admin(self.plugin, name):
                return  # admins exempt
        except Exception:
            pass

        # Read current mode (best-effort, tolerate enums/ints/strings)
        try:
            gm = None
            for attr in ("game_mode", "gamemode", "mode", "get_game_mode"):
                v = getattr(p, attr, None)
                if v is None:
                    continue
                try:
                    gm = v() if callable(v) else v
                    break
                except Exception:
                    continue

            # Normalize the value to a comparable string
            gms = str(gm).lower() if gm is not None else ""
            # Common enum names include "GameMode.SURVIVAL" → check substring too
            if gms in ("0", "survival", "gamemode.survival") or "survival" in gms:
                return  # already in Survival
        except Exception:
            # If we can’t read it, we’ll attempt to set anyway.
            pass

        # Native setters first
        for setter in ("set_game_mode", "setGamemode", "set_gamemode"):
            fn = getattr(p, setter, None)
            if callable(fn):
                # Try string then numeric; many forks accept either.
                for val in ("survival", 0):
                    try:
                        fn(val)
                        return
                    except Exception:
                        continue

        # Console fallback (quotes-safe name not required here)
        try:
            sender = getattr(self.plugin.server, "console_sender", None) \
                     or getattr(self.plugin.server, "command_sender", None)
            if sender is not None and hasattr(self.plugin.server, "dispatch_command"):
                self.plugin.server.dispatch_command(sender, f"gamemode s {getattr(p, 'name', '')}")
                return
        except Exception:
            pass

        # Last resort: player self-command
        try:
            p.perform_command("gamemode s")
        except Exception:
            pass

    # ---------- internals ----------

    def _player_in_claim(self, p: Player):
        try:
            x, z = int(p.location.x), int(p.location.z)
            dim_key = self._dim_key_of_player(p)
            owner, claim = checks.claim_owner_at(self.plugin, x, z, player=p, dim_key=dim_key)
            return owner, claim
        except Exception:
            return (None, None)

    def _is_admin_or_mate(self, p) -> bool:
        try:
            if self.plugin and hasattr(p, "name"):
                if checks.is_admin(self.plugin, p.name):
                    return True
                owner, claim = self._player_in_claim(p)
                if owner == p.name:
                    return True
                mates = (claim or {}).get("mates", [])
                if isinstance(mates, dict):
                    keys = {str(k).lower() for k in mates.keys()}
                    return p.name.lower() in keys
                # legacy list
                return p.name in {str(m) for m in mates}
        except Exception:
            pass
        return False

    def _deny_if_forbidden(self, p, key: str) -> bool:
        """
        Single check for:
          - claims (normal bases)
          - spawn (treated like a base with its own flags)
          - free-build areas near spawn (always allowed)
        Admins/owners/basemates always bypass.
        """
        # Admins / owner / basemates always bypass
        if hasattr(p, "name") and self._is_admin_or_mate(p):
            return False

        # First see if we're in a claim
        owner, claim = self._player_in_claim(p)

        # Use player's current location for spawn/free-area checks
        try:
            x = int(p.location.x)
            y = int(p.location.y)
            z = int(p.location.z)
        except Exception:
            x = z = 0
            y = 64

        dim_key = self._dim_key_of_player(p)

        if claim:
            allow_build, allow_interact, allow_kill = checks.claim_flags(claim)
        else:
            # No claim -> check free-build areas first
            try:
                if checks.inside_spawn_free_area(self.plugin, x, y, z, dim_key):
                    # Inside a configured free-build area => ALWAYS allowed
                    return False
            except Exception:
                pass

            # No claim -> treat spawn as a "virtual base" if inside its radius
            sx, sz, spr, _ = self._spawn_cfg(dim_key)
            if spr <= 0:
                return False  # no spawn protection configured

            if checks.dist2d(x, z, sx, sz) >= spr:
                return False  # outside spawn radius → wilderness

            # Inside spawn radius → use spawn security flags
            allow_build, allow_interact, allow_kill = checks.spawn_security_flags(self.plugin, dim_key)

        # Map our call-site keys to "deny?" booleans
        if key in ("visitors_place", "visitors_break", "visitors_build"):
            return not allow_build
        if key == "allow_interact":
            return not allow_interact
        if key == "block_kill_passive":
            return not allow_kill

        # Fallback (kept for odd callers): deny nothing else
        return False

    def _guard_build(self, event, action: str):
        try:
            p = event.player
        except Exception:
            return
        if not self._deny_if_forbidden(p, "visitors_build"):
            return
        self._cancel(event)
        self._warn(p, f"You can't {action} blocks here.")

    def _cancel(self, event):
        set_cancelled = getattr(event, "set_cancelled", None) or getattr(event, "set_canceled", None)
        if callable(set_cancelled):
            try:
                set_cancelled(True); return
            except Exception:
                pass
        cancel = getattr(event, "cancel", None)
        if callable(cancel):
            try:
                cancel(); return
            except Exception:
                pass

    def _warn(self, p: Player, msg: str):
        try:
            p.send_popup(f"§c{msg}")
        except Exception:
            try:
                p.send_message(f"§c{msg}")
            except Exception:
                pass

    def _toast(self, p: Player, title: str, content: Optional[str] = None):
        try:
            p.send_toast(title=title, content=content or ""); return
        except Exception:
            pass
        for call in (
            lambda: p.send_title(title, content or "", fade_in=4, stay=30, fade_out=8),
            lambda: p.send_message(f"{title} — {content or ''}"),
        ):
            try:
                call(); return
            except Exception:
                continue
