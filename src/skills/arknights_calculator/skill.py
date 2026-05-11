from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CalcRequest:
    enabled: bool
    kind: str = ""
    attack: float | None = None
    multiplier: float = 1.0
    attack_interval: float | None = None
    duration: float | None = None
    hit_count: int = 1
    target_count: int = 1
    enemy_defense: float = 0
    enemy_res: float = 0
    heal_amount: float | None = None
    heal_interval: float | None = None
    note: str = ""


@dataclass(slots=True)
class CalcResult:
    kind: str
    summary: str
    details: str


def calculate(request: CalcRequest) -> CalcResult | None:
    if not request.enabled:
        return None

    kind = request.kind.lower()
    if kind in {"physical_dps", "physical_total"}:
        return _physical_damage(request)
    if kind in {"arts_dps", "arts_total"}:
        return _arts_damage(request)
    if kind in {"true_dps", "true_total"}:
        return _true_damage(request)
    if kind in {"hps", "heal_total"}:
        return _healing(request)
    return None


def _physical_damage(request: CalcRequest) -> CalcResult | None:
    if request.attack is None or request.attack_interval is None:
        return None

    damage_per_hit = max(request.attack * request.multiplier - request.enemy_defense, 0)
    damage_per_attack = damage_per_hit * request.hit_count * request.target_count
    dps = damage_per_attack / request.attack_interval
    total = dps * request.duration if request.duration else None
    return _damage_result("physical", request, damage_per_hit, dps, total)


def _arts_damage(request: CalcRequest) -> CalcResult | None:
    if request.attack is None or request.attack_interval is None:
        return None

    res_factor = max(1 - request.enemy_res / 100, 0.05)
    damage_per_hit = request.attack * request.multiplier * res_factor
    damage_per_attack = damage_per_hit * request.hit_count * request.target_count
    dps = damage_per_attack / request.attack_interval
    total = dps * request.duration if request.duration else None
    return _damage_result("arts", request, damage_per_hit, dps, total)


def _true_damage(request: CalcRequest) -> CalcResult | None:
    if request.attack is None or request.attack_interval is None:
        return None

    damage_per_hit = request.attack * request.multiplier
    damage_per_attack = damage_per_hit * request.hit_count * request.target_count
    dps = damage_per_attack / request.attack_interval
    total = dps * request.duration if request.duration else None
    return _damage_result("true", request, damage_per_hit, dps, total)


def _healing(request: CalcRequest) -> CalcResult | None:
    heal_amount = request.heal_amount if request.heal_amount is not None else request.attack
    interval = request.heal_interval if request.heal_interval is not None else request.attack_interval
    if heal_amount is None or interval is None:
        return None

    heal_per_action = heal_amount * request.multiplier * request.hit_count * request.target_count
    hps = heal_per_action / interval
    total = hps * request.duration if request.duration else None
    total_text = f", total healing {total:.0f}" if total is not None else ""
    return CalcResult(
        kind="healing",
        summary=f"HPS {hps:.1f}{total_text}",
        details=(
            f"heal/action={heal_per_action:.1f}, interval={interval:g}s, "
            f"duration={request.duration or 'not provided'}"
        ),
    )


def _damage_result(
    kind: str,
    request: CalcRequest,
    damage_per_hit: float,
    dps: float,
    total: float | None,
) -> CalcResult:
    total_text = f", total damage {total:.0f}" if total is not None else ""
    defense_text = ""
    if kind == "physical":
        defense_text = f", enemy DEF={request.enemy_defense:g}"
    elif kind == "arts":
        defense_text = f", enemy RES={request.enemy_res:g}"

    return CalcResult(
        kind=kind,
        summary=f"DPS {dps:.1f}{total_text}",
        details=(
            f"damage/hit={damage_per_hit:.1f}, multiplier={request.multiplier:g}, "
            f"interval={request.attack_interval:g}s, hits={request.hit_count}, "
            f"targets={request.target_count}{defense_text}"
        ),
    )

