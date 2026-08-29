#!/usr/bin/env python3
"""Schematic generator for the detector HAT KiCad project.

Emits KiCad 8-format .kicad_sch files from component/label tables.
Style: symbols placed on a grid, every pin connected via a global label at the
pin's connection point (no drawn wires). All pins are electrically 'passive' so
ERC checks connectivity/unconnected-pins, not driver conflicts — the netlist is
the deliverable, layout inherits it.

Run: python3 tools/sch_gen.py  (from kicad/)
"""

import itertools

ROOT_UUID = "a1b2c3d4-0000-4000-8000-000000000001"
POWER_SHEET_UUID = "a1b2c3d4-0000-4000-8000-00000000c001"

_uuid_counter = itertools.count(1)


def uid():
    return f"c0ffee00-0000-4000-8000-{next(_uuid_counter):012x}"


F = "(effects (font (size 1.27 1.27)))"
FH = "(effects (font (size 1.27 1.27)) (hide yes))"


def pin(num, name, x, y, angle):
    return (f'      (pin passive line (at {x} {y} {angle}) (length 2.54)\n'
            f'        (name "{name}" {F})\n'
            f'        (number "{num}" {F})\n'
            f'      )\n')


def lib_symbol(name, rect, pins):
    (x1, y1, x2, y2) = rect
    s = (f'    (symbol "hat:{name}" (exclude_from_sim no) (in_bom yes) (on_board yes)\n'
         f'      (property "Reference" "U" (at 0 {y2 + 2.54} 0) {F})\n'
         f'      (property "Value" "{name}" (at 0 {y1 - 2.54} 0) {F})\n'
         f'      (property "Footprint" "" (at 0 0 0) {FH})\n'
         f'      (property "Datasheet" "" (at 0 0 0) {FH})\n'
         f'      (symbol "{name}_0_1"\n'
         f'        (rectangle (start {x1} {y1}) (end {x2} {y2})'
         f' (stroke (width 0.254) (type default)) (fill (type background)))\n'
         f'      )\n'
         f'      (symbol "{name}_1_1"\n')
    for p in pins:
        s += pin(*p)
    s += '      )\n    )\n'
    return s


# ---- symbol library ---------------------------------------------------------
# 2-pin verticals: pin 1 top (local +5.08), pin 2 bottom. Connection point is
# the pin's (at). Schematic Y is inverted vs symbol-local Y.

V2 = [("1", "~", 0, 5.08, 270), ("2", "~", 0, -5.08, 90)]
DIODE = [("1", "K", 0, 5.08, 270), ("2", "A", 0, -5.08, 90)]

