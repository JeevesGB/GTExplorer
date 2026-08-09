import struct
from pathlib import Path

from .gtzip import gtzip_decompress, gtzip_compress
from .tim_pack import parse_tim_pack, build_tim_pack
from .audio import expand_sample_bank
from .detect import detect_type
from .filelist import lookup, safe_filename, archive_stem
from .namelist import parse_name_list
from .replay import is_replay_save


def _gtzip_decompress_full(src: bytes) -> bytes:
    dst = bytearray()
    pos = 0
    while pos < len(src):
        flags = src[pos]
        pos += 1
        for _ in range(8):
            if pos >= len(src):
                return bytes(dst)
            if (flags & 1) == 0:
                dst.append(src[pos])
                pos += 1
            else:
                if pos + 1 >= len(src):
                    return bytes(dst)
                length = src[pos]
                pos += 1
                disp = src[pos]
                pos += 1
                if disp >= 0x80:
                    if pos >= len(src):
                        return bytes(dst)
                    disp = (disp - 0x80) * 0x100 + src[pos]
                    pos += 1
                for _ in range(length + 3):
                    dst.append(dst[-(disp + 1)] if disp + 1 <= len(dst) else 0)
            flags >>= 1
    return bytes(dst)


class GTArc:
    def __init__(self):
        self.path = None
        self.kind = None
        self.content_type = 0x8001
        self.files = []
        self.raw = b""
        self.name_map = None  
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
            try:
                decomp = _gtzip_decompress_full(self.raw)
            except Exception:
                self.kind = "gtarc_compressed"
                self.files.append({
                    "index": 0, "offset": 0, "comp_size": len(self.raw),
                    "decomp_size": 0, "data": None,
                    "type": "Compressed GT-ARC", "ext": ".bin",
                    "label": "000_compressed_arc"
                })
                return

            if decomp[:12] != b"@(#)GT-ARC\0\0":
                self.kind = "gtarc_compressed"
                self.files.append({
                    "index": 0, "offset": 0, "comp_size": len(self.raw),
                    "decomp_size": 0, "data": None,
                    "type": "Compressed GT-ARC", "ext": ".bin",
                    "label": "000_compressed_arc"
                })
                return

            self.raw = decomp
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

        if is_replay_save(self.raw):
            self.kind = "replay_save"
            self.files = [{
                "index": 0,
                "label": "REPLAY",
                "ext": ".replay",
                "type": "GT Replay Save",
                "offset": 0,
                "comp_size": len(self.raw),
                "decomp_size": len(self.raw),
                "data": self.raw,
                "real_name": "REPLAY.DAT",
            }]
            return

        self.kind = "gtzip_raw"
        self.files.append({
            "index": 0,
            "offset": 0,
            "comp_size": len(self.raw),
            "decomp_size": 0x8000,
            "data": None,
            "type": "Raw GT-ZIP",
            "ext": ".bin",
            "label": "000",
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
                mapping = {}
                for idx, name in enumerate(names):
                    mapping[(self.stem, idx)] = name.lstrip("_")
                self.name_map = mapping
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
        """
        Pack a folder of extracted files back into a GT-ARC / GT-ZIP archive.

        Prefer order from manifest.txt when present and valid.
        Fall back to scanning the folder if the manifest is missing,
        incomplete, or references files that do not exist on disk.
        """
        src = Path(src_dir)
        if not src.is_dir():
            raise FileNotFoundError(f"Not a directory: {src}")

        def is_packable(p: Path) -> bool:
            if not p.is_file():
                return False
            if p.name.lower() == "manifest.txt":
                return False
            # Skip expanded TIM packs / sample banks (they are rebuilt from parent)
            if any(part.endswith(("_tims", "_samples")) for part in p.parts):
                return False
            return True

        def scan_folder_files() -> list:
            files = sorted(
                [p for p in src.iterdir() if is_packable(p)],
                key=lambda p: (
                    p.stem.zfill(8) if p.stem.isdigit() else p.stem.lower(),
                    p.suffix.lower(),
                ),
            )
            return [p.name for p in files]

        content_type = 0x0001 if force_uncompressed else 0x8001
        names = []

        manifest_path = src / "manifest.txt"
        if manifest_path.exists():
            try:
                lines = [
                    l.strip()
                    for l in manifest_path.read_text(encoding="utf-8").splitlines()
                    if l.strip()
                ]
                idx = 0
                if lines and lines[0].startswith("kind="):
                    idx = 1
                # content_type line
                if idx < len(lines) and "content_type=" in lines[idx]:
                    ct = int(lines[idx].split("=", 1)[1], 0)
                    if not force_uncompressed:
                        content_type = ct
                    idx += 1
                # nfiles line
                nfiles_declared = None
                if idx < len(lines) and lines[idx].startswith("nfiles="):
                    nfiles_declared = int(lines[idx].split("=", 1)[1])
                    idx += 1
                # remaining lines are filenames
                candidate_names = lines[idx:]
                if nfiles_declared is not None:
                    candidate_names = candidate_names[:nfiles_declared]

                # Only keep names that actually exist on disk
                valid = [n for n in candidate_names if (src / n).is_file()]
                if valid:
                    names = valid
            except Exception:
                # Bad / corrupt manifest → fall through to folder scan
                names = []

        if not names:
            names = scan_folder_files()

        if not names:
            # Useful diagnostic instead of a silent failure
            all_entries = list(src.iterdir())
            file_names = [p.name for p in all_entries if p.is_file()]
            dir_names = [p.name for p in all_entries if p.is_dir()]
            raise FileNotFoundError(
                "No packable files found in folder.\n\n"
                f"Folder: {src}\n"
                f"Files present: {file_names[:30]}{' …' if len(file_names) > 30 else ''}\n"
                f"Subdirs: {dir_names[:10]}{' …' if len(dir_names) > 10 else ''}\n\n"
                "Make sure the extracted .tim / .car / .tex / .txt files sit "
                "directly in this folder (not inside a subfolder)."
            )

        nfiles = len(names)
        payloads = []

        for ni, name in enumerate(names):
            p = src / name
            if not p.is_file():
                raise FileNotFoundError(f"Missing file listed for pack: {name}")

            stem = Path(name).stem
            tims_dir = src / f"{stem}_tims"
            if name.lower().endswith(".tpk") and tims_dir.is_dir():
                if progress_cb:
                    progress_cb(ni + 1, nfiles, name, "rebuild-tpk")
                tim_list = [
                    (tp.name, tp.read_bytes())
                    for tp in sorted(tims_dir.glob("*.tim"))
                ]
                if not tim_list:
                    raise FileNotFoundError(f"No .tim files in {tims_dir}")
                raw = build_tim_pack(tim_list)
                # Keep on-disk .tpk consistent with rebuilt content
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

        # Build GT-ARC header (fixed 0x800-byte header region)
        header = bytearray()
        header += b"@(#)GT-ARC\0\0"
        header += struct.pack("<HH", content_type, nfiles)
        data_start = 0x800
        offset = data_start
        for comp, decomp in payloads:
            header += struct.pack("<III", offset, len(comp), decomp)
            offset += len(comp)
        if len(header) > data_start:
            raise ValueError(
                f"Too many files ({nfiles}) for fixed 0x800 header "
                f"(header would be {len(header)} bytes)"
            )
        header += b"\0" * (data_start - len(header))

        with open(out_path, "wb") as f:
            f.write(header)
            for comp, _ in payloads:
                f.write(comp)

        return out_path
