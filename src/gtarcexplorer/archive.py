"""GTArc: load / extract / repack GT-ARC (.DAT) archives."""
import struct
from pathlib import Path

from .gtzip import gtzip_decompress, gtzip_compress
from .tim_pack import parse_tim_pack, build_tim_pack
from .audio import expand_sample_bank
from .detect import detect_type
from .filelist import lookup, safe_filename, archive_stem
from .namelist import parse_name_list

# Archive
class GTArc:
    def __init__(self):
        self.path = None
        self.kind = None
        self.content_type = 0x8001
        self.files = []
        self.raw = b""
        self.name_map = None  # optional filelist NameMap
        self.stem = ""

    def load(self, path: str):
        self.path = path
        self.stem = archive_stem(path)
        self.raw = Path(path).read_bytes()
        self.files = []

        if self.raw[:12] == b"@(#)GT-ARC\0\0":
            self.kind = "gtarc"
            self.content_type, nfiles = struct.unpack_from("<HH", self.raw, 12)
            for i in range(nfiles):
                off, csz, dsz = struct.unpack_from("<III", self.raw, 0x10 + i * 12)
                self.files.append({
                    "index": i, "offset": off, "comp_size": csz,
                    "decomp_size": dsz, "data": None,
                    "type": "…", "ext": ".bin", "label": f"{i:03d}"
                })
            return

        if self.raw[1:8] == b"@(#)GT-" and b"RC" in self.raw[8:14]:
            self.kind = "gtarc_compressed"
            self.files.append({
                "index": 0, "offset": 0, "comp_size": len(self.raw),
                "decomp_size": 0, "data": None,
                "type": "Compressed GT-ARC", "ext": ".bin",
                "label": "000_compressed_arc"
            })
            return

        self.kind = "gtzip_raw"
        self.files.append({
            "index": 0, "offset": 0, "comp_size": len(self.raw),
            "decomp_size": 0x8000, "data": None,
            "type": "Raw GT-ZIP", "ext": ".bin", "label": "000"
        })


    def try_embedded_names(self):
        """If an entry is a filename list whose length matches nfiles, use it as name_map."""
        if self.kind != "gtarc" or not self.files:
            return False
        n = len(self.files)
        for i in range(n):
            try:
                data = self.get_data(i)
            except Exception:
                continue
            names = parse_name_list(data)
            if len(names) == n:
                # Build a temporary map for this stem
                mapping = {}
                for idx, name in enumerate(names):
                    mapping[(self.stem, idx)] = name.lstrip("_")
                self.name_map = mapping
                # Refresh labels
                for f in self.files:
                    real = names[f["index"]].lstrip("_") if f["index"] < len(names) else None
                    if real:
                        from pathlib import Path as _P
                        f["label"] = _P(real).stem
                        if _P(real).suffix:
                            f["ext"] = _P(real).suffix
                        f["real_name"] = real
                return True
        return False

    def get_data(self, idx: int) -> bytes:
        f = self.files[idx]
        if f["data"] is not None:
            return f["data"]

        if self.kind == "gtarc":
            payload = self.raw[f["offset"]: f["offset"] + f["comp_size"]]
            if self.content_type == 0x8001 and f["decomp_size"] > 0:
                payload = gtzip_decompress(payload, f["decomp_size"])
            f["data"] = payload
        elif self.kind == "gtzip_raw":
            try:
                payload = gtzip_decompress(self.raw, f["decomp_size"] or 0x10000)
            except Exception:
                payload = self.raw
            f["data"] = payload
        else:
            f["data"] = self.raw

        tname, ext = detect_type(f["data"])
        f["type"] = tname
        f["ext"] = ext
        real = lookup(self.name_map, self.stem, f["index"])
        if real:
            # Prefer list basename; keep list extension if present
            stem_part = Path(real).stem
            list_ext = Path(real).suffix
            f["label"] = stem_part
            if list_ext:
                f["ext"] = list_ext
            f["real_name"] = real
        else:
            f["label"] = f"{f['index']:03d}"
            f["real_name"] = None
        return f["data"]

    def extract_all(self, out_dir: str, indices=None, expand_tim_packs=False,
                    expand_inst_banks=False, progress_cb=None):
        """
        Lossless extract.
        expand_tim_packs: also write individual .tim files from each TIM Pack.
        expand_inst_banks: also decode INST/ENGN sample banks to WAV (+ raw ADPCM).
        The original container file is always kept.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        if indices is None:
            indices = list(range(len(self.files)))

        manifest = []
        for n, i in enumerate(indices):
            data = self.get_data(i)
            f = self.files[i]
            if f.get("real_name"):
                name = safe_filename(f["real_name"])
            else:
                name = f"{f['label']}{f['ext']}"
            # Avoid collisions
            dest = out / name
            if dest.exists():
                dest = out / f"{f['index']:03d}_{name}"
                name = dest.name
            dest.write_bytes(data)
            manifest.append(name)

            extra = ""
            if expand_tim_packs and f["type"] == "TIM Pack":
                tims = parse_tim_pack(data)
                sub = out / f"{f['label']}_tims"
                sub.mkdir(exist_ok=True)
                for tname, tdata in tims:
                    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in tname)
                    if not safe.lower().endswith(".tim"):
                        safe += ".tim"
                    (sub / safe).write_bytes(tdata)
                extra += f" + {len(tims)} TIMs"

            if expand_inst_banks and f["type"] in ("Sound Instrument", "Engine Sound"):
                sub = out / f"{f['label']}_samples"
                count = expand_sample_bank(data, sub)
                extra += f" + {count} samples"

            if progress_cb:
                progress_cb(n + 1, len(indices), name + extra)

        with open(out / "manifest.txt", "w", encoding="utf-8") as m:
            m.write(f"kind={self.kind}\n")
            m.write(f"content_type=0x{self.content_type:04x}\n")
            m.write(f"nfiles={len(self.files)}\n")
            for name in manifest:
                m.write(name + "\n")
        return out

    @staticmethod
    def pack_from_folder(src_dir: str, out_path: str,
                        force_uncompressed: bool = False,
                        compress_level: int = 6,
                        progress_cb=None):
        src = Path(src_dir)
        manifest_path = src / "manifest.txt"

        if manifest_path.exists():
            lines = [l.strip() for l in manifest_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            idx = 0
            if lines and lines[0].startswith("kind="):
                idx = 1
            content_type = int(lines[idx].split("=")[1], 0)
            if force_uncompressed:
                content_type = 0x0001
            nfiles = int(lines[idx + 1].split("=")[1])
            names = lines[idx + 2: idx + 2 + nfiles]
        else:
            content_type = 0x0001 if force_uncompressed else 0x8001

            def is_packable(p: Path) -> bool:
                if not p.is_file():
                    return False
                if p.name.lower() == "manifest.txt":
                    return False
                if any(part.endswith(("_tims", "_samples")) for part in p.parts):
                    return False
                return True

            files = sorted(
                [p for p in src.iterdir() if is_packable(p)],
                key=lambda p: (p.stem.zfill(8) if p.stem.isdigit() else p.stem.lower(), p.suffix.lower())
            )
            if not files:
                raise FileNotFoundError("No packable files found in folder")
            names = [p.name for p in files]
            nfiles = len(names)

        payloads = []
        for ni, name in enumerate(names):
            p = src / name
            if not p.exists():
                raise FileNotFoundError(f"Missing file listed for pack: {name}")

            stem = Path(name).stem
            tims_dir = src / f"{stem}_tims"
            if name.lower().endswith(".tpk") and tims_dir.is_dir():
                if progress_cb:
                    progress_cb(ni + 1, nfiles, name, "rebuild-tpk")
                tim_list = [(tp.name, tp.read_bytes()) for tp in sorted(tims_dir.glob("*.tim"))]
                if not tim_list:
                    raise FileNotFoundError(f"No .tim files in {tims_dir}")
                raw = build_tim_pack(tim_list)
                p.write_bytes(raw)
            else:
                raw = p.read_bytes()

            if progress_cb:
                action = "compress" if content_type == 0x8001 else "copy"
                progress_cb(ni + 1, nfiles, name, action)

            if content_type == 0x8001:
                comp = gtzip_compress(raw, level=compress_level)
                payloads.append((comp, len(raw)))
            else:
                payloads.append((raw, len(raw)))

        # write
        header = bytearray()
        header += b"@(#)GT-ARC\0\0"
        header += struct.pack("<HH", content_type, nfiles)
        data_start = 0x800
        offset = data_start
        for comp, decomp in payloads:
            header += struct.pack("<III", offset, len(comp), decomp)
            offset += len(comp)
        header += b"\0" * (data_start - len(header))

        with open(out_path, "wb") as f:
            f.write(header)
            for comp, _ in payloads:
                f.write(comp)

        return out_path