LIB = {
    "R": ((-2.54, -3.81, 2.54, 3.81), V2),
    "C": ((-2.54, -3.81, 2.54, 3.81), V2),
    "L": ((-2.54, -3.81, 2.54, 3.81), V2),
    "Fuse": ((-2.54, -3.81, 2.54, 3.81), V2),
    "D_Schottky": ((-2.54, -3.81, 2.54, 3.81), DIODE),
    "Conn_02": ((-5.08, -5.08, 5.08, 5.08),
                [("1", "1", 7.62, 2.54, 180), ("2", "2", 7.62, -2.54, 180)]),
    # Pin "numbers" = pad names of the USB_C_Receptacle_HRO_TYPE-C-31-M-12 footprint.
    "USB_C": ((-5.08, -22.86, 5.08, 22.86),
              [("A1", "GND", 7.62, 20.32, 180), ("A4", "VBUS", 7.62, 17.78, 180),
               ("A5", "CC1", 7.62, 15.24, 180), ("A6", "D+", 7.62, 12.7, 180),
               ("A7", "D-", 7.62, 10.16, 180), ("A8", "SBU1", 7.62, 7.62, 180),
               ("A9", "VBUS", 7.62, 5.08, 180), ("A12", "GND", 7.62, 2.54, 180),
               ("B1", "GND", 7.62, 0, 180), ("B4", "VBUS", 7.62, -2.54, 180),
               ("B5", "CC2", 7.62, -5.08, 180), ("B6", "D+", 7.62, -7.62, 180),
               ("B7", "D-", 7.62, -10.16, 180), ("B8", "SBU2", 7.62, -12.7, 180),
               ("B9", "VBUS", 7.62, -15.24, 180), ("B12", "GND", 7.62, -17.78, 180),
               ("S1", "SHIELD", 7.62, -20.32, 180)]),
    "Q_PMOS": ((-5.08, -5.08, 5.08, 5.08),
               [("1", "G", -7.62, 0, 0), ("2", "S", 7.62, 2.54, 180),
                ("3", "D", 7.62, -2.54, 180)]),
    "DW01A": ((-5.08, -5.08, 5.08, 5.08),
              [("1", "OD", -7.62, 2.54, 0), ("2", "CSI", -7.62, 0, 0),
               ("3", "OC", -7.62, -2.54, 0), ("4", "TD", 7.62, -2.54, 180),
               ("5", "VCC", 7.62, 0, 180), ("6", "GND", 7.62, 2.54, 180)]),
    "MT3608": ((-5.08, -5.08, 5.08, 5.08),
               [("1", "SW", -7.62, 2.54, 0), ("2", "GND", -7.62, 0, 0),
                ("3", "FB", -7.62, -2.54, 0), ("4", "EN", 7.62, -2.54, 180),
                ("5", "IN", 7.62, 0, 180), ("6", "NC", 7.62, 2.54, 180)]),
    "TP4056": ((-5.08, -6.35, 5.08, 6.35),
               [("1", "TEMP", -7.62, 3.81, 0), ("2", "PROG", -7.62, 1.27, 0),
                ("3", "GND", -7.62, -1.27, 0), ("4", "VCC", -7.62, -3.81, 0),
                ("5", "BAT", 7.62, -3.81, 180), ("6", "STDBY", 7.62, -1.27, 180),
                ("7", "CHRG", 7.62, 1.27, 180), ("8", "CE", 7.62, 3.81, 180)]),
    "FS8205A": ((-5.08, -6.35, 5.08, 6.35),
                [("1", "S1", -7.62, 3.81, 0), ("2", "G1", -7.62, 1.27, 0),
                 ("3", "S2", -7.62, -1.27, 0), ("4", "G2", -7.62, -3.81, 0),
                 ("5", "D2", 7.62, -3.81, 180), ("6", "D2b", 7.62, -1.27, 180),
                 ("7", "D1", 7.62, 1.27, 180), ("8", "D1b", 7.62, 3.81, 180)]),
    "D": ((-2.54, -3.81, 2.54, 3.81), DIODE),
    "Q_NMOS": ((-5.08, -5.08, 5.08, 5.08),
               [("1", "G", -7.62, 0, 0), ("2", "D", 7.62, 2.54, 180),
                ("3", "S", 7.62, -2.54, 180)]),
    # SOT-223 variant: pad 4 is the tab, internally the drain (STN1HNK60
    # datasheet pin config) — bound to the same net as pin 2 so the copper
    # tab gets net'd for heat spreading instead of floating.
    "Q_NMOS_TAB": ((-5.08, -5.08, 5.08, 5.08),
               [("1", "G", -7.62, 0, 0), ("2", "D", 7.62, 2.54, 180),
                ("3", "S", 7.62, -2.54, 180), ("4", "TAB", 7.62, 0, 180)]),
    "TC4427": ((-5.08, -6.35, 5.08, 6.35),
               [("1", "NC1", -7.62, 3.81, 0), ("2", "INA", -7.62, 1.27, 0),
                ("3", "GND", -7.62, -1.27, 0), ("4", "INB", -7.62, -3.81, 0),
                ("5", "OUTB", 7.62, -3.81, 180), ("6", "VDD", 7.62, -1.27, 180),
                ("7", "OUTA", 7.62, 1.27, 180), ("8", "NC2", 7.62, 3.81, 180)]),
    "NE5534": ((-5.08, -6.35, 5.08, 6.35),
               [("1", "BAL1", -7.62, 3.81, 0), ("2", "IN-", -7.62, 1.27, 0),
                ("3", "IN+", -7.62, -1.27, 0), ("4", "V-", -7.62, -3.81, 0),
                ("5", "COMP1", 7.62, -3.81, 180), ("6", "OUT", 7.62, -1.27, 180),
                ("7", "V+", 7.62, 1.27, 180), ("8", "COMP2", 7.62, 3.81, 180)]),
    "TL072": ((-5.08, -6.35, 5.08, 6.35),
              [("1", "OUT1", -7.62, 3.81, 0), ("2", "IN1-", -7.62, 1.27, 0),
               ("3", "IN1+", -7.62, -1.27, 0), ("4", "V-", -7.62, -3.81, 0),
               ("5", "IN2+", 7.62, -3.81, 180), ("6", "IN2-", 7.62, -1.27, 180),
               ("7", "OUT2", 7.62, 1.27, 180), ("8", "V+", 7.62, 3.81, 180)]),
    "MCP41010": ((-5.08, -6.35, 5.08, 6.35),
                 [("1", "CS", -7.62, 3.81, 0), ("2", "SCK", -7.62, 1.27, 0),
                  ("3", "SI", -7.62, -1.27, 0), ("4", "VSS", -7.62, -3.81, 0),
                  ("5", "PB0", 7.62, -3.81, 180), ("6", "PW0", 7.62, -1.27, 180),
                  ("7", "PA0", 7.62, 1.27, 180), ("8", "VDD", 7.62, 3.81, 180)]),
    # DRV8833 PWP16 — pinout verified against TI datasheet SLVSAR1E (2026-07-17):
    # 11 VCP, 12 VM, 13 GND, 14 VINT (an earlier from-memory guess had these four
    # rotated; the datasheet check caught it).
    "DRV8833": ((-5.08, -11.43, 5.08, 11.43),
                [("1", "nSLEEP", -7.62, 8.89, 0), ("2", "AOUT1", -7.62, 6.35, 0),
                 ("3", "AISEN", -7.62, 3.81, 0), ("4", "AOUT2", -7.62, 1.27, 0),
                 ("5", "BOUT2", -7.62, -1.27, 0), ("6", "BISEN", -7.62, -3.81, 0),
                 ("7", "BOUT1", -7.62, -6.35, 0), ("8", "nFAULT", -7.62, -8.89, 0),
                 ("9", "BIN1", 7.62, -8.89, 180), ("10", "BIN2", 7.62, -6.35, 180),
                 ("11", "VCP", 7.62, -3.81, 180), ("12", "VM", 7.62, -1.27, 180),
                 ("13", "GND", 7.62, 1.27, 180), ("14", "VINT", 7.62, 3.81, 180),
                 ("15", "AIN2", 7.62, 6.35, 180), ("16", "AIN1", 7.62, 8.89, 180),
                 # pad 17 = PowerPAD exposed pad; TI SLVSAR1E requires it tied
                 # to GND (it is the device's substrate connection, not just
                 # thermal) — was floating before 2026-07-22.
                 ("17", "PAD", 0, -13.97, 90)]),
    "Conn_12": ((-5.08, -16.51, 5.08, 16.51),
                [("1", "1", 7.62, 13.97, 180),
                 ("2", "2", 7.62, 11.43, 180),
                 ("3", "3", 7.62, 8.89, 180),
                 ("4", "4", 7.62, 6.35, 180),
                 ("5", "5", 7.62, 3.81, 180),
                 ("6", "6", 7.62, 1.27, 180),
                 ("7", "7", 7.62, -1.27, 180),
                 ("8", "8", 7.62, -3.81, 180),
                 ("9", "9", 7.62, -6.35, 180),
                 ("10", "10", 7.62, -8.89, 180),
                 ("11", "11", 7.62, -11.43, 180),
                 ("12", "12", 7.62, -13.97, 180)]),
    "Cell_18650": ((-5.08, -5.08, 5.08, 5.08),
                [("1", "+", 7.62, 2.54, 180), ("2", "-", 7.62, -2.54, 180)]),
    "Edge_12": ((-5.08, -16.51, 5.08, 16.51),
                [("1", "1", 7.62, 13.97, 180),
                 ("2", "2", 7.62, 11.43, 180),
                 ("3", "3", 7.62, 8.89, 180),
                 ("4", "4", 7.62, 6.35, 180),
                 ("5", "5", 7.62, 3.81, 180),
                 ("6", "6", 7.62, 1.27, 180),
                 ("7", "7", 7.62, -1.27, 180),
                 ("8", "8", 7.62, -3.81, 180),
                 ("9", "9", 7.62, -6.35, 180),
                 ("10", "10", 7.62, -8.89, 180),
                 ("11", "11", 7.62, -11.43, 180),
                 ("12", "12", 7.62, -13.97, 180)]),
    "Edge_Coil": ((-5.08, -5.08, 5.08, 5.08),
                [("1", "COIL_A", 7.62, 2.54, 180), ("4", "COIL_B", 7.62, -2.54, 180)]),
    "Conn_03": ((-5.08, -5.08, 5.08, 5.08),
                [("1", "1", 7.62, 2.54, 180), ("2", "2", 7.62, 0, 180),
                 ("3", "3", 7.62, -2.54, 180)]),
    "Conn_04": ((-5.08, -6.35, 5.08, 6.35),
                [("1", "1", 7.62, 3.81, 180), ("2", "2", 7.62, 1.27, 180),
                 ("3", "3", 7.62, -1.27, 180), ("4", "4", 7.62, -3.81, 180)]),
    # Raspberry Pi Pico module, 40-pin: left 1-20 top-down, right 40-21 top-down.
    "Pico": ((-12.7, -26.67, 12.7, 26.67),
             [(str(i + 1), n, -15.24, 24.13 - i * 2.54, 0) for i, n in enumerate(
                 ["GP0", "GP1", "GND", "GP2", "GP3", "GP4", "GP5", "GND", "GP6",
                  "GP7", "GP8", "GP9", "GND", "GP10", "GP11", "GP12", "GP13",
                  "GND", "GP14", "GP15"])] +
             [(str(40 - i), n, 15.24, 24.13 - i * 2.54, 180) for i, n in enumerate(
                 ["VBUS", "VSYS", "GND", "3V3_EN", "3V3", "ADC_VREF", "GP28",
                  "AGND", "GP27", "GP26", "RUN", "GP22", "GND", "GP21", "GP20",
                  "GP19", "GP18", "GND", "GP17", "GP16"])]),
}


