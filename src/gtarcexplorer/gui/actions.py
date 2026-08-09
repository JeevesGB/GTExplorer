from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QFileDialog, QInputDialog,
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QDialogButtonBox, QLabel, QAbstractItemView, QTreeWidgetItem,
)

from ..utils.archive import GTArc
from ..utils.replay import is_replay_save
from ..utils.spec import is_spec_type, export_spec_strings
from . import names

ARCHIVE_GLOBS = ("*.dat", "*.DAT", "*.arc", "*.ARC")

def last_dir(win, key: str = "last_open_dir") -> str:
    return win.settings.value(key, "", type=str) or ""


def set_last_dir(win, path: str, key: str = "last_open_dir") -> None:
    p = Path(path)
    d = str(p if p.is_dir() else p.parent)
    win.settings.setValue(key, d)


def open_path(win, path: str, push_nav: bool = True) -> None:
    p = Path(path)
    if not p.exists():
        QMessageBox.warning(win, "Missing", f"Path not found:\n{path}")
        return
    if p.is_dir():
        open_folder_path(win, p)
    else:
        open_file_path(win, p, push_nav=push_nav)


def open_archive(win) -> None:
    path, _ = QFileDialog.getOpenFileName(
        win, "Open GT archive or extracted file",
        win._last_dir(),
        "GT archives (*.dat *.DAT *.arc *.ARC);;"
        "Extracted files (*.tim *.TIM *.seq *.SEQ *.ins *.INS "
        "*.es *.ES *.tex *.TEX *.ps *.PS *.bin *.BIN *.htm *.HTM "
        "*.idx *.IDX *.usedcar);;"
        "All files (*.*)",
    )
    if not path:
        return
    win._nav_stack.clear()
    open_file_path(win, Path(path), push_nav=False)


def open_folder(win) -> None:
    folder = QFileDialog.getExistingDirectory(
        win, "Open extract folder", win._last_dir("last_extract_dir")
    )
    if not folder:
        return
    win._nav_stack.clear()
    open_folder_path(win, Path(folder))


def open_file_path(win, path: Path, push_nav: bool = True) -> None:
    win._set_last_dir(str(path))
    win._add_recent(str(path))
    win.set_status(f"Reading {path.name}… please wait")
    win.progress.setRange(0, 0)
    win.act_open.setEnabled(False)
    win._cancel_load = False
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def worker():
        try:
            with open(path, "rb") as f:
                header = f.read(256)

            if is_replay_save(header):
                raw = path.read_bytes()
                win.arc = GTArc()
                win.arc.path = str(path)
                win.arc.raw = raw
                win.arc.kind = "replay_save"
                win.arc.stem = path.stem
                win.arc.name_map = None
                win.arc.files = [{
                    "index": 0, "label": path.stem, "ext": ".replay",
                    "type": "GT Replay Save", "offset": 0,
                    "comp_size": len(raw), "decomp_size": len(raw),
                    "data": raw, "real_name": path.name,
                }]
                win.finished_signal.emit(True, str(path))
                return

            if (header.startswith(b"@(#)GT-ARC") or header[1:9] == b"@(#)GT-A"
                    or header.startswith(b"@(#)GT-ZIP")):
                win.arc.load(str(path))
                names.apply_filelist(win)
                named = sum(1 for f in win.arc.files if f.get("real_name"))
                if named == 0:
                    try:
                        win.arc.try_embedded_names()
                    except Exception:
                        pass
                total = len(win.arc.files)
                if win._lazy_load:
                    for i in range(total):
                        if win._cancel_load:
                            break
                        try:
                            win.arc.get_data(i)
                        except Exception:
                            pass
                        if i % 16 == 0 or i == total - 1:
                            win.progress_signal.emit(i + 1, total)
                else:
                    for i in range(total):
                        try:
                            win.arc.get_data(i)
                        except Exception:
                            pass
                        if i % 8 == 0 or i == total - 1:
                            win.progress_signal.emit(i + 1, total)
                win.finished_signal.emit(True, str(path))
                return

            raw = path.read_bytes()
            from ..utils.detect import detect_type
            type_name, ext = detect_type(raw)
            if path.suffix and ext in (".bin", ".txt"):
                ext = path.suffix.lower()
            win.arc = GTArc()
            win.arc.path = str(path)
            win.arc.raw = raw
            win.arc.kind = "single_file"
            win.arc.stem = path.stem
            win.arc.name_map = None
            win.arc.files = [{
                "index": 0, "label": path.stem, "ext": ext, "type": type_name,
                "offset": 0, "comp_size": len(raw), "decomp_size": len(raw),
                "data": raw, "real_name": path.name,
            }]
            win.finished_signal.emit(True, str(path))
        except Exception as e:
            import traceback
            traceback.print_exc()
            win.finished_signal.emit(False, f"{type(e).__name__}: {e}")

    threading.Thread(target=worker, daemon=True).start()


