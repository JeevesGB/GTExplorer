from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QMessageBox, 
    QFileDialog, QInputDialog,
    QDialog, QVBoxLayout, 
    QTableWidget, QTableWidgetItem,
    QDialogButtonBox, QLabel, 
    QAbstractItemView, QTreeWidgetItem,
    QCheckBox, QGroupBox,
    QPushButton, QHBoxLayout,
    QFormLayout, QLineEdit,   
)

from ..utils.archive import GTArc
from ..utils.replay import is_replay_save
from ..utils.spec import is_spec_type, export_spec_strings
from ..utils import user_paths as up_mod
from ..utils.user_paths import UserPaths
from ..utils.tim_pack import parse_tim_pack, build_tim_pack
from . import names

ARCHIVE_GLOBS = ("*.dat", "*.DAT", "*.arc", "*.ARC")


def _win_alive(win) -> bool:
    """Return False if the Qt window has been destroyed (worker still running)."""
    try:
        # PyQt6
        from PyQt6 import sip
        return not sip.isdeleted(win)
    except Exception:
        pass
    try:
        from PyQt5 import sip
        return not sip.isdeleted(win)
    except Exception:
        pass
    try:
        # shiboken fallback
        import shiboken6
        return shiboken6.isValid(win)
    except Exception:
        pass
    try:
        # Last resort: accessing a Qt property
        _ = win.objectName()
        return True
    except RuntimeError:
        return False
    except Exception:
        return False


def _emit_progress(win, cur: int, total: int) -> bool:
    if not _win_alive(win):
        return False
    try:
        win.progress_signal.emit(cur, total)
        return True
    except RuntimeError:
        return False