def snap(v):
    """Snap to KiCad's 1.27 mm connection grid."""
    return round(round(v / 1.27) * 1.27, 2)


def pin_pos(lib, sx, sy):
    """Schematic-space connection points (and pin angles) of a placed symbol."""
    return [(num, sx + px, sy - py, a) for (num, _n, px, py, a) in LIB[lib][1]]


SMALL = {"R", "C", "L", "Fuse", "D_Schottky", "D"}  # 2-pin verticals: text beside body

# ---- Footprint assignment (all names verified to exist in KiCad 9's libraries,
# 2026-07-17; "hat:" = project lib generated below). LCSC codes get confirmed in
# JLCPCB's BOM-matching UI from the Value/MPN strings — the schematic carries an
# empty LCSC field for that step to fill.

_R0603 = "Resistor_SMD:R_0603_1608Metric"
_C0603 = "Capacitor_SMD:C_0603_1608Metric"
_C0805 = "Capacitor_SMD:C_0805_2012Metric"
_C1206 = "Capacitor_SMD:C_1206_3216Metric"
_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
_SOT236 = "Package_TO_SOT_SMD:SOT-23-6"
_GH2 = "Connector_JST:JST_GH_BM02B-GHS-TBT_1x02-1MP_P1.25mm_Vertical"
_GH3 = "Connector_JST:JST_GH_BM03B-GHS-TBT_1x03-1MP_P1.25mm_Vertical"
_GH4 = "Connector_JST:JST_GH_BM04B-GHS-TBT_1x04-1MP_P1.25mm_Vertical"

LCSC = { "BT1": "C19184085", "C1": "C440198", "C10": "C14663", "C11": "C14663", "C12": "C14663", "C13": "C1603", "C14": "C14663", "C16": "C14663", "C17": "C57112", "C18": "C377773", "C19": "C14663", "C2": "C14663", "C20": "C2891567", "C3": "C12891", "C4": "C12891", "C5": "C12891", "C6": "C12891", "C7": "C4747974", "C8": "C4747974", "C9": "C4747974", "D1": "C8678", "D10": "C7502705", "D2": "C2940198", "D3": "C81598", "D4": "C81598", "D5": "C7502705", "D6": "C7502705", "D7": "C8678", "D8": "C8678", "D9": "C7502705", "F1": "C3102", "J10": "C2905423", "J11": "C2905423", "J4": "C32713263", "J5": "C239346", "J9": "C54582898", "L1": "C15857", "L2": "C15857", "Q1": "C15127", "Q2": "C5148694", "Q3": "C2764050", "Q4": "C39303", "Q5": "C39303", "Q6": "C39303", "R1": "C25803", "R10": "C175457", "R11": "C23228", "R12": "C23138", "R13": "C22808", "R14": "C185372", "R15": "C98220", "R16": "C22775", "R17": "C22775", "R18": "C22775", "R2": "C22548", "R20": "C22548", "R21": "C23212", "R22": "C22978", "R23": "C22859", "R24": "C25803", "R25": "C25803", "R26": "C25803", "R3": "C23186", "R30": "C23138", "R31": "C23162", "R32": "C23162", "R4": "C23186", "R40": "C22775", "R41": "C98220", "R42": "C98220", "R43": "C98220", "R44": "C23260", "R45": "C22548", "R47": "C22548", "R48": "C22548", "R49": "C25803", "R5": "C22775", "R6": "C22548", "R7": "C22765", "R8": "C22932", "R9": "C98220", "U1": "C382139", "U2": "C18164398", "U3": "C19189893", "U4": "C19189893", "U5": "C20551", "U6": "C49396707", "U7": "C136395", "U8": "C50506", "U9": "C5157710" }