def open_folder_path(win, folder: Path) -> None:
    win._set_last_dir(str(folder), "last_extract_dir")
    win._add_recent(str(folder))
    files = sorted(
        [p for p in folder.iterdir() if p.is_file()],
        key=lambda p: p.name.lower(),
    )
    if not files:
        QMessageBox.information(win, "Empty folder", "No files found in that folder.")
        return
    win.set_status(f"Reading folder {folder.name}…")
    win.progress.setRange(0, 0)
    win.act_open.setEnabled(False)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def worker():
        try:
            from ..utils.detect import detect_type
            entries = []
            total = len(files)
            for i, fp in enumerate(files):
                if win._cancel_load:
                    break
                try:
                    data = fp.read_bytes()
                    type_name, ext = detect_type(data)
                    if fp.suffix and ext in (".bin", ".txt", ""):
                        ext = fp.suffix.lower()
                except Exception:
                    data = b""
                    type_name, ext = "Unknown", fp.suffix.lower() or ".bin"
                entries.append({
                    "index": i, "label": fp.stem, "ext": ext, "type": type_name,
                    "offset": 0, "comp_size": len(data), "decomp_size": len(data),
                    "data": data, "real_name": fp.name,
                })
                if i % 8 == 0 or i == total - 1:
                    win.progress_signal.emit(i + 1, total)
            win.arc = GTArc()
            win.arc.path = str(folder)
            win.arc.raw = b""
            win.arc.kind = "folder"
            win.arc.stem = folder.name
            win.arc.name_map = None
            win.arc.files = entries
            win.extract_dir = folder
            win.finished_signal.emit(True, str(folder))
        except Exception as e:
            import traceback
            traceback.print_exc()
            win.finished_signal.emit(False, f"{type(e).__name__}: {e}")

    threading.Thread(target=worker, daemon=True).start()


def open_nested_arc(win) -> None:
    items = win.tree.selectedItems()
    if not items:
        QMessageBox.information(
            win, "Nothing selected", "Select a Nested GT-ARC entry first."
        )
        return
    idx = int(items[0].text(0))
    f = win.arc.files[idx]
    if f.get("type") != "Nested GT-ARC" and f.get("ext") != ".arc":
        QMessageBox.information(
            win, "Not an ARC", "Selected entry is not a nested GT-ARC."
        )
        return

    data = win.arc.get_data(idx)
    name = f.get("real_name") or f"{f['label']}.arc"
    tmp = Path(tempfile.gettempdir()) / Path(name).name
    tmp.write_bytes(data)

    try:
        parent_label = (
            Path(win.arc.path).name if getattr(win.arc, "path", None)
            else getattr(win.arc, "kind", "?")
        )
    except Exception:
        parent_label = "?"
    parent_path = getattr(win.arc, "path", None)
    parent_snapshot = win.arc

    win._nav_stack.append({
        "path": parent_path,
        "label": parent_label,
        "snapshot": parent_snapshot,
    })
    update_breadcrumb(win)

    win.set_status(f"Opening nested {tmp.name}…")
    win.progress.setRange(0, 0)
    win.act_open.setEnabled(False)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def worker():
        try:
            nested = GTArc()
            nested.load(str(tmp))
            win.arc = nested
            names.apply_filelist(win)
            total = len(win.arc.files)
            for i in range(total):
                try:
                    win.arc.get_data(i)
                except Exception:
                    pass
                if i % 8 == 0 or i == total - 1:
                    win.progress_signal.emit(i + 1, total)
            win.finished_signal.emit(True, str(tmp))
        except Exception as e:
            if win._nav_stack:
                win._nav_stack.pop()
            import traceback
            traceback.print_exc()
            win.finished_signal.emit(False, str(e))

    threading.Thread(target=worker, daemon=True).start()


