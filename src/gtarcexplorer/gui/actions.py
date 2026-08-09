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

    # Prefer the folder currently open in the tree (Open Folder),
    # then the last extract_dir, otherwise ask the user.
    folder = None
    if getattr(win, "arc", None) is not None and getattr(win.arc, "kind", None) == "folder":
        p = getattr(win.arc, "path", None)
        if p and Path(p).is_dir():
            folder = Path(p)
    if folder is None:
        folder = win.extract_dir
    if not folder or not Path(folder).is_dir():
        folder = QFileDialog.getExistingDirectory(
            win, "Select folder to pack", win._last_dir("last_extract_dir")
        )
        if not folder:
            return
        folder = Path(folder)
    else:
        folder = Path(folder)
    win.extract_dir = folder

    if not (folder / "manifest.txt").exists():
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



def project_root() -> Path:
    """Repo / app root (folder that contains tools/, src/, runtool.bat)."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # actions.py -> gui -> gtarcexplorer -> src -> root
    return Path(__file__).resolve().parent.parent.parent.parent


def tools_dir() -> Path:
    return project_root() / "tools"


def default_mkpsxiso_exe() -> str:
    """Prefer tools/mkpsxiso(.exe) next to the app; else empty."""
    td = tools_dir()
    candidates = [
        td / "mkpsxiso.exe",
        td / "mkpsxiso",
        td / "bin" / "mkpsxiso.exe",
        td / "bin" / "mkpsxiso",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return ""


def set_workspace(win, first_run: bool = False) -> None:
    """Workspace / first-run setup: working folders + optional disc tools."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
        QPushButton, QHBoxLayout, QFileDialog, QMessageBox, QLabel,
        QVBoxLayout, QCheckBox, QGroupBox,
    )

    dlg = QDialog(win)
    dlg.setWindowTitle("Welcome — Setup" if first_run else "Setup / Workspace")
    dlg.resize(660, 580)
    dlg.setMinimumSize(580, 500)

    root = QVBoxLayout(dlg)
    root.setSpacing(12)
    root.setContentsMargins(14, 14, 14, 14)

    title = QLabel("Welcome to GTExplorer" if first_run else "Workspace setup")
    title.setStyleSheet("font-size: 15px; font-weight: 600;")
    root.addWidget(title)

    subtitle = QLabel(
        "Choose working folders and, optionally, disc dump/rebuild paths. "
        "You can change these later from <b>File → Setup / Workspace…</b>."
        if first_run else
        "Working folders for archives/mods, and disc dump/rebuild (dumpsxiso / mkpsxiso)."
    )
    subtitle.setWordWrap(True)
    subtitle.setStyleSheet("color: #aaa;")
    root.addWidget(subtitle)

    def _path_row(default: str = "", placeholder: str = ""):
        edit = QLineEdit(default)
        edit.setPlaceholderText(placeholder)
        edit.setMinimumWidth(300)
        edit.setClearButtonEnabled(True)
        btn = QPushButton("Browse…")
        btn.setFixedWidth(80)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        return edit, btn, row

    # ---- 1. Working folders ----
    folders_box = QGroupBox("1. Working folders")
    folders_lay = QVBoxLayout(folders_box)
    folders_help = QLabel(
        "<b>Input</b> — original <code>.DAT</code> / <code>.ARC</code> files (not overwritten).<br>"
        "<b>Output</b> — extracts and repacked mods."
    )
    folders_help.setWordWrap(True)
    folders_help.setStyleSheet("color: #bbb;")
    folders_lay.addWidget(folders_help)

    folders_form = QFormLayout()
    folders_form.setSpacing(8)
    folders_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

    in_edit, in_btn, in_row = _path_row(
        win.settings.value("workspace/input_dir", "", type=str) or "",
        placeholder=r"e.g. D:\GT1\GAMEFILES",
    )
    out_edit, out_btn, out_row = _path_row(
        win.settings.value("workspace/output_dir", "", type=str) or "",
        placeholder=r"e.g. D:\GT1\_mods",
    )
    folders_form.addRow("Input folder:", in_row)
    folders_form.addRow("Output folder:", out_row)
    folders_lay.addLayout(folders_form)
    root.addWidget(folders_box)

    def browse_in():
        path = QFileDialog.getExistingDirectory(
            dlg, "Input folder (original game archives)",
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

    # ---- 2. Disc dump & rebuild ----
    mk_box = QGroupBox("2. Disc dump & rebuild (optional)")
    mk_lay = QVBoxLayout(mk_box)

    mk_enable = QCheckBox("Enable disc tools (dumpsxiso / mkpsxiso)")
    mk_enable.setChecked(bool(win.settings.value("mkpsxiso/enabled", False, type=bool)))
    mk_lay.addWidget(mk_enable)

    tools_path = tools_dir()
    mk_help = QLabel(
        f"Put official binaries in <code>{tools_path}</code> "
        "(see <code>tools/README.txt</code>). "
        "<a href='https://github.com/Lameguy64/mkpsxiso/releases'>Download mkpsxiso</a><br>"
        "<b>Dump</b> extracts a disc image to files + XML. "
        "<b>Build</b> rebuilds a <code>.bin</code>/<code>.cue</code> after you mod files in the disc folder."
    )
    mk_help.setWordWrap(True)
    mk_help.setOpenExternalLinks(True)
    mk_help.setStyleSheet("color: #bbb;")
    mk_lay.addWidget(mk_help)

    mk_form = QFormLayout()
    mk_form.setSpacing(8)
    mk_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

    saved_exe = win.settings.value("mkpsxiso/exe", "", type=str) or ""
    if not saved_exe:
        saved_exe = default_mkpsxiso_exe()

    mk_exe_edit, mk_exe_btn, mk_exe_row = _path_row(
        saved_exe, placeholder=str(tools_path / "mkpsxiso.exe")
    )
    img_edit, img_btn, img_row = _path_row(
        win.settings.value("mkpsxiso/last_image", "", type=str) or "",
        placeholder=r"e.g. D:\ISOs\GT1.bin or GT1.cue",
    )
    mk_xml_edit, mk_xml_btn, mk_xml_row = _path_row(
        win.settings.value("mkpsxiso/xml", "", type=str) or "",
        placeholder=r"e.g. D:\GT1\gt1.xml",
    )
    mk_files_edit, mk_files_btn, mk_files_row = _path_row(
        win.settings.value("mkpsxiso/files_dir", "", type=str) or "",
        placeholder=r"e.g. D:\GT1\disc_files",
    )
    mk_out_edit, mk_out_btn, mk_out_row = _path_row(
        win.settings.value("mkpsxiso/output_dir", "", type=str) or "",
        placeholder=r"e.g. D:\GT1\_built",
    )

    mk_form.addRow("mkpsxiso program:", mk_exe_row)
    mk_form.addRow("Disc image to dump:", img_row)
    mk_form.addRow("Project XML:", mk_xml_row)
    mk_form.addRow("Disc files folder:", mk_files_row)
    mk_form.addRow("Build output folder:", mk_out_row)
    mk_lay.addLayout(mk_form)

    # Action buttons for dump / build
    act_row = QHBoxLayout()
    btn_dump = QPushButton("Dump disc now…")
    btn_dump.setToolTip("Run dumpsxiso using the paths above")
    btn_build = QPushButton("Build disc now…")
    btn_build.setToolTip("Run mkpsxiso using the paths above")
    btn_tools = QPushButton("Open tools folder")
    act_row.addWidget(btn_dump)
    act_row.addWidget(btn_build)
    act_row.addWidget(btn_tools)
    act_row.addStretch(1)
    mk_lay.addLayout(act_row)
    root.addWidget(mk_box)

    mk_widgets = [
        mk_help, mk_exe_edit, mk_exe_btn, img_edit, img_btn,
        mk_xml_edit, mk_xml_btn, mk_files_edit, mk_files_btn,
        mk_out_edit, mk_out_btn, btn_dump, btn_build, btn_tools,
    ]

    def _set_mk_enabled(on: bool):
        for w in mk_widgets:
            w.setEnabled(on)

    _set_mk_enabled(mk_enable.isChecked())
    mk_enable.toggled.connect(_set_mk_enabled)

    def browse_exe():
        start = mk_exe_edit.text() or str(tools_dir())
        path, _ = QFileDialog.getOpenFileName(
            dlg, "mkpsxiso executable", start,
            "Executable (mkpsxiso.exe mkpsxiso);;All (*.*)",
        )
        if path:
            mk_exe_edit.setText(path)

    def browse_img():
        path, _ = QFileDialog.getOpenFileName(
            dlg, "Disc image",
            img_edit.text() or win._last_dir(),
            "Disc images (*.bin *.cue *.iso *.img);;All (*.*)",
        )
        if path:
            img_edit.setText(path)
            stem = Path(path).stem
            parent = Path(path).parent
            if not mk_files_edit.text().strip():
                mk_files_edit.setText(str(parent / f"{stem}_files"))
            if not mk_xml_edit.text().strip():
                mk_xml_edit.setText(str(parent / f"{stem}.xml"))
            if not mk_out_edit.text().strip():
                mk_out_edit.setText(str(parent / "_built"))

    def browse_xml():
        path, _ = QFileDialog.getOpenFileName(
            dlg, "Project XML",
            mk_xml_edit.text() or win._last_dir(),
            "XML (*.xml);;All (*.*)",
        )
        if path:
            mk_xml_edit.setText(path)
            if not mk_files_edit.text().strip():
                p = Path(path)
                cand = p.with_suffix("")
                if cand.is_dir():
                    mk_files_edit.setText(str(cand))
                elif p.parent.is_dir():
                    mk_files_edit.setText(str(p.parent))

    def browse_files():
        path = QFileDialog.getExistingDirectory(
            dlg, "Disc files folder",
            mk_files_edit.text() or win._last_dir(),
        )
        if path:
            mk_files_edit.setText(path)

    def browse_mk_out():
        path = QFileDialog.getExistingDirectory(
            dlg, "Build output folder",
            mk_out_edit.text() or out_edit.text() or win._last_dir("last_extract_dir"),
        )
        if path:
            mk_out_edit.setText(path)

    mk_exe_btn.clicked.connect(browse_exe)
    img_btn.clicked.connect(browse_img)
    mk_xml_btn.clicked.connect(browse_xml)
    mk_files_btn.clicked.connect(browse_files)
    mk_out_btn.clicked.connect(browse_mk_out)

    def _save_fields_to_settings():
        """Persist current form values so Dump/Build dialogs see them."""
        win.settings.setValue("mkpsxiso/enabled", mk_enable.isChecked())
        win.settings.setValue(
            "mkpsxiso/exe",
            mk_exe_edit.text().strip() or default_mkpsxiso_exe(),
        )
        win.settings.setValue("mkpsxiso/last_image", img_edit.text().strip())
        win.settings.setValue("mkpsxiso/xml", mk_xml_edit.text().strip())
        win.settings.setValue("mkpsxiso/files_dir", mk_files_edit.text().strip())
        win.settings.setValue("mkpsxiso/output_dir", mk_out_edit.text().strip())

    def on_dump():
        _save_fields_to_settings()
        dump_disc(win)

    def on_build():
        _save_fields_to_settings()
        build_disc(win)

    def on_tools():
        open_tools_folder(win)

    btn_dump.clicked.connect(on_dump)
    btn_build.clicked.connect(on_build)
    btn_tools.clicked.connect(on_tools)

    # ---- Dialog buttons ----
    root.addStretch(1)
    if first_run:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save & continue")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Skip for now")
    else:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    root.addWidget(buttons)

    result = dlg.exec()
    if result != QDialog.DialogCode.Accepted:
        if first_run:
            win.settings.setValue("setup/completed", True)
        return

    in_dir = in_edit.text().strip()
    out_dir = out_edit.text().strip()

    if first_run and not in_dir:
        win.settings.setValue("setup/completed", True)
        win.set_status("Setup skipped — set folders later via File → Setup / Workspace…")
        return

    if in_dir and not Path(in_dir).is_dir():
        QMessageBox.warning(win, "Setup", "Input folder is not a valid directory.")
        return
    if in_dir and not out_dir:
        out_dir = str(Path(in_dir) / "_mods")
    if out_dir:
        try:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(win, "Setup", f"Could not create output folder:\n{e}")
            return

    if in_dir:
        win.settings.setValue("workspace/input_dir", in_dir)
        win._workspace_input = in_dir
        win._set_last_dir(in_dir)
    if out_dir:
        win.settings.setValue("workspace/output_dir", out_dir)
        win._workspace_output = out_dir
        win._set_last_dir(out_dir, "last_extract_dir")
        win.extract_dir = Path(out_dir)

    _save_fields_to_settings()
    win.settings.setValue("setup/completed", True)

    mk_exe = mk_exe_edit.text().strip() or default_mkpsxiso_exe()
    if mk_enable.isChecked() and mk_exe and not Path(mk_exe).is_file():
        QMessageBox.information(
            win, "mkpsxiso not found",
            f"mkpsxiso was not found at:\n{mk_exe}\n\n"
            f"Download the official release into:\n{tools_dir()}",
        )

    refresh_input_file_list(win)
    status_bits = []
    if in_dir:
        status_bits.append(f"in={in_dir}")
    if out_dir:
        status_bits.append(f"out={out_dir}")
    if mk_enable.isChecked():
        status_bits.append("disc tools=on")
    win.set_status(
        "Setup  •  " + "  •  ".join(status_bits) if status_bits else "Setup saved"
    )


