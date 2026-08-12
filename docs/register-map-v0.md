# Register map — protocol v0, 80-register devices

Empirically derived against a **FOSSiBOT/SYDPOWER `POWER-8043`**:

| Parameter | Value |
| --- | --- |
| `protocol_version` | 0 (legacy single-register writes) |
| `modbus_address` | 17 (`0x11`) |
| `modbus_count` | 80 (`0x50`) |

Upstream [Ylianst/ESP-FBot](https://github.com/Ylianst/ESP-FBot) derived its
constants from a **v1** device. Everything below was re-verified on this v0
unit; where the two agree it is noted, because agreement across protocol
versions is what makes a mapping trustworthy enough to write to.

> **All values here were collected after the response-desync fix** described at
> the end of this document. Readings taken before that fix could silently return
> the wrong register bank, and several early conclusions drawn from them were
> wrong. Treat any register observation not reproduced post-fix as unverified.

## Method

Registers were identified by differential observation, not by guessing:

1. Snapshot both banks with a known output state.
2. Change exactly **one** thing (physical button press, or a single register
   write).
3. Snapshot again and diff.

Only registers that moved in response to a known stimulus are listed as
confirmed.

## Control registers (holding bank, FC 0x03 / write FC 0x06)

All four are transition-confirmed and all four match upstream. Three have since
been commanded successfully from Home Assistant.

| Register | Function | Values | Upstream | Written? |
| --- | --- | --- | --- | --- |
| 24 | USB output | 0 = off, 1 = on | `REG_USB_CONTROL` ✓ | **yes** (0) |
| 25 | DC output | 0 = off, 1 = on | `REG_DC_CONTROL` ✓ | **yes** (0) |
| 26 | AC output | 0 = off, 1 = on | `REG_AC_CONTROL` ✓ | no |
| 27 | Light / mode | 0 = off, 1 = on, 2 = SOS, 3 = flashing | `REG_LIGHT_CONTROL` ✓ | **yes** (all four) |

All four light modes were commanded from Home Assistant and observed taking
effect on the device, so register 27 is fully verified across its allowlisted
range of 0–3.

Register 26 is the only output-control register never written: its mapping rests
on observing a physical toggle, not on commanding one.

### Settings registers

Also commanded from Home Assistant and confirmed by reading back, which matters
because these are the persisted registers implicated in the boot loop:

| Register | Function | Written | Read back |
| --- | --- | --- | --- |
| 13 | AC charge limit (charge speed) | 2 | 2 → 500 W |
| 57 | AC silent charging | 0 | 0 (off) |
| 66 | Discharge floor, permille | 100 | 100 (10.0%) |
| 67 | Charge ceiling, permille | 830, then 1000 | 1000 (100.0%) |

Register 67 accepted 830 as readily as 1000, so the charge ceiling is not
restricted to round figures. Register **56 (key sound) has never been written**.

The AC charge limit is 1-based: option index + 1 goes to the register, so 2
selects the second option. Confirmed against the device reporting 500 W.

A read with USB on, DC on, AC on and light off returned
`holding[24,25,26,27] = 1, 1, 1, 0`, matching physical state exactly.

### Verified write

Register 27 was written over BLE in both directions and every mirror followed:

```
TX 11 06 001B 0000 5DFB  →  RX 11 06 001B 0000 5DFB   (27 = 0, light off)
TX 11 06 001B 0001 9D3A  →  RX 11 06 001B 0001 9D3A   (27 = 1, light on)
```

This confirms the v0 write encoding — `[addr][0x06][2-byte register][2-byte
value][CRC]`, with the device echoing the request frame verbatim.

**v0 has no multi-register write encoding.** `build_write_registers` raises
`ProtocolError` rather than silently writing only the first value.

## Telemetry (input bank, FC 0x04)

### Confirmed

| Register | Function | Scale | Evidence |
| --- | --- | --- | --- |
| 15 | Light output power | ÷10 → W | 0 ↔ 10 (1.0 W) tracking the light exactly |
| 25 | Light state | 0/1 | Follows holding 27 |
| 30 | USB-A port 1 power | ÷10 → W | Flickers 0 ↔ 1 with a USB load; matches upstream `REG_USB_A1_OUT` |
| 31 | USB-A port 2 power | ÷10 → W | Same behaviour; matches upstream `REG_USB_A2_OUT` |
| 35 | USB-C port power | ÷10 → W | 196–199 (19.6–19.9 W) with a battery pack charging; matches upstream `REG_USB_C2_OUT` |
| 41 | Output state bitfield | see below | Each output sets a distinct bit |
| 56 | State of charge | ÷10 → % | 757 → 753 (75.7% → 75.3%) falling under sustained load |
| 59 | Remaining discharge runtime | minutes | 3225 → 3217 → 3212 while discharging, monotonically decreasing; stable across 25 consecutive samples; **0 while charging**. Matches upstream. See the power section below |

### `input[41]` bitfield

| Bit | Meaning | Evidence |
| --- | --- | --- |
| 1, 3 | AC-related, unresolved | Set throughout |
| 2 | AC-related, unresolved | Cleared together with bit 11 on AC off |
| 7 | DC-side output active (aggregate) | Set by USB and by light; **not** set by AC output alone |
| 9 | USB output active | `0x080E` → `0x0A8E` |
| 10 | DC output active | `0x0A8E` → `0x0E8E` |
| 11 | AC output active | `0x0E8E` → `0x068A` on AC off |
| 12 | Light active | `0x080E` → `0x188E` |

Bits 9–12 form a contiguous USB / DC / AC / Light group.

### `input[42]` is a bitfield, not a power reading

Reads `0x0000` with only AC output on, `0x03D8` with USB enabled, and `0xE3D8`
with USB and DC enabled. Completely static under a live 19.8 W load across two
separate sampling runs, so it is not a wattage. It relates to the USB/DC side
only. `0x03D8` has exactly six bits set and this family exposes six USB ports,
so a per-port mask is plausible but unproven.

### AC voltage and frequency

| Register | Function | Scale | Notes |
| --- | --- | --- | --- |
| 22 | AC frequency | ÷100 → Hz | 5998–6001 = 59.98–60.01 Hz |
| 18 | AC voltage | ÷10 → V | ~120.1–120.3 V, consistently ~0.3 V above register 21 |
| 21 | AC voltage | ÷10 → V | ~119.7–120.0 V |

Whether 18/21 are input vs output, or two measurement points on the same rail,
is unresolved — mains was connected and AC output was enabled for most of the
session, so the two cases were never separated.

### Power and duration: registers 3, 4, 6, 20, 39, 58

These are **raw units** — watts and minutes, no divisor. Confirmed by reading the
device's own display alongside a register dump: the screen showed 628 W input,
380 W output and 83 minutes to full while registers 6, 39 and 58 held exactly
628, 380 and 83.

| Register | Function | Unit |
| --- | --- | --- |
| 3 | Power into the battery (charging) | W |
| 4 | DC / solar input power | W — **unverified**, always 0 so far |
| 6 | Total input power | W |
| 20 | Byte-identical to 39 in every sample | W |
| 39 | Output power | W |
| 58 | Time until full | minutes |
| 59 | Remaining discharge runtime | minutes — 0 while charging |

The device's accounting is internally consistent, with this identity holding in
every sample including those taken while not charging:

```
input[6] = input[39] + input[3]        613 = 365 + 248
                                       512 = 512 +   0   (idle, not charging)
```

Register 4 is the open question. Nothing has ever been connected to the DC/solar
input, so it is unproven whether solar appears as a fourth term in that identity
or is folded into register 3. Its number comes from the earlier ESP-FBot
integration, whose other power indices (3, 6, 20, 39) all proved correct here.

Note that the absolute figures are reportedly higher than an external meter
shows. That is the device's own inaccuracy — the registers match its display
exactly, so there is no scaling error to correct on this side.

An earlier revision of this document guessed 6/20/39 were a ÷10 pack voltage,
on the strength of their tracking each other and sitting in a plausible range
for a 16S LiFePO4 pack. That was wrong; the display comparison settled it.

## Response desynchronisation (fixed)

`ResponseBuffer` declared an `expected_func_code` field and never compared it to
the function code actually received. Holding (`0x03`) and input (`0x04`) reads
produce identically shaped frames for the same register count, so a reply
arriving out of order was accepted as valid and **every register in the bank was
misinterpreted**.

Observed live: across one long-held connection, `read_holding_registers()`
returned input-bank data for tens of seconds — `holding[21]` read 1212 where the
true value is 768, `holding[42]` read 58328 where the true value is 0. It
resynchronised on its own, which is what made the symptom look like flaky
hardware.

`feed()` now raises `ProtocolError` on any function-code mismatch, so `_send`
retries instead of returning wrong data. After the fix, 10/10 and 25/25 sample
runs completed with zero desync errors, and register 59 — previously written off
as returning "three unrelated constants" — became completely stable.

**Consequence for polling design:** the desync appeared during a single
long-lived connection with rapid interleaved reads of both banks. The Home
Assistant coordinator opens a fresh connection per poll and reads each bank
once, which is a much lower-risk pattern. If you switch to holding the
connection open for responsiveness, keep this failure mode in mind.

## Timing

Full connect → read both banks → disconnect cycles, measured over 5 runs on a
local macOS adapter: **median 2.99 s, max 3.71 s, 5/5 successful**. At a 30 s
poll interval that is roughly a 10% duty cycle.

## Still unmapped

- Whether DC/solar input appears in register 4, and how it enters the input
  power identity. Needs a panel or DC source connected.
- Commanding register 26 (AC output) and register 56 (key sound). Every other
  allowlisted register has now been written successfully and read back.
- Remaining USB port power registers; upstream lists 34, 36, 37 in addition to
  the confirmed 30, 31, 35.
- Whether `input[18]` / `input[21]` are AC input vs output.
- Meaning of `input[41]` bits 1–3, and the `input[42]` bit layout.
- Settings registers (13 AC charge limit, 56/57 key sound and silent charging,
  66/67 charge and discharge thresholds). These are the persisted registers
  implicated in the boot-loop failure mode — see `WRITABLE_HOLDING_REGISTERS`
  in `sydpower/constants.py` before touching any of them.
