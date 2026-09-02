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
                hex_dump(win, data[:4096])
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
                hex_dump(win, data[:4096])

        elif f["type"] == "GT-ENV System Config":
            try:
                parsed = parse_gtenv(data)
                win.preview_text.append(format_gtenv_preview(parsed, len(data)))
            except Exception as e:
                win.preview_text.append(f"GTENV parse error: {e}")
                hex_dump(win, data[:4096])

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
                hex_dump(win, data[:4096])

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
                hex_dump(win, data[:4096])

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

        elif f["type"] == "GT-CAR Model":
            win.preview_text.append("GT-CAR car model\n")
            try:
                from ..utils.gtcar import GTCarModel
                model = GTCarModel.from_bytes(data)
                win.preview_text.append(model.summary())
            except Exception as e:
                win.preview_text.append(f"Parse error: {e}")

            tex_data = None
            try:
                from . import viewer as viewer_mod
                tex_data = viewer_mod._find_companion_tex(win, f)
            except Exception:
                pass

            win.show_car_in_viewer(
                data,
                (f.get("label") or "") + (f.get("ext") or ""),
                tex_data=tex_data,
            )
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
            win.preview_text.append("=== Hex dump (first 4kb) ===")
            hex_dump(win, data[:4096])

    except Exception as e:
        win.preview_text.clear()
        win.preview_text.append(f"Preview error: {e}")

    def header_info(self) -> dict:
        return parse_gtps_header(self.raw)

def hex_dump_lines(chunk: bytes) -> list[str]:
    lines = []
    for i in range(0, len(chunk), 16):
        line = chunk[i : i + 16]
        hx = " ".join(f"{b:02x}" for b in line)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in line)
        lines.append(f"{i:04x}  {hx:<48}  {asc}")
    return lines


def _set_preview(win, lines: list[str]) -> None:
    """Set preview text in one shot and keep view at the top."""
    win.preview_text.setPlainText("\n".join(lines))
    win.preview_text.verticalScrollBar().setValue(0)


