"""File-type sniffing for entries pulled out of a GT-ARC container."""
import struct
def detect_type(data: bytes) -> tuple:
    """Return (type_name, extension). Data is never altered."""
    if not data:
        return ("Empty", ".bin")

    if data.startswith(b"@(#)GT-PS"):
        return ("GT-PS Model", ".gtps")
    if data.startswith(b"@(#)GT-CAR"):
        return ("GT-CAR Model", ".gtcar")
    if data.startswith(b"@(#)GT-CTEX"):
        return ("GT-CTEX Texture", ".ctex")
    if data.startswith(b"@(#)GT-SKY"):
        return ("GT-SKY Skybox", ".gtsky")
    if data.startswith(b"@(#)GT-ZIP"):
        return ("GT-ZIP", ".gtzip")
    if data.startswith(b"@(#)GT-ARC"):
        return ("Nested GT-ARC", ".arc")
    if data.startswith(b"@(#)USEDCAR"):
        return ("Used Car Data", ".usedcar")

    if data.startswith(b"INST"):
        return ("Sound Instrument", ".inst")
    if data.startswith(b"ENGN"):
        return ("Engine Sound", ".engn")

    if len(data) >= 8 and data[0] == 0x10 and data[1] == 0x00 and data[2] == 0x00 and data[3] == 0x00:
        return ("TIM Texture", ".tim")

    if len(data) >= 24:
        count = struct.unpack_from("<I", data, 0)[0]
        if 1 <= count <= 512:
            name = data[4:20].split(b"\0")[0]
            if b".tim" in name.lower():
                return ("TIM Pack", ".tpk")

    sample = data[:64]
    printable = sum(1 for b in sample if (32 <= b < 127) or b in (0, 9, 10, 13))
    if len(sample) >= 16 and printable >= len(sample) * 0.85:
        # avoid mis-detecting binary that happens to have some ASCII
        if b".tim" not in sample and b"@(#)" not in sample:
            return ("Text / Messages", ".txt")

    if b".tim\n" in data[:200] or b".seq\n" in data[:200] or b".htm\n" in data[:200]:
        return ("Filename List", ".lst")

    return ("Unknown", ".bin")

