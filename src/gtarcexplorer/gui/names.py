from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox, QFileDialog

from ..utils.filelist import load_bundled, parse_filelist, lookup, bundled_lists
from ..utils.namelist import parse_name_list


def apply_filelist(win) -> None:
    if not win.arc.files:
        return
    name = win.filelist_combo.currentText()
    try:
        if win._custom_filelist_path:
            win.arc.name_map = parse_filelist(win._custom_filelist_path)
        elif name and name != "(none)":
            win.arc.name_map = load_bundled(name)
        else:
            win.arc.name_map = None
    except Exception as e:
        QMessageBox.warning(win, "File list", f"Could not load names:\n{e}")
        win.arc.name_map = None

    for f in win.arc.files:
        real = lookup(win.arc.name_map, win.arc.stem, f["index"])
        if real:
            f["label"] = Path(real).stem
            if Path(real).suffix:
                f["ext"] = Path(real).suffix
            f["real_name"] = real
        else:
            f["label"] = f.get("label") or f"{f['index']:03d}"
            f["real_name"] = None


def apply_name_list(win, names: list[str], overwrite: bool = False) -> int:
    applied = 0
    for i, f in enumerate(win.arc.files):
        if i >= len(names):
            break
        if f.get("real_name") and not overwrite:
            continue
        nm = (names[i] or "").strip()
        if not nm:
            continue
        nm = nm.replace("\\", "/").split("/")[-1]
        f["real_name"] = nm
        f["label"] = Path(nm).stem or nm
        suf = Path(nm).suffix
        if suf:
            f["ext"] = suf
        applied += 1
    return applied


def count_named(win) -> int:
    return sum(1 for f in win.arc.files if f.get("real_name"))