def show_preview(win, idx: int) -> None:
    try:
        data = win.arc.get_data(idx)
        f = win.arc.files[idx]

        win.preview_info.setText(
            f"#{idx}  •  {f['type']}  •  {len(data):,} bytes  •  {f['ext']}"
        )

        lines: list[str] = [
            f"Type     : {f['type']}",
            f"Extension: {f['ext']}",
            f"Size     : {len(data):,} bytes",
            "",
        ]

        if is_replay_save(data) or f.get("type") == "GT Replay Save":
            try:
                save = parse_replay_save(data)
                lines.append(format_replay_preview(save))
            except Exception as e:
                lines.append(f"REPLAY.DAT parse error: {e}")
                lines.extend(hex_dump_lines(data[:4096]))
            _set_preview(win, lines)
            return

        if f["type"] == "TIM Pack":
            tims = parse_tim_pack(data)
            lines.append(f"TIM Pack – {len(tims)} textures")
            lines.append("")
            for name, tim in tims:
                lines.append(f"{name:<20} {len(tim):>10,}")
            _set_preview(win, lines)
            win.show_pack_in_viewer(data)
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] in ("Filename List", "Text / Messages"):
            names_list = parse_name_list(data)
            if names_list:
                lines.append(f"Filename list – {len(names_list)} entries")
                lines.append("")
                lines.append(f"{'Idx':>4}  Name")
                lines.append("-" * 40)
                for i, nm in enumerate(names_list):
                    lines.append(f"{i:4d}  {nm}")
                    if i >= 499:
                        lines.append(f"... ({len(names_list) - 500} more)")
                        break
            else:
                try:
                    strings = extract_message_strings(data)
                    if strings:
                        lines.append(f"Text / Messages – {len(strings)} strings")
                        lines.append("")
                        for i, s in enumerate(strings):
                            lines.append(f"{i:4d}  {s}")
                            if i >= 1999:
                                remaining = len(strings) - 2000
                                if remaining > 0:
                                    lines.append(f"... ({remaining} more)")
                                break
                    else:
                        lines.append(data[:8000].decode("utf-8", errors="replace"))
                except Exception:
                    lines.append(repr(data[:200]))
            _set_preview(win, lines)

        elif f["type"] == "TIM Texture":
            _set_preview(win, lines)
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
                lines.append(format_gthtml_preview(parsed))
            except Exception as e:
                lines.append(f"GTHTML parse error: {e}")
                lines.extend(hex_dump_lines(data[:4096]))
            _set_preview(win, lines)

        elif f["type"] == "GT-ENV System Config":
            try:
                parsed = parse_gtenv(data)
                lines.append(format_gtenv_preview(parsed, len(data)))
            except Exception as e:
                lines.append(f"GTENV parse error: {e}")
                lines.extend(hex_dump_lines(data[:4096]))
            _set_preview(win, lines)

        elif f["type"] == "Nested GT-ARC" or f.get("ext") == ".arc":
            try:
                if not data.startswith(b"@(#)GT-ARC"):
                    raise ValueError("Not a GT-ARC")
                ct, nfiles = struct.unpack_from("<HH", data, 0x0C)
                lines.append("Nested GT-ARC")
                lines.append(
                    f"Content type : 0x{ct:04X}  "
                    f"({'compressed' if ct == 0x8001 else 'uncompressed'})"
                )
                lines.append(f"Files        : {nfiles}")
                lines.append("")
                lines.append(
                    "Double-click the entry or use 'Open Nested ARC' to browse it."
                )
            except Exception as e:
                lines.append(f"Nested ARC preview error: {e}")
                lines.extend(hex_dump_lines(data[:4096]))
            _set_preview(win, lines)

        elif f["type"] == "GT-CTEX Texture":
            try:
                hdr = parse_ctex_header(data)
                lines.append(
                    f"GT-CTEX  name={hdr['name']!r}  "
                    f"palettes={hdr['palette_count']}  "
                    f"{hdr['width']}x{hdr['height']} 4bpp"
                )
            except Exception as e:
                lines.append(f"CTEX header: {e}")
            _set_preview(win, lines)
            win.show_ctex_in_viewer(data, f["label"] + f["ext"])
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] == "GT Menu Image (SLT)":
            try:
                _, info = decode_slt_page(data)
                lines.append(
                    f"SLT menu image  •  {info['width']}x{info['height']}  •  8-bit grayscale"
                )
            except Exception as e:
                lines.append(f"SLT decode error: {e}")
            _set_preview(win, lines)
            win.show_slt_in_viewer(data, f["label"] + f["ext"])
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] == "SLT Index (32B)":
            try:
                sidx = parse_slt_index(data)
                lines.append("SLT index block (32 bytes, 16 x u16 LE)")
                lines.append("")
                lines.append(str(sidx["values"]))
                lines.append("")
                lines.append(
                    "Field meanings unconfirmed - likely references/sizes for "
                    "the sibling page files (e.g. tvr-muffler1/2/3.slt)."
                )
            except Exception as e:
                lines.append(f"SLT index parse error: {e}")
            lines.extend(hex_dump_lines(data))
            _set_preview(win, lines)

        elif is_spec_type(f["type"]):
            try:
                parsed = parse_spec_table(data)
                lines.append(format_spec_preview(parsed))
            except Exception as e:
                lines.append(f"Spec parse error: {e}")
                lines.extend(hex_dump_lines(data[:4096]))
            _set_preview(win, lines)

        elif f["type"] == "GT-PS Model":
            lines.append("GT-PS course / track model")
            lines.append("")
            try:
                hdr = parse_gtps_header(data)
                lines.append(f"Size        : {hdr['size']:,} bytes")
                lines.append(f"Field 0x1C  : {hdr['field_1c']}")
            except Exception as e:
                lines.append(f"Header: {e}")
            _set_preview(win, lines)
            win.show_model_in_viewer(data, f["label"] + f["ext"])
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] == "GT-CAR Model":
            lines.append("GT-CAR car model")
            lines.append("")
            try:
                from ..utils.gtcar import GTCarModel
                model = GTCarModel.from_bytes(data)
                lines.append(model.summary())
            except Exception as e:
                lines.append(f"Parse error: {e}")
            _set_preview(win, lines)

            tex_data = None
            try:
                from . import viewer as viewer_mod
                tex_data = viewer_mod._find_companion_tex(win, f)
            except Exception:
                pass

            win.show_car_in_viewer(
                data,
                (f.get("label") or "") + (f.get("ext") or ""),
                tex_data=tex_data,
            )
            win._switch_canvas(CANVAS_VIEWER)

        elif f["type"] in ("Sound Instrument", "Engine Sound"):
            _, samples = parse_sample_bank(data)
            lines.append(f"{f['type']} – {len(samples)} ADPCM samples")
            lines.append("")
            for i, (s, e) in enumerate(samples):
                frames = (e - s) // 16
                dur = frames * 28 / 22050
                lines.append(f"{i:4d}  0x{s:08x}  {e - s:8d}  {dur:9.3f}s")
            _set_preview(win, lines)

        else:
            lines.append("=== Hex dump (first 4kb) ===")
            lines.extend(hex_dump_lines(data[:4096]))
            _set_preview(win, lines)

    except Exception as e:
        win.preview_text.setPlainText(f"Preview error: {e}")
        win.preview_text.verticalScrollBar().setValue(0)   