def maybe_show_first_run_setup(win) -> None:
    """Show setup wizard once on first launch (or if never completed)."""
    done = win.settings.value("setup/completed", False, type=bool)
    if done:
        return
    set_workspace(win, first_run=True)


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


def _resolve_tool_exe(win, which: str) -> Path | None:
    """
    which: 'mkpsxiso' or 'dumpsxiso'
    Prefer settings path for mkpsxiso; otherwise tools/ folder.
    """
    if which == "mkpsxiso":
        saved = (win.settings.value("mkpsxiso/exe", "", type=str) or "").strip()
        if saved and Path(saved).is_file():
            return Path(saved)
    td = tools_dir()
    names = []
    if which == "mkpsxiso":
        names = ["mkpsxiso.exe", "mkpsxiso"]
    else:
        names = ["dumpsxiso.exe", "dumpsxiso"]
    for n in names:
        p = td / n
        if p.is_file():
            return p
        p2 = td / "bin" / n
        if p2.is_file():
            return p2
    return None


def _run_tool_with_log(win, title: str, exe: Path, args: list, cwd: Path | None = None) -> None:
    """Run external tool in a dialog with live-ish log (buffered read on finish)."""
    import subprocess
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox, QLabel, QMessageBox,
    )
    from PyQt6.QtCore import Qt

    dlg = QDialog(win)
    dlg.setWindowTitle(title)
    dlg.resize(720, 420)
    lay = QVBoxLayout(dlg)
    info = QLabel(f"<code>{exe.name}</code>  " + " ".join(f'"{a}"' if " " in a else a for a in args))
    info.setWordWrap(True)
    info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lay.addWidget(info)
    log = QTextEdit()
    log.setReadOnly(True)
    log.setPlaceholderText("Running…")
    lay.addWidget(log, stretch=1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.button(QDialogButtonBox.StandardButton.Close).setEnabled(False)
    buttons.rejected.connect(dlg.reject)
    buttons.accepted.connect(dlg.accept)
    lay.addWidget(buttons)

    dlg.show()
    QApplication.processEvents()

    cmd = [str(exe)] + args
    workdir = str(cwd or exe.parent)
    log.append(f"$ cd {workdir}\n$ {' '.join(cmd)}\n")
    QApplication.processEvents()

    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=None,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if out.strip():
            log.append(out)
        log.append(f"\nExit code: {proc.returncode}")
        if proc.returncode == 0:
            win.set_status(f"{title} — success")
        else:
            win.set_status(f"{title} — failed (code {proc.returncode})")
    except FileNotFoundError:
        log.append(f"ERROR: could not run {exe}")
        QMessageBox.critical(win, title, f"Could not run:\n{exe}")
    except Exception as e:
        log.append(f"ERROR: {e}")
        QMessageBox.critical(win, title, str(e))

    buttons.button(QDialogButtonBox.StandardButton.Close).setEnabled(True)
    buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(dlg.accept)
    dlg.exec()


def dump_disc(win) -> None:
    """GUI wrapper for dumpsxiso — extract disc image to files + XML."""
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
        QHBoxLayout, QFileDialog, QDialogButtonBox, QLabel, QMessageBox,
    )

    exe = _resolve_tool_exe(win, "dumpsxiso")
    if not exe:
        QMessageBox.warning(
            win, "dumpsxiso not found",
            f"Place dumpsxiso.exe in:\n{tools_dir()}\n\n"
            "Download: https://github.com/Lameguy64/mkpsxiso/releases",
        )
        return

    dlg = QDialog(win)
    dlg.setWindowTitle("Dump disc (dumpsxiso)")
    dlg.setMinimumWidth(560)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(
        "Extract a PlayStation disc image to a folder and create a rebuild XML "
        "for mkpsxiso. Original image is not modified."
    ))

    form = QFormLayout()

    def row(default="", ph=""):
        e = QLineEdit(default)
        e.setPlaceholderText(ph)
        e.setClearButtonEnabled(True)
        b = QPushButton("Browse…")
        b.setFixedWidth(80)
        h = QHBoxLayout()
        h.addWidget(e, 1)
        h.addWidget(b)
        return e, b, h

    img_default = win.settings.value("mkpsxiso/last_image", "", type=str) or ""
    out_default = win.settings.value("mkpsxiso/files_dir", "", type=str) or ""
    xml_default = win.settings.value("mkpsxiso/xml", "", type=str) or ""

    img_e, img_b, img_r = row(img_default, r"D:\ISOs\game.bin or game.cue")
    out_e, out_b, out_r = row(out_default, r"D:\GT1\disc_files")
    xml_e, xml_b, xml_r = row(xml_default, r"D:\GT1\gt1.xml")

    form.addRow("Disc image (.bin / .cue):", img_r)
    form.addRow("Extract files to:", out_r)
    form.addRow("Write project XML:", xml_r)
    lay.addLayout(form)

    def browse_img():
        p, _ = QFileDialog.getOpenFileName(
            dlg, "Disc image",
            img_e.text() or win._last_dir(),
            "Disc images (*.bin *.cue *.iso *.img);;All (*.*)",
        )
        if p:
            img_e.setText(p)
            stem = Path(p).stem
            parent = str(Path(p).parent)
            if not out_e.text().strip():
                out_e.setText(str(Path(parent) / f"{stem}_files"))
            if not xml_e.text().strip():
                xml_e.setText(str(Path(parent) / f"{stem}.xml"))

    def browse_out():
        p = QFileDialog.getExistingDirectory(dlg, "Extract folder", out_e.text() or win._last_dir())
        if p:
            out_e.setText(p)

    def browse_xml():
        p, _ = QFileDialog.getSaveFileName(
            dlg, "Project XML",
            xml_e.text() or win._last_dir(),
            "XML (*.xml)",
        )
        if p:
            xml_e.setText(p)

    img_b.clicked.connect(browse_img)
    out_b.clicked.connect(browse_out)
    xml_b.clicked.connect(browse_xml)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Dump disc")
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    image = img_e.text().strip()
    out_dir = out_e.text().strip()
    xml_path = xml_e.text().strip()
    if not image or not Path(image).is_file():
        QMessageBox.warning(win, "Dump disc", "Choose a valid disc image file.")
        return
    if not out_dir:
        QMessageBox.warning(win, "Dump disc", "Choose an extract folder.")
        return
    if not xml_path:
        QMessageBox.warning(win, "Dump disc", "Choose where to write the project XML.")
        return

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(xml_path).parent.mkdir(parents=True, exist_ok=True)

    args = ["-x", out_dir, "-s", xml_path, image]
    _run_tool_with_log(win, "Dump disc (dumpsxiso)", exe, args, cwd=exe.parent)

    # Remember paths for Build disc / Setup
    win.settings.setValue("mkpsxiso/last_image", image)
    win.settings.setValue("mkpsxiso/files_dir", out_dir)
    win.settings.setValue("mkpsxiso/xml", xml_path)
    if not (win.settings.value("mkpsxiso/exe", "", type=str) or "").strip():
        mk = _resolve_tool_exe(win, "mkpsxiso")
        if mk:
            win.settings.setValue("mkpsxiso/exe", str(mk))
    win.settings.setValue("mkpsxiso/enabled", True)

    if Path(xml_path).is_file():
        QMessageBox.information(
            win, "Dump finished",
            f"Files:\n{out_dir}\n\nXML:\n{xml_path}\n\n"
            "These paths were saved for Build disc / Setup.",
        )


