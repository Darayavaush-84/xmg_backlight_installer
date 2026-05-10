"""udev-related helpers for ITE keyboard detection and rule generation."""

from __future__ import annotations

import re
from dataclasses import dataclass

DeviceId = tuple[str, str]


@dataclass(frozen=True)
class DeviceIdParseResult:
    ids: list[DeviceId]
    unmatched: list[str]


def parse_device_id_lines(lines: list[str]) -> DeviceIdParseResult:
    ids: list[DeviceId] = []
    unmatched: list[str] = []
    vendor_patterns = [
        r"\bidvendor\s*[:=]?\s*(?:0x)?([0-9a-fA-F]{4})\b",
        r"\bvendor\s*[:=]?\s*(?:0x)?([0-9a-fA-F]{4})\b",
        r"\bmanufacturer\s*[:=]?\s*(?:0x)?([0-9a-fA-F]{4})\b",
    ]
    product_patterns = [
        r"\bidproduct\s*[:=]?\s*(?:0x)?([0-9a-fA-F]{4})\b",
        r"\bproduct\s*[:=]?\s*(?:0x)?([0-9a-fA-F]{4})\b",
    ]
    pair_patterns = [
        r"\bid\s+(?:0x)?([0-9a-fA-F]{4})\s*:\s*(?:0x)?([0-9a-fA-F]{4})\b",
        r"\b(?:0x)?([0-9a-fA-F]{4})\s*:\s*(?:0x)?([0-9a-fA-F]{4})\b",
    ]
    for line in lines:
        vendor = None
        product = None
        for pattern in vendor_patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                vendor = match.group(1)
                break
        for pattern in product_patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                product = match.group(1)
                break
        if not (vendor and product):
            for pattern in pair_patterns:
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if match:
                    vendor = match.group(1)
                    product = match.group(2)
                    break
        if vendor and product:
            ids.append((vendor.lower().zfill(4), product.lower().zfill(4)))
        else:
            stripped = line.strip()
            if stripped:
                unmatched.append(stripped)
    return DeviceIdParseResult(ids=list(dict.fromkeys(ids)), unmatched=unmatched)


def existing_rule_contains_device(existing_text: str, vendor: str, product: str) -> bool:
    return (
        f'ATTRS{{idVendor}}=="{vendor}"' in existing_text
        and f'ATTRS{{idProduct}}=="{product}"' in existing_text
    )


def format_udev_rule(vendor: str, product: str) -> str:
    return (
        'SUBSYSTEMS=="usb", '
        f'ATTRS{{idVendor}}=="{vendor}", '
        f'ATTRS{{idProduct}}=="{product}", '
        'MODE:="0666"'
    )

