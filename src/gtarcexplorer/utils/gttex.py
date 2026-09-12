from __future__ import annotations
import io
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List, Optional, Sequence, Tuple
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
TEX_HEADER = bytes([0x40, 0x28, 0x23, 0x29, 0x47, 0x54, 0x2D, 0x43, 0x54, 0x45, 0x58, 0x00, 0x02])
# "@(#)GT-CTEX\0\x02"  — first bytes are 0x40='@' with the rest matching @(#)GT-CTEX
COLOUR_COUNT_INDEX = 0x0E
PALETTE_START = 0x8060
PALETTE_SIZE = 0x200  # 16 CLUTs * 16 colours * 2 bytes
BITMAP_START = 0x60
BITMAP_FILL_SIZE = 0x1000
FLAGS_START = 0x20
BITMAP_W = 256
BITMAP_H = 224
NUM_CLUTS = 16
COLOURS_PER_CLUT = 16
MAX_CAR_COLOURS = 16
ALPHA_BIT = 0x8000


def _u16(f: BinaryIO) -> int:
    return struct.unpack("<H", f.read(2))[0]


def _write_u16(f: BinaryIO, v: int) -> None:
    f.write(struct.pack("<H", v & 0xFFFF))


def bgr555_to_rgb(c: int) -> Tuple[int, int, int]:
    r = (c & 0x1F) * 8
    g = ((c >> 5) & 0x1F) * 8
    b = ((c >> 10) & 0x1F) * 8
    return r, g, b