def _emit_finished(win, ok: bool, payload) -> bool:
    if not _win_alive(win):
        return False
    try:
        win.finished_signal.emit(ok, payload)
        return True
    except RuntimeError:
        return False



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
                _emit_finished(win, True, str(path))
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
                        if not _win_alive(win) or getattr(win, "_cancel_load", False):
                            break
                        try:
                            win.arc.get_data(i)
                        except Exception:
                            pass
                        if i % 16 == 0 or i == total - 1:
                            if not _emit_progress(win, i + 1, total):
                                break
                else:
                    for i in range(total):
                        if not _win_alive(win) or getattr(win, "_cancel_load", False):
                            break
                        try:
                            win.arc.get_data(i)
                        except Exception:
                            pass
                        if i % 8 == 0 or i == total - 1:
                            if not _emit_progress(win, i + 1, total):
                                break
                _emit_finished(win, True, str(path))
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
            _emit_finished(win, True, str(path))
        except Exception as e:
            import traceback
            traceback.print_exc()
            _emit_finished(win, False, f"{type(e).__name__}: {e}")

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
                    _emit_progress(win, i + 1, total)
            win.arc = GTArc()
            win.arc.path = str(folder)
            win.arc.raw = b""
            win.arc.kind = "folder"
            win.arc.stem = folder.name
            win.arc.name_map = None
            win.arc.files = entries
            win.extract_dir = folder
            _emit_finished(win, True, str(folder))
        except Exception as e:
            import traceback
            traceback.print_exc()
            _emit_finished(win, False, f"{type(e).__name__}: {e}")

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
                    _emit_progress(win, i + 1, total)
            _emit_finished(win, True, str(tmp))
        except Exception as e:
            if win._nav_stack:
                win._nav_stack.pop()
            import traceback
            traceback.print_exc()
            _emit_finished(win, False, str(e))

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
        up = getattr(win, "_user_paths", None)
        if up and up.extracted_dir:
            default_out = up.extracted_dir
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
            _emit_finished(win, True, result)
        except Exception as e:
            _emit_finished(win, False, str(e))

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
        up = getattr(win, "_user_paths", None)
        if up and up.original_files_dir:
            default_pack = up.original_files_dir

    out, _ = QFileDialog.getSaveFileName(
        win, "Save repacked archive",
        default_pack or win._last_dir(),
        "DAT (*.DAT *.dat);;All (*.*)",
    )
    if not out:
        return
    win._set_last_dir(out)

    if would_write_into_disk_dir(win, out):
        QMessageBox.warning(
            win, "Refusing overwrite",
            "Packed file would be written into the Disk folder "
            "(your original disc image). Choose a different location — "
            "ORIGINAL FILES is the usual target.",
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
            _emit_finished(win, True, result)
        except Exception as e:
            _emit_finished(win, False, str(e))

    try:
        win.finished_signal.disconnect()
    except TypeError:
        pass
    win.finished_signal.connect(lambda ok, data: on_repack_finished(win, ok, data))
    threading.Thread(target=worker, daemon=True).start()

def would_write_into_disk_dir(win, out_path: str) -> bool:
    """True if out_path is inside the configured Disk folder (protects the
    pristine original disc image from being overwritten by a repack)."""
    up = getattr(win, "_user_paths", None)
    disk_dir = up.disk_dir if up else None
    if not disk_dir or not out_path:
        return False
    try:
        out_p = Path(out_path).resolve()
        disk_p = Path(disk_dir).resolve()
        return disk_p in out_p.parents or out_p.parent == disk_p
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
    return up_mod.app_root()

def tools_dir() -> Path:
    """Legacy fallback tools location (project_root/tools), used when the
    user hasn't configured a tools folder in Setup / Workspace."""
    return project_root() / "tools"

def effective_tools_dir(win) -> Path:
    """The tools folder to use: the one configured in Setup / Workspace if
    set, otherwise the legacy project_root/tools fallback."""
    up = getattr(win, "_user_paths", None)
    if up and up.tools_dir:
        return Path(up.tools_dir)
    return tools_dir()

def _ask_setup_mode(win) -> str | None:
    dlg = QDialog(win)
    dlg.setWindowTitle("Welcome to GTExplorer")
    dlg.setMinimumWidth(480)
    lay = QVBoxLayout(dlg)
    lay.setSpacing(14)
    lay.setContentsMargins(20, 20, 20, 16)

    title = QLabel("First-time Setup")
    title.setStyleSheet("font-size: 16px; font-weight: 600;")
    lay.addWidget(title)

    msg = QLabel(
        "GTExplorer needs five working folders next to the app (or anywhere you choose):"
        "<ul style='margin-top:6px;margin-bottom:6px;'>"
        "<li><b>Disk</b> — original disc images (.bin / .cue)</li>"
        "<li><b>ORIGINAL FILES</b> — dumped game archives (.DAT / .ARC)</li>"
        "<li><b>EXTRACTED</b> — archive extracts for editing</li>"
        "<li><b>Modified Disks</b> — rebuilt disc images</li>"
        "<li><b>tools</b> — optional mkpsxiso / dumpsxiso</li>"
        "</ul>"
        "Create them automatically under the app folder, or pick your own paths."
    )
    msg.setWordWrap(True)
    lay.addWidget(msg)

    choice = {"value" : None}

    def pick(v):
        choice["value"] = v
        dlg.accept()

    row = QHBoxLayout()
    row.setSpacing(8)
    btn_auto = QPushButton("Create Automatically")
    btn_auto.setDefault(True)
    btn_auto.setMinimumHeight(32)
    btn_manual = QPushButton("Create Manually")
    btn_manual.setMinimumHeight(32)
    btn_cancel = QPushButton("Skip for now")
    btn_cancel.setProperty("class","secondary")
    btn_auto.clicked.connect(lambda: pick("auto"))
    btn_manual.clicked.connect(lambda: pick("manual"))
    btn_cancel.clicked.connect(dlg.reject)
    row.addWidget(btn_auto)
    row.addWidget(btn_manual)
    row.addStretch(1)
    row.addWidget(btn_cancel)
    lay.addLayout(row)

    dlg.exec()
    return choice["value"]

def _apply_and_refresh(win, new_paths: UserPaths) -> None:
    win._user_paths = new_paths
    if new_paths.extracted_dir:
        win.extract_dir = Path(new_paths.extracted_dir)
    if hasattr(win, "input_list"):
        refresh_input_file_list(win)

def _show_folder_guide(win, new_paths: UserPaths, created: list[str]) -> None:
    lines = ["Workspace folders are ready:", ""]
    for field_name, folder_name, desc in up_mod.FOLDER_SPECS:
        path = getattr(new_paths, field_name, "")
        lines.append(f"{folder_name}\n{path}")
    if created:
        lines.append("")
        lines.append(f"Created {len(created)} folder(s).")
        QMessageBox.information(win, "Workspace ready", "\n".join(lines))

def clear_workspace_paths(win) -> None: 
    reply = QMessageBox.question(
        win,
        "Clear saved paths?",
        "This clears all folder and tool paths saved in user_paths.json. \n\n"
        "The file itself is kept. Folders on disk are not deleted.\n"
        "You can run Setup again afterwards.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )     
    if reply != QMessageBox.StandardButton.Yes:
        return

    win._user_paths = up_mod.clear_user_paths()
    win.extract_dir = None 
    win._workspace_pack_out = None 
    if hasattr(win, "input_list"):
        win.input_list.clear() 

    win.set_status("Paths cleared")
    QMessageBox.information(
        win,
        "Paths cleared",
        "Saved paths were cleared in user_paths.json.\n\n"
        "Use File -> Setup / Workspace to set them again.",
    )

def set_workspace(win, first_run: bool = False) -> None:

    existing = up_mod.load_user_paths() or UserPaths()

    mode = "manual"
    if first_run or not existing.is_complete():
        mode = _ask_setup_mode(win)
        if mode is None:
            win.set_status(
                "Setup skipped — run File → Setup / Workspace… to configure folders"
            )
            return

    if mode == "auto":
        new_paths = up_mod.default_auto_paths()
        new_paths.mkpsxiso_exe = existing.mkpsxiso_exe
        new_paths.mkpsxiso_enabled = existing.mkpsxiso_enabled
        new_paths.last_dump_image = existing.last_dump_image
        new_paths.last_dump_xml = existing.last_dump_xml
        created = up_mod.create_missing_folders(new_paths)
        up_mod.save_user_paths(new_paths)
        _apply_and_refresh(win, new_paths)
        _show_folder_guide(win, new_paths, created)
        win.set_status("Setup saved — folders created automatically")
        return

    # ---- Manual path picker ----
    dlg = QDialog(win)
    dlg.setWindowTitle("Welcome — Setup" if first_run else "Setup / Workspace")
    dlg.resize(680, 560)
    dlg.setMinimumSize(580, 480)

    root = QVBoxLayout(dlg)
    root.setSpacing(12)
    root.setContentsMargins(14, 14, 14, 14)

    title = QLabel("Choose your folders")
    title.setStyleSheet("font-size: 15px; font-weight: 600;")
    root.addWidget(title)

    subtitle = QLabel(
        "Pick where each GTExplorer working folder should live. "
        "You can change these later from <b>File → Setup / Workspace…</b>."
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
        row_lay = QHBoxLayout()
        row_lay.setSpacing(6)
        row_lay.addWidget(edit, stretch=1)
        row_lay.addWidget(btn)
        return edit, btn, row_lay

    folders_box = QGroupBox("Working folders")
    form = QFormLayout(folders_box)
    form.setSpacing(8)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

    edits: dict[str, QLineEdit] = {}
    for field_name, folder_name, desc in up_mod.FOLDER_SPECS:
        default = getattr(existing, field_name, "") or str(up_mod.app_root() / folder_name)
        edit, btn, row_lay = _path_row(default, placeholder=str(up_mod.app_root() / folder_name))
        edit.setToolTip(desc)
        label = QLabel(f"{folder_name}:")
        label.setToolTip(desc)
        form.addRow(label, row_lay)
        edits[field_name] = edit

        def browse(_checked=False, edit=edit, title=folder_name):
            path = QFileDialog.getExistingDirectory(
                dlg, f"{title} folder", edit.text() or str(up_mod.app_root())
            )
            if path:
                edit.setText(path)

        btn.clicked.connect(browse)

    root.addWidget(folders_box)

    # ---- Disc dump & rebuild (optional) ----
    mk_box = QGroupBox("Disc dump & rebuild (optional)")
    mk_lay = QVBoxLayout(mk_box)
    mk_enable = QCheckBox("Enable disc tools (dumpsxiso / mkpsxiso)")
    mk_enable.setChecked(existing.mkpsxiso_enabled)
    mk_lay.addWidget(mk_enable)

    mk_help = QLabel(
        "Put official binaries in your <b>tools</b> folder above "
        "(see tools/README.txt). "
        "<a href='https://github.com/Lameguy64/mkpsxiso/releases'>Download mkpsxiso</a>"
    )
    mk_help.setWordWrap(True)
    mk_help.setOpenExternalLinks(True)
    mk_help.setStyleSheet("color: #bbb;")
    mk_lay.addWidget(mk_help)

    mk_exe_edit, mk_exe_btn, mk_exe_row = _path_row(
        existing.mkpsxiso_exe, placeholder=r"tools\mkpsxiso.exe"
    )
    mk_form = QFormLayout()
    mk_form.addRow("mkpsxiso program:", mk_exe_row)
    mk_lay.addLayout(mk_form)

    def browse_mk_exe():
        start = mk_exe_edit.text() or edits["tools_dir"].text() or str(up_mod.app_root())
        path, _ = QFileDialog.getOpenFileName(
            dlg, "mkpsxiso executable", start,
            "Executable (mkpsxiso.exe mkpsxiso);;All (*.*)",
        )
        if path:
            mk_exe_edit.setText(path)

    mk_exe_btn.clicked.connect(browse_mk_exe)
    root.addWidget(mk_box)

    root.addStretch(1)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    if first_run:
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save & continue")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Skip for now")
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    root.addWidget(buttons)

    result = dlg.exec()
    if result != QDialog.DialogCode.Accepted:
        win.set_status(
            "Setup skipped — run File → Setup / Workspace… to configure folders"
        )
        return

    new_paths = UserPaths(
        disk_dir=edits["disk_dir"].text().strip(),
        original_files_dir=edits["original_files_dir"].text().strip(),
        extracted_dir=edits["extracted_dir"].text().strip(),
        modified_disks_dir=edits["modified_disks_dir"].text().strip(),
        tools_dir=edits["tools_dir"].text().strip(),
        mkpsxiso_exe=mk_exe_edit.text().strip(),
        mkpsxiso_enabled=mk_enable.isChecked(),
        last_dump_image=existing.last_dump_image,
        last_dump_xml=existing.last_dump_xml,
    )

    if not new_paths.is_complete():
        QMessageBox.warning(
            win, "Setup", "Please fill in all five folder paths."
        )
        return

    try:
        created = up_mod.create_missing_folders(new_paths)
    except OSError as e:
        QMessageBox.warning(win, "Setup", f"Could not create a folder:\n{e}")
        return

    up_mod.save_user_paths(new_paths)
    _apply_and_refresh(win, new_paths)

    if mk_enable.isChecked() and new_paths.mkpsxiso_exe and not Path(new_paths.mkpsxiso_exe).is_file():
        QMessageBox.information(
            win, "mkpsxiso not found",
            f"mkpsxiso was not found at:\n{new_paths.mkpsxiso_exe}\n\n"
            f"Download the official release into:\n{new_paths.tools_dir}",
        )

    if created:
        _show_folder_guide(win, new_paths, created)

    win.set_status("Setup saved")

def maybe_show_first_run_setup(win) -> None:
    """Show setup wizard once on first launch (or if paths are incomplete)."""
    up = up_mod.load_user_paths()
    if up and up.is_complete():
        return
    set_workspace(win, first_run=True)

def apply_workspace_paths(win) -> None:
    up = up_mod.load_user_paths() or UserPaths()
    win._user_paths = up
    if up.extracted_dir:
        win.extract_dir = Path(up.extracted_dir)  # base; per-file extract uses subfolder
    if hasattr(win, "input_list"):
        refresh_input_file_list(win)

def refresh_input_file_list(win) -> None:
    if not hasattr(win, "input_list"):
        return
    win.input_list.clear()
    up = getattr(win, "_user_paths", None)
    in_dir = up.original_files_dir if up else ""
    if not in_dir or not Path(in_dir).is_dir():
        return

    files = []
    root = Path(in_dir)
    for pat in ARCHIVE_GLOBS:
        files.extend(root.rglob(pat))
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

    win.set_status(f"ORIGINAL FILES: {len(uniq)} archive(s) in {in_dir}")

def on_input_file_clicked(win) -> None:
    items = win.input_list.selectedItems()
    if not items:
        return
    path = items[0].data(0, Qt.ItemDataRole.UserRole)
    if not path or not Path(path).is_file():
        return

    up = getattr(win, "_user_paths", None)
    stem = Path(path).stem
    if up and up.extracted_dir:
        extract = Path(up.extracted_dir) / f"{stem}_extract"
        extract.mkdir(parents=True, exist_ok=True)
        win.extract_dir = extract

    # Repack target defaults to overwriting this same archive in ORIGINAL FILES
    # (ready for mkpsxiso to pick up when building Modified Disks).
    win._workspace_pack_out = str(path)

    win._nav_stack.clear()
    open_file_path(win, Path(path), push_nav=False)

def _resolve_tool_exe(win, which: str) -> Path | None:
    """
    which: 'mkpsxiso' or 'dumpsxiso'
    Prefer the configured mkpsxiso_exe path, then the configured tools
    folder, then the legacy project_root/tools fallback.
    """
    up = getattr(win, "_user_paths", None)
    if which == "mkpsxiso" and up and up.mkpsxiso_exe:
        saved = Path(up.mkpsxiso_exe)
        if saved.is_file():
            return saved

    names = ["mkpsxiso.exe", "mkpsxiso"] if which == "mkpsxiso" else ["dumpsxiso.exe", "dumpsxiso"]

    search_dirs = []
    if up and up.tools_dir:
        search_dirs.append(Path(up.tools_dir))
    search_dirs.append(tools_dir())

    for td in search_dirs:
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
            f"Place dumpsxiso.exe in:\n{effective_tools_dir(win)}\n\n"
            "Download: https://github.com/Lameguy64/mkpsxiso/releases",
        )
        return

    up = getattr(win, "_user_paths", None) or UserPaths()

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

    img_default = up.last_dump_image or ""
    if not img_default and up.disk_dir and Path(up.disk_dir).is_dir():
        for pat in ("*.cue", "*.CUE", "*.bin", "*.BIN"):
            hit = next(Path(up.disk_dir).glob(pat), None)
            if hit:
                img_default = str(hit)
                break
    out_default = up.original_files_dir or ""
    xml_default = up.last_dump_xml or ""

    img_e, img_b, img_r = row(img_default, r"e.g. Disk\game.bin or game.cue")
    out_e, out_b, out_r = row(out_default, r"e.g. ORIGINAL FILES")
    xml_e, xml_b, xml_r = row(xml_default, r"e.g. ORIGINAL FILES\gt1.xml")

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
    up.last_dump_image = image
    up.last_dump_xml = xml_path
    if not up.mkpsxiso_exe:
        mk = _resolve_tool_exe(win, "mkpsxiso")
        if mk:
            up.mkpsxiso_exe = str(mk)
    up.mkpsxiso_enabled = True
    up_mod.save_user_paths(up)
    win._user_paths = up

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
            f"Place mkpsxiso.exe in:\n{effective_tools_dir(win)}\n\n"
            "Or set the path in File → Setup / Workspace…",
        )
        return

    up = getattr(win, "_user_paths", None) or UserPaths()

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

    xml_default = up.last_dump_xml or ""
    out_default = up.modified_disks_dir or ""
    if out_default and Path(out_default).is_dir() and xml_default:
        stem = Path(xml_default).stem
        bin_default = str(Path(out_default) / f"{stem}_mod.bin")
        cue_default = str(Path(out_default) / f"{stem}_mod.cue")
    elif xml_default:
        bin_default = str(Path(xml_default).with_name(Path(xml_default).stem + "_mod.bin"))
        cue_default = str(Path(xml_default).with_name(Path(xml_default).stem + "_mod.cue"))
    else:
        bin_default, cue_default = "", ""

    xml_e, xml_b, xml_r = row(xml_default, r"e.g. ORIGINAL FILES\gt1.xml")
    bin_e, bin_b, bin_r = row(bin_default, r"e.g. Modified Disks\gt1_mod.bin")
    cue_e, cue_b, cue_r = row(cue_default, r"e.g. Modified Disks\gt1_mod.cue")

    form.addRow("Project XML:", xml_r)
    form.addRow("Output .bin:", bin_r)
    form.addRow("Output .cue:", cue_r)
    lay.addLayout(form)

    files_dir = up.original_files_dir or ""
    if files_dir:
        lay.addWidget(QLabel(f"Disc files folder (ORIGINAL FILES): <code>{files_dir}</code>"))

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

    up.last_dump_xml = xml_path
    up.mkpsxiso_enabled = True
    up_mod.save_user_paths(up)
    win._user_paths = up

    if Path(bin_path).is_file():
        msg = f"Created:\n{bin_path}"
        if cue_path and Path(cue_path).is_file():
            msg += f"\n{cue_path}"
        QMessageBox.information(win, "Build finished", msg)

