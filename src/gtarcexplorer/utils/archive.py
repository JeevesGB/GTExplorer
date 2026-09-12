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

def _gtarc_data_start(nfiles: int, preferred: int | None = None) -> int:
    table_end = 0x10 + int(nfiles) * 12
    if preferred is not None and preferred >= table_end:
        return int(preferred)
    # Round up to 0x800
    return ((table_end + 0x7FF) // 0x800) * 0x800

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

        if self.raw[:12] == b"@(#)GT-ARC" + b"\x00\x00":
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

            if decomp[:12] != b"@(#)GT-ARC" + b"\x00\x00":
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
            if tname == "TIM Pack":
                f["ext"] = ".tpk"
                f["real_name"] = f"{stem_part}.tpk"
            else:
                if list_ext:
                    f["ext"] = list_ext
                f["real_name"] = real
        else:
            f["label"] = f"{f['index']:03d}"
            f["real_name"] = None
        return f["data"]

    def extract_all(self, out_dir: str, indices=None, expand_tim_packs=False, expand_inst_banks=False, progress_cb=None):

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
                # Folder name must match pack_from_folder: <file_stem>_tims
                pack_stem = Path(name).stem
                sub = out / f"{pack_stem}_tims"
                sub.mkdir(exist_ok=True)
                order_names = []
                for tname, tdata in tims:
                    safe = "".join(
                        c if c.isalnum() or c in "._-" else "_" for c in tname
                    )
                    if not safe.lower().endswith(".tim"):
                        safe += ".tim"
                    (sub / safe).write_bytes(tdata)
                    order_names.append(safe)
                (sub / "tim_order.txt").write_text(
                    "\n".join(order_names) + "\n", encoding="utf-8"
                )
                extra += f" + {len(tims)} TIMs"

            if expand_inst_banks and f["type"] in ("Sound Instrument", "Engine Sound"):
                sub = out / f"{Path(name).stem}_samples"
                count = expand_sample_bank(data, sub)
                extra += f" + {count} samples"

            if progress_cb:
                progress_cb(n + 1, len(indices), name + extra)

        # Optional convenience file — not required for repack
        with open(out / "manifest.txt", "w", encoding="utf-8") as m:
            m.write(f"kind={self.kind}\n")
            m.write(f"content_type=0x{self.content_type:04x}\n")
            m.write(f"nfiles={len(indices)}\n")
            for name in manifest:
                m.write(name + "\n")
        return out

    @staticmethod
    def patch_file_entry(
        arc_path: str,
        index: int,
        uncompressed: bytes,
        compress_level: int = 6,
    ) -> dict:
        path = Path(arc_path)
        raw = bytearray(path.read_bytes())
        if raw[:12] != b"@(#)GT-ARC" + b"\x00\x00":
            raise ValueError(f"Not a GT-ARC: {path}")
        content_type, nfiles = struct.unpack_from("<HH", raw, 12)
        if index < 0 or index >= nfiles:
            raise IndexError(f"Entry {index} out of range (0..{nfiles-1})")

        off, csz, dsz = struct.unpack_from("<III", raw, 0x10 + index * 12)
        if content_type == 0x8001:
            comp = gtzip_compress(uncompressed, level=compress_level)
        else:
            comp = uncompressed

        if len(comp) > csz:
            # Try higher compression levels before giving up
            if content_type == 0x8001:
                for lvl in range(compress_level + 1, 10):
                    comp = gtzip_compress(uncompressed, level=lvl)
                    if len(comp) <= csz:
                        break
            if len(comp) > csz:
                raise ValueError(
                    f"Compressed entry #{index} is {len(comp)} bytes but "
                    f"slot is only {csz}. Full rebuild required."
                )

        # Write compressed data; zero-pad the rest of the slot so offsets stay valid
        slot = comp + bytes([0]) * (csz - len(comp))
        raw[off : off + csz] = slot
        # Keep original csz in the table so layout/size stay identical
        struct.pack_into("<III", raw, 0x10 + index * 12, off, csz, len(uncompressed))

        path.write_bytes(raw)
        return {
            "path": str(path),
            "index": index,
            "comp_size": len(comp),
            "slot_size": csz,
            "decomp_size": len(uncompressed),
            "file_size": len(raw),
        }

    def save_preserving(
        self,
        out_path: str,
        compress_level: int = 6,
        pad_to_size: int | None = None,
    ) -> str:
        if self.kind != "gtarc" or not self.raw:
            raise ValueError("save_preserving requires an open GT-ARC with raw bytes")

        content_type, nfiles = struct.unpack_from("<HH", self.raw, 12)
        if nfiles != len(self.files):
            raise ValueError("file count mismatch")

        payloads = []  # (comp_bytes, decomp_size)
        for i, f in enumerate(self.files):
            off, csz, dsz = struct.unpack_from("<III", self.raw, 0x10 + i * 12)
            orig_comp = bytes(self.raw[off : off + csz])
            dirty = bool(f.get("_dirty"))
            data = f.get("data")
            if dirty and data is not None:
                data = bytes(data)
                if content_type == 0x8001:
                    comp = gtzip_compress(data, level=compress_level)
                    if len(comp) > csz:
                        for lvl in range(compress_level + 1, 10):
                            cand = gtzip_compress(data, level=lvl)
                            if len(cand) < len(comp):
                                comp = cand
                            if len(comp) <= csz:
                                break
                else:
                    comp = data
                payloads.append((comp, len(data)))
            else:
                payloads.append((orig_comp, dsz))

        header = bytearray()
        header += b"@(#)GT-ARC" + bytes([0, 0])
        header += struct.pack("<HH", content_type, nfiles)
        try:
            preferred = struct.unpack_from("<I", self.raw, 0x10)[0]
        except Exception:
            preferred = None
        data_start = _gtarc_data_start(nfiles, preferred)
        offset = data_start
        for comp, decomp in payloads:
            header += struct.pack("<III", offset, len(comp), decomp)
            offset += len(comp)
        if len(header) > data_start:
            data_start = _gtarc_data_start(nfiles, len(header))
            header = bytearray()
            header += b"@(#)GT-ARC" + bytes([0, 0])
            header += struct.pack("<HH", content_type, nfiles)
            offset = data_start
            for comp, decomp in payloads:
                header += struct.pack("<III", offset, len(comp), decomp)
                offset += len(comp)
        header += bytes([0]) * (data_start - len(header))

        out = Path(out_path)
        tmp = out.with_suffix(out.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(header)
            for comp, _ in payloads:
                fh.write(comp)
            end = fh.tell()
            target = pad_to_size if pad_to_size is not None else len(self.raw)
            if target < end:
                target = end
            aligned = ((target + 2047) // 2048) * 2048
            if aligned < end:
                aligned = ((end + 2047) // 2048) * 2048
            if aligned > end:
                fh.write(bytes([0]) * (aligned - end))
        tmp.replace(out)

        # Refresh raw to match what we wrote
        self.raw = out.read_bytes()
        self.path = str(out)
        self.content_type = content_type
        for i, f in enumerate(self.files):
            off, csz, dsz = struct.unpack_from("<III", self.raw, 0x10 + i * 12)
            f["offset"] = off
            f["comp_size"] = csz
            f["decomp_size"] = dsz
            f["index"] = i
        return str(out)

    def pack_to_path(
        self,
        out_path: str,
        force_uncompressed: bool = False,
        compress_level: int = 6,
        progress_cb=None,
    ) -> str:
        if not self.files:
            raise ValueError("Archive has no files to pack")

        content_type = 0x0001 if force_uncompressed else int(self.content_type or 0x8001)
        nfiles = len(self.files)
        payloads = []
        raw = self.raw or b""

        for ni, f in enumerate(self.files):
            name = f.get("label") or f.get("real_name") or f"{ni:03d}"
            data = f.get("data")

            if data is None and raw and f.get("offset") is not None and f.get("comp_size"):
                # Fast path: keep original compressed blob
                off = int(f["offset"])
                csz = int(f["comp_size"])
                dsz = int(f.get("decomp_size") or 0)
                chunk = raw[off: off + csz]
                if len(chunk) == csz and csz > 0:
                    if progress_cb:
                        progress_cb(ni + 1, nfiles, str(name), "copy")
                    payloads.append((chunk, dsz if dsz > 0 else csz))
                    continue

            # Modified (or missing original blob) — compress / store fresh data
            if data is None:
                data = self.get_data(int(f["index"]))
            data = bytes(data)
            if progress_cb:
                progress_cb(
                    ni + 1, nfiles, str(name),
                    "compress" if content_type == 0x8001 else "copy",
                )
            if content_type == 0x8001:
                comp = gtzip_compress(data, level=compress_level)
                payloads.append((comp, len(data)))
            else:
                payloads.append((data, len(data)))

        header = bytearray()
        header += b"@(#)GT-ARC" + bytes([0, 0])
        header += struct.pack("<HH", content_type, nfiles)
        try:
            preferred = struct.unpack_from("<I", self.raw, 0x10)[0]
        except Exception:
            preferred = None
        data_start = _gtarc_data_start(nfiles, preferred)
        offset = data_start
        for comp, decomp in payloads:
            header += struct.pack("<III", offset, len(comp), decomp)
            offset += len(comp)
        if len(header) > data_start:
            data_start = _gtarc_data_start(nfiles, len(header))
            header = bytearray()
            header += b"@(#)GT-ARC" + bytes([0, 0])
            header += struct.pack("<HH", content_type, nfiles)
            offset = data_start
            for comp, decomp in payloads:
                header += struct.pack("<III", offset, len(comp), decomp)
                offset += len(comp)
        header += bytes([0]) * (data_start - len(header))

        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish write: build to temp beside target, then replace
        tmp_p = out_p.with_suffix(out_p.suffix + ".tmp")
        try:
            with open(tmp_p, "wb") as fh:
                fh.write(header)
                for comp, _ in payloads:
                    fh.write(comp)
            tmp_p.replace(out_p)
        except Exception:
            try:
                if tmp_p.is_file():
                    tmp_p.unlink()
            except Exception:
                pass
            raise

        # Refresh in-memory view
        self.path = str(out_p)
        self.raw = out_p.read_bytes()
        self.kind = "gtarc"
        self.content_type = content_type
        for i, f in enumerate(self.files):
            off, csz, dsz = struct.unpack_from("<III", self.raw, 0x10 + i * 12)
            f["offset"] = off
            f["comp_size"] = csz
            f["decomp_size"] = dsz
            f["index"] = i
        return str(out_p)

    def pack_from_folder(src_dir: str, out_path: str,
                         force_uncompressed: bool = False,
                         compress_level: int = 6,
                         progress_cb=None):
        src = Path(src_dir)
        if not src.is_dir():
            raise FileNotFoundError(f"Not a directory: {src}")

        def is_packable(p: Path) -> bool:
            if not p.is_file():
                return False
            if p.name.lower() in ("manifest.txt", "tim_order.txt"):
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

        def load_tims_for_pack(tims_dir: Path) -> list:
            order_file = tims_dir / "tim_order.txt"
            if order_file.is_file():
                names = [
                    ln.strip()
                    for ln in order_file.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                ]
                tim_list = []
                for n in names:
                    tp = tims_dir / n
                    if not tp.is_file() and not n.lower().endswith(".tim"):
                        tp = tims_dir / (n + ".tim")
                    if not tp.is_file():
                        raise FileNotFoundError(
                            f"tim_order.txt lists '{n}' but it is missing in {tims_dir}"
                        )
                    tim_list.append((tp.name, tp.read_bytes()))
                return tim_list
            return [
                (tp.name, tp.read_bytes())
                for tp in sorted(tims_dir.glob("*.tim"))
            ]

        content_type = 0x0001 if force_uncompressed else 0x8001
        names = []

        # Optional manifest — use only when it lists files that exist
        manifest_path = src / "manifest.txt"
        if manifest_path.is_file():
            try:
                lines = [
                    ln.strip()
                    for ln in manifest_path.read_text(encoding="utf-8").splitlines()
                    if ln.strip()
                ]
                idx = 0
                if idx < len(lines) and lines[idx].startswith("kind="):
                    idx += 1
                if idx < len(lines) and "content_type=" in lines[idx]:
                    if not force_uncompressed:
                        content_type = int(lines[idx].split("=", 1)[1], 0)
                    idx += 1
                nfiles_declared = None
                if idx < len(lines) and lines[idx].startswith("nfiles="):
                    nfiles_declared = int(lines[idx].split("=", 1)[1])
                    idx += 1
                candidate_names = lines[idx:]
                if nfiles_declared is not None:
                    candidate_names = candidate_names[:nfiles_declared]
                valid = [n for n in candidate_names if (src / n).is_file()]
                if valid:
                    names = valid
            except Exception:
                names = []

        # No manifest (or unusable) → scan folder
        if not names:
            names = scan_folder_files()

        if not names:
            all_entries = list(src.iterdir())
            file_names = [p.name for p in all_entries if p.is_file()]
            dir_names = [p.name for p in all_entries if p.is_dir()]
            raise FileNotFoundError(
                "No packable files found in folder.\n\n"
                f"Folder: {src}\n"
                f"Files present: {file_names[:30]}{' …' if len(file_names) > 30 else ''}\n"
                f"Subdirs: {dir_names[:10]}{' …' if len(dir_names) > 10 else ''}\n\n"
                "Put the extracted files directly in this folder "
                "(not only inside subfolders)."
            )

        nfiles = len(names)
        payloads = []

        for ni, name in enumerate(names):
            p = src / name
            if not p.is_file():
                raise FileNotFoundError(f"Missing file listed for pack: {name}")

            stem = Path(name).stem
            tims_dir = src / f"{stem}_tims"

            # Rebuild TPK from <stem>_tims when present
            if name.lower().endswith(".tpk") and tims_dir.is_dir():
                if progress_cb:
                    progress_cb(ni + 1, nfiles, name, "rebuild-tpk")
                tim_list = load_tims_for_pack(tims_dir)
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

        header = bytearray()
        header += b"@(#)GT-ARC" + bytes([0, 0])
        header += struct.pack("<HH", content_type, nfiles)
        data_start = _gtarc_data_start(nfiles, None)
        offset = data_start
        for comp, decomp in payloads:
            header += struct.pack("<III", offset, len(comp), decomp)
            offset += len(comp)
        if len(header) > data_start:
            data_start = _gtarc_data_start(nfiles, len(header))
            header = bytearray()
            header += b"@(#)GT-ARC" + bytes([0, 0])
            header += struct.pack("<HH", content_type, nfiles)
            offset = data_start
            for comp, decomp in payloads:
                header += struct.pack("<III", offset, len(comp), decomp)
                offset += len(comp)
        header += bytes([0]) * (data_start - len(header))

        with open(out_path, "wb") as fh:
            fh.write(header)
            for comp, _ in payloads:
                fh.write(comp)

        return out_path