FOOTPRINTS = {
    # power sheet
    "BT1": "hat:BatteryHolder_MYOUNG_A6AJ002",
    "F1": "Fuse:Fuse_1812_4532Metric",
    "U2": _SOT236, "R5": _R0603, "C2": _C0603, "R6": _R0603,
    "Q2": "Package_SO:TSSOP-8_4.4x3mm_P0.65mm",
    "Q1": "Package_TO_SOT_SMD:SOT-23", "R1": _R0603, "R2": _R0603,
    "D7": "Diode_SMD:D_SMA",
    "J3": "Connector_PinSocket_2.54mm:PinSocket_1x02_P2.54mm_Vertical",
    "U1": "Package_SO:SO-8_3.9x4.9mm_P1.27mm", "R7": _R0603, "C1": _C0805,
    "U3": _SOT236, "U4": _SOT236,
    "L1": "Inductor_SMD:L_Sunlord_SWPA8040S",
    "L2": "Inductor_SMD:L_Sunlord_SWPA8040S",
    "D1": "Diode_SMD:D_SMA", "D8": "Diode_SMD:D_SMA",
    "C3": _C1206, "C4": _C1206, "C5": _C1206, "C6": _C1206,
    "R8": _R0603, "R9": _R0603, "R14": _R0603, "R15": _R0603,
    "C7": "Capacitor_SMD:CP_Elec_8x10.5", "C8": "Capacitor_SMD:CP_Elec_8x10.5",
    "C9": "Capacitor_SMD:CP_Elec_8x10.5",
    # TX sheet
    "U5": _SOIC8, "C10": _C0603, "R23": _R0603,
    "Q3": "Package_TO_SOT_SMD:TO-252-2",
    "J4": "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Horizontal",
    "D2": "Diode_SMD:D_SMB", "R10": "Resistor_SMD:R_2512_6332Metric",
    "R11": _R0603, "R12": _R0603, "R13": _R0603,
    "Q4": "Package_TO_SOT_SMD:SOT-223", "Q5": "Package_TO_SOT_SMD:SOT-223",
    "Q6": "Package_TO_SOT_SMD:SOT-223",
    "R16": _R0603, "R17": _R0603, "R18": _R0603,
    "R24": _R0603, "R25": _R0603, "R26": _R0603,
    # RX sheet
    "R20": _R0603, "D3": "Diode_SMD:D_SOD-123", "D4": "Diode_SMD:D_SOD-123",
    "C11": _C0603, "R49": _R0603,
    "U6": _SOIC8, "R40": _R0603, "R41": _R0603, "C12": _C0603,
    "R48": _R0603, "D9": "Diode_SMD:D_SOD-123", "D10": "Diode_SMD:D_SOD-123",
    "U7": _SOIC8, "C16": _C0603, "U9": _SOIC8,
    "R45": _R0603, "R44": _R0603, "R42": _R0603, "R43": _R0603, "C14": _C0603,
    "R21": _R0603, "R22": _R0603, "R47": _R0603, "C13": _C0603,
    "D5": "Diode_SMD:D_SOD-123", "D6": "Diode_SMD:D_SOD-123",
    # IO sheet
    "U10": "hat:RPi_Pico_Socket",
    "U8": "Package_SO:HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm",
    "C17": _C0603, "C18": _C0805, "C19": _C0603,
    "J1": "Connector_PinSocket_2.54mm:PinSocket_1x02_P2.54mm_Vertical",
    "J2": "Connector_PinSocket_2.54mm:PinSocket_1x02_P2.54mm_Vertical",
    "R30": _R0603, "C20": "Capacitor_SMD:CP_Elec_6.3x7.7",
    "R31": _R0603, "R32": _R0603,
    "J6": _GH4, "J7": _GH4, "J8": _GH3,
    "J9": "Connector_JST:JST_GH_SM03B-GHS-TB_1x03-1MP_P1.25mm_Horizontal",
}


def instance(ref, lib, value, x, y, sheet_uuid):
    if lib in SMALL:
        refpos, valpos = (x + 3.81, y - 1.27), (x + 3.81, y + 1.27)
        just = "(justify left)"
    else:
        refpos, valpos = (x, y - 10.16), (x, y + 10.16)
        just = ""
    s = (f'  (symbol (lib_id "hat:{lib}") (at {x} {y} 0) (unit 1)\n'
         f'    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)\n'
         f'    (uuid "{uid()}")\n'
         f'    (property "Reference" "{ref}" (at {refpos[0]} {refpos[1]} 0)'
         f' (effects (font (size 1.27 1.27)) {just}))\n'
         f'    (property "Value" "{value}" (at {valpos[0]} {valpos[1]} 0)'
         f' (effects (font (size 1.27 1.27)) {just}))\n'
         f'    (property "Footprint" "{FOOTPRINTS.get(ref, "")}" (at {x} {y} 0) {FH})\n'
         f'    (property "Datasheet" "" (at {x} {y} 0) {FH})\n'
         f'    (property "LCSC" "{LCSC.get(ref, "")}" (at {x} {y} 0) {FH})\n')
    for (num, _name, _px, _py, _a) in LIB[lib][1]:
        s += f'    (pin "{num}" (uuid "{uid()}"))\n'
    s += (f'    (instances (project "detector-hat"'
          f' (path "/{ROOT_UUID}/{sheet_uuid}" (reference "{ref}") (unit 1))))\n'
          f'  )\n')
    return s


def glabel(net, x, y, pin_angle):
    # Label extends away from the symbol body: opposite the pin's direction.
    angle = (pin_angle + 180) % 360
    justify = "left" if angle in (0, 90) else "right"
    return (f'  (global_label "{net}" (shape input) (at {x} {y} {angle})'
            f' (fields_autoplaced yes)\n'
            f'    (effects (font (size 1.27 1.27)) (justify {justify}))\n'
            f'    (uuid "{uid()}")\n'
            f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {x} {y} 0) {FH})\n'
            f'  )\n')


def no_connect(x, y):
    return f'  (no_connect (at {x} {y}) (uuid "{uid()}"))\n'