def open_tools_folder(win) -> None:
    """Open the configured tools/ directory in the system file manager."""
    td = effective_tools_dir(win)
    td.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(td)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{td}"')
    else:
        os.system(f'xdg-open "{td}"')

def repack_selected_tpk(win) -> None:
    """Rebuild selected TIM Pack entry from <stem>_tims folder on disk."""
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    from pathlib import Path
    from ..utils.tim_pack import parse_tim_pack, build_tim_pack

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

    # Prefer workspace extract folder
    label = f.get("label") or f"{idx:03d}"
    stem = Path(f.get("real_name") or (label + ".tpk")).stem

    candidates = []
    if win.extract_dir:
        candidates.append(Path(win.extract_dir) / f"{stem}_tims")
        candidates.append(Path(win.extract_dir) / f"{label}_tims")
    # also next to a previously extracted .tpk if user points at it

    tims_dir = next((p for p in candidates if p.is_dir()), None)
    if tims_dir is None:
        start = str(win.extract_dir or win._last_dir())
        chosen = QFileDialog.getExistingDirectory(
            win,
            f"Folder of .tim files for {stem}.tpk (e.g. {stem}_tims)",
            start,
        )
        if not chosen:
            return
        tims_dir = Path(chosen)

    # Load TIMs (prefer order file)
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
                QMessageBox.critical(
                    win, "Repack TPK", f"Missing TIM listed in tim_order.txt:\n{n}"
                )
                return
            tim_list.append((tp.name, tp.read_bytes()))
    else:
        files = sorted(tims_dir.glob("*.tim"))
        if not files:
            QMessageBox.critical(win, "Repack TPK", f"No .tim files in:\n{tims_dir}")
            return
        tim_list = [(p.name, p.read_bytes()) for p in files]

    try:
        raw = build_tim_pack(tim_list)
    except Exception as e:
        QMessageBox.critical(win, "Repack TPK", str(e))
        return

    # Update in-memory archive entry
    f["data"] = raw
    f["type"] = "TIM Pack"
    f["ext"] = ".tpk"
    f["decomp_size"] = len(raw)
    f["comp_size"] = len(raw)

    # Optional: also write .tpk next to the _tims folder
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
    # Refresh preview
    if hasattr(win, "on_select"):
        win.on_select()

def pack_folder_to_tpk(win) -> None:
    folder = QFileDialog.getExistingDirectory(
        win, "Folder containing .tim files", str(win.extract_dir or win._last_dir())
    )
    if not folder:
        return
    folder = Path(folder)

    order_file = folder / "tim_order.txt"
    if order_file.is_file():
        names = [
            ln.strip()
            for ln in order_file.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        tim_list = []
        for n in names:
            tp = folder / n
            if not tp.is_file() and not n.lower().endswith(".tim"):
                tp = folder / (n + ".tim")
            if not tp.is_file():
                QMessageBox.critical(win, "Pack TPK", f"Missing: {n}")
                return
            tim_list.append((tp.name, tp.read_bytes()))
    else:
        files = sorted(folder.glob("*.tim"))
        if not files:
            QMessageBox.critical(win, "Pack TPK", f"No .tim files in:\n{folder}")
            return
        tim_list = [(p.name, p.read_bytes()) for p in files]

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
        QMessageBox.critical(win, "Pack TPK", str(e))
        return

    win.set_status(f"Packed {len(tim_list)} TIM(s) → {out}")
    QMessageBox.information(win, "Pack TPK", f"Saved:\n{out}\n\n{len(tim_list)} texture(s)")