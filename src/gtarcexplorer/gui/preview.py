"""Archive entry preview (text pane + hand-off to viewer)."""
from __future__ import annotations

import struct

from ..utils.tim_pack import parse_tim_pack
from ..utils.audio import parse_sample_bank
from ..utils.gtps import parse_gtps_header
from ..utils.ctex import parse_ctex_header
from ..utils.slt import parse_slt_index, decode_slt_page
from ..utils.spec import is_spec_type, parse_spec_table, format_spec_preview
from ..utils.namelist import parse_name_list
from ..utils.messagetext import extract_message_strings
from ..utils.replay import is_replay_save, parse_replay_save, format_replay_preview
from ..utils.gthtml import is_gthtml, parse_gthtml, format_gthtml_preview
from ..utils.gtenv import parse_gtenv, format_gtenv_preview

CANVAS_VIEWER = 2


def hex_dump(win, chunk: bytes) -> None:
    for i in range(0, len(chunk), 16):
        line = chunk[i : i + 16]
        hx = " ".join(f"{b:02x}" for b in line)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in line)
        win.preview_text.append(f"{i:04x}  {hx:<48}  {asc}")


def show_preview(win, idx: int) -> None:
    try:
        data = win.arc.get_data(idx)
        f = win.arc.files[idx]

        win.preview_info.setText(
            f"#{idx}  •  {f['type']}  •  {len(data):,} bytes  •  {f['ext']}"
        )
        win.preview_text.clear()
        win.preview_text.append(f"Type     : {f['type']}")
        win.preview_text.append(f"Extension: {f['ext']}")
        win.preview_text.append(f"Size     : {len(data):,} bytes\n")

        if is_replay_save(data) or f.get("type") == "GT Replay Save":
            try:
                save = parse_replay_save(data)
                win.preview_text.append(format_replay_preview(save))
            except Exception as e:
                win.preview_text.append(f"REPLAY.DAT parse error: {e}")
                hex_dump(win, data[:256])
            return

        if f["type"] == "TIM Pack":
            tims = parse_tim_pack(data)
            win.preview_text.append(f"TIM Pack – {len(tims)} textures\n")
            for name, tim in tims:
                win.preview_text.append(f"{name:<20} {len(tim):>10,}")
            win.show_pack_in_viewer(data)
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] in ("Filename List", "Text / Messages"):
            names_list = parse_name_list(data)
            if names_list:
                win.preview_text.append(f"Filename list – {len(names_list)} entries\n")
                win.preview_text.append(f"{'Idx':>4}  Name")
                win.preview_text.append("-" * 40)
                for i, nm in enumerate(names_list):
                    win.preview_text.append(f"{i:4d}  {nm}")
                    if i >= 499:
                        win.preview_text.append(f"... ({len(names_list) - 500} more)")
                        break
            else:
                try:
                    strings = extract_message_strings(data)
                    if strings:
                        win.preview_text.append(
                            f"Text / Messages – {len(strings)} strings\n"
                        )
                        for i, s in enumerate(strings):
                            win.preview_text.append(f"{i:4d}  {s}")
                            if i >= 1999:
                                remaining = len(strings) - 2000
                                if remaining > 0:
                                    win.preview_text.append(f"... ({remaining} more)")
                                break
                    else:
                        win.preview_text.append(
                            data[:8000].decode("utf-8", errors="replace")
                        )
                except Exception:
                    win.preview_text.append(repr(data[:200]))

        elif f["type"] == "TIM Texture":
            win._viewer_mode = "tim"
            win.tim_list.clear()
            win._pack_tims = []
            win._model_verts = []
            win._ctex_data = None
            win.show_in_viewer(data, f["label"] + f["ext"])
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] == "GT HTML" or is_gthtml(data):
            try:
                parsed = parse_gthtml(data)
                win.preview_text.append(format_gthtml_preview(parsed))
            except Exception as e:
                win.preview_text.append(f"GTHTML parse error: {e}")
                hex_dump(win, data[:256])

        elif f["type"] == "GT-ENV System Config":
            try:
                parsed = parse_gtenv(data)
                win.preview_text.append(format_gtenv_preview(parsed, len(data)))
            except Exception as e:
                win.preview_text.append(f"GTENV parse error: {e}")
                hex_dump(win, data[:256])

        elif f["type"] == "Nested GT-ARC" or f.get("ext") == ".arc":
            try:
                if not data.startswith(b"@(#)GT-ARC"):
                    raise ValueError("Not a GT-ARC")
                ct, nfiles = struct.unpack_from("<HH", data, 0x0C)
                win.preview_text.append("Nested GT-ARC")
                win.preview_text.append(
                    f"Content type : 0x{ct:04X}  "
                    f"({'compressed' if ct == 0x8001 else 'uncompressed'})"
                )
                win.preview_text.append(f"Files        : {nfiles}")
                win.preview_text.append("")
                win.preview_text.append(
                    "Double-click the entry or use 'Open Nested ARC' to browse it."
                )
            except Exception as e:
                win.preview_text.append(f"Nested ARC preview error: {e}")
                hex_dump(win, data[:256])

        elif f["type"] == "GT-CTEX Texture":
            try:
                hdr = parse_ctex_header(data)
                win.preview_text.append(
                    f"GT-CTEX  name={hdr['name']!r}  "
                    f"palettes={hdr['palette_count']}  "
                    f"{hdr['width']}x{hdr['height']} 4bpp\n"
                )
            except Exception as e:
                win.preview_text.append(f"CTEX header: {e}")
            win.show_ctex_in_viewer(data, f["label"] + f["ext"])
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] == "GT Menu Image (SLT)":
            try:
                _, info = decode_slt_page(data)
                win.preview_text.append(
                    f"SLT menu image  •  {info['width']}x{info['height']}  •  8-bit grayscale\n"
                )
            except Exception as e:
                win.preview_text.append(f"SLT decode error: {e}")
            win.show_slt_in_viewer(data, f["label"] + f["ext"])
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] == "SLT Index (32B)":
            try:
                sidx = parse_slt_index(data)
                win.preview_text.append("SLT index block (32 bytes, 16 x u16 LE)\n")
                win.preview_text.append(str(sidx["values"]))
                win.preview_text.append(
                    "\n\nField meanings unconfirmed - likely references/sizes for "
                    "the sibling page files (e.g. tvr-muffler1/2/3.slt)."
                )
            except Exception as e:
                win.preview_text.append(f"SLT index parse error: {e}")
            hex_dump(win, data)

        elif is_spec_type(f["type"]):
            try:
                parsed = parse_spec_table(data)
                win.preview_text.append(format_spec_preview(parsed))
            except Exception as e:
                win.preview_text.append(f"Spec parse error: {e}")
                hex_dump(win, data[:256])

        elif f["type"] == "GT-PS Model":
            win.preview_text.append("GT-PS course / track model\n")
            try:
                hdr = parse_gtps_header(data)
                win.preview_text.append(f"Size        : {hdr['size']:,} bytes")
                win.preview_text.append(f"Field 0x1C  : {hdr['field_1c']}")
            except Exception as e:
                win.preview_text.append(f"Header: {e}")
            win.show_model_in_viewer(data, f["label"] + f["ext"])
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] in ("Sound Instrument", "Engine Sound"):
            _, samples = parse_sample_bank(data)
            win.preview_text.append(f"{f['type']} – {len(samples)} ADPCM samples\n")
            for i, (s, e) in enumerate(samples):
                frames = (e - s) // 16
                dur = frames * 28 / 22050
                win.preview_text.append(
                    f"{i:4d}  0x{s:08x}  {e - s:8d}  {dur:9.3f}s"
                )

        else:
            win.preview_text.append("=== Hex dump (first 256 bytes) ===")
            hex_dump(win, data[:256])

    except Exception as e:
        win.preview_text.clear()
        win.preview_text.append(f"Preview error: {e}")
    def header_info(self) -> dict:
        return parse_gtps_header(self.raw)