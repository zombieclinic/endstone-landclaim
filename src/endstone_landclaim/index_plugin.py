# src/endstone_landclaim/index_plugin.py
# Strict Endstone-friendly. No future annotations.

from typing import Callable, List, Tuple, Optional, Dict, Any
import os, json, math

from endstone.plugin import Plugin
from endstone.command import Command, CommandSender
from endstone import Player
from endstone.event import (
    event_handler,
    ScriptMessageEvent,
    PlayerMoveEvent,
    BlockPlaceEvent,
    BlockBreakEvent,
    PlayerInteractEvent,
)

# Optional join/quit types (graceful if not present)
try:
    from endstone.event import PlayerJoinEvent, PlayerQuitEvent
except Exception:
    PlayerJoinEvent = None
    PlayerQuitEvent = None

# Extra fallbacks (some builds use different names)
try:
    from endstone.event import PlayerDisconnectEvent
except Exception:
    PlayerDisconnectEvent = None
try:
    from endstone.event import PlayerLeaveEvent
except Exception:
    PlayerLeaveEvent = None
try:
    from endstone.event import PlayerKickEvent
except Exception:
    PlayerKickEvent = None

from endstone.level import Location

# Passive-mob protection (if exposed by your build)
try:
    from endstone.event import ActorDamageEvent as DamageEvent
except Exception:
    try:
        from endstone.event import EntityDamageEvent as DamageEvent
    except Exception:
        DamageEvent = None

from .adminmenu import AdminUI as AdminMenu
from .landclaimui import LandClaimUI
from .protection import Protection
from .teleporter_ui import TeleporterUI

# Claims bump hook + free-area lookup + spawn config + owner lookup
try:
    from .checks import (
        bump_claims_version,
        spawn_free_area_name_at as _spawn_free_area_name_at,
        spawn_config as _spawn_config,
        claim_owner_at as _claim_owner_at,
    )
except Exception:

    def bump_claims_version(_plugin):
        try:
            v = int(getattr(_plugin, "_claims_version", 0))
            setattr(_plugin, "_claims_version", v + 1)
        except Exception:
            pass

    def _spawn_free_area_name_at(*_args, **_kwargs):
        return None, None

    def _spawn_config(*_args, **_kwargs):
        # sx, sz, radius, label
        return 0, 0, 0, "Spawn"

    def _claim_owner_at(*_args, **_kwargs):
        return None, None