def emit_sheet(filename, sheet_uuid, file_uuid, parts):
    """parts: list of (ref, lib, value, x, y, {pin_num: net or 'NC'})"""
    body = ""
    used_libs = sorted({lib for (_r, lib, *_rest) in parts})
    for (ref, lib, value, x, y, nets) in parts:
        x, y = snap(x), snap(y)
        body += instance(ref, lib, value, x, y, sheet_uuid)
        for (num, cx, cy, pang) in pin_pos(lib, x, y):
            net = nets[num]  # KeyError = table bug, want it loud
            cx, cy = round(cx, 2), round(cy, 2)
            if net == "NC":
                body += no_connect(cx, cy)
            else:
                body += glabel(net, cx, cy, pang)

    libs = "".join(lib_symbol(name, *LIB[name]) for name in used_libs)
    content = (f'(kicad_sch\n'
               f'  (version 20231120)\n'
               f'  (generator "sch_gen")\n'
               f'  (generator_version "8.0")\n'
               f'  (uuid "{file_uuid}")\n'
               f'  (paper "A3")\n'
               f'  (lib_symbols\n{libs}  )\n'
               f'{body})\n')
    with open(filename, "w") as f:
        f.write(content)
    print(f"wrote {filename}: {len(parts)} parts")


# ---- Power sheet (docs/HAT-SCHEMATIC-SPEC.md sheet 1) ------------------------

POWER = [
    # battery input + protection
    ("BT1", "Cell_18650", "18650 THT terminals mid-board bottom (MYOUNG BH-18650-A6AJ002)", 40, 45,
     {"1": "VBAT_RAW", "2": "BAT_NEG"}),
    ("F1", "Fuse", "polyfuse 2A", 65, 45, {"1": "VBAT_RAW", "2": "VBAT_P"}),
    ("U2", "DW01A", "DW01A", 90, 45,
     {"1": "DW_OD", "2": "DW_CS", "3": "DW_OC", "4": "NC", "5": "DW_VCC", "6": "BAT_NEG"}),
    ("R5", "R", "100R", 115, 45, {"1": "VBAT_P", "2": "DW_VCC"}),
    ("C2", "C", "100nF 50V", 140, 45, {"1": "DW_VCC", "2": "BAT_NEG"}),
    ("R6", "R", "1k", 165, 45, {"1": "DW_CS", "2": "GND"}),
    ("Q2", "FS8205A", "FS8205A", 190, 45,
     {"1": "BAT_NEG", "2": "DW_OD", "3": "GND", "4": "DW_OC",
      "5": "FET_D", "6": "FET_D", "7": "FET_D", "8": "FET_D"}),
    # main switch (reed) + VSYS diode-OR
    ("Q1", "Q_PMOS", "AO3401A", 40, 75, {"1": "Q1_G", "2": "VBAT_P", "3": "VBAT_SW"}),
    ("R1", "R", "100k", 65, 75, {"1": "VBAT_P", "2": "Q1_G"}),
    ("R2", "R", "1k", 90, 75, {"1": "Q1_G", "2": "REED"}),
    ("D7", "D_Schottky", "SS34", 140, 75, {"1": "VSYS_PICO", "2": "VBAT_SW"}),
    # charger
    # 2026-07-24: USB-C dropped. External micro-USB jack on the housing feeds
    # 5V+GND into this 1x2 socket (VBUS_C kept as the charge-input net name, in
    # the Power netclass). CC pull-downs R3/R4 deleted (no CC handshake now).
    ("J3", "Conn_02", "5V charge input (1x2 socket, ext micro-USB)", 40, 105,
     {"1": "VBUS_C", "2": "GND"}),
    ("U1", "TP4056", "TP4056", 115, 105,
     {"1": "GND", "2": "TP_PROG", "3": "GND", "4": "VBUS_C",
      "5": "VBAT_P", "6": "NC", "7": "NC", "8": "VBUS_C"}),
    ("R7", "R", "1k2", 140, 105, {"1": "TP_PROG", "2": "GND"}),
    ("C1", "C", "10uF 25V", 165, 105, {"1": "VBUS_C", "2": "GND"}),
    # boost 12V TX rail
    ("U3", "MT3608", "MT3608 12V", 40, 135,
     {"1": "SW1", "2": "GND", "3": "FB1", "4": "VBAT_SW", "5": "VBAT_SW", "6": "NC"}),
    ("L1", "L", "22uH 3A", 65, 135, {"1": "VBAT_SW", "2": "SW1"}),
    ("D1", "D_Schottky", "SS34", 90, 135, {"1": "V12_TX", "2": "SW1"}),
    ("C3", "C", "22uF 25V", 115, 135, {"1": "VBAT_SW", "2": "GND"}),
    ("C4", "C", "22uF 25V", 140, 135, {"1": "V12_TX", "2": "GND"}),
    ("R8", "R", "191k", 165, 135, {"1": "V12_TX", "2": "FB1"}),
    ("R9", "R", "10k", 190, 135, {"1": "FB1", "2": "GND"}),
    ("C7", "C", "220uF 25V", 215, 135, {"1": "V12_TX", "2": "GND"}),
    ("C8", "C", "220uF 25V", 240, 135, {"1": "V12_TX", "2": "GND"}),
    # boost 9V sounder rail + third bulk cap
    ("U4", "MT3608", "MT3608 9V", 40, 165,
     {"1": "SW2", "2": "GND", "3": "FB2", "4": "VBAT_SW", "5": "VBAT_SW", "6": "NC"}),
    ("L2", "L", "22uH 3A", 65, 165, {"1": "VBAT_SW", "2": "SW2"}),
    ("D8", "D_Schottky", "SS34", 90, 165, {"1": "V9_SND", "2": "SW2"}),
    ("C5", "C", "22uF 25V", 115, 165, {"1": "VBAT_SW", "2": "GND"}),
    ("C6", "C", "22uF 25V", 140, 165, {"1": "V9_SND", "2": "GND"}),
    ("R14", "R", "140k", 165, 165, {"1": "V9_SND", "2": "FB2"}),
    ("R15", "R", "10k", 190, 165, {"1": "FB2", "2": "GND"}),
    ("C9", "C", "220uF 25V", 215, 165, {"1": "V12_TX", "2": "GND"}),
]

def emit_library(filename):
    """Project symbol library so the 'hat' nickname resolves (kills ERC noise)."""
    libs = "".join(lib_symbol(name, *LIB[name]) for name in sorted(LIB))
    libs = libs.replace('(symbol "hat:', '(symbol "')
    with open(filename, "w") as f:
        f.write(f'(kicad_symbol_lib (version 20231120) (generator "sch_gen")\n'
                f'{libs})\n')
    print(f"wrote {filename}")


