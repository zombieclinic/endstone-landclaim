# src/endstone_landclaim/adminmenu/spawn_settings.py
# Strict Endstone-friendly. No future annotations.

from typing import Dict, Any, Tuple, Optional, List
import json

from endstone import Player
from endstone.form import ActionForm, ModalForm, Label, TextInput

# ---------------------------------------------------------------------------
# Helper: robust modal parsing (same style as landclaimui / landclaim_modify)
# ---------------------------------------------------------------------------

try:
    from endstone.form import ModalFormResponse  # some builds pass this
except Exception:
    class ModalFormResponse:  # type: ignore
        form_values = None
        response = None
        pass


def _parse_modal_values_str(s):
    try:
        data = json.loads(s or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _get_modal_values(resp):
    if resp is None:
        return None
    if isinstance(resp, ModalFormResponse):
        if resp.form_values is not None:
            return resp.form_values
        if resp.response is not None:
            return _parse_modal_values_str(resp.response)
        return None
    if isinstance(resp, dict):
        vals = resp.get("formValues") or resp.get("values") or resp.get("form_values")
        if vals is not None:
            return vals
        if isinstance(resp.get("response"), str):
            return _parse_modal_values_str(resp["response"])
        return None
    if isinstance(resp, str):
        return _parse_modal_values_str(resp)
    return None


# ---------------------------------------------------------------------------
# Spawn Settings UI
# ---------------------------------------------------------------------------

class SpawnSettingsUI:
    """
    Admin-side spawn / protection config.

    Stores under plugin.data["settings"]:
      spawns: {
        "overworld": { "name": str, "pos": "x y z", "radius": int },
        "nether":    { ... },
        "end":       { ... }
      }

    Also mirrors for compatibility with landclaim / checks.py:
      worldspawn_overworld / spawn_protection_radius_overworld
      worldspawn_nether    / spawn_protection_radius_nether
      worldspawn_end       / spawn_protection_radius_end

    And legacy overworld-only:
      worldspawn
      spawn_protection_radius

    Security flags per dim:
      spawn_security_<dim>_build
      spawn_security_<dim>_interact
      spawn_security_<dim>_kill_passive

    Free-build areas near spawn (multiple per dimension):
      spawn_free_areas = {
        "overworld": [ { "name": str?, "a": [x1,y1,z1], "b": [x2,y2,z2] }, ... ],
        "nether":    [ ... ],
        "end":       [ ... ],
      }

    Legacy single-area keys (auto-migrated if present):
      spawn_free_area_<dim> = "x1 y1 z1 x2 y2 z2"   (or older x1 z1 x2 z2)
    """

    def __init__(self, plugin, back_fn=None):
        self.plugin = plugin
        # Back function the AdminMenu passes (go back to main admin UI)
        self._back_fn = back_fn

    # ---------- settings + save helpers ----------

    def _settings(self):
        data = getattr(self.plugin, "data", None)
        if data is None:
            data = {}
            setattr(self.plugin, "data", data)
        return data.setdefault("settings", {})

    def _save(self):
        # Try a few common methods to persist settings
        for name in ("save_config", "save_settings", "_save", "save"):
            fn = getattr(self.plugin, name, None)
            if callable(fn):
                try:
                    fn()
                    return
                except Exception:
                    continue
        # Fallback: do nothing (admin can reload manually)

    # ---------- internal spawn helpers ----------

    def _norm_dim(self, dim):
        dim = (dim or "overworld").lower()
        if dim == "the_end":
            dim = "end"
        if "nether" in dim:
            return "nether"
        if "end" in dim:
            return "end"
        return "overworld"

    def _parse_pos(self, txt):
        try:
            parts = str(txt or "").replace(",", " ").split()
            if len(parts) >= 3:
                x = int(float(parts[0]))
                y = int(float(parts[1]))
                z = int(float(parts[2]))
                return x, y, z
        except Exception:
            pass
        return 0, 64, 0

    def _pos_str(self, x, y, z):
        return "%d %d %d" % (int(x), int(y), int(z))

    def _spawn_row(self, dim):
        """
        Returns (name, sx, sy, sz, radius) for the dimension.
        If unset, defaults to 0 64 0 with radius 0.
        """
        dk = self._norm_dim(dim)
        s = self._settings()

        # Preferred: settings["spawns"][dim]
        spawns = s.get("spawns", {})
        if not isinstance(spawns, dict):
            spawns = {}
        row = spawns.get(dk, {}) or {}

        def _dim_label(d):
            if d == "nether":
                return "Nether Spawn"
            if d == "end":
                return "The End Spawn"
            return "Overworld Spawn"

        name = str(row.get("name", _dim_label(dk)))

        # Position: row["pos"] or worldspawn_<dim> or worldspawn (overworld)
        pos_s = str(row.get("pos", "")).strip()
        if not pos_s:
            wkey = "worldspawn_%s" % dk
            pos_s = str(s.get(wkey, "")).strip()
        if not pos_s and dk == "overworld":
            pos_s = str(s.get("worldspawn", "")).strip()
        sx, sy, sz = self._parse_pos(pos_s or "0 64 0")

        # Radius: row["radius"] or spawn_protection_radius_<dim> or legacy
        rad = row.get("radius", None)
        if rad is None:
            rkey = "spawn_protection_radius_%s" % dk
            try:
                rad = int(float(str(s.get(rkey, 0))))
            except Exception:
                rad = 0
        if dk == "overworld" and (rad is None or rad <= 0):
            try:
                rad = int(float(str(s.get("spawn_protection_radius", 0))))
            except Exception:
                rad = 0
        if rad is None:
            rad = 0

        return name, int(sx), int(sy), int(sz), max(0, int(rad))

    def _write_spawn(self, dim, name, x, y, z, radius):
        dk = self._norm_dim(dim)
        s = self._settings()

        spawns = s.get("spawns", {})
        if not isinstance(spawns, dict):
            spawns = {}
            s["spawns"] = spawns

        row = spawns.get(dk, {}) or {}
        if name is not None:
            row["name"] = str(name)[:32]
        row["pos"] = self._pos_str(x, y, z)
        if radius is not None:
            row["radius"] = int(radius)
        spawns[dk] = row
        s["spawns"] = spawns

        # Mirror to worldspawn_<dim> / spawn_protection_radius_<dim>
        s["worldspawn_%s" % dk] = self._pos_str(x, y, z)
        if radius is not None:
            s["spawn_protection_radius_%s" % dk] = int(radius)

        # Legacy overworld keys too
        if dk == "overworld":
            s["worldspawn"] = self._pos_str(x, y, z)
            if radius is not None:
                s["spawn_protection_radius"] = int(radius)

        self._save()

    def _get_security(self, dim):
        dk = self._norm_dim(dim)
        s = self._settings()
        sec_build = bool(s.get("spawn_security_%s_build" % dk, False))
        sec_interact = bool(s.get("spawn_security_%s_interact" % dk, False))
        sec_kill = bool(s.get("spawn_security_%s_kill_passive" % dk, False))
        return sec_build, sec_interact, sec_kill

    def _set_security(self, dim, build=None, interact=None, kill=None):
        dk = self._norm_dim(dim)
        s = self._settings()
        if build is not None:
            s["spawn_security_%s_build" % dk] = bool(build)
        if interact is not None:
            s["spawn_security_%s_interact" % dk] = bool(interact)
        if kill is not None:
            s["spawn_security_%s_kill_passive" % dk] = bool(kill)
        self._save()

    # ---------- free-area helpers ----------

    def _free_areas_for_dim(self, dim) -> List[Dict[str, Any]]:
        dk = self._norm_dim(dim)
        s = self._settings()

        root = s.get("spawn_free_areas", {})
        if not isinstance(root, dict):
            root = {}
        areas = root.get(dk, [])
        if not isinstance(areas, list):
            areas = []

        # Legacy single-area migration: spawn_free_area_<dim>
        legacy_key = f"spawn_free_area_{dk}"
        legacy = s.get(legacy_key)
        if legacy:
            try:
                parts = str(legacy).replace(",", " ").split()
                nums = [int(float(x)) for x in parts if x]
                if len(nums) >= 6:
                    x1, y1, z1, x2, y2, z2 = nums[:6]
                elif len(nums) >= 4:
                    x1, z1, x2, z2 = nums[:4]
                    # wide vertical band if old 2D format
                    y1, y2 = -64, 320
                else:
                    x1 = y1 = z1 = x2 = y2 = z2 = 0
                areas.append({"a": [x1, y1, z1], "b": [x2, y2, z2]})
            except Exception:
                pass
            # clear legacy key so we don't keep re-importing
            try:
                s.pop(legacy_key, None)
            except Exception:
                pass

        # normalize shapes but preserve "name" if present
        norm: List[Dict[str, Any]] = []
        for it in areas:
            try:
                a = it.get("a", [])
                b = it.get("b", [])
                if not isinstance(a, list) or not isinstance(b, list):
                    continue
                if len(a) < 3 or len(b) < 3:
                    continue
                ax, ay, az = int(a[0]), int(a[1]), int(a[2])
                bx, by, bz = int(b[0]), int(b[1]), int(b[2])

                entry: Dict[str, Any] = {
                    "a": [ax, ay, az],
                    "b": [bx, by, bz],
                }
                # keep existing name if any
                if "name" in it:
                    try:
                        nm = str(it.get("name", "")).strip()
                        if nm:
                            entry["name"] = nm
                    except Exception:
                        pass

                norm.append(entry)
            except Exception:
                continue

        # write back normalized
        root[dk] = norm
        s["spawn_free_areas"] = root
        self._save()
        return norm

    def _save_free_areas_for_dim(self, dim, areas: List[Dict[str, Any]]):
        dk = self._norm_dim(dim)
        s = self._settings()
        root = s.get("spawn_free_areas", {})
        if not isinstance(root, dict):
            root = {}

        clean: List[Dict[str, Any]] = []
        for it in (areas or []):
            try:
                a = it.get("a", [])
                b = it.get("b", [])
                if not isinstance(a, list) or not isinstance(b, list):
                    continue
                if len(a) < 3 or len(b) < 3:
                    continue
                ax, ay, az = int(a[0]), int(a[1]), int(a[2])
                bx, by, bz = int(b[0]), int(b[1]), int(b[2])

                entry: Dict[str, Any] = {
                    "a": [ax, ay, az],
                    "b": [bx, by, bz],
                }

                # Preserve name if provided
                try:
                    nm = str(it.get("name", "")).strip()
                    if nm:
                        entry["name"] = nm
                except Exception:
                    pass

                clean.append(entry)
            except Exception:
                continue

        root[dk] = clean
        s["spawn_free_areas"] = root
        self._save()

    def _format_corner(self, triplet):
        try:
            return "(%d, %d, %d)" % (int(triplet[0]), int(triplet[1]), int(triplet[2]))
        except Exception:
            return "(0, 0, 0)"

    # ---------- public entry ----------

    def open(self, p: Player):
        """
        Entry point used from AdminUI (SpawnSettingsUI.open(player)).
        """
        return self.open_main(p)

    def open_main(self, p):
        """
        Main Spawn/Protection menu.
        """
        dims = ["overworld", "nether", "end"]
        lines = ["§lSpawn & Protection\n"]
        for dk in dims:
            name, sx, sy, sz, rad = self._spawn_row(dk)
            sec_b, sec_i, sec_k = self._get_security(dk)

            def onoff(v):
                return "§aON§r" if v else "§cOFF§r"

            dim_label = {
                "overworld": "Overworld",
                "nether": "Nether",
                "end": "The End",
            }.get(dk, dk.title())

            areas = self._free_areas_for_dim(dk)
            lines.append(
                "§e%s§7: %s §7@ §b(%d, %d, %d) §7r=§b%d"
                % (dim_label, name, sx, sy, sz, rad)
            )
            lines.append(
                "   §7Security: Break/Place %s, Interact %s, Kill-passive %s"
                % (onoff(sec_b), onoff(sec_i), onoff(sec_k))
            )
            lines.append(
                "   §7Free-build areas: §b%d" % len(areas)
            )
            lines.append("")

        content = "\n".join(lines).strip()
        f = ActionForm(title="§lSpawn / Protection", content=content)
        buttons = []

        buttons.append(("Overworld Spawn", "overworld"))
        buttons.append(("Nether Spawn", "nether"))
        buttons.append(("End Spawn", "end"))
        buttons.append(("Free-build Areas", "free_areas"))
        buttons.append(("Close", "close"))

        for label, _ in buttons:
            f.add_button(label)

        def pick(pl, idx):
            if idx is None or idx < 0 or idx >= len(buttons):
                # If admin menu gave us a back_fn, use it on cancel
                if callable(self._back_fn):
                    try:
                        self._back_fn(pl)
                    except Exception:
                        pass
                return
            action = buttons[idx][1]
            if action == "close":
                if callable(self._back_fn):
                    try:
                        self._back_fn(pl)
                    except Exception:
                        pass
                return
            if action == "free_areas":
                return self._open_free_areas_menu(pl)
            return self._open_dim_menu(pl, action)

        f.on_submit = pick
        p.send_form(f)

    # ---------- per-dimension menu ----------

    def _dim_title(self, dim):
        dk = self._norm_dim(dim)
        if dk == "nether":
            return "§lNether Spawn"
        if dk == "end":
            return "§lThe End Spawn"
        return "§lOverworld Spawn"

    def _open_dim_menu(self, p, dim):
        dk = self._norm_dim(dim)
        name, sx, sy, sz, rad = self._spawn_row(dk)
        sec_b, sec_i, sec_k = self._get_security(dk)

        def onoff(v):
            return "§aON§r" if v else "§cOFF§r"

        body_lines = [
            "%s" % name,
            "§7Pos: §b(%d, %d, %d)" % (sx, sy, sz),
            "§7Radius: §b%d" % rad,
            "",
            "§lSecurity (ON = randoms BLOCKED)",
            "§7Break/place: %s" % onoff(sec_b),
            "§7Interact:    %s" % onoff(sec_i),
            "§7Kill passive: %s" % onoff(sec_k),
            "",
            "§8(Admins always bypass.)",
        ]
        f = ActionForm(title=self._dim_title(dk), content="\n".join(body_lines))

        # Buttons
        # 0: Set position to current
        # 1: Edit radius
        # 2: Toggle break/place security
        # 3: Toggle interact security
        # 4: Toggle kill-passive security
        # 5: Back
        f.add_button("Set spawn to my position")     # 0
        f.add_button("Edit radius")                  # 1
        f.add_button("Toggle break/place security")  # 2
        f.add_button("Toggle interact security")     # 3
        f.add_button("Toggle kill-passive security") # 4
        f.add_button("Back")                         # 5

        def pick(pl, idx):
            if idx is None:
                return self.open_main(pl)
            if idx == 0:
                # Set spawn to player position (keep name, keep radius)
                _, _, _, _, current_r = self._spawn_row(dk)
                loc = pl.location
                x, y, z = int(loc.x), int(loc.y), int(loc.z)
                self._write_spawn(dk, name, x, y, z, current_r)
                try:
                    pl.send_message(
                        "§a%s spawn set to §b(%d, %d, %d)§a."
                        % (dk.title(), x, y, z)
                    )
                except Exception:
                    pass
                return self._open_dim_menu(pl, dk)
            if idx == 1:
                return self._edit_radius(pl, dk)
            if idx == 2:
                self._set_security(dk, build=(not sec_b))
                try:
                    pl.send_message(
                        "§aBreak/place security is now %s for %s."
                        % ("ON" if (not sec_b) else "OFF", dk)
                    )
                except Exception:
                    pass
                return self._open_dim_menu(pl, dk)
            if idx == 3:
                self._set_security(dk, interact=(not sec_i))
                try:
                    pl.send_message(
                        "§aInteract security is now %s for %s."
                        % ("ON" if (not sec_i) else "OFF", dk)
                    )
                except Exception:
                    pass
                return self._open_dim_menu(pl, dk)
            if idx == 4:
                self._set_security(dk, kill=(not sec_k))
                try:
                    pl.send_message(
                        "§aKill-passive security is now %s for %s."
                        % ("ON" if (not sec_k) else "OFF", dk)
                    )
                except Exception:
                    pass
                return self._open_dim_menu(pl, dk)
            # back
            return self.open_main(pl)

        f.on_submit = pick
        p.send_form(f)

    # ---------- radius editor ----------

    def _edit_radius(self, p, dim):
        dk = self._norm_dim(dim)
        name, sx, sy, sz, rad = self._spawn_row(dk)

        f = ModalForm(title="Radius — %s" % name, submit_button="Save")
        body = (
            "%s\n"
            "§7Pos: §b(%d, %d, %d)\n"
            "§7Current radius: §b%d\n\n"
            "Enter new radius in blocks (0 = disabled)."
            % (name, sx, sy, sz, rad)
        )
        f.add_control(Label(body))
        f.add_control(
            TextInput(
                "Radius",
                placeholder=str(rad or 0),
                default_value=str(rad or 0),
            )
        )

        def on_submit(pl, data):
            vals = _get_modal_values(data)
            if not vals:
                return self._open_dim_menu(pl, dk)
            raw = str(vals[-1] or "").strip()
            try:
                new_r = int(float(raw))
            except Exception:
                new_r = rad
            if new_r < 0:
                new_r = 0

            # Keep existing name + position, only change radius
            _, sx2, sy2, sz2, _ = self._spawn_row(dk)
            self._write_spawn(dk, name, sx2, sy2, sz2, new_r)
            try:
                pl.send_message(
                    "§aSpawn radius for §e%s§a set to §b%d§a blocks."
                    % (dk, new_r)
                )
            except Exception:
                pass
            return self._open_dim_menu(pl, dk)

        f.on_submit = on_submit
        p.send_form(f)

    # ---------- free-area UI ----------

    def _open_free_areas_menu(self, p: Player):
        dims = ["overworld", "nether", "end"]
        lines = [
            "§lFree-build Areas\n",
            "§7Players inside these areas may build and interact",
            "§7even if spawn security is ON.",
            "",
            "§7Pick a dimension to edit:",
        ]
        f = ActionForm(title="§lSpawn Free-build Areas", content="\n".join(lines))
        buttons: List[Tuple[str, str]] = []
        for dk in dims:
            areas = self._free_areas_for_dim(dk)
            label = {
                "overworld": "Overworld",
                "nether": "Nether",
                "end": "The End",
            }.get(dk, dk.title())
            buttons.append((f"{label} (§b{len(areas)}§r)", dk))
            f.add_button(f"{label} (§b{len(areas)}§r)")
        buttons.append(("Back", "back"))
        f.add_button("Back")

        def pick(pl, idx):
            if idx is None or idx < 0 or idx >= len(buttons):
                return self.open_main(pl)
            action = buttons[idx][1]
            if action == "back":
                return self.open_main(pl)
            return self._open_dim_free_areas_menu(pl, action)

        f.on_submit = pick
        p.send_form(f)

    def _open_dim_free_areas_menu(self, p: Player, dim: str):
        dk = self._norm_dim(dim)
        areas = self._free_areas_for_dim(dk)

        label = {
            "overworld": "Overworld",
            "nether": "Nether",
            "end": "The End",
        }.get(dk, dk.title())

        lines = [
            "§l%s Free-build Areas" % label,
            "",
            "§7Players inside these boxes may build and interact",
            "§7even when spawn security is ON.",
            "",
            "§7Select an area to edit, or add a new one.",
            "",
        ]
        if not areas:
            lines.append("§8No areas yet.")

        f = ActionForm(
            title="§lFree-build — %s" % label,
            content="\n".join(lines),
        )

        buttons: List[Tuple[str, Optional[int]]] = []
        f.add_button("§a+ Add new area")
        buttons.append(("add", None))

        for idx, area in enumerate(areas):
            a = area.get("a", [0, 0, 0])
            b = area.get("b", [0, 0, 0])
            nm = ""
            try:
                nm = str(area.get("name", "") or "").strip()
            except Exception:
                nm = ""
            name_suffix = f" — {nm}" if nm else ""
            f.add_button(
                "Area %d%s: %s → %s"
                % (idx + 1, name_suffix, self._format_corner(a), self._format_corner(b))
            )
            buttons.append(("edit", idx))

        f.add_button("Back")
        buttons.append(("back", None))

        def pick(pl, btn_idx):
            if btn_idx is None or btn_idx < 0 or btn_idx >= len(buttons):
                return self._open_free_areas_menu(pl)
            action, index = buttons[btn_idx]
            if action == "back":
                return self._open_free_areas_menu(pl)
            if action == "add":
                return self._edit_free_area(pl, dk, None)
            if action == "edit":
                return self._edit_free_area(pl, dk, index)
            return self._open_dim_free_areas_menu(pl, dk)

        f.on_submit = pick
        p.send_form(f)

    def _parse_xyz(self, txt: str, fallback: Tuple[int, int, int]) -> Tuple[int, int, int]:
        s = (txt or "").strip()
        if not s:
            return fallback
        try:
            parts = s.replace(",", " ").split()
            nums: List[int] = []
            for part in parts:
                try:
                    nums.append(int(float(part)))
                except Exception:
                    continue
            if len(nums) >= 3:
                return nums[0], nums[1], nums[2]
        except Exception:
            pass
        return fallback

    def _edit_free_area(self, p: Player, dim: str, index: Optional[int]):
        dk = self._norm_dim(dim)
        areas = self._free_areas_for_dim(dk)
        label = {
            "overworld": "Overworld",
            "nether": "Nether",
            "end": "The End",
        }.get(dk, dk.title())

        if index is not None and (index < 0 or index >= len(areas)):
            # index out of range -> just go back
            return self._open_dim_free_areas_menu(p, dk)

        if index is None:
            title = "New Free-build Area — %s" % label
            a_default = (int(p.location.x), int(p.location.y), int(p.location.z))
            b_default = a_default
            current_name = ""
        else:
            title = "Edit Free-build Area %d — %s" % (index + 1, label)
            area = areas[index]
            a_list = area.get(
                "a", [int(p.location.x), int(p.location.y), int(p.location.z)]
            )
            b_list = area.get("b", a_list)
            a_default = (int(a_list[0]), int(a_list[1]), int(a_list[2]))
            b_default = (int(b_list[0]), int(b_list[1]), int(b_list[2]))
            try:
                current_name = str(area.get("name", "") or "")
            except Exception:
                current_name = ""

        f = ModalForm(title=title, submit_button="Save")
        body = (
            "§7Players may build and interact freely inside this box.\n"
            "§7Enter corners as §bX Y Z§7.\n"
            "§7Leave BOTH corners blank to §cdelete§7 this area.\n\n"
            "Dimension: §b%s§r"
        ) % label
        f.add_control(Label(body))

        # Name field
        f.add_control(
            TextInput(
                "Area name (optional)",
                placeholder=current_name or "Free Area",
                default_value=current_name,
            )
        )

        f.add_control(
            TextInput(
                "Corner A (X Y Z)",
                placeholder="%d %d %d" % a_default,
                default_value="%d %d %d" % a_default,
            )
        )
        f.add_control(
            TextInput(
                "Corner B (X Y Z)",
                placeholder="%d %d %d" % b_default,
                default_value="%d %d %d" % b_default,
            )
        )

        def on_submit(pl, data):
            vals = _get_modal_values(data) or []

            name_txt = str(vals[1] if len(vals) > 1 else "").strip()
            a_txt = str(vals[2] if len(vals) > 2 else "").strip()
            b_txt = str(vals[3] if len(vals) > 3 else "").strip()

            if not a_txt and not b_txt:
                # delete if editing existing
                if index is not None and 0 <= index < len(areas):
                    try:
                        areas.pop(index)
                        self._save_free_areas_for_dim(dk, areas)
                        pl.send_message("§aFree-build area removed.")
                    except Exception:
                        pass
                return self._open_dim_free_areas_menu(pl, dk)

            a = self._parse_xyz(a_txt or "", a_default)
            b = self._parse_xyz(b_txt or "", b_default)

            # If editing and name is blank, keep old name
            if index is not None:
                old_name = ""
                try:
                    old_name = str(areas[index].get("name", "") or "")
                except Exception:
                    pass
                effective_name = name_txt or old_name
            else:
                effective_name = name_txt

            new_entry: Dict[str, Any] = {
                "a": [a[0], a[1], a[2]],
                "b": [b[0], b[1], b[2]],
            }
            if effective_name:
                new_entry["name"] = effective_name

            if index is None:
                areas.append(new_entry)
            else:
                areas[index] = new_entry

            self._save_free_areas_for_dim(dk, areas)
            try:
                display_name = effective_name or "Free Area %d" % (
                    (index + 1) if index is not None else len(areas)
                )
                pl.send_message(
                    "§aFree-build area saved for §e%s§a: §b%s§a (%s → %s)."
                    % (
                        label,
                        display_name,
                        self._format_corner(a),
                        self._format_corner(b),
                    )
                )
            except Exception:
                pass
            return self._open_dim_free_areas_menu(pl, dk)

        f.on_submit = on_submit
        p.send_form(f)