def update_breadcrumb(win) -> None:
    if not hasattr(win, "breadcrumb"):
        return
    parts = [s.get("label", "?") for s in win._nav_stack]
    current = ""
    try:
        current = (
            Path(win.arc.path).name
            if getattr(win.arc, "path", None)
            else getattr(win.arc, "kind", "")
        )
    except Exception:
        current = getattr(win.arc, "kind", "") or ""
    trail = "  →  ".join(parts + ([str(current)] if current else []))
    win.breadcrumb.setText(trail or "(root)")
    win.btn_nav_back.setEnabled(bool(win._nav_stack))


def nav_back(win) -> None:
    if not win._nav_stack:
        update_breadcrumb(win)
        return
    state = win._nav_stack.pop()
    path = state.get("path")
    snap = state.get("snapshot")
    if snap is not None:
        try:
            win.arc = snap
            win.filter_edit.clear()
            win.populate_tree()
            win._update_action_states()
            update_breadcrumb(win)
            label = state.get("label") or Path(getattr(win.arc, "path", "") or "?").name
            win.set_status(
                f"Back → {label}  •  {len(win.arc.files)} file(s)  •  {win.arc.kind}"
            )
            win.preview_text.clear()
            win.preview_info.setText("Select a file to preview")
            return
        except Exception as e:
            print("nav_back snapshot restore failed:", e)
    if path and Path(path).exists():
        open_path(win, path, push_nav=False)
    else:
        QMessageBox.warning(
            win, "Cannot go back",
            "Parent archive is no longer available.\n"
            f"path={path!r}",
        )
        update_breadcrumb(win)


def extract_all(win) -> None:
    if not win.arc.files:
        QMessageBox.warning(win, "No archive", "Open a file first")
        return

    default_out = ""
    if getattr(win, "extract_dir", None) and Path(win.extract_dir).exists():
        default_out = str(win.extract_dir)
    else:
        default_out = win.settings.value("workspace/extract_dir", "", type=str) or ""
    if not default_out:
        default_out = win._last_dir("last_extract_dir")

    out = QFileDialog.getExistingDirectory(
        win, "Choose extract folder", default_out
    )
    if not out:
        return
    win._set_last_dir(out, "last_extract_dir")
    win.extract_dir = Path(out)

    expand = win.chk_tims.isChecked()
    expand_inst = win.chk_inst.isChecked()
    win.set_progress(0, len(win.arc.files))
    win.set_status("Extracting…")

    def worker():
        try:
            result = win.arc.extract_all(
                out,
                expand_tim_packs=expand,
                expand_inst_banks=expand_inst,
            )
            win.finished_signal.emit(True, result)
        except Exception as e:
            win.finished_signal.emit(False, str(e))

    try:
        win.finished_signal.disconnect()
    except TypeError:
        pass
    win.finished_signal.connect(lambda ok, data: on_extract_finished(win, ok, data))
    threading.Thread(target=worker, daemon=True).start()


def on_extract_finished(win, success: bool, data) -> None:
    try:
        win.finished_signal.disconnect()
    except TypeError:
        pass
    win.finished_signal.connect(win._on_load_finished)
    win.progress.setValue(0)
    if success:
        win.extract_dir = Path(data)
        win._update_action_states()
        win.set_status(f"Lossless extract → {data}")
        populate_struct_tree(win, win.extract_dir)
        QMessageBox.information(
            win, "Done", f"Extracted {len(win.arc.files)} file(s) to:\n{data}"
        )
    else:
        QMessageBox.critical(win, "Extract failed", str(data))


def extract_selected(win) -> None:
    items = win.tree.selectedItems()
    if not items:
        QMessageBox.warning(win, "Nothing selected", "Select one or more files")
        return
    out = QFileDialog.getExistingDirectory(
        win, "Choose extract folder", win._last_dir("last_extract_dir")
    )
    if not out:
        return
    win._set_last_dir(out, "last_extract_dir")
    indices = [int(i.text(0)) for i in items]
    expand = win.chk_tims.isChecked()
    expand_inst = win.chk_inst.isChecked()
    try:
        win.arc.extract_all(
            out, indices=indices,
            expand_tim_packs=expand, expand_inst_banks=expand_inst,
        )
        win.set_status(f"Extracted {len(indices)} file(s) → {out}")
        QMessageBox.information(win, "Done", f"Extracted {len(indices)} file(s)")
    except Exception as e:
        QMessageBox.critical(win, "Error", str(e))