def collect_name_candidates(win) -> list[tuple[str, list[str]]]:
    if not win.arc.files:
        return []
    n = len(win.arc.files)
    found: list[tuple[str, list[str]]] = []

    def consider(label: str, data: bytes | None = None):
        try:
            if not data:
                return
            names = parse_name_list(data)
            if not names:
                return
            if len(names) == n or (n < len(names) <= n + 3):
                found.append((label, names[:n]))
            elif n > 4 and abs(len(names) - n) <= max(2, n // 20):
                found.append((label, names[:n] if len(names) >= n else names))
        except Exception:
            pass

    for f in win.arc.files:
        t = (f.get("type") or "").lower()
        ext = (f.get("ext") or "").lower()
        rn = (f.get("real_name") or f.get("label") or "").lower()
        looks_like_list = (
            "filename" in t or "text" in t or "message" in t
            or ext in (".idx", ".txt", ".lst", ".nam", ".list")
            or any(k in rn for k in ("idx", "list", "name", "htmls", "sound", "file"))
        )
        if not looks_like_list:
            try:
                data = f.get("data")
                if data is None or len(data) > 500_000:
                    continue
                sample = data[:256]
                printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
                if not sample or printable < len(sample) * 0.9:
                    continue
                if data.count(b"\n") < max(3, n // 4):
                    continue
            except Exception:
                continue
        try:
            data = win.arc.get_data(f["index"])
        except Exception:
            data = f.get("data")
        if data:
            consider(f.get("real_name") or f.get("label") or f"entry#{f['index']}", data)

    try:
        base = Path(win.arc.path) if getattr(win.arc, "path", None) else None
        parent = base.parent if base else None
        if parent and parent.is_dir():
            patterns = (
                "*.idx", "*.IDX", "*.txt", "*.TXT", "*.lst", "*.LST",
                "*.nam", "*.NAM", "*list*", "*names*", "filelist*",
            )
            seen: set[str] = set()
            for pat in patterns:
                for sp in parent.glob(pat):
                    if not sp.is_file():
                        continue
                    key = str(sp.resolve())
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        if sp.stat().st_size > 2_000_000:
                            continue
                        raw = sp.read_bytes()
                    except Exception:
                        continue
                    sample = raw[:512]
                    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
                    if sample and printable < len(sample) * 0.8:
                        continue
                    consider(sp.name, raw)
    except Exception:
        pass

    if win._nav_stack:
        snap = win._nav_stack[-1].get("snapshot")
        if snap is not None and getattr(snap, "files", None):
            for f in snap.files:
                t = (f.get("type") or "").lower()
                ext = (f.get("ext") or "").lower()
                if not (
                    "filename" in t or "text" in t or "message" in t
                    or ext in (".idx", ".txt", ".lst", ".nam")
                ):
                    continue
                try:
                    data = f.get("data")
                    if data is None:
                        data = snap.get_data(f["index"])
                    if data:
                        consider(f"parent:{f.get('real_name') or f.get('label')}", data)
                except Exception:
                    pass

    return found


def try_all_bundled_filelists(win) -> tuple[int, str]:
    n = len(win.arc.files)
    if n == 0:
        return 0, ""

    stem = (getattr(win.arc, "stem", None) or "").upper()
    stems: set[str] = {stem} if stem else set()
    try:
        p = Path(win.arc.path) if getattr(win.arc, "path", None) else None
        if p:
            stems.add(p.stem.upper())
    except Exception:
        pass
    stems.discard("")

    best_map = None
    best_name = ""
    best_hits = -1
    best_stem = stem

    lists = bundled_lists() or []
    current = win.filelist_combo.currentText()
    if current in lists:
        lists = [current] + [x for x in lists if x != current]

    for list_name in lists:
        if list_name == "(none)":
            continue
        try:
            mapping = load_bundled(list_name)
        except Exception:
            continue
        for st in (stems or {stem}):
            hits = sum(1 for f in win.arc.files if lookup(mapping, st, f["index"]))
            if hits > best_hits:
                best_hits = hits
                best_map = mapping
                best_name = f"{list_name} [{st}]"
                best_stem = st

    if best_map is None or best_hits <= 0:
        return count_named(win), ""

    win.arc.name_map = best_map
    for f in win.arc.files:
        real = lookup(best_map, best_stem, f["index"])
        if not real:
            for st in stems:
                real = lookup(best_map, st, f["index"])
                if real:
                    break
        if real:
            f["label"] = Path(real).stem
            if Path(real).suffix:
                f["ext"] = Path(real).suffix
            f["real_name"] = real
        elif not f.get("real_name"):
            f["label"] = f.get("label") or f"{f['index']:03d}"

    win_list = best_name.split()[0] if best_name else ""
    if win_list:
        items = [win.filelist_combo.itemText(i) for i in range(win.filelist_combo.count())]
        if win_list in items:
            win.filelist_combo.blockSignals(True)
            win.filelist_combo.setCurrentText(win_list)
            win.filelist_combo.blockSignals(False)

    return count_named(win), best_name


def auto_scan_names(win) -> tuple[int, str]:
    if not win.arc.files:
        return 0, ""

    n = len(win.arc.files)
    sources: list[str] = []

    try:
        win.arc.try_embedded_names()
        if count_named(win):
            sources.append("embedded")
    except Exception:
        pass

    named, fl_src = try_all_bundled_filelists(win)
    if fl_src:
        sources.append(fl_src)

    if count_named(win) >= n:
        return count_named(win), " + ".join(sources) if sources else "filelist"

    candidates = collect_name_candidates(win)
    if candidates:
        def score(item: tuple[str, list[str]]) -> tuple:
            label, names = item
            low = label.lower()
            exact = 0 if len(names) == n else 1
            hint = sum(-1 for h in ("html", "sound", "file", "name", "list", "idx", "menu") if h in low)
            return (exact, hint, -len(names))

        candidates.sort(key=score)
        best_label, best_names = candidates[0]
        if apply_name_list(win, best_names, overwrite=False):
            sources.append(best_label)

    return count_named(win), " + ".join(sources) if sources else ""


def on_filelist_changed(win, _name=None):
    win._custom_filelist_path = None
    if win.arc.files:
        apply_filelist(win)
        win.populate_tree()
        named = sum(1 for f in win.arc.files if f.get("real_name"))
        win.set_status(
            f"Names: {win.filelist_combo.currentText()}  •  "
            f"{named}/{len(win.arc.files)} named"
        )


def load_custom_filelist(win):
    path, _ = QFileDialog.getOpenFileName(
        win, "Open GT1 file list", win._last_dir(),
        "Text (*.txt);;All (*.*)",
    )
    if not path:
        return
    win._custom_filelist_path = path
    win.filelist_combo.setCurrentText(Path(path).name)
    if win.arc.files:
        apply_filelist(win)
        win.populate_tree()
        named = sum(1 for f in win.arc.files if f.get("real_name"))
        win.set_status(f"Applied names from {Path(path).name}  •  {named} named")