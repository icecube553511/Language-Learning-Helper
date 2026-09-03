"""Platform-neutral Bingzi appearance selection rules.

The selector consumes facts supplied by presentation/application boundaries.
It never scans files or reads persistence; asset discovery belongs to the
resource preparation tool and the platform edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Iterable


PET_APPEARANCE_VERSION = "pet-appearance-v1"
PET_AIRBORNE_THRESHOLD_SECONDS = 3.0
PET_STATIONARY_THRESHOLD_SECONDS = 30.0
PET_DOUBLE_TAP_WINDOW_MS = 300
PET_HUNGRY_SATIETY = 0.0
PET_LARGE_LANDING_SPEED = 437.5
_HAPPY_ASSET_PATTERN = re.compile(r"^happy([1-9][0-9]*)\.png$")


class PetAppearance(str, Enum):
    NORMAL = "normal"
    PAIN = "pain"
    SCARED = "scared"
    HUNGRY = "hungry"
    SLEEP = "sleep"
    HAPPY = "happy"


@dataclass(frozen=True)
class PetAppearanceAssets:
    """An injected, already-discovered set of optional runtime asset names."""

    state_files: frozenset[str] = frozenset()
    happy_files: tuple[str, ...] = ()

    @classmethod
    def from_file_names(
        cls,
        state_files: Iterable[str] = (),
        happy_files: Iterable[str] = (),
    ) -> "PetAppearanceAssets":
        normalized_happy = {
            str(name).strip()
            for name in happy_files
            if _HAPPY_ASSET_PATTERN.fullmatch(str(name).strip())
        }
        ordered_happy = tuple(
            sorted(
                normalized_happy,
                key=lambda name: (int(_HAPPY_ASSET_PATTERN.fullmatch(name).group(1)), name),
            )
        )
        return cls(frozenset(str(name).strip() for name in state_files), ordered_happy)

    @property
    def complete(self) -> bool:
        return all(name in self.state_files for name in ("pain.png", "scared.png", "sleep.png", "hungry.png")) and bool(self.happy_files)


@dataclass(frozen=True)
class PetAppearanceContext:
    """Transient facts needed to choose the next appearance."""

    landing_impact_speed: float = 0.0
    airborne_seconds: float = 0.0
    stationary_seconds: float = 0.0
    moving: bool = False
    satiety: float | None = None
    rapid_double_tap: bool = False
    happy_asset_index: int = 0


@dataclass(frozen=True)
class PetAppearanceDecision:
    appearance: PetAppearance
    asset_name: str | None
    reason: str


def _at_least(value: float, threshold: float) -> bool:
    return math.isfinite(value) and value >= threshold


def _state_decision(
    appearance: PetAppearance,
    filename: str,
    reason: str,
    assets: PetAppearanceAssets,
) -> PetAppearanceDecision | None:
    if filename not in assets.state_files:
        return None
    return PetAppearanceDecision(appearance, filename, reason)


def select_pet_appearance(
    context: PetAppearanceContext,
    assets: PetAppearanceAssets = PetAppearanceAssets(),
) -> PetAppearanceDecision:
    """Apply the shared priority order to transient pet facts.

    The recommended deterministic order is pain > scared > hungry > sleep >
    happy > normal. Missing files disable only the corresponding choice; with
    the current empty asset set the result is always the existing normal sprite.
    """
    if _at_least(context.landing_impact_speed, PET_LARGE_LANDING_SPEED):
        decision = _state_decision(PetAppearance.PAIN, "pain.png", "large-landing", assets)
        if decision is not None:
            return decision
    if _at_least(context.airborne_seconds, PET_AIRBORNE_THRESHOLD_SECONDS):
        decision = _state_decision(PetAppearance.SCARED, "scared.png", "airborne-too-long", assets)
        if decision is not None:
            return decision
    if context.satiety is not None and math.isfinite(context.satiety) and context.satiety <= PET_HUNGRY_SATIETY:
        decision = _state_decision(PetAppearance.HUNGRY, "hungry.png", "satiety-zero", assets)
        if decision is not None:
            return decision
    if not context.moving and _at_least(context.stationary_seconds, PET_STATIONARY_THRESHOLD_SECONDS):
        decision = _state_decision(PetAppearance.SLEEP, "sleep.png", "stationary-too-long", assets)
        if decision is not None:
            return decision
    if not context.moving and context.rapid_double_tap and assets.happy_files:
        index = context.happy_asset_index % len(assets.happy_files)
        return PetAppearanceDecision(PetAppearance.HAPPY, assets.happy_files[index], "stationary-double-tap")
    return PetAppearanceDecision(PetAppearance.NORMAL, None, "normal")


selectPetAppearance = select_pet_appearance
