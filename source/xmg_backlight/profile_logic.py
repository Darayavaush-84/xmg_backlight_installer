"""Pure profile-domain transformations used by the GUI."""

from __future__ import annotations

from copy import deepcopy


class ProfileDomainError(ValueError):
    pass


def validate_profile_name(name: str) -> str:
    normalized = str(name).strip()
    if not normalized or len(normalized) > 128:
        raise ProfileDomainError("Profile names must contain 1 to 128 characters")
    return normalized


def rename_profile(store: dict, settings: dict, old_name: str, new_name: str):
    new_name = validate_profile_name(new_name)
    if old_name not in store["profiles"]:
        raise ProfileDomainError(f"Unknown profile: {old_name}")
    if new_name in store["profiles"] and new_name != old_name:
        raise ProfileDomainError(f"Profile already exists: {new_name}")
    new_store = deepcopy(store)
    new_settings = dict(settings)
    new_store["profiles"][new_name] = new_store["profiles"].pop(old_name)
    if new_store["active"] == old_name:
        new_store["active"] = new_name
    for key in ("ac_profile", "battery_profile"):
        if new_settings.get(key) == old_name:
            new_settings[key] = new_name
    return new_store, new_settings


def delete_profile(store: dict, settings: dict, name: str):
    if name not in store["profiles"]:
        raise ProfileDomainError(f"Unknown profile: {name}")
    if len(store["profiles"]) <= 1:
        raise ProfileDomainError("At least one profile must remain")
    new_store = deepcopy(store)
    new_settings = dict(settings)
    del new_store["profiles"][name]
    if new_store["active"] == name:
        new_store["active"] = next(iter(new_store["profiles"]))
    for key in ("ac_profile", "battery_profile"):
        if new_settings.get(key) == name:
            new_settings[key] = ""
    return new_store, new_settings
