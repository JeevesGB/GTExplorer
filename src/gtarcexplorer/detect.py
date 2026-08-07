import struct
from .replay import detect_replay

# (magic_bytes, type_name, extension)
# Order matters: longer / more specific magics first where needed.
_PREFIX_MAGICS = [
    # Core GT containers / models
    (b"@(#)GT-ARC", "Nested GT-ARC", ".arc"),
    (b"@(#)GT-PS", "GT-PS Model", ".ps"),
    (b"@(#)GT-CAR", "GT-CAR Model", ".car"),
    (b"@(#)GT-CTEX", "GT-CTEX Texture", ".tex"),
    (b"@(#)GT-SKY", "GT-SKY Skybox", ".sky"),
    (b"@(#)GT-ZIP", "GT-ZIP", ".gtzip"),
    (b"@(#)USEDCAR", "Used Car Data", ".usedcar"),
    (b"@(#)GTHTML", "GT HTML", ".gthtml"),
    # Car / tuning part tables (CARINF-style)
    (b"@(#)ADJUST", "Align Adjustment", ".adjust"),
    (b"@(#)BALANCE", "Balance Weight", ".balance"),
    (b"@(#)BRAKE", "Brake", ".brake"),
    (b"@(#)BRKCTRL", "Brake Controller", ".brkctrl"),
    (b"@(#)CLUTCH", "Clutch", ".clutch"),
    (b"@(#)COLOR", "Car Color", ".color"),
    (b"@(#)COMPRES", "Computer / ECU", ".compres"),
    (b"@(#)COMPUTE", "Computer", ".compute"),
    (b"@(#)DISPLAC", "Displacement", ".displac"),
    (b"@(#)EQUIP", "Equipment", ".equip"),
    (b"@(#)FLYWHEL", "Flywheel", ".flywhel"),
    (b"@(#)GEAR", "Gearbox", ".gear"),
    (b"@(#)INCOOL", "Intercooler", ".incool"),
    (b"@(#)LWEIGHT", "Lightweight", ".lweight"),
    (b"@(#)MUFFLER", "Muffler", ".muffler"),
    (b"@(#)NATUNE", "NA Tune", ".natune"),
    (b"@(#)POLISH", "Port Polish", ".polish"),
    (b"@(#)PRPSHFT", "Prop Shaft", ".prpshft"),
    (b"@(#)RACING", "Racing Modify", ".racing"),
    (b"@(#)SPEC", "Car Spec", ".spec"),
    (b"@(#)STABILZ", "Stabilizer", ".stabilz"),
    (b"@(#)SUSPENS", "Suspension", ".suspens"),
    (b"@(#)TIRECMP", "Tire Compound", ".tirecmp"),
    (b"@(#)TIRESIZ", "Tire Size", ".tiresiz"),
    (b"@(#)TIRE", "Tire", ".tire"),
    (b"@(#)TURBINE", "Turbo / Turbine", ".turbine"),
    # Sound / sequence (4-byte)
    (b"INST", "Sound Instrument", ".ins"),
    (b"ENGN", "Engine Sound", ".es"),
    (b"SEQG", "Sequence", ".seq"),
]


def detect_type(data: bytes) -> tuple:
    """Return (type_name, extension). Data is never altered."""
    if not data:
        return ("Empty", ".bin")

    r = detect_replay(data)
    if r is not None:
        return r

    for magic, name, ext in _PREFIX_MAGICS:
        if data.startswith(magic):
            return (name, ext)

    # PlayStation TIM (little-endian 0x00000010)
    if len(data) >= 8 and data[0] == 0x10 and data[1] == 0x00 and data[2] == 0x00 and data[3] == 0x00:
        return ("TIM Texture", ".tim")

    # TIM pack: u32 count + 16-byte name containing ".tim"
    if len(data) >= 24:
        count = struct.unpack_from("<I", data, 0)[0]
        if 1 <= count <= 512:
            name = data[4:20].split(b"\0")[0]
            if b".tim" in name.lower():
                return ("TIM Pack", ".tpk")

    # Mostly ASCII text
    sample = data[:64]
    printable = sum(1 for b in sample if (32 <= b < 127) or b in (0, 9, 10, 13))
    if len(sample) >= 16 and printable >= len(sample) * 0.85:
        if b".tim" not in sample and b"@(#)" not in sample:
            return ("Text / Messages", ".txt")

    if b".tim\n" in data[:200] or b".seq\n" in data[:200] or b".htm\n" in data[:200]:
        return ("Filename List", ".lst")

    return ("Unknown", ".bin")