def build_disc(win) -> None:
    """GUI wrapper for mkpsxiso — rebuild .bin/.cue from project XML."""
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
        QHBoxLayout, QFileDialog, QDialogButtonBox, QLabel, QMessageBox,
    )

    exe = _resolve_tool_exe(win, "mkpsxiso")
    if not exe:
        QMessageBox.warning(
            win, "mkpsxiso not found",
            f"Place mkpsxiso.exe in:\n{tools_dir()}\n\n"
            "Or set the path in File → Setup / Workspace…",
        )
        return

    dlg = QDialog(win)
    dlg.setWindowTitle("Build disc (mkpsxiso)")
    dlg.setMinimumWidth(560)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(
        "Rebuild a PlayStation disc image from a dumpsxiso XML and file tree. "
        "Put modded .DAT files into the disc files folder before building."
    ))

    form = QFormLayout()

    def row(default="", ph=""):
        e = QLineEdit(default)
        e.setPlaceholderText(ph)
        e.setClearButtonEnabled(True)
        b = QPushButton("Browse…")
        b.setFixedWidth(80)
        h = QHBoxLayout()
        h.addWidget(e, 1)
        h.addWidget(b)
        return e, b, h

    xml_default = win.settings.value("mkpsxiso/xml", "", type=str) or ""
    out_default = win.settings.value("mkpsxiso/output_dir", "", type=str) or ""
    if out_default and Path(out_default).is_dir() and xml_default:
        stem = Path(xml_default).stem
        bin_default = str(Path(out_default) / f"{stem}_mod.bin")
        cue_default = str(Path(out_default) / f"{stem}_mod.cue")
    elif xml_default:
        bin_default = str(Path(xml_default).with_name(Path(xml_default).stem + "_mod.bin"))
        cue_default = str(Path(xml_default).with_name(Path(xml_default).stem + "_mod.cue"))
    else:
        bin_default, cue_default = "", ""

    xml_e, xml_b, xml_r = row(xml_default, r"D:\GT1\gt1.xml")
    bin_e, bin_b, bin_r = row(bin_default, r"D:\GT1\_built\gt1_mod.bin")
    cue_e, cue_b, cue_r = row(cue_default, r"D:\GT1\_built\gt1_mod.cue")

    form.addRow("Project XML:", xml_r)
    form.addRow("Output .bin:", bin_r)
    form.addRow("Output .cue:", cue_r)
    lay.addLayout(form)

    files_dir = win.settings.value("mkpsxiso/files_dir", "", type=str) or ""
    if files_dir:
        lay.addWidget(QLabel(f"Disc files folder (from setup): <code>{files_dir}</code>"))

    def browse_xml():
        p, _ = QFileDialog.getOpenFileName(
            dlg, "Project XML", xml_e.text() or win._last_dir(), "XML (*.xml);;All (*.*)"
        )
        if p:
            xml_e.setText(p)

    def browse_bin():
        p, _ = QFileDialog.getSaveFileName(
            dlg, "Output BIN", bin_e.text() or win._last_dir(), "BIN (*.bin);;ISO (*.iso);;All (*.*)"
        )
        if p:
            bin_e.setText(p)
            if not cue_e.text().strip():
                cue_e.setText(str(Path(p).with_suffix(".cue")))

    def browse_cue():
        p, _ = QFileDialog.getSaveFileName(
            dlg, "Output CUE", cue_e.text() or win._last_dir(), "CUE (*.cue);;All (*.*)"
        )
        if p:
            cue_e.setText(p)

    xml_b.clicked.connect(browse_xml)
    bin_b.clicked.connect(browse_bin)
    cue_b.clicked.connect(browse_cue)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Build disc")
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    xml_path = xml_e.text().strip()
    bin_path = bin_e.text().strip()
    cue_path = cue_e.text().strip()
    if not xml_path or not Path(xml_path).is_file():
        QMessageBox.warning(win, "Build disc", "Choose a valid project XML.")
        return
    if not bin_path:
        QMessageBox.warning(win, "Build disc", "Choose an output .bin path.")
        return

    Path(bin_path).parent.mkdir(parents=True, exist_ok=True)
    if cue_path:
        Path(cue_path).parent.mkdir(parents=True, exist_ok=True)

    args = ["-o", bin_path]
    if cue_path:
        args += ["-c", cue_path]
    args.append(xml_path)

    _run_tool_with_log(win, "Build disc (mkpsxiso)", exe, args, cwd=exe.parent)

    win.settings.setValue("mkpsxiso/xml", xml_path)
    win.settings.setValue("mkpsxiso/output_dir", str(Path(bin_path).parent))
    win.settings.setValue("mkpsxiso/enabled", True)

    if Path(bin_path).is_file():
        msg = f"Created:\n{bin_path}"
        if cue_path and Path(cue_path).is_file():
            msg += f"\n{cue_path}"
        QMessageBox.information(win, "Build finished", msg)


def open_tools_folder(win) -> None:
    """Open the tools/ directory in the system file manager."""
    td = tools_dir()
    td.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(td)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{td}"')
    else:
        os.system(f'xdg-open "{td}"')
