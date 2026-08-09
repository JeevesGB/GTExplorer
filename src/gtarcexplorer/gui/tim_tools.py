from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QFileDialog, QDialog, QDialogButtonBox,
    QFormLayout, QComboBox, QCheckBox,
)

from ..utils.tim_image import decode_tim, encode_tim, convert_file_to_tim, read_tim_header
from ..utils.tim_pack import build_tim_pack

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def ask_tim_options(parent, default_bpp: int = 8, show_match_header: bool = False):
    dlg = QDialog(parent)
    dlg.setWindowTitle("TIM options")
    form = QFormLayout(dlg)

    bpp_combo = QComboBox()
    bpp_combo.addItem("4 bpp (16 colours)", 4)
    bpp_combo.addItem("8 bpp (256 colours)", 8)
    bpp_combo.addItem("16 bpp (direct colour)", 16)
    bpp_combo.setCurrentIndex({4: 0, 8: 1, 16: 2}.get(default_bpp, 1))
    form.addRow("Colour depth:", bpp_combo)

    chk_black = QCheckBox("Treat pure black as transparent")
    chk_black.setChecked(True)
    form.addRow(chk_black)

    chk_match = QCheckBox("Match original VRAM / CLUT positions")
    chk_match.setChecked(True)
    chk_match.setVisible(show_match_header)
    form.addRow(chk_match)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return (
        bpp_combo.currentData(),
        chk_black.isChecked(),
        chk_match.isChecked() if show_match_header else False,
    )