def emit_sym_lib_table(filename):
    with open(filename, "w") as f:
        f.write('(sym_lib_table\n  (version 7)\n'
                '  (lib (name "hat") (type "KiCad")'
                ' (uri "${KIPRJMOD}/hat.kicad_sym") (options "") (descr "project symbols"))\n)\n')
    print(f"wrote {filename}")


def emit_battery_footprint():
    """MYOUNG BH-18650-A6AJ002: 2 THT solder-terminal pads ARE the mounting
    holes (no separate pegs). Datasheet: overall 77mm +/-0.5, hole spacing
    71.45mm, hole 1.3x2.6mm, centered on holder width. Authored at rotation=0
    (pads on local Y axis) so board-space X/Y extents match directly."""
    d = 35.725  # half of 71.45mm spacing
    pads = ""
    for num, y in (("1", d), ("2", -d)):  # 1=VBAT_RAW (south), 2=BAT_NEG (north)
        pads += (f'  (pad "{num}" thru_hole rect (at 0 {y})'
                 f' (size 2.9 1.6) (drill oval 2.6 1.3) (layers "*.Cu" "*.Mask"))\n')
    # third mounting/keying hole (round, NPTH), from corrected datasheet:
    # 2.4mm dia, 7.9mm across width (toward Q1/U2/U1 side), 36mm along
    # length toward the + terminal side (local +y, matching VBAT_RAW's sign)
    pads += ('  (pad "" np_thru_hole circle (at -7.9 36.0)'
             ' (size 2.4 2.4) (drill 2.4) (layers "*.Cu" "*.Mask"))\n')
    # body outline (fab) + courtyard so KiCad flags overlaps when parts are
    # dragged onto the holder. Body ~20.5mm wide x 77mm long (datasheet
    # overall 77); courtyard = body + 0.25mm keep-out all round. Both authored
    # on F.* — the pipeline flip to the bottom carries them to B.* with it.
    hw, hl = 10.25, 38.5          # half-width, half-length of the body
    cw, cl = hw + 0.25, hl + 0.25  # courtyard half-extents
    outlines = (
        f'  (fp_rect (start {-hw} {-hl}) (end {hw} {hl})'
        ' (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))\n'
        f'  (fp_rect (start {-cw} {-cl}) (end {cw} {cl})'
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))\n')
    with open("hat.pretty/BatteryHolder_MYOUNG_A6AJ002.kicad_mod", "w") as f:
        f.write('(footprint "BatteryHolder_MYOUNG_A6AJ002" (version 20221018) (generator "sch_gen")\n'
                '  (layer "F.Cu")\n  (attr through_hole)\n'
                '  (fp_text reference "REF**" (at 0 -40) (layer "F.SilkS")'
                ' (effects (font (size 1 1) (thickness 0.15))))\n'
                '  (fp_text value "BatteryHolder_MYOUNG_A6AJ002" (at 0 40) (layer "F.Fab")'
                ' (effects (font (size 1 1) (thickness 0.15))))\n'
                + outlines + pads + ')\n')
    print("wrote hat.pretty/BatteryHolder_MYOUNG_A6AJ002.kicad_mod")


def emit_pico_footprint():
    """Custom footprint: Pico socket (2x20 THT @2.54mm, rows 17.78mm apart,
    pin 1 top-left / 20 bottom-left / 21 bottom-right / 40 top-right) plus the
    Pico's four 2.1 mm mounting holes on the 11.4 x 47 mm pattern."""
    import os
    os.makedirs("hat.pretty", exist_ok=True)
    pads = ""
    for i in range(20):  # left column, 1..20 top->bottom
        y = -24.13 + i * 2.54
        shape = "rect" if i == 0 else "circle"
        pads += (f'  (pad "{i + 1}" thru_hole {shape} (at -8.89 {y:.2f})'
                 f' (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))\n')
    for i in range(20):  # right column, 21..40 bottom->top
        y = 24.13 - i * 2.54
        pads += (f'  (pad "{i + 21}" thru_hole circle (at 8.89 {y:.2f})'
                 f' (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))\n')
    for hx in (-5.7, 5.7):
        for hy in (-23.5, 23.5):
            pads += (f'  (pad "" np_thru_hole circle (at {hx} {hy})'
                     f' (size 2.1 2.1) (drill 2.1) (layers "*.Cu" "*.Mask"))\n')
    outline = ""
    for (x1, y1, x2, y2) in [(-10.5, -25.5, 10.5, -25.5), (10.5, -25.5, 10.5, 25.5),
                             (10.5, 25.5, -10.5, 25.5), (-10.5, 25.5, -10.5, -25.5)]:
        outline += (f'  (fp_line (start {x1} {y1}) (end {x2} {y2})'
                    f' (stroke (width 0.12) (type solid)) (layer "F.SilkS"))\n')
    with open("hat.pretty/RPi_Pico_Socket.kicad_mod", "w") as f:
        f.write('(footprint "RPi_Pico_Socket" (version 20221018) (generator "sch_gen")\n'
                '  (layer "F.Cu")\n  (attr through_hole)\n'
                '  (fp_text reference "REF**" (at 0 -27) (layer "F.SilkS")'
                ' (effects (font (size 1 1) (thickness 0.15))))\n'
                '  (fp_text value "RPi_Pico_Socket" (at 0 27) (layer "F.Fab")'
                ' (effects (font (size 1 1) (thickness 0.15))))\n'
                + outline + pads + ')\n')
    with open("fp-lib-table", "w") as f:
        f.write('(fp_lib_table\n  (version 7)\n'
                '  (lib (name "hat") (type "KiCad")'
                ' (uri "${KIPRJMOD}/hat.pretty") (options "") (descr "project footprints"))\n)\n')
    print("wrote hat.pretty/RPi_Pico_Socket.kicad_mod + fp-lib-table")


# ---- TX + damping sheet (spec sheet 2) --------------------------------------