def repack(win) -> None:
    level, ok = QInputDialog.getInt(
        win, "Compression level",
        "0 = store, 1 = fastest, 9 = best\n(recommended: 4-6)",
        value=6, min=0, max=9,
    )
    if not ok:
        return

    folder = win.extract_dir
    if not folder or not Path(folder).is_dir():
        folder = QFileDialog.getExistingDirectory(
            win, "Select folder to pack", win._last_dir("last_extract_dir")
        )
        if not folder:
            return
        win.extract_dir = Path(folder)

    if not (Path(folder) / "manifest.txt").exists():
        QMessageBox.information(
            win, "No manifest",
            "No manifest.txt found.\n"
            "Files will be packed in sorted order from the folder.",
        )

    default_pack = getattr(win, "_workspace_pack_out", None) or ""
    if not default_pack:
        default_pack = win.settings.value("workspace/pack_out", "", type=str) or ""

    out, _ = QFileDialog.getSaveFileName(
        win, "Save repacked archive",
        default_pack or win._last_dir(),
        "DAT (*.DAT *.dat);;All (*.*)",
    )
    if not out:
        return
    win._set_last_dir(out)

    if would_write_into_input(win, out):
        QMessageBox.warning(
            win, "Refusing overwrite",
            "Packed file would be written into the input (game) folder.\n"
            "Use the workspace output folder instead.",
        )
        return

    force_unc = QMessageBox.question(
        win, "Compression",
        "Force uncompressed archive?\n\nYes = uncompressed\nNo = GT-ZIP compressed",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    ) == QMessageBox.StandardButton.Yes

    win.set_status("Repacking…")

    def worker():
        try:
            result = GTArc.pack_from_folder(
                str(win.extract_dir), out,
                force_uncompressed=force_unc,
                compress_level=level,
            )
            win.finished_signal.emit(True, result)
        except Exception as e:
            win.finished_signal.emit(False, str(e))

    try:
        win.finished_signal.disconnect()
    except TypeError:
        pass
    win.finished_signal.connect(lambda ok, data: on_repack_finished(win, ok, data))
    threading.Thread(target=worker, daemon=True).start()

def would_write_into_input(win, out_path: str) -> bool:
    """True if out_path is inside the workspace input (game) folder."""
    in_dir = getattr(win, "_workspace_input", None)
    if not in_dir or not out_path:
        return False
    try:
        out_p = Path(out_path).resolve()
        in_p = Path(in_dir).resolve()
        return in_p in out_p.parents or out_p.parent == in_p
    except Exception:
        return False

def on_repack_finished(win, success: bool, data) -> None:
    try:
        win.finished_signal.disconnect()
    except TypeError:
        pass
    win.finished_signal.connect(win._on_load_finished)
    if success:
        win.set_status(f"Repacked → {data}")
        QMessageBox.information(win, "Done", f"Saved:\n{data}")
    else:
        QMessageBox.critical(win, "Repack failed", str(data))


def save_selected(win) -> None:
    items = win.tree.selectedItems()
    if not items:
        QMessageBox.information(win, "Nothing selected", "Select one or more files.")
        return
    out = QFileDialog.getExistingDirectory(
        win, "Save selected files to…", win._last_dir("last_extract_dir")
    )
    if not out:
        return
    win._set_last_dir(out, "last_extract_dir")
    outp = Path(out)
    n = 0
    for it in items:
        try:
            idx = int(it.text(0))
            f = win.arc.files[idx]
            data = win.arc.get_data(idx)
            name = f.get("real_name") or f"{f['label']}{f.get('ext', '.bin')}"
            dest = outp / Path(name).name
            dest.write_bytes(data)
            n += 1
        except Exception as e:
            print("save error", e)
    win.set_status(f"Saved {n} file(s) → {out}")
    QMessageBox.information(win, "Done", f"Saved {n} file(s) to:\n{out}")


def save_entry(win, idx: int) -> None:
    f = win.arc.files[idx]
    data = win.arc.get_data(idx)
    default_name = f.get("real_name") or f"{f['label']}{f.get('ext', '.bin')}"
    path, _ = QFileDialog.getSaveFileName(
        win, "Save file",
        str(Path(win._last_dir("last_extract_dir")) / Path(default_name).name),
        "All files (*.*)",
    )
    if not path:
        return
    Path(path).write_bytes(data)
    win._set_last_dir(path, "last_extract_dir")
    win.set_status(f"Saved → {path}")


