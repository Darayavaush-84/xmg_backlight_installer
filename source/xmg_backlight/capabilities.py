"""Authoritative capabilities for the bundled ite8291r3-ctl driver."""

from __future__ import annotations

from dataclasses import dataclass


STATIC_COLORS = (
    "white",
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "teal",
    "purple",
)

DYNAMIC_COLORS = (
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "teal",
    "purple",
    "random",
)

DIRECTIONS = ("none", "right", "left", "up", "down")


@dataclass(frozen=True)
class EffectCapability:
    speed: bool = False
    color: bool = False
    direction: bool = False
    reactive: bool = False


EFFECT_CAPABILITIES = {
    "breathing": EffectCapability(speed=True, color=True),
    "wave": EffectCapability(speed=True, direction=True),
    "random": EffectCapability(speed=True, color=True, reactive=True),
    "rainbow": EffectCapability(),
    "ripple": EffectCapability(speed=True, color=True, reactive=True),
    "marquee": EffectCapability(speed=True),
    "raindrop": EffectCapability(speed=True, color=True),
    "aurora": EffectCapability(speed=True, color=True, reactive=True),
    "fireworks": EffectCapability(speed=True, color=True, reactive=True),
}

EFFECTS = ("static", *EFFECT_CAPABILITIES.keys())


def capability_for(mode: str) -> EffectCapability:
    return EFFECT_CAPABILITIES.get(mode, EffectCapability())