def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    return ((b // 8) << 10) | ((g // 8) << 5) | (r // 8)


@dataclass
class Palette:
    colours: List[int] = field(default_factory=lambda: [0xFFFF] * COLOURS_PER_CLUT)

    @property
    def is_empty(self) -> bool:
        return all(c == 0xFFFF for c in self.colours)

    def load_from_stream(self, f: BinaryIO) -> List[int]:
        alpha_idxs: List[int] = []
        self.colours = []
        for i in range(COLOURS_PER_CLUT):
            c = _u16(f)
            if c != 0xFFFF and (c & ALPHA_BIT):
                alpha_idxs.append(i)
            self.colours.append(c)
        return alpha_idxs

    def write_to_stream(self, f: BinaryIO, alpha_idxs: Sequence[int]) -> None:
        for i, c in enumerate(self.colours):
            if i in alpha_idxs:
                _write_u16(f, c | ALPHA_BIT)
            else:
                _write_u16(f, c & ~ALPHA_BIT)

    def to_rgb_list(self) -> List[Tuple[int, int, int]]:
        out = []
        for c in self.colours:
            if c == 0xFFFF:
                out.append((0, 0, 0))
            else:
                out.append(bgr555_to_rgb(c & ~ALPHA_BIT))
        return out

    def write_jasc(self, path: Path) -> None:
        lines = ["JASC-PAL", "0100", "16"]
        for r, g, b in self.to_rgb_list():
            lines.append(f"{r} {g} {b}")
        path.write_text("\n".join(lines) + "\n", encoding="ascii")

    @classmethod
    def from_jasc(cls, path: Path) -> "Palette":
        lines = [ln.strip() for ln in path.read_text(encoding="ascii", errors="replace").splitlines() if ln.strip()]
        if len(lines) < 19 or lines[0] != "JASC-PAL":
            raise ValueError(f"Invalid JASC palette: {path}")
        pal = cls()
        cols = []
        for i in range(16):
            parts = lines[3 + i].split()
            if len(parts) != 3:
                raise ValueError(f"Invalid colour line in {path}: {lines[3+i]}")
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            cols.append(rgb_to_bgr555(r, g, b))
        pal.colours = cols
        return pal


@dataclass
class BitMask16:
    flags: List[bool] = field(default_factory=lambda: [False] * 16)

    def load_from_stream(self, f: BinaryIO) -> None:
        val = _u16(f)
        self.flags = []
        for _ in range(16):
            self.flags.append((val & 1) == 1)
            val >>= 1

    def write_to_stream(self, f: BinaryIO) -> None:
        val = 0
        for bit in reversed(self.flags):
            val <<= 1
            if bit:
                val |= 1
        _write_u16(f, val)

    def write_jasc(self, path: Path) -> None:
        lines = ["JASC-PAL", "0100", "16"]
        for on in self.flags:
            lines.append("248 248 248" if on else "0 0 0")
        path.write_text("\n".join(lines) + "\n", encoding="ascii")

    @classmethod
    def from_jasc(cls, path: Path) -> "BitMask16":
        lines = [ln.strip() for ln in path.read_text(encoding="ascii", errors="replace").splitlines() if ln.strip()]
        m = cls()
        m.flags = []
        for i in range(16):
            m.flags.append(lines[3 + i] != "0 0 0")
        return m


@dataclass
class CarColour:
    colour_id: int = 0
    palettes: List[Palette] = field(default_factory=lambda: [Palette() for _ in range(NUM_CLUTS)])
    illumination: List[BitMask16] = field(default_factory=lambda: [BitMask16() for _ in range(NUM_CLUTS)])
    paint: List[BitMask16] = field(default_factory=lambda: [BitMask16() for _ in range(NUM_CLUTS)])
    # (clut_index, colour_index) pairs that had alpha bit
    alpha: List[Tuple[int, int]] = field(default_factory=list)

    def load_from_game(self, data: bytes, colour_number: int) -> None:
        self.colour_id = data[COLOUR_COUNT_INDEX + 2 + colour_number]
        base = PALETTE_START + PALETTE_SIZE * colour_number
        f = io.BytesIO(data[base : base + PALETTE_SIZE])
        self.palettes = []
        self.alpha = []
        for clut in range(NUM_CLUTS):
            pal = Palette()
            alpha_idxs = pal.load_from_stream(f)
            for ci in alpha_idxs:
                self.alpha.append((clut, ci))
            self.palettes.append(pal)

        if colour_number == 0:
            fflags = io.BytesIO(data[FLAGS_START : FLAGS_START + 64])
            self.illumination = []
            for _ in range(NUM_CLUTS):
                m = BitMask16()
                m.load_from_stream(fflags)
                self.illumination.append(m)
            self.paint = []
            for _ in range(NUM_CLUTS):
                m = BitMask16()
                m.load_from_stream(fflags)
                self.paint.append(m)
        else:
            self.illumination = [BitMask16() for _ in range(NUM_CLUTS)]
            self.paint = [BitMask16() for _ in range(NUM_CLUTS)]

    def export_editable(self, directory: Path, write_masks: bool) -> None:
        d = directory / f"Colour{self.colour_id:02X}"
        d.mkdir(parents=True, exist_ok=True)
        for i, pal in enumerate(self.palettes):
            if not pal.is_empty:
                pal.write_jasc(d / f"ColourPalette{i:02d}.pal")
        if write_masks:
            for i, m in enumerate(self.illumination):
                m.write_jasc(d / f"IlluminationMask{i:02d}.pal")
            for i, m in enumerate(self.paint):
                m.write_jasc(d / f"PaintMask{i:02d}.pal")
        if self.alpha:
            lines = [f"{clut} {ci}" for clut, ci in self.alpha]
            (d / "Alpha.txt").write_text("\n".join(lines) + "\n", encoding="ascii")

    def load_editable(self, directory: Path) -> None:
        name = directory.name  # ColourXX
        if name.startswith("Colour") and len(name) >= 8:
            try:
                self.colour_id = int(name[6:8], 16)
            except ValueError:
                self.colour_id = 0
        self.palettes = [Palette() for _ in range(NUM_CLUTS)]
        for p in directory.glob("ColourPalette??.pal"):
            try:
                num = int(p.stem[-2:])
            except ValueError:
                continue
            if 0 <= num < NUM_CLUTS:
                self.palettes[num] = Palette.from_jasc(p)
        for p in directory.glob("IlluminationMask??.pal"):
            try:
                num = int(p.stem[-2:])
            except ValueError:
                continue
            if 0 <= num < NUM_CLUTS:
                self.illumination[num] = BitMask16.from_jasc(p)
        for p in directory.glob("PaintMask??.pal"):
            try:
                num = int(p.stem[-2:])
            except ValueError:
                continue
            if 0 <= num < NUM_CLUTS:
                self.paint[num] = BitMask16.from_jasc(p)
        alpha_path = directory / "Alpha.txt"
        self.alpha = []
        if alpha_path.exists():
            for line in alpha_path.read_text(encoding="ascii").splitlines():
                parts = line.split()
                if len(parts) == 2:
                    self.alpha.append((int(parts[0]), int(parts[1])))


@dataclass
class GTTex:
    colours: List[CarColour] = field(default_factory=list)
    # bitmapData[x][y] = index 0..15
    pixels: List[List[int]] = field(default_factory=list)
    raw_size: int = 0

    def __post_init__(self) -> None:
        if not self.pixels:
            self.pixels = [[0] * BITMAP_H for _ in range(BITMAP_W)]

    @classmethod
    def from_bytes(cls, data: bytes) -> "GTTex":
        if len(data) < 0x1060 + (BITMAP_W * BITMAP_H // 2):
            raise ValueError(f"TEX too small ({len(data)} bytes)")
        # Accept magic variants
        if b"GT-CTEX" not in data[:16] and not data.startswith(TEX_HEADER[:8]):
            # still try if colour count looks sane
            pass

        colour_count = struct.unpack_from("<H", data, COLOUR_COUNT_INDEX)[0]
        if colour_count == 0 or colour_count > MAX_CAR_COLOURS:
            # some files store only low byte
            colour_count = data[COLOUR_COUNT_INDEX]
            if colour_count == 0 or colour_count > MAX_CAR_COLOURS:
                raise ValueError(f"Implausible colour count {colour_count}")

        tex = cls()
        tex.raw_size = len(data)
        tex.colours = []
        for i in range(colour_count):
            cc = CarColour()
            cc.load_from_game(data, i)
            # masks only live on colour 0; copy refs for convenience
            if i > 0 and tex.colours:
                cc.illumination = tex.colours[0].illumination
                cc.paint = tex.colours[0].paint
            tex.colours.append(cc)

        # bitmap
        off = BITMAP_START + BITMAP_FILL_SIZE
        tex.pixels = [[0] * BITMAP_H for _ in range(BITMAP_W)]
        for y in range(BITMAP_H):
            for x in range(0, BITMAP_W, 2):
                pair = data[off]
                off += 1
                tex.pixels[x][y] = pair & 0xF
                tex.pixels[x + 1][y] = (pair >> 4) & 0xF
        return tex

    @classmethod
    def from_file(cls, path: Path | str) -> "GTTex":
        return cls.from_bytes(Path(path).read_bytes())

    def export_editable(self, out_dir: Path | str, basename: str | None = None) -> Path:
        if not HAS_PIL:
            raise RuntimeError("Pillow is required for texture export")

        out_dir = Path(out_dir)
        if basename is None:
            basename = out_dir.name
        folder = out_dir / basename if out_dir.name != basename else out_dir
        folder.mkdir(parents=True, exist_ok=True)

        # Main indexed sheet with palette 0 of colour 0
        self._save_indexed_bmp(folder / f"{basename}.bmp", clut_index=0, colour_index=0)
        self._save_png(folder / f"{basename}.png", clut_index=0, colour_index=0)

        # paletteXX.png dumps for model tool (colour 0)
        for i in range(NUM_CLUTS):
            self._save_png(folder / f"palette{i:02d}.png", clut_index=i, colour_index=0)
            self._save_indexed_bmp(folder / f"palette{i:02d}.bmp", clut_index=i, colour_index=0)

        for i, cc in enumerate(self.colours):
            cc.export_editable(folder, write_masks=(i == 0))

        return folder

    def _palette_for(self, colour_index: int, clut_index: int) -> List[Tuple[int, int, int]]:
        if not self.colours:
            return [(0, 0, 0)] * 16
        ci = min(colour_index, len(self.colours) - 1)
        return self.colours[ci].palettes[clut_index].to_rgb_list()

    def _save_png(self, path: Path, clut_index: int, colour_index: int) -> None:
        rgb = self._palette_for(colour_index, clut_index)
        img = Image.new("RGB", (BITMAP_W, BITMAP_H))
        px = img.load()
        for y in range(BITMAP_H):
            for x in range(BITMAP_W):
                idx = self.pixels[x][y] & 0xF
                px[x, y] = rgb[idx]
        img.save(path)

    def _save_indexed_bmp(self, path: Path, clut_index: int, colour_index: int) -> None:
        rgb = self._palette_for(colour_index, clut_index)
        img = Image.new("P", (BITMAP_W, BITMAP_H))
        # Pillow palette is 768 R,G,B bytes
        pal = []
        for r, g, b in rgb:
            pal.extend([r, g, b])
        while len(pal) < 768:
            pal.extend([0, 0, 0])
        img.putpalette(pal)
        px = img.load()
        for y in range(BITMAP_H):
            for x in range(BITMAP_W):
                px[x, y] = self.pixels[x][y] & 0xF
        img.save(path, format="BMP")

    @classmethod
    def from_editable(cls, folder: Path | str) -> "GTTex":
        if not HAS_PIL:
            raise RuntimeError("Pillow is required for texture import")
        folder = Path(folder)
        tex = cls()

        # find sheet bmp/png
        bmp_candidates = list(folder.glob("*.bmp")) + list(folder.glob("*.png"))
        sheet = None
        for c in bmp_candidates:
            if c.stem.startswith("palette"):
                continue
            sheet = c
            break
        if sheet is None:
            raise ValueError(f"No sheet BMP/PNG in {folder}")

        img = Image.open(sheet)
        if img.size != (BITMAP_W, BITMAP_H):
            raise ValueError(f"Sheet must be {BITMAP_W}x{BITMAP_H}, got {img.size}")

        # Prefer indexed; otherwise quantize to 16 colours (lossy)
        if img.mode != "P":
            img = img.convert("RGB").quantize(colors=16, method=Image.Quantize.MEDIANCUT)
        img = img.convert("P")
        px = img.load()
        tex.pixels = [[0] * BITMAP_H for _ in range(BITMAP_W)]
        for y in range(BITMAP_H):
            for x in range(BITMAP_W):
                tex.pixels[x][y] = int(px[x, y]) & 0xF

        # colours
        colour_dirs = sorted(folder.glob("Colour??"))
        if not colour_dirs:
            # synthesise one colour from sheet palette
            cc = CarColour(colour_id=0)
            pal_data = img.getpalette() or [0] * 768
            cols = []
            for i in range(16):
                r, g, b = pal_data[i * 3], pal_data[i * 3 + 1], pal_data[i * 3 + 2]
                cols.append(rgb_to_bgr555(r, g, b))
            cc.palettes[0] = Palette(colours=cols)
            tex.colours = [cc]
        else:
            tex.colours = []
            for d in colour_dirs:
                cc = CarColour()
                cc.load_editable(d)
                tex.colours.append(cc)
            # ensure masks on colour 0
            if tex.colours:
                for i in range(1, len(tex.colours)):
                    tex.colours[i].illumination = tex.colours[0].illumination
                    tex.colours[i].paint = tex.colours[0].paint
        return tex

    def write_tex(self, path: Path | str | None = None) -> bytes:
        # Size: palettes end at 0x8060 + colour_count * 0x200
        n = max(1, len(self.colours))
        size = PALETTE_START + n * PALETTE_SIZE
        buf = bytearray(size)

        # header
        buf[0 : len(TEX_HEADER)] = TEX_HEADER
        # colour count (ushort at 0x0E) — tool writes a byte but layout says ushort
        buf[COLOUR_COUNT_INDEX] = n & 0xFF
        buf[COLOUR_COUNT_INDEX + 1] = 0

        # colour IDs
        for i, cc in enumerate(self.colours):
            buf[COLOUR_COUNT_INDEX + 2 + i] = cc.colour_id & 0xFF

        # flags at 0x20 from colour 0
        if self.colours:
            fflags = io.BytesIO()
            for m in self.colours[0].illumination:
                m.write_to_stream(fflags)
            for m in self.colours[0].paint:
                m.write_to_stream(fflags)
            flag_bytes = fflags.getvalue()
            buf[FLAGS_START : FLAGS_START + len(flag_bytes)] = flag_bytes

        # bitmap fill 0xFF
        for i in range(BITMAP_FILL_SIZE):
            buf[BITMAP_START + i] = 0xFF

        # bitmap data
        off = BITMAP_START + BITMAP_FILL_SIZE
        for y in range(BITMAP_H):
            for x in range(0, BITMAP_W, 2):
                lo = self.pixels[x][y] & 0xF
                hi = self.pixels[x + 1][y] & 0xF
                buf[off] = (hi << 4) | lo
                off += 1

        # pad up to palette start if needed
        if off < PALETTE_START:
            # leave zeros
            pass

        # palettes
        for i, cc in enumerate(self.colours):
            base = PALETTE_START + i * PALETTE_SIZE
            f = io.BytesIO()
            for clut, pal in enumerate(cc.palettes):
                alpha_idxs = [ci for (c, ci) in cc.alpha if c == clut]
                pal.write_to_stream(f, alpha_idxs)
            pdata = f.getvalue()
            buf[base : base + len(pdata)] = pdata

        data = bytes(buf)
        if path is not None:
            Path(path).write_bytes(data)
        return data

    def summary(self) -> str:
        lines = [
            f"GT-CTEX  size={self.raw_size or 'n/a'}",
            f"  colours: {len(self.colours)}",
            f"  sheet: {BITMAP_W}x{BITMAP_H} 4bpp",
        ]
        for i, cc in enumerate(self.colours):
            used = sum(1 for p in cc.palettes if not p.is_empty)
            lines.append(f"    [{i}] id=0x{cc.colour_id:02X}  non-empty CLUTs={used}")
        return "\n".join(lines)

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python gttex.py export <file.tex> [out_dir]")
        print("  python gttex.py import <folder> [out.tex]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "export":
        src = Path(sys.argv[2])
        out = Path(sys.argv[3]) if len(sys.argv) > 3 else src.with_suffix("")
        tex = GTTex.from_file(src)
        print(tex.summary())
        folder = tex.export_editable(out, basename=src.stem)
        print(f"Exported to {folder}")
    elif cmd == "import":
        folder = Path(sys.argv[2])
        dest = Path(sys.argv[3]) if len(sys.argv) > 3 else folder.with_suffix(".tex")
        tex = GTTex.from_editable(folder)
        data = tex.write_tex(dest)
        print(tex.summary())
        print(f"Wrote {dest} ({len(data)} bytes)")
    else:
        # treat as export path
        src = Path(cmd)
        tex = GTTex.from_file(src)
        print(tex.summary())
        folder = tex.export_editable(src.with_suffix(""), basename=src.stem)
        print(f"Exported to {folder}")
