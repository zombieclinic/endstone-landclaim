# src/endstone_landclaim/landclaim_modifyui.py
# Strict Endstone-friendly. No future annotations.

from typing import Any, Dict, List, Tuple, Optional

from endstone import Player
from endstone.form import ActionForm, MessageForm

# Only pull settings from shared; we define our own currency_name here.
from .adminmenu.shared import settings as _settings

MONEY_OBJ = "Money"


def _currency_name(plugin) -> str:
    """
    Display-only name from Currency Settings.

    This ONLY affects UI text (e.g., "Mana", "Credits").
    ALL ECONOMY LOGIC ALWAYS USES THE 'Money' SCOREBOARD OBJECTIVE.
    """
    try:
        st = _settings(plugin)
        nm = str(st.get("currency_name", "Currency")).strip()
        return nm or "Currency"
    except Exception:
        return "Currency"


class ModifyUI:
    """
    UI for enlarging an existing claim.

    Called from LandClaimUI._base_menu as:

        self._modify_ui.open(
            player,
            claim_id,
            claim,
            max_radius_from_rules,
            self._save_claims,
            self.open_main,
        )
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self._warned_money = False

    # ------------------------------------------------------------------#
    # Money helpers – always use scoreboard objective "Money"
    # ------------------------------------------------------------------#
    def _objective(self) -> Any:
        try:
            sv = self.plugin.server
            sb = sv.scoreboard
        except Exception:
            return None

        try:
            obj = sb.get_objective(MONEY_OBJ)
            if obj is not None:
                return obj
        except Exception:
            obj = None

        # If it doesn't exist yet, try to create a dummy objective.
        try:
            from endstone.scoreboard import Criteria  # type: ignore

            return sb.add_objective(MONEY_OBJ, MONEY_OBJ, Criteria.DUMMY)
        except Exception:
            try:
                return sb.add_objective(MONEY_OBJ, MONEY_OBJ)
            except Exception:
                return None

    def _warn_missing_money_once(self, p: Player) -> None:
        if self._warned_money:
            return
        self._warned_money = True
        try:
            p.send_message(
                "§cMoney scoreboard objective is missing; "
                "economy features may not work correctly."
            )
        except Exception:
            pass

    def _get_money(self, p: Player) -> int:
        obj = self._objective()
        if obj is None:
            self._warn_missing_money_once(p)
            return 0

        # Try a few different key types – different Endstone builds
        # expose different ways of addressing the score.
        candidates: List[Any] = []
        try:
            candidates.append(p)
        except Exception:
            pass
        try:
            sid = getattr(p, "scoreboard_identity", None)
            if sid is not None:
                candidates.append(sid)
        except Exception:
            pass
        try:
            nm = getattr(p, "name", None)
            if nm:
                candidates.append(nm)
        except Exception:
            pass

        for key in candidates:
            try:
                score = obj.get_score(key)
            except Exception:
                continue
            try:
                # Newer API: Score object with value / is_score_set
                if hasattr(score, "is_score_set"):
                    if not score.is_score_set:
                        continue
                    return int(score.value)
            except Exception:
                pass
            try:
                # Older API: direct integer
                return int(score)
            except Exception:
                continue

        return 0

    def _set_money(self, p: Player, value: int) -> None:
        value = max(0, int(value))
        obj = self._objective()
        if obj is None:
            self._warn_missing_money_once(p)
            return

        candidates: List[Any] = []
        try:
            candidates.append(p)
        except Exception:
            pass
        try:
            sid = getattr(p, "scoreboard_identity", None)
            if sid is not None:
                candidates.append(sid)
        except Exception:
            pass
        try:
            nm = getattr(p, "name", None)
            if nm:
                candidates.append(nm)
        except Exception:
            pass

        for key in candidates:
            try:
                score = obj.get_score(key)
            except Exception:
                score = None
            try:
                if hasattr(score, "is_score_set"):
                    score.value = value
                    return
            except Exception:
                pass
            try:
                obj.set_score(key, value)
                return
            except Exception:
                continue

        # Last-resort: fall back to console command
        try:
            sv = self.plugin.server
            nm = getattr(p, "name", None)
            if nm and hasattr(sv, "dispatch_command"):
                sv.dispatch_command(
                    sv.command_sender,
                    f'scoreboard players set "{nm}" {MONEY_OBJ} {value}',
                )
        except Exception:
            pass

    def _add_money(self, p: Player, delta: int) -> None:
        if not delta:
            return
        cur = self._get_money(p)
        self._set_money(p, cur + int(delta))

    # ------------------------------------------------------------------#
    # Spacing helpers – reuse logic from landclaimui lazily to avoid
    # circular imports.
    # ------------------------------------------------------------------#
    def _spacing_for_radius(
        self,
        owner: str,
        claim: Dict[str, Any],
        new_radius: int,
    ) -> Tuple[bool, bool]:
        """
        Returns (blocked_by_spawn, blocked_by_other_claims)
        for expanding this claim to `new_radius`.
        """
        from . import landclaimui as lc  # local import to avoid cycle

        try:
            x = int(claim.get("x", 0))
            z = int(claim.get("z", 0))
            dim_here = lc._dim_of_claim(claim)  # type: ignore[attr-defined]
        except Exception:
            return False, False

        blocked_spawn = False
        blocked_other = False

        try:
            if lc._spawn_blocked(self.plugin, x, z, new_radius, dim_here):  # type: ignore[attr-defined]
                blocked_spawn = True
        except Exception:
            pass

        try:
            offenders = lc._conflicts_with_bases(  # type: ignore[attr-defined]
                self.plugin,
                owner,
                x,
                z,
                new_radius,
                dim_here,
                ignore_same_center=(x, z),
            )
            if offenders:
                blocked_other = True
        except Exception:
            pass

        return blocked_spawn, blocked_other

    # ------------------------------------------------------------------#
    # Main entry
    # ------------------------------------------------------------------#
    def open(
        self,
        p: Player,
        claim_id: str,
        claim: Dict[str, Any],
        max_radius_from_rules: int,
        save_cb,
        open_main_cb,
    ) -> None:
        """
        Show the "buy land" menu for an existing claim.
        """
        s = _settings(self.plugin)

        price_per_50 = int(s.get("land_price_per_50", 1000))
        cur_name = _currency_name(self.plugin)
        owner = getattr(p, "name", "")

        current_r = int(claim.get("radius", 100))
        rule_max = max(0, int(max_radius_from_rules or 0))

        balance = self._get_money(p)

        # Possible expansion steps
        steps: List[int] = [50, 100, 150, 200]

        usable: List[Tuple[int, int]] = []  # (delta, cost)
        can_expand_somewhere = False
        missing_money = False
        min_required_cost = None
        blocked_spawn = False
        blocked_other = False

        for delta in steps:
            target_r = current_r + delta
            if target_r > rule_max:
                continue  # beyond rule cap

            can_expand_somewhere = True

            cost = (delta // 50) * price_per_50

            bs, bo = self._spacing_for_radius(owner, claim, target_r)
            if bs:
                blocked_spawn = True
                continue
            if bo:
                blocked_other = True
                continue

            # At this point spacing is OK
            if balance >= cost:
                usable.append((delta, cost))
            else:
                missing_money = True
                if min_required_cost is None or cost < min_required_cost:
                    min_required_cost = cost

        # Build body text
        body_lines: List[str] = []
        body_lines.append("Use the buttons below to buy extra radius.")
        body_lines.append("")
        body_lines.append(f"Current radius: §e{current_r}")
        body_lines.append(f"Max radius from rules: §e{rule_max}")
        body_lines.append(f"Cost per +50: §e{price_per_50} {cur_name}")
        body_lines.append(f"Your balance: §e{balance} {cur_name}")
        body_lines.append("")

        if current_r >= rule_max:
            body_lines.append("§cThis base is already at the maximum radius allowed.")
        elif not can_expand_somewhere:
            body_lines.append(
                "§cYou cannot expand this base any further at this location."
            )
        elif not usable:
            if missing_money:
                body_lines.append(
                    "§cYou can expand farther here, but you don't have enough money."
                )
                if min_required_cost is not None:
                    body_lines.append(
                        f"§7(Need at least §e{min_required_cost} {cur_name}§7 for +50.)"
                    )
            elif blocked_spawn:
                body_lines.append(
                    "§cYou cannot expand: too close to spawn protection for this dimension."
                )
            elif blocked_other:
                body_lines.append(
                    "§cYou cannot expand: expansion would be too close to another player's base."
                )

        f = ActionForm(title="§lAdjust Claim Radius", content="\n".join(body_lines))

        buttons: List[Tuple[str, Optional[int]]] = []

        for delta, cost in usable:
            label = f"+{delta} radius (cost {cost} {cur_name})"
            buttons.append((label, delta))
            f.add_button(label)

        # Always add a Back button
        buttons.append(("Back", None))
        f.add_button("Back")

        def apply_delta(pl: Player, delta: int, cost: int) -> None:
            # Re-check money and spacing at the moment of purchase.
            new_balance = self._get_money(pl)
            if new_balance < cost:
                try:
                    pl.send_message("§cYou no longer have enough money.")
                except Exception:
                    pass
                return self.open(pl, claim_id, claim, max_radius_from_rules, save_cb, open_main_cb)

            new_r = int(claim.get("radius", current_r)) + delta
            bs, bo = self._spacing_for_radius(owner, claim, new_r)
            if bs or bo:
                try:
                    pl.send_message("§cExpansion is no longer possible at this radius.")
                except Exception:
                    pass
                return self.open(pl, claim_id, claim, max_radius_from_rules, save_cb, open_main_cb)

            # Charge and apply
            self._add_money(pl, -cost)
            claim["radius"] = new_r
            try:
                save_cb()
            except Exception:
                pass
            try:
                pl.send_message(
                    f"§aBase radius increased by §e{delta}§a (now {new_r})."
                )
            except Exception:
                pass
            return self.open(pl, claim_id, claim, max_radius_from_rules, save_cb, open_main_cb)

        def pick(pl: Player, idx: int) -> None:
            if idx is None or idx < 0 or idx >= len(buttons):
                return
            label, delta = buttons[idx]
            if delta is None:
                return open_main_cb(pl)  # Back
            # Find the cost we stored for this delta
            for d, cost in usable:
                if d == delta:
                    return apply_delta(pl, d, cost)
            return

        f.on_submit = pick
        p.send_form(f)