TX = [
    ("U5", "TC4427", "TC4427", 40, 45,
     {"1": "NC", "2": "TX_GATE", "3": "GND", "4": "TX_GATE",
      "5": "DRV_OUT", "6": "V12_TX", "7": "DRV_OUT", "8": "NC"}),
    ("C10", "C", "100nF 50V", 65, 45, {"1": "V12_TX", "2": "GND"}),
    ("R23", "R", "10R", 90, 45, {"1": "DRV_OUT", "2": "Q3_G"}),
    ("Q3", "Q_NMOS", "STF10N60", 115, 45, {"1": "Q3_G", "2": "COIL_A", "3": "GND"}),
    ("J4", "Edge_Coil", "coil dock: 1x4 right-angle header, outer pins only (7.62mm gap for 300V)", 140, 45,
     {"1": "COIL_A", "4": "V12_TX"}),
    ("D2", "D", "MUR160", 165, 45, {"1": "V12_TX", "2": "COIL_A"}),
    ("R10", "R", "1k 2W", 190, 45, {"1": "COIL_A", "2": "GND"}),
    # damping bank: COIL_A -> R -> HV FET -> GND, gate from DAMPn GPIO
    ("R11", "R", "680R", 40, 85, {"1": "COIL_A", "2": "DMP0"}),
    ("Q4", "Q_NMOS_TAB", "STN1HNK60", 65, 85, {"1": "DG0", "2": "DMP0", "3": "GND", "4": "DMP0"}),
    ("R16", "R", "100R", 90, 85, {"1": "DAMP0", "2": "DG0"}),
    ("R24", "R", "100k", 115, 85, {"1": "DG0", "2": "GND"}),
    ("R12", "R", "330R", 40, 115, {"1": "COIL_A", "2": "DMP1"}),
    ("Q5", "Q_NMOS_TAB", "STN1HNK60", 65, 115, {"1": "DG1", "2": "DMP1", "3": "GND", "4": "DMP1"}),
    ("R17", "R", "100R", 90, 115, {"1": "DAMP1", "2": "DG1"}),
    ("R25", "R", "100k", 115, 115, {"1": "DG1", "2": "GND"}),
    ("R13", "R", "150R", 40, 145, {"1": "COIL_A", "2": "DMP2"}),
    ("Q6", "Q_NMOS_TAB", "STN1HNK60", 65, 145, {"1": "DG2", "2": "DMP2", "3": "GND", "4": "DMP2"}),
    ("R18", "R", "100R", 90, 145, {"1": "DAMP2", "2": "DG2"}),
    ("R26", "R", "100k", 115, 145, {"1": "DG2", "2": "GND"}),
]

# ---- RX chain sheet (spec sheet 3) ------------------------------------------

RX = [
    # input conditioning: COIL_A -> series R -> clamp -> AC couple -> bias
    ("R20", "R", "1k", 40, 45, {"1": "COIL_A", "2": "RX_CL"}),
    ("D3", "D", "1N4148W", 65, 45, {"1": "V9_SND", "2": "RX_CL"}),
    ("D4", "D", "1N4148W", 90, 45, {"1": "RX_CL", "2": "GND"}),
    ("C11", "C", "100nF 50V", 115, 45, {"1": "RX_CL", "2": "RX_B"}),
    ("R49", "R", "100k", 140, 45, {"1": "RX_B", "2": "VREF"}),
    # stage 1: NE5534 non-inverting x101 around VREF
    ("U6", "NE5534", "NE5534", 40, 85,
     {"1": "NC", "2": "U6_FB", "3": "RX_B", "4": "GND",
      "5": "NC", "6": "U6_OUT", "7": "V9_SND", "8": "NC"}),
    ("R40", "R", "100R", 65, 85, {"1": "U6_FB", "2": "VREF"}),
    ("R41", "R", "10k", 90, 85, {"1": "U6_OUT", "2": "U6_FB"}),
    ("C12", "C", "100nF 50V", 115, 85, {"1": "V9_SND", "2": "GND"}),
    # inter-stage clamp to digipot's 3V3 domain
    ("R48", "R", "1k", 140, 85, {"1": "U6_OUT", "2": "POT_A"}),
    ("D9", "D", "BAT54W", 165, 85, {"1": "3V3", "2": "POT_A"}),
    ("D10", "D", "BAT54W", 190, 85, {"1": "POT_A", "2": "GND"}),
    # digipot as gain attenuator (SPI from Pico)
    ("U7", "MCP41010", "MCP41010", 40, 125,
     {"1": "POT_CS", "2": "SPI_SCK", "3": "SPI_MOSI", "4": "GND",
      "5": "VREF", "6": "STG2_IN", "7": "POT_A", "8": "3V3"}),
    ("C16", "C", "100nF 50V", 65, 125, {"1": "3V3", "2": "GND"}),
    # stage 2 (TL072 A) x10 + VREF buffer (TL072 B) from 3V3 divider
    ("U9", "TL072", "TL072", 90, 125,
     {"1": "STG2_OUT", "2": "U9_FB", "3": "STG2_IN", "4": "GND",
      "5": "VREF_DIV", "6": "VREF", "7": "VREF", "8": "V9_SND"}),
    ("R45", "R", "1k", 115, 125, {"1": "U9_FB", "2": "VREF"}),
    ("R44", "R", "9k1", 140, 125, {"1": "STG2_OUT", "2": "U9_FB"}),
    ("R42", "R", "10k", 165, 125, {"1": "3V3", "2": "VREF_DIV"}),
    ("R43", "R", "10k", 190, 125, {"1": "VREF_DIV", "2": "GND"}),
    ("C14", "C", "100nF 50V", 215, 125, {"1": "V9_SND", "2": "GND"}),
    # ADC scaling, anti-alias, clamp -> Pico GP26
    ("R21", "R", "6k8", 40, 165, {"1": "STG2_OUT", "2": "RX_DIV"}),
    ("R22", "R", "3k3", 65, 165, {"1": "RX_DIV", "2": "GND"}),
    ("R47", "R", "1k", 90, 165, {"1": "RX_DIV", "2": "RX_ADC"}),
    ("C13", "C", "220pF 50V", 115, 165, {"1": "RX_ADC", "2": "GND"}),
    ("D5", "D", "BAT54W", 140, 165, {"1": "3V3", "2": "RX_ADC"}),
    ("D6", "D", "BAT54W", 165, 165, {"1": "RX_ADC", "2": "GND"}),
]

# ---- IO / Pico sheet (spec sheet 4) -----------------------------------------