def export_strings(win) -> None:
    if not win.arc.files:
        QMessageBox.warning(win, "No archive", "Open a file first")
        return

    items = win.tree.selectedItems()
    if items:
        indices = []
        for it in items:
            try:
                indices.append(int(it.text(0)))
            except ValueError:
                pass
    else:
        indices = [
            f["index"] for f in win.arc.files
            if is_spec_type(f.get("type", ""))
        ]

    if not indices:
        QMessageBox.information(
            win, "Nothing to export",
            "No SPEC / COLOR / EQUIP / … tables selected (or present).",
        )
        return

    out_dir = QFileDialog.getExistingDirectory(
        win, "Choose folder for string exports", win._last_dir("last_extract_dir")
    )
    if not out_dir:
        return
    out = Path(out_dir)
    win._set_last_dir(out_dir, "last_extract_dir")

    written = 0
    errors = []
    for idx in indices:
        try:
            f = win.arc.files[idx]
            data = win.arc.get_data(idx)
            if not is_spec_type(f.get("type", "")):
                continue
            text = export_spec_strings(data)
            name = f.get("real_name") or f"{f['label']}{f['ext']}"
            stem = Path(name).stem
            dest = out / f"{stem}_strings.txt"
            dest.write_text(text, encoding="utf-8")
            written += 1
        except Exception as e:
            errors.append(f"#{idx}: {e}")

    msg = f"Exported strings from {written} table(s) to:\n{out}"
    if errors:
        msg += "\n\nSome entries failed:\n" + "\n".join(errors[:8])
        if len(errors) > 8:
            msg += f"\n… and {len(errors)-8} more"
        QMessageBox.warning(win, "Export finished with errors", msg)
    else:
        QMessageBox.information(win, "Done", msg)
    win.set_status(f"Exported strings from {written} table(s)")


def open_extract_folder(win) -> None:
    if win.extract_dir and Path(win.extract_dir).exists():
        if sys.platform == "win32":
            os.startfile(win.extract_dir)
        elif sys.platform == "darwin":
            os.system(f'open "{win.extract_dir}"')
        else:
            os.system(f'xdg-open "{win.extract_dir}"')
    else:
        QMessageBox.information(win, "No folder", "Extract first")


def populate_struct_tree(win, root: Path) -> None:
    win.struct_tree.clear()
    root_item = QTreeWidgetItem([str(root.name)])
    root_item.setExpanded(True)
    win.struct_tree.addTopLevelItem(root_item)
    for item in sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.is_dir():
            dir_item = QTreeWidgetItem([f"{item.name}/"])
            dir_item.setIcon(
                0,
                win.style().standardIcon(win.style().StandardPixmap.SP_DirIcon),
            )
            root_item.addChild(dir_item)
            for sub in sorted(item.iterdir()):
                if sub.is_file():
                    size = sub.stat().st_size
                    dir_item.addChild(
                        QTreeWidgetItem([f"{sub.name}  ({size:,} B)"])
                    )
        else:
            size = item.stat().st_size
            root_item.addChild(QTreeWidgetItem([f"{item.name}  ({size:,} B)"]))


def diff_vs_folder(win) -> None:
    if not win.arc.files:
        QMessageBox.warning(win, "No archive", "Open an archive first")
        return

    folder = win.extract_dir
    if not folder or not Path(folder).is_dir():
        folder = QFileDialog.getExistingDirectory(
            win, "Select extract folder to compare",
            win._last_dir("last_extract_dir"),
        )
        if not folder:
            return
        folder = Path(folder)

    rows = []
    for f in win.arc.files:
        idx = f["index"]
        name = (
            Path(f["real_name"]).name
            if f.get("real_name")
            else f"{f['label']}{f['ext']}"
        )
        disk_path = folder / name
        if not disk_path.exists():
            alt = folder / f"{idx:03d}_{name}"
            if alt.exists():
                disk_path = alt
        left_size = (
            len(f["data"]) if f.get("data") is not None
            else (f.get("decomp_size") or 0)
        )
        if disk_path.exists():
            right_size = disk_path.stat().st_size
            delta = right_size - left_size
            status = "same" if delta == 0 else ("larger" if delta > 0 else "smaller")
        else:
            right_size = None
            delta = None
            status = "missing"
        rows.append((idx, name, left_size, right_size, delta, status))

    show_diff_dialog(win, rows, f"Archive  ↔  {folder}")


