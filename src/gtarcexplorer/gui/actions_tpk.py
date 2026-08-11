"""TIM Pack (.tpk) pack / repack actions."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from ..utils.tim_pack import parse_tim_pack, build_tim_pack


def _load_tims_from_folder(folder: Path) -> list[tuple[str, bytes]]:
    order_file = folder / "tim_order.txt"
    if order_file.is_file():
        names = [
            ln.strip()
            for ln in order_file.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        tim_list: list[tuple[str, bytes]] = []
        for n in names:
            tp = folder / n
            if not tp.is_file() and not n.lower().endswith(".tim"):
                tp = folder / (n + ".tim")
            if not tp.is_file():
                raise FileNotFoundError(f"Missing TIM listed in tim_order.txt: {n}")
            tim_list.append((tp.name, tp.read_bytes()))
        return tim_list

    files = sorted(folder.glob("*.tim"))
    if not files:
        raise FileNotFoundError(f"No .tim files in {folder}")
    return [(p.name, p.read_bytes()) for p in files]


def repack_selected_tpk(win) -> None:
    """Rebuild selected TIM Pack from its *_tims folder."""
    items = win.tree.selectedItems()
    if not items:
        QMessageBox.information(win, "Repack TPK", "Select a TIM Pack entry in the tree.")
        return

    idx = int(items[0].text(0))
    f = win.arc.files[idx]
    data = win.arc.get_data(idx)

    if f.get("type") != "TIM Pack" and not parse_tim_pack(data):
        QMessageBox.warning(win, "Repack TPK", "Selected entry is not a TIM Pack.")
        return

    label = f.get("label") or f"{idx:03d}"
    stem = Path(f.get("real_name") or (label + ".tpk")).stem

    candidates = []
    if getattr(win, "extract_dir", None):
        candidates.append(Path(win.extract_dir) / f"{stem}_tims")
        candidates.append(Path(win.extract_dir) / f"{label}_tims")

    tims_dir = next((p for p in candidates if p.is_dir()), None)
    if tims_dir is None:
        start = str(getattr(win, "extract_dir", None) or win._last_dir())
        chosen = QFileDialog.getExistingDirectory(
            win,
            f"Folder of .tim files for {stem}.tpk (e.g. {stem}_tims)",
            start,
        )
        if not chosen:
            return
        tims_dir = Path(chosen)

    try:
        tim_list = _load_tims_from_folder(tims_dir)
        raw = build_tim_pack(tim_list)
    except Exception as e:
        QMessageBox.critical(win, "Repack TPK", str(e))
        return

    f["data"] = raw
    f["type"] = "TIM Pack"
    f["ext"] = ".tpk"
    f["decomp_size"] = len(raw)
    f["comp_size"] = len(raw)

    out_tpk = tims_dir.parent / f"{stem}.tpk"
    try:
        out_tpk.write_bytes(raw)
    except OSError:
        out_tpk = None

    win.set_status(
        f"Rebuilt TPK #{idx} from {tims_dir.name} ({len(tim_list)} TIM(s))"
        + (f" → {out_tpk.name}" if out_tpk else "")
    )
    QMessageBox.information(
        win,
        "Repack TPK",
        f"Rebuilt TIM Pack from:\n{tims_dir}\n\n"
        f"{len(tim_list)} texture(s)\n"
        f"Size: {len(raw):,} bytes\n\n"
        "In-memory archive entry updated.\n"
        "Use Extract → Repack to write a new .DAT if needed."
        + (f"\n\nAlso saved:\n{out_tpk}" if out_tpk else ""),
    )
    if hasattr(win, "on_select"):
        win.on_select()


def pack_folder_to_tpk(win) -> None:
    """Pick a folder of .tim files and save a standalone .tpk."""
    start = str(getattr(win, "extract_dir", None) or win._last_dir())
    folder = QFileDialog.getExistingDirectory(
        win, "Folder containing .tim files (e.g. au_tims)", start
    )
    if not folder:
        return
    folder = Path(folder)

    try:
        tim_list = _load_tims_from_folder(folder)
    except Exception as e:
        QMessageBox.critical(win, "Pack folder to TPK", str(e))
        return

    default_name = folder.name.replace("_tims", "") + ".tpk"
    out, _ = QFileDialog.getSaveFileName(
        win,
        "Save TIM Pack",
        str(folder.parent / default_name),
        "TIM Pack (*.tpk);;All (*.*)",
    )
    if not out:
        return

    try:
        raw = build_tim_pack(tim_list)
        Path(out).write_bytes(raw)
    except Exception as e:
        QMessageBox.critical(win, "Pack folder to TPK", str(e))
        return

    win.set_status(f"Packed {len(tim_list)} TIM(s) → {out}")
    QMessageBox.information(
        win,
        "Pack folder to TPK",
        f"Saved:\n{out}\n\n{len(tim_list)} texture(s), {len(raw):,} bytes",
    )