IO = [
    ("U10", "Pico", "Raspberry Pi Pico (socketed)", 60, 80,
     {"1": "UART_TX", "2": "UART_RX", "3": "GND", "4": "SPI_SCK", "5": "SPI_MOSI",
      "6": "NC", "7": "NC", "8": "GND", "9": "POT_CS", "10": "NC",
      "11": "I2C_SDA", "12": "I2C_SCL", "13": "GND", "14": "DAMP0", "15": "DAMP1",
      "16": "DAMP2", "17": "WS_GP", "18": "GND", "19": "SND_A", "20": "SND_B",
      "21": "NC", "22": "TX_GATE", "23": "GND", "24": "NC", "25": "NC",
      "26": "NC", "27": "NC", "28": "GND", "29": "NC", "30": "NC",
      "31": "RX_ADC", "32": "NC", "33": "GND", "34": "NC", "35": "NC",
      "36": "3V3", "37": "NC", "38": "GND", "39": "VSYS_PICO", "40": "NC"}),
    ("U8", "DRV8833", "DRV8833PWP", 130, 60,
     {"1": "3V3", "2": "PIEZO_P", "3": "GND", "4": "PIEZO_N", "17": "GND",
      "5": "NC", "6": "GND", "7": "NC", "8": "NC",
      "9": "GND", "10": "GND", "11": "DRV_VCP", "12": "V9_SND",
      "13": "GND", "14": "DRV_VINT", "15": "SND_B", "16": "SND_A"}),
    ("C17", "C", "10nF 25V", 155, 60, {"1": "DRV_VCP", "2": "V9_SND"}),
    ("C18", "C", "2.2uF 16V", 180, 60, {"1": "DRV_VINT", "2": "GND"}),
    ("C19", "C", "100nF 50V", 205, 60, {"1": "V9_SND", "2": "GND"}),
    # 2026-07-24: OLED/depth/LED moved to top-side GH docks J6/J7/J8; the old
    # 2x6 dock J5 is retired and split into two 1x2 sockets (same 2.54mm socket
    # type as J5) — J1 piezo, J2 power switch — to be placed at the board corners.
    ("J1", "Conn_02", "piezo dock (1x2 socket)", 130, 95,
     {"1": "PIEZO_P", "2": "PIEZO_N"}),
    ("J2", "Conn_02", "power switch dock (1x2 socket)", 155, 95,
     {"1": "REED", "2": "GND"}),
    ("R30", "R", "330R", 155, 120, {"1": "WS_GP", "2": "WS_DATA"}),
    ("C20", "C", "100uF 10V", 180, 120, {"1": "VBAT_SW", "2": "GND"}),
    ("R31", "R", "4k7", 155, 150, {"1": "3V3", "2": "I2C_SDA"}),
    ("R32", "R", "4k7", 180, 150, {"1": "3V3", "2": "I2C_SCL"}),
    ("J9", "Conn_03", "debug UART (GH)", 130, 210,
     {"1": "GND", "2": "UART_TX", "3": "UART_RX"}),
    # top-side display/sensor docks (vertical GH, glued devices plug in from above)
    ("J6", "Conn_04", "OLED I2C dock (GH BM04B-GHS-TBT)", 230, 60,
     {"1": "3V3", "2": "I2C_SDA", "3": "I2C_SCL", "4": "GND"}),
    ("J7", "Conn_04", "depth meter I2C dock (GH BM04B-GHS-TBT)", 230, 100,
     {"1": "3V3", "2": "I2C_SDA", "3": "I2C_SCL", "4": "GND"}),
    ("J8", "Conn_03", "WS2812 LED dock (GH BM03B-GHS-TBT)", 230, 140,
     {"1": "VBAT_SW", "2": "WS_DATA", "3": "GND"}),
]



def emit_edge_footprints():
    """Card-edge finger footprints. Origin on the board edge, fingers extend
    +y into the board; place at (x,0,0) for the north edge, (x,135,180) south."""
    def finger(num, x, layer):
        mask = layer.replace("Cu", "Mask")
        return (f'  (pad "{num}" smd rect (at {x} 3.5) (size 1.8 7)'
                f' (layers "{layer}" "{mask}"))\n')
    fps = {
        "EdgeFingers_2x6":
            "".join(finger(i + 1, -6.35 + i * 2.54, "F.Cu") for i in range(6)) +
            "".join(finger(i + 7, -6.35 + i * 2.54, "B.Cu") for i in range(6)),
        "EdgeFingers_Coil4":
            finger(1, -3.81, "F.Cu") + finger(1, -3.81, "B.Cu") +
            finger(2, 3.81, "F.Cu") + finger(2, 3.81, "B.Cu"),
    }
    for name, pads in fps.items():
        with open(f"hat.pretty/{name}.kicad_mod", "w") as f:
            f.write(f'(footprint "{name}" (version 20221018) (generator "sch_gen")\n'
                    f'  (layer "F.Cu")\n  (attr smd exclude_from_pos_files)\n'
                    f'  (fp_text reference "REF**" (at 0 9) (layer "F.SilkS")'
                    f' (effects (font (size 1 1) (thickness 0.15))))\n'
                    f'  (fp_text value "{name}" (at 0 11) (layer "F.Fab")'
                    f' (effects (font (size 1 1) (thickness 0.15))))\n'
                    + pads + ')\n')
    print("wrote edge finger footprints")

if __name__ == "__main__":
    emit_library("hat.kicad_sym")
    emit_sym_lib_table("sym-lib-table")
    emit_pico_footprint()
    emit_battery_footprint()
    emit_edge_footprints()
    emit_sheet("power.kicad_sch", POWER_SHEET_UUID,
               "b1b2c3d4-0000-4000-8000-000000000001", POWER)
    emit_sheet("tx_damping.kicad_sch", "a1b2c3d4-0000-4000-8000-00000000c002",
               "b1b2c3d4-0000-4000-8000-000000000002", TX)
    emit_sheet("rx_chain.kicad_sch", "a1b2c3d4-0000-4000-8000-00000000c003",
               "b1b2c3d4-0000-4000-8000-000000000003", RX)
    emit_sheet("io_pico.kicad_sch", "a1b2c3d4-0000-4000-8000-00000000c004",
               "b1b2c3d4-0000-4000-8000-000000000004", IO)