def diff_vs_dat(win) -> None:
    if not win.arc.files:
        QMessageBox.warning(win, "No archive", "Open the first archive first")
        return

    path, _ = QFileDialog.getOpenFileName(
        win, "Open second .DAT to compare",
        win._last_dir(),
        "DAT / ARC (*.dat *.DAT *.arc *.ARC);;All (*.*)",
    )
    if not path:
        return
    win._set_last_dir(path)

    other = GTArc()
    try:
        other.load(path)
        other.name_map = win.arc.name_map
        for i in range(len(other.files)):
            try:
                other.get_data(i)
            except Exception:
                pass
    except Exception as e:
        QMessageBox.critical(win, "Error", f"Could not load second archive:\n{e}")
        return

    rows = []
    n = max(len(win.arc.files), len(other.files))
    for i in range(n):
        left = win.arc.files[i] if i < len(win.arc.files) else None
        right = other.files[i] if i < len(other.files) else None
        if left and right:
            name = (
                Path(left["real_name"]).name if left.get("real_name")
                else f"{left['label']}{left['ext']}"
            )
            left_size = (
                len(left["data"]) if left.get("data") is not None
                else (left.get("decomp_size") or 0)
            )
            right_size = (
                len(right["data"]) if right.get("data") is not None
                else (right.get("decomp_size") or 0)
            )
            delta = right_size - left_size
            status = "same" if delta == 0 else ("larger" if delta > 0 else "smaller")
        elif left and not right:
            name = f"{left['label']}{left['ext']}"
            left_size = (
                len(left["data"]) if left.get("data") is not None
                else (left.get("decomp_size") or 0)
            )
            right_size = None
            delta = None
            status = "only in A"
        else:
            name = f"{right['label']}{right['ext']}"
            left_size = None
            right_size = (
                len(right["data"]) if right.get("data") is not None
                else (right.get("decomp_size") or 0)
            )
            delta = None
            status = "only in B"
        rows.append((i, name, left_size, right_size, delta, status))

    show_diff_dialog(
        win, rows,
        f"{Path(win.arc.path).name}  ↔  {Path(path).name}",
    )


def show_diff_dialog(win, rows, title: str) -> None:
    dlg = QDialog(win)
    dlg.setWindowTitle("Size diff")
    dlg.resize(820, 540)
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel(title))

    table = QTableWidget(len(rows), 6)
    table.setHorizontalHeaderLabels(["#", "Name", "Left", "Right", "Δ", "Status"])
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    changed = 0
    for r, (idx, name, left, right, delta, status) in enumerate(rows):
        table.setItem(r, 0, QTableWidgetItem(str(idx)))
        table.setItem(r, 1, QTableWidgetItem(name))
        table.setItem(r, 2, QTableWidgetItem(f"{left:,}" if left is not None else "—"))
        table.setItem(r, 3, QTableWidgetItem(f"{right:,}" if right is not None else "—"))
        table.setItem(r, 4, QTableWidgetItem(f"{delta:+,}" if delta is not None else "—"))
        table.setItem(r, 5, QTableWidgetItem(status))
        color = {
            "same": "#1E7B4D", "larger": "#8F5A08", "smaller": "#5B8FD4",
            "missing": "#8E1E1E", "only in A": "#8E1E1E", "only in B": "#8E1E1E",
        }.get(status, "#BFBFBF")
        table.item(r, 5).setForeground(QColor(color))
        if status != "same":
            changed += 1

    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    layout.addWidget(table)
    layout.addWidget(QLabel(f"{changed} difference(s)  •  {len(rows)} entries"))
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    dlg.exec()