def offer_inject(win, new_data: bytes, suggested_name: str = "new.tim"):
    if not win.arc.files:
        return

    items = win.tree.selectedItems()
    can_replace_entry = bool(items)
    can_replace_pack = (
        win._viewer_mode == "pack"
        and bool(win._pack_tims)
        and bool(win.tim_list.selectedItems())
    )
    if not can_replace_entry and not can_replace_pack:
        return

    reply = QMessageBox.question(
        win,
        "Inject into archive?",
        "Also replace the currently selected entry / texture in the open archive?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

    if can_replace_pack:
        row = win.tim_list.indexOfTopLevelItem(win.tim_list.selectedItems()[0])
        name, _ = win._pack_tims[row]
        win._pack_tims[row] = (name, new_data)
        pack_bytes = build_tim_pack(win._pack_tims)
        if items:
            idx = int(items[0].text(0))
            win.arc.files[idx]["data"] = pack_bytes
            win.arc.files[idx]["decomp_size"] = len(pack_bytes)
            win.arc.files[idx]["comp_size"] = len(pack_bytes)
            win.set_status(f"Replaced texture '{name}' inside TIM pack #{idx}")
            from . import viewer
            viewer.show_pack_in_viewer(win, pack_bytes)
            win.populate_tree()
        return

    idx = int(items[0].text(0))
    win.arc.files[idx]["data"] = new_data
    win.arc.files[idx]["decomp_size"] = len(new_data)
    win.arc.files[idx]["comp_size"] = len(new_data)
    win.set_status(f"Replaced entry #{idx} with new TIM ({len(new_data):,} bytes)")
    win.populate_tree()
    win.show_preview(idx)


def convert_image_to_tim(win):
    if not HAS_PIL:
        QMessageBox.warning(win, "Pillow required", "Install Pillow to convert images.")
        return

    path, _ = QFileDialog.getOpenFileName(
        win, "Open image or TIM", win._last_dir(),
        "Images (*.png *.bmp *.jpg *.jpeg *.gif *.tga *.tim *.TIM);;All (*.*)",
    )
    if not path:
        return
    win._set_last_dir(path)

    opts = ask_tim_options(win, default_bpp=8)
    if opts is None:
        return
    bpp, force_black, _ = opts

    out, _ = QFileDialog.getSaveFileName(
        win, "Save TIM as…", str(Path(path).with_suffix(".tim")),
        "TIM (*.tim *.TIM);;All (*.*)",
    )
    if not out:
        return
    win._set_last_dir(out)

    try:
        convert_file_to_tim(path, out, bpp=bpp, force_black_transparent=force_black)
        new_data = Path(out).read_bytes()
        win.set_status(f"Wrote TIM → {out}")
        QMessageBox.information(win, "Done", f"Saved:\n{out}")
        offer_inject(win, new_data, Path(out).name)
    except Exception as e:
        QMessageBox.critical(win, "Convert failed", str(e))


def reencode_selected_tim(win):
    if not HAS_PIL:
        QMessageBox.warning(win, "Pillow required", "Install Pillow to re-encode TIMs.")
        return

    items = win.tree.selectedItems()
    if not items:
        return
    idx = int(items[0].text(0))
    f = win.arc.files[idx]
    data = win.arc.get_data(idx)

    try:
        hdr = read_tim_header(data)
        default_bpp = {0: 4, 1: 8, 2: 16}.get(hdr["bpp"], 8)
    except Exception:
        hdr = None
        default_bpp = 8

    opts = ask_tim_options(win, default_bpp=default_bpp, show_match_header=True)
    if opts is None:
        return
    bpp, force_black, match_hdr = opts

    name = f.get("real_name") or f"{f['label']}.tim"
    out, _ = QFileDialog.getSaveFileName(
        win, "Save re-encoded TIM as…",
        str(Path(win._last_dir("last_extract_dir")) / Path(name).name),
        "TIM (*.tim *.TIM);;All (*.*)",
    )
    if not out:
        return
    win._set_last_dir(out, "last_extract_dir")

    try:
        img, _ = decode_tim(data)
        kwargs = {}
        if match_hdr and hdr:
            kwargs = dict(
                vram_x=hdr["vram_x"], vram_y=hdr["vram_y"],
                clut_x=hdr["clut_x"], clut_y=hdr["clut_y"],
            )
        new_data = encode_tim(img, bpp=bpp, force_black_transparent=force_black, **kwargs)
        Path(out).write_bytes(new_data)
        win.set_status(f"Re-encoded TIM → {out}")
        QMessageBox.information(win, "Done", f"Saved:\n{out}")
        offer_inject(win, new_data, Path(out).name)
    except Exception as e:
        QMessageBox.critical(win, "Re-encode failed", str(e))


def replace_selected_with_image(win):
    if not HAS_PIL:
        QMessageBox.warning(win, "Pillow required", "Install Pillow to replace TIMs.")
        return

    items = win.tree.selectedItems()
    if not items:
        return
    idx = int(items[0].text(0))
    original = win.arc.get_data(idx)

    try:
        hdr = read_tim_header(original)
        default_bpp = {0: 4, 1: 8, 2: 16}.get(hdr["bpp"], 8)
    except Exception:
        hdr = None
        default_bpp = 8

    path, _ = QFileDialog.getOpenFileName(
        win, "Open replacement image", win._last_dir(),
        "Images (*.png *.bmp *.jpg *.jpeg *.gif *.tga);;All (*.*)",
    )
    if not path:
        return
    win._set_last_dir(path)

    opts = ask_tim_options(win, default_bpp=default_bpp, show_match_header=True)
    if opts is None:
        return
    bpp, force_black, match_hdr = opts

    try:
        img = Image.open(path)
        kwargs = {}
        if match_hdr and hdr:
            kwargs = dict(
                vram_x=hdr["vram_x"], vram_y=hdr["vram_y"],
                clut_x=hdr["clut_x"], clut_y=hdr["clut_y"],
            )
        new_data = encode_tim(img, bpp=bpp, force_black_transparent=force_black, **kwargs)
        win.arc.files[idx]["data"] = new_data
        win.arc.files[idx]["decomp_size"] = len(new_data)
        win.arc.files[idx]["comp_size"] = len(new_data)
        win.set_status(f"Replaced #{idx} with image ({len(new_data):,} bytes)")
        win.populate_tree()
        win.show_preview(idx)
        QMessageBox.information(
            win, "Done",
            f"Entry #{idx} now contains the new TIM.\nExtract or repack when you are ready.",
        )
    except Exception as e:
        QMessageBox.critical(win, "Replace failed", str(e))


def batch_convert_folder(win):
    if not HAS_PIL:
        QMessageBox.warning(win, "Pillow required", "Install Pillow to convert images.")
        return

    src_dir = QFileDialog.getExistingDirectory(win, "Folder of PNGs / images", win._last_dir())
    if not src_dir:
        return
    win._set_last_dir(src_dir)

    opts = ask_tim_options(win, default_bpp=8)
    if opts is None:
        return
    bpp, force_black, _ = opts

    out_dir = QFileDialog.getExistingDirectory(
        win, "Output folder for TIMs", win._last_dir("last_extract_dir")
    )
    if not out_dir:
        return
    win._set_last_dir(out_dir, "last_extract_dir")

    exts = {".png", ".bmp", ".jpg", ".jpeg", ".gif", ".tga", ".tim"}
    files = [p for p in Path(src_dir).iterdir() if p.is_file() and p.suffix.lower() in exts]
    if not files:
        QMessageBox.information(win, "Empty", "No supported images found in that folder.")
        return

    win.set_status(f"Converting {len(files)} image(s)…")
    win.progress.setRange(0, len(files))
    ok = fail = 0
    for i, src in enumerate(sorted(files)):
        try:
            dst = Path(out_dir) / (src.stem + ".tim")
            convert_file_to_tim(src, dst, bpp=bpp, force_black_transparent=force_black)
            ok += 1
        except Exception as e:
            print("batch convert", src, e)
            fail += 1
        win.progress.setValue(i + 1)
        QApplication.processEvents()

    win.progress.setValue(0)
    win.set_status(f"Batch convert done – {ok} ok, {fail} failed → {out_dir}")
    QMessageBox.information(
        win, "Done",
        f"Converted {ok} file(s)\nFailed: {fail}\n\nOutput:\n{out_dir}",
    )