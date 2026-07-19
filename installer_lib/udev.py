"""udev-related helpers for ITE keyboard detection and rule generation."""

from __future__ import annotations

def iter_udev_records(existing_text: str):
    """Yield logical udev records, joining backslash-continued physical lines."""
    parts = []
    for raw_line in existing_text.splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not parts):
            continue
        continued = line.endswith("\\")
        parts.append(line[:-1].rstrip() if continued else line)
        if not continued:
            yield " ".join(parts)
            parts.clear()
    if parts:
        yield " ".join(parts)


def _record_matches_device(record: str, vendor: str, product: str) -> bool:
    record = record.lower()
    vendor = vendor.lower()
    product = product.lower()
    vendor_tokens = (
        f'attr{{idvendor}}=="{vendor}"',
        f'attrs{{idvendor}}=="{vendor}"',
    )
    product_tokens = (
        f'attr{{idproduct}}=="{product}"',
        f'attrs{{idproduct}}=="{product}"',
    )
    return any(token in record for token in vendor_tokens) and any(
        token in record for token in product_tokens
    )


def existing_rule_contains_device(existing_text: str, vendor: str, product: str) -> bool:
    for record in iter_udev_records(existing_text):
        if _record_matches_device(record, vendor, product):
            return True
    return False


def rule_grants_world_write(existing_text: str, vendor: str, product: str) -> bool:
    for record in iter_udev_records(existing_text):
        compact = "".join(record.lower().split())
        if _record_matches_device(record, vendor, product) and (
            'mode="0666"' in compact or 'mode:="0666"' in compact
        ):
            return True
    return False


def format_udev_rule(vendor: str, product: str) -> str:
    return (
        'SUBSYSTEM=="usb", '
        f'ATTR{{idVendor}}=="{vendor}", '
        f'ATTR{{idProduct}}=="{product}", '
        'TAG+="uaccess"'
    )
