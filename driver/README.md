# ite8291r3-ctl — XMG Backlight bundled fork

This package is derived from upstream
[`pobrn/ite8291r3-ctl`](https://github.com/pobrn/ite8291r3-ctl) 0.4 and remains
licensed under GPL-2.0-only.

The downstream `0.4.post1` release is the versioned userspace driver shipped by
XMG Backlight Management. It keeps the driver separate from the GPLv3 GUI and
adds explicit device/revision validation required by the installer.

## Supported controllers

| idVendor | idProduct | bcdDevice |
| --- | --- | --- |
| `048d` | `6004` | `0003` |
| `048d` | `6006` | `0003` |
| `048d` | `600b` | `0003` |
| `048d` | `ce00` | `0003` |

An unknown product or revision is rejected before any USB command is sent.

## Downstream changes

- Added `048d:600b` revision `0003` to the explicit compatibility map.
- Added `--version` and device listing without opening a controller handle.
- Preserved upstream traffic callbacks and fixed screen-mode throttling.
- Tightened RGB, subcommand, device, and revision validation.
- Restricted wheel contents to the `ite8291r3_ctl` package and its GPLv2 license.

## Runtime

The package requires Python 3.10 or newer, pyusb 1.3.1, and a working libusb
backend. XMG Backlight installs the local driver and pyusb wheels into its
dedicated venv; it never resolves the driver from PyPI at runtime.

The optional experimental `mode --screen` command additionally imports
python-xlib and Pillow. Those packages are not needed by XMG Backlight and are
not part of its runtime installation.

The system installer grants the active local session device access with
`TAG+="uaccess"` in `/etc/udev/rules.d/70-xmg-backlight.rules`.

The userspace driver takes direct ownership of USB interface 1 and detaches an
active kernel driver from that interface. It therefore cannot safely coexist
with the `ite_8291` RGB module from `tuxedo-drivers`; selecting and managing a
single owner remains required.

## Commands

```bash
ite8291r3-ctl --version
ite8291r3-ctl query --devices
ite8291r3-ctl query --brightness --state
ite8291r3-ctl off
ite8291r3-ctl brightness 30
ite8291r3-ctl monocolor -b 30 --name white
ite8291r3-ctl effect -b 30 -s 5 wave
```

Run `ite8291r3-ctl --help` or a subcommand with `--help` for the complete CLI.

## Build

From the repository root:

```bash
python3 -m pip wheel --no-deps ./driver
```

After replacing the wheel under `vendor/`, update its SHA-256 in
`vendor/manifest.json` and run the repository test suite.