class MyPlugin(Plugin):
    """
    pyproject.toml:
      [project.entry-points."endstone"]
      landclaim = "endstone_landclaim.index_plugin:MyPlugin"
    """

    api_version = "0.10"

    commands = {
        "adminui": {
            "description": "Open the landclaim admin menu.",
            "usages": ["/adminui"],
            "permissions": ["landclaim.command.adminui"],
        },
        "landclaimui": {
            "description": "Open the land claim menu.",
            "usages": ["/landclaimui"],
            "permissions": ["landclaim.command.landclaimui"],
        },
        "teleporterui": {
            "description": "Open the teleporter menu (runs block claim/move check).",
            "usages": ["/teleporterui"],
            "permissions": ["landclaim.command.teleporterui"],
        },
        "exit": {
            "description": "Evacuate upward with Slow Falling (only inside others' claims).",
            "usages": ["/exit"],
            "permissions": ["landclaim.command.exit"],
        },
    }

    permissions = {
        "landclaim.command.adminui": {
            "description": "Use /adminui",
            "default": "op",
        },
        "landclaim.command.landclaimui": {
            "description": "Use /landclaimui",
            "default": "true",
        },
        "landclaim.command.teleporterui": {
            "description": "Use /teleporterui",
            "default": "op",
        },
        "landclaim.command.exit": {
            "description": "Use /exit",
            "default": "true",
        },
        "landclaim.admin": {
            "description": "Bypass protections",
            "default": "op",
        },
    }

    _entered_claim: Dict[str, Optional[str]] = {}
    _entered_free_area: Dict[str, Optional[str]] = {}

    def on_enable(self) -> None:
        self.logger.info("Loading Landclaim...")

        self.data: Dict[str, Any] = {"settings": {}, "players": {}}

        # load persisted files
        self.data_dir()
        settings = self.read_json("admin_config.json")
        if isinstance(settings, dict):
            self.data["settings"].update(settings)
        persisted = self.read_json("claims.json")
        if isinstance(persisted, dict):
            self.data["players"] = persisted.get(
                "players", self.data.get("players", {})
            )

        # subsystems
        self.admin = AdminMenu(self)
        self.land = LandClaimUI(self)
        self.teleporter = TeleporterUI(self)
        self.protection = Protection(self)

        # events
        try:
            self.register_events(self)
            self.logger.info("Landclaim: events registered.")
        except Exception as e:
            self.logger.error(f"Failed to register events: {e}")

        # periodic “/exit” hint loop
        self._start_exit_hint_loop()

        try:
            self.logger.info(
                "Commands registered: "
                + ", ".join(sorted(self.commands.keys()))
            )
        except Exception:
            pass

        self.logger.info(
            "Enabled. Commands: /adminui, /landclaimui, "
            "/teleporterui, /exit"
        )

    def on_disable(self) -> None:
        self._save_claims()

    # ---------- storage helpers ----------

    def data_dir(self) -> str:
        base = getattr(self, "data_folder", None) or getattr(
            self, "data_path", None
        )
        if not base:
            base = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(base, exist_ok=True)
        return base

    def write_json(self, filename: str, payload: dict) -> bool:
        try:
            path = os.path.join(self.data_dir(), filename)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"Failed to save {filename}: {e}")
            return False

    def read_json(self, filename: str) -> dict:
        try:
            path = os.path.join(self.data_dir(), filename)
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_claims(self) -> None:
        try:
            bump_claims_version(self)
        except Exception:
            pass
        try:
            self.write_json("admin_config.json", self.data.get("settings", {}))
            self.write_json(
                "claims.json", {"players": self.data.get("players", {})}
            )
        except Exception:
            pass

    # ---------- ScriptMessageEvent bridges ----------

    @event_handler
    def _on_script_message_tp(self, ev: ScriptMessageEvent) -> None:
        try:
            msg_id = (getattr(ev, "message_id", "") or "").strip().lower()
        except Exception:
            return
        if msg_id not in {"zc:teleporterui", "zc:teleportor", "zc:tpblock"}:
            return

        target: Optional[Player] = None
        try:
            s = getattr(ev, "sender", None)
            target = s if isinstance(s, Player) else None
        except Exception:
            target = None
        if target is None:
            try:
                s = getattr(ev, "sender", None)
                if s:
                    s.send_error_message("Player not found.")
            except Exception:
                pass
            return

        def _open():
            try:
                self.open_teleporter_from_block(target)
            except Exception as e:
                try:
                    target.send_message("§cCouldn’t open Teleporter (block).")
                except Exception:
                    pass
                self.logger.error(
                    f"Teleporter block flow failed for "
                    f"{getattr(target, 'name', target)}: {e}"
                )

        try:
            self.server.scheduler.run_task(self, _open, delay=1)
        except Exception:
            _open()

    @event_handler
    def _on_script_message_community(self, ev: ScriptMessageEvent) -> None:
        try:
            msg_id = (getattr(ev, "message_id", "") or "").strip().lower()
        except Exception:
            return
        if msg_id not in {
            "zc:community_teleport",
            "zc:comunity_teleport",
            "zc:communitytp",
        }:
            return

        target: Optional[Player] = None
        try:
            s = getattr(ev, "sender", None)
            target = s if isinstance(s, Player) else None
        except Exception:
            target = None
        if target is None:
            try:
                s = getattr(ev, "sender", None)
                if s:
                    s.send_error_message("Player not found.")
            except Exception:
                pass
            return

        def _open():
            try:
                self.teleporter.open_community_teleport(target)
            except Exception as e:
                try:
                    target.send_message(
                        "§cCouldn’t open Community Teleporter."
                    )
                except Exception:
                    pass
                self.logger.error(
                    f"Community teleporter failed for "
                    f"{getattr(target, 'name', target)}: {e}"
                )

        try:
            self.server.scheduler.run_task(self, _open, delay=1)
        except Exception:
            _open()

    @event_handler
    def _on_script_message_land(self, ev: ScriptMessageEvent) -> None:
        self._handle_script_event(
            ev, ids=("zc:landclaimui",), opener=self.open_landclaim_ui
        )

    def _handle_script_event(
        self,
        ev: ScriptMessageEvent,
        ids: Tuple[str, ...],
        opener: Callable[[Player], None],
    ) -> None:
        try:
            msg_id = (getattr(ev, "message_id", "") or "").strip()
            raw = (getattr(ev, "message", "") or "").strip().strip('"')
        except Exception:
            return
        if msg_id not in ids:
            return

        target: Optional[Player] = None
        if raw:
            try:
                target = self.server.get_player(raw)
            except Exception:
                target = None
        if target is None:
            try:
                s = getattr(ev, "sender", None)
                target = s if isinstance(s, Player) else None
            except Exception:
                target = None
        if target is None:
            try:
                s = getattr(ev, "sender", None)
                if s:
                    s.send_error_message("Player not found.")
            except Exception:
                pass
            return

        def _open():
            try:
                opener(target)
            except Exception as e:
                try:
                    target.send_message(
                        "§cCouldn’t open menu. Ask an admin to check logs."
                    )
                except Exception:
                    pass
                self.logger.error(
                    f"UI open failed for {getattr(target, 'name', target)}: {e}"
                )

        try:
            self.server.scheduler.run_task(self, _open, delay=1)
        except Exception:
            _open()

    # ---------- entry points ----------

    def open_landclaim_ui(self, p: Player) -> None:
        self.land.open_main(p)

    def open_teleporter_ui(self, p: Player) -> None:
        self.teleporter.open_from_block_trigger(p)

    def open_teleporter_from_block(self, p: Player) -> None:
        self.teleporter.open_from_block_trigger(p)

    # ---------- command handling ----------

    def on_command(
        self, sender: CommandSender, command: Command, args: List[str]
    ) -> bool:
        name = (command.name or "").lower()

        if name == "adminui":
            p = self._as_player(sender)
            if not p:
                sender.send_message("§7This command is player-only.")
                return True
            if not self._is_op_or_perm(p, "landclaim.command.adminui"):
                p.send_message("§cYou do not have permission.")
                return True
            try:
                self.admin.open_root(p)
            except Exception as e:
                self.logger.error(f"/adminui error: {e}")
            return True

        if name == "landclaimui":
            p = self._as_player(sender)
            if not p:
                sender.send_message("§7This command is player-only.")
                return True

            # Global toggle: cmd_landclaimui_admin_only
            try:
                s = dict(self.data.get("settings", {}))
                admin_only = bool(s.get("cmd_landclaimui_admin_only", True))
            except Exception:
                admin_only = True

            if admin_only:
                # ONLY listed admins bypass when this is ON
                if not self._is_listed_admin(p):
                    p.send_message(
                        "§cOnly admins can use §e/landclaimui§c "
                        "(toggle in Admin → Command Settings)."
                    )
                    return True

            try:
                self.open_landclaim_ui(p)
            except Exception as e:
                self.logger.error(f"/landclaimui error: {e}")
            return True

        if name == "teleporterui":
            p = self._as_player(sender)
            if not p:
                sender.send_message("§7This command is player-only.")
                return True
            if not self._is_op_or_perm(p, "landclaim.command.teleporterui"):
                p.send_message("§cYou do not have permission.")
                return True
            try:
                self.open_teleporter_ui(p)
            except Exception as e:
                self.logger.error(f"/teleporterui error: {e}")
            return True

        if name == "exit":
            p = self._as_player(sender)
            if not p:
                sender.send_message("§7This command is player-only.")
                return True

            dk = self._dim_key(p)
            if dk in ("nether", "end"):
                p.send_message(
                    "§cYou can’t use §e/exit§c in the Nether or the End."
                )
                return True

            if not self._can_use_exit_here(p):
                p.send_message(
                    "§cYou can only use §e/exit§c while exploring "
                    "someone else’s base."
                )
                return True

            try:
                if not self._apply_slow_fall(p, seconds=30):
                    p.send_message(
                        "§cCouldn’t apply Slow Falling — cancelling /exit."
                    )
                    return True

                def _do_tp():
                    try:
                        self._tp_up_console(p, delta_y=200)
                        self._apply_slow_fall(p, seconds=10)
                        p.send_message(
                            "§aEvacuated upward with Slow Falling."
                        )
                    except Exception as e:
                        self.logger.error(f"/exit TP error: {e}")

                try:
                    self.server.scheduler.run_task(self, _do_tp, delay=2)
                except Exception:
                    _do_tp()
            except Exception as e:
                self.logger.error(f"/exit error: {e}")
            return True

        return False

    # ---------- event routing ----------

    @event_handler
    def on_player_move(self, event: PlayerMoveEvent):
        try:
            self.protection.handle_player_move(event)
        except Exception:
            pass
        try:
            self._check_free_area_entry(event)
        except Exception:
            pass

    @event_handler
    def on_block_place(self, event: BlockPlaceEvent):
        try:
            self.protection.handle_block_place(event)
        except Exception:
            pass

    @event_handler
    def on_block_break(self, event: BlockBreakEvent):
        try:
            self.protection.handle_block_break(event)
        except Exception:
            pass

    @event_handler
    def on_player_interact(self, event: PlayerInteractEvent):
        try:
            self.protection.handle_player_interact(event)
        except Exception:
            pass

    if DamageEvent is not None:

        @event_handler
        def on_entity_damage(self, event: DamageEvent):
            try:
                self.protection.handle_actor_damage(event)
            except Exception:
                pass

    # ---------- 400-tick hint loop ----------

    def _start_exit_hint_loop(self) -> None:
        def loop():
            try:
                for p in self._all_players():
                    if self._can_use_exit_here(p):
                        try:
                            p.send_message(
                                "§7Tip: type §e/exit §7 in chat if you get stuck."
                            )
                        except Exception:
                            pass
            finally:
                try:
                    self.server.scheduler.run_task(self, loop, delay=400)
                except Exception:
                    pass

        try:
            self.server.scheduler.run_task(self, loop, delay=400)
        except Exception:
            pass

    # ---------- FREE-AREA ENTRY POPUPS / TOASTS ----------

    def _check_free_area_entry(self, event: PlayerMoveEvent) -> None:
        """
        Handle entering/leaving spawn free-build areas and show toasts.

        Uses:
          - _spawn_free_area_name_at(self, x, y, z, dim_key)
          - self._entered_free_area[player_name] to avoid spam.
        """
        try:
            p = getattr(event, "player", None)
            if not isinstance(p, Player):
                return

            name = str(getattr(p, "name", "") or "")
            if not name:
                return

            loc = getattr(p, "location", None)
            if not loc:
                return

            x = int(getattr(loc, "x", 0))
            y = int(getattr(loc, "y", 0))
            z = int(getattr(loc, "z", 0))

            dk = self._dim_key(p)
            area_id, area_name = _spawn_free_area_name_at(self, x, y, z, dk)

            prev_id = self._entered_free_area.get(name)

            # No change (still in same area or still in none)
            if area_id == prev_id:
                return

            # Update tracker
            self._entered_free_area[name] = area_id

            # --- ENTERING a free area ---
            if area_id is not None:
                label = area_name or "Free Area"
                title = f"§lEntering §a{label}"
                content = "§7Free-build area near spawn."
                try:
                    if hasattr(p, "send_toast"):
                        p.send_toast(title=title, content=content)
                    elif hasattr(p, "send_popup"):
                        p.send_popup(label)
                    else:
                        p.send_message(f"§aYou entered §e{label}§a.")
                except Exception:
                    pass
                return

            # --- LEAVING a free area (area_id is None now) ---
            # If we're now in a claim, let the normal claim system
            # handle its own toast.
            try:
                owner, claim = _claim_owner_at(self, x, z, dim_key=dk)
            except Exception:
                owner, claim = None, None
            if owner or claim:
                return

            # If we're still inside the spawn radius, show a "Spawn"
            # toast instead of letting only "Wilderness" show.
            inside_spawn = False
            spawn_label = "Spawn"
            try:
                sx, sz, sr, sname = _spawn_config(self, dk)
                spawn_label = sname or "Spawn"
                if sr > 0:
                    inside_spawn = (math.hypot(x - sx, z - sz) <= sr)
            except Exception:
                inside_spawn = False

            if inside_spawn:
                title = f"§lEntering §e{spawn_label}"
                content = "§7Protected spawn area."
                try:
                    if hasattr(p, "send_toast"):
                        p.send_toast(title=title, content=content)
                    else:
                        p.send_message(f"{title}\n{content}")
                except Exception:
                    pass

        except Exception:
            return

    # ---------- misc helpers ----------

    def _current_tick(self) -> int:
        for attr in ("current_tick", "tick_count", "tick"):
            try:
                v = getattr(self.server, attr, None)
                v = v() if callable(v) else v
                if isinstance(v, int):
                    return v
            except Exception:
                pass
        try:
            import time

            return int(time.time() * 20)
        except Exception:
            return 0

    def _online_ids(self) -> List[str]:
        out: List[str] = []
        for p in self._all_players():
            try:
                xuid = str(getattr(p, "xuid", "") or "")
                pfid = str(getattr(p, "pfid", "") or "")
                nm = str(getattr(p, "name", "") or "")
                out.append(xuid or pfid or nm)
            except Exception:
                continue
        return out

    def _all_players(self) -> List[Player]:
        for meth in ("get_players", "get_online_players"):
            m = getattr(self.server, meth, None)
            if callable(m):
                try:
                    return list(m())
                except Exception:
                    pass
        for attr in ("players", "online_players"):
            if hasattr(self.server, attr):
                try:
                    v = getattr(self.server, attr)
                    if isinstance(v, (list, tuple, set)):
                        return list(v)
                except Exception:
                    pass
        return []

    def _as_player(self, s: CommandSender) -> Optional[Player]:
        try:
            return s if isinstance(s, Player) else None
        except Exception:
            return s if hasattr(s, "location") and hasattr(
                s, "send_message"
            ) else None

    def _is_op_or_perm(self, p: Player, perm: str) -> bool:
        """
        Permission helper.

        SPECIAL CASE:
          - For 'landclaim.admin' we ONLY respect the Admin Manager list.
            OP or other perm plugins do NOT give bypass.
        """
        if perm == "landclaim.admin":
            return self._is_listed_admin(p)

        # Normal command perms still respect OP / permission nodes.
        for attr in ("is_op", "isOp"):
            if hasattr(p, attr):
                v = getattr(p, attr)
                try:
                    if (v() if callable(v) else bool(v)):
                        return True
                except Exception:
                    pass
        for meth in ("has_permission", "hasPermission", "check_permission"):
            if hasattr(p, meth):
                try:
                    if getattr(p, meth)(perm):
                        return True
                except Exception:
                    pass
        return False

    def _is_listed_admin(self, who) -> bool:
        try:
            name = who if isinstance(who, str) else getattr(who, "name", "")
            admins = [
                str(x).lower()
                for x in (
                    self.data.get("settings", {}).get("admins", []) or []
                )
            ]
            return str(name).lower() in admins
        except Exception:
            return False

    def _dim_key(self, p: Player) -> str:
        try:
            loc = getattr(p, "location", None)
            dim = getattr(loc, "dimension", None)
            try:
                if isinstance(dim, int):
                    if dim in (0,):
                        return "overworld"
                    if dim in (-1, 1):
                        return "nether" if dim == -1 else "end"
                    if dim in (2,):
                        return "end"
            except Exception:
                pass
            try:
                dname = str(getattr(dim, "name", "")).lower()
                if "nether" in dname:
                    return "nether"
                if "end" in dname:
                    return "end"
                if "overworld" in dname:
                    return "overworld"
            except Exception:
                pass
            try:
                lvl = getattr(loc, "level", None)
                lname = str(getattr(lvl, "name", "")).lower()
                if "nether" in lname:
                    return "nether"
                if "the_end" in lname or lname == "end" or "end" in lname:
                    return "end"
                if "overworld" in lname or lname == "world":
                    return "overworld"
            except Exception:
                pass
        except Exception:
            pass
        return "overworld"

    def _can_use_exit_here(self, p: Player) -> bool:
        try:
            if self._dim_key(p) != "overworld":
                return False
            x = float(getattr(p.location, "x", 0.0))
            z = float(getattr(p.location, "z", 0.0))
            owner, claim = self._find_claim_at(x, z)
            if not claim or not owner:
                return False
            if getattr(p, "name", "") == owner:
                return False
            mates = [str(m).lower() for m in (claim.get("mates") or [])]
            return getattr(p, "name", "").lower() not in mates
        except Exception:
            return False

    def _find_claim_at(
        self, x: float, z: float
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        try:
            players = (self.data or {}).get("players", {}) or {}
            for owner, rec in players.items():
                claims = (rec or {}).get("claims", {}) or {}
                for c in claims.values():
                    if not isinstance(c, dict):
                        continue
                    cx = float(c.get("x", 0.0))
                    cz = float(c.get("z", 0.0))
                    r = float(c.get("radius", 0.0))
                    if r <= 0:
                        continue
                    if math.hypot(cx - x, cz - z) <= r:
                        return owner, c
        except Exception:
            pass
        return None, None

    def _name_for_selector(self, p: Player) -> str:
        try:
            return str(getattr(p, "name", "")).replace('"', r"\"")
        except Exception:
            return ""

    def _dispatch_console(self, cmd: str) -> bool:
        try:
            return bool(
                self.server.dispatch_command(self.server.command_sender, cmd)
            )
        except Exception:
            return False

    def _apply_slow_fall(self, p: Player, seconds: int = 20) -> bool:
        secs = max(1, int(seconds))
        ticks = secs * 20
        for applier in (
            lambda: p.add_effect(
                "slow_falling",
                duration=ticks,
                amplifier=0,
                show_particles=False,
            ),
            lambda: p.add_effect(
                "minecraft:slow_falling", duration=ticks, amplifier=0
            ),
            lambda: p.add_status_effect("slow_falling", ticks, 0),
        ):
            try:
                applier()
                return True
            except Exception:
                continue
        return self._slow_fall_console(p, secs)

    def _slow_fall_console(self, p: Player, seconds: int = 30) -> bool:
        secs = max(1, int(seconds or 1))
        n = self._name_for_selector(p)
        for core in (
           
            f"effect @s slow_falling {secs} 0 true",
        ):
            if self._dispatch_console(
                f'execute as @a[name="{n}"] at @s run {core}'
            ):
                return True
        return False

    def _tp_up_console(self, p: Player, delta_y: int = 200) -> None:
        dy = int(delta_y)
        n = self._name_for_selector(p)
        for core in (f"tp @s ~ {dy} ~", f"teleport @s ~ {dy} ~"):
            if self._dispatch_console(
                f'execute as @a[name="{n}"] at @s run {core}'
            ):
                return
        raise Exception("No teleport API available")