def set_workspace(win) -> None:
    from PyQt6.QtWidgets import (
        QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
        QPushButton, QHBoxLayout, QFileDialog, QMessageBox, QLabel,
    )

    dlg = QDialog(win)
    dlg.setWindowTitle("Set workspace")
    dlg.setMinimumWidth(520)
    form = QFormLayout(dlg)

    def _row(default: str = ""):
        edit = QLineEdit(default)
        btn = QPushButton("…")
        btn.setFixedWidth(32)
        row = QHBoxLayout()
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        return edit, btn, row

    in_edit, in_btn, in_row = _row(
        win.settings.value("workspace/input_dir", "", type=str) or ""
    )
    out_edit, out_btn, out_row = _row(
        win.settings.value("workspace/output_dir", "", type=str) or ""
    )

    form.addRow(QLabel(
        "Input folder = original game archives (.DAT / .ARC)\n"
        "Output folder = extracts and packed mods (originals are never overwritten)."
    ))
    form.addRow("Input folder:", in_row)
    form.addRow("Output folder:", out_row)

    def browse_in():
        path = QFileDialog.getExistingDirectory(
            dlg, "Input folder (game files)",
            in_edit.text() or win._last_dir(),
        )
        if path:
            in_edit.setText(path)
            if not out_edit.text().strip():
                out_edit.setText(str(Path(path) / "_mods"))

    def browse_out():
        path = QFileDialog.getExistingDirectory(
            dlg, "Output folder (extracts / packs)",
            out_edit.text() or in_edit.text() or win._last_dir("last_extract_dir"),
        )
        if path:
            out_edit.setText(path)

    in_btn.clicked.connect(browse_in)
    out_btn.clicked.connect(browse_out)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    in_dir = in_edit.text().strip()
    out_dir = out_edit.text().strip()
    if not in_dir or not Path(in_dir).is_dir():
        QMessageBox.warning(win, "Workspace", "Choose a valid input folder.")
        return
    if not out_dir:
        out_dir = str(Path(in_dir) / "_mods")

    Path(out_dir).mkdir(parents=True, exist_ok=True)

    win.settings.setValue("workspace/input_dir", in_dir)
    win.settings.setValue("workspace/output_dir", out_dir)
    win._workspace_input = in_dir
    win._workspace_output = out_dir
    win._set_last_dir(in_dir)
    win._set_last_dir(out_dir, "last_extract_dir")

    refresh_input_file_list(win)
    win.set_status(f"Workspace  •  in={in_dir}  •  out={out_dir}")


def apply_workspace_paths(win) -> None:
    in_dir = win.settings.value("workspace/input_dir", "", type=str) or ""
    out_dir = win.settings.value("workspace/output_dir", "", type=str) or ""
    win._workspace_input = in_dir or None
    win._workspace_output = out_dir or None
    if out_dir:
        win.extract_dir = Path(out_dir)  # base; per-file extract uses subfolder
    if in_dir and Path(in_dir).is_dir() and hasattr(win, "input_list"):
        refresh_input_file_list(win)


def refresh_input_file_list(win) -> None:
    if not hasattr(win, "input_list"):
        return
    win.input_list.clear()
    in_dir = getattr(win, "_workspace_input", None) or ""
    if not in_dir or not Path(in_dir).is_dir():
        return

    files = []
    root = Path(in_dir)
    for pat in ARCHIVE_GLOBS:
        files.extend(root.glob(pat))
    # unique, sorted
    seen = set()
    uniq = []
    for p in sorted(files, key=lambda x: x.name.lower()):
        key = str(p.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)

    for p in uniq:
        item = QTreeWidgetItem([p.name, f"{p.stat().st_size:,}"])
        item.setData(0, Qt.ItemDataRole.UserRole, str(p))
        win.input_list.addTopLevelItem(item)

    win.set_status(f"Input folder: {len(uniq)} archive(s) in {in_dir}")


def on_input_file_clicked(win) -> None:
    items = win.input_list.selectedItems()
    if not items:
        return
    path = items[0].data(0, Qt.ItemDataRole.UserRole)
    if not path or not Path(path).is_file():
        return

    # Per-archive extract / pack defaults under output folder
    out_root = getattr(win, "_workspace_output", None) or win.settings.value(
        "workspace/output_dir", "", type=str
    )
    stem = Path(path).stem
    if out_root:
        extract = Path(out_root) / f"{stem}_extract"
        pack_out = Path(out_root) / f"{stem}_mod{Path(path).suffix or '.DAT'}"
        extract.mkdir(parents=True, exist_ok=True)
        win.extract_dir = extract
        win._workspace_pack_out = str(pack_out)
        win.settings.setValue("workspace/extract_dir", str(extract))
        win.settings.setValue("workspace/pack_out", str(pack_out))

    win._nav_stack.clear()
    open_file_path(win, Path(path), push_nav=False)