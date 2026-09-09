"""Discover and bind MENU_HTM + MENU_IMG + IDX companions for the Menu Editor."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .archive import GTArc
from .gthtml import is_gthtml, parse_gthtml
from .tim_image import tim_to_image

try:
    from .gthtml import friendly_page_title
except ImportError:
    def friendly_page_title(name: str) -> str:
        base = name.replace("\\", "/").split("/")[-1]
        if "." in base:
            base = base.rsplit(".", 1)[0]
        return base.replace("_", " ").replace("-", " ").title() or name


@dataclass
class MenuPage:
    name: str
    title: str
    htm_index: int
    tim_index: Optional[int]
    tim_name: Optional[str]
    parsed: dict = field(default_factory=dict)


@dataclass
class MenuBundle:
    htm_arc: Optional[GTArc] = None
    img_arc: Optional[GTArc] = None
    htm_path: Optional[str] = None
    img_path: Optional[str] = None
    htmls_idx: List[str] = field(default_factory=list)
    images_idx: List[str] = field(default_factory=list)
    pages: List[MenuPage] = field(default_factory=list)
    source_label: str = ""


def _read_idx_lines(path: Path) -> List[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="ascii", errors="replace")
    return [ln.strip() for ln in text.replace("\0", "\n").splitlines() if ln.strip()]


def _load_arc(path: Path) -> Optional[GTArc]:
    if not path.is_file():
        return None
    try:
        arc = GTArc()
        arc.load(str(path))
        return arc
    except Exception:
        return None


def _basename_key(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base.lower().lstrip("_")


def discover_menu_bundle(path: str | Path, arc: Optional[GTArc] = None) -> MenuBundle:
    """
    Locate MENU_HTM / MENU_IMG / IDX next to *path* (file or folder).

    Accepts:
      - path to MENU_HTM.ARC / MENU_IMG.ARC
      - path to MENU/ folder
      - currently open GTArc whose path is one of the above
    """
    bundle = MenuBundle()
    p = Path(path) if path else None

    folder: Optional[Path] = None
    htm_path: Optional[Path] = None
    img_path: Optional[Path] = None

    if p is not None:
        if p.is_dir():
            folder = p
        elif p.is_file():
            folder = p.parent
            name = p.name.upper()
            if "MENU_HTM" in name or name.endswith(".HTM"):
                htm_path = p
            elif "MENU_IMG" in name:
                img_path = p

    if folder is None and arc is not None and getattr(arc, "path", None):
        ap = Path(arc.path)
        folder = ap.parent if ap.is_file() else ap
        if ap.is_file():
            if "MENU_HTM" in ap.name.upper():
                htm_path = ap
                bundle.htm_arc = arc
            elif "MENU_IMG" in ap.name.upper() and ap.parent.name.upper() == "MENU":
                img_path = ap
                bundle.img_arc = arc

    if folder is not None:
        if htm_path is None:
            for cand in (folder / "MENU_HTM.ARC", folder / "menu_htm.arc"):
                if cand.is_file():
                    htm_path = cand
                    break
        if img_path is None:
            for cand in (folder / "MENU_IMG.ARC", folder / "menu_img.arc"):
                if cand.is_file():
                    # Prefer MENU/MENU_IMG.ARC over a huge root MENU_IMG if both exist
                    img_path = cand
                    break
        bundle.htmls_idx = _read_idx_lines(folder / "HTMLS.IDX")
        if not bundle.htmls_idx:
            bundle.htmls_idx = _read_idx_lines(folder / "htmls.idx")
        bundle.images_idx = _read_idx_lines(folder / "IMAGES.IDX")
        if not bundle.images_idx:
            bundle.images_idx = _read_idx_lines(folder / "images.idx")

    if bundle.htm_arc is None and htm_path is not None:
        bundle.htm_arc = _load_arc(htm_path)
        bundle.htm_path = str(htm_path) if htm_path else None
    elif htm_path is not None:
        bundle.htm_path = str(htm_path)

    if bundle.img_arc is None and img_path is not None:
        bundle.img_arc = _load_arc(img_path)
        bundle.img_path = str(img_path) if img_path else None
    elif img_path is not None:
        bundle.img_path = str(img_path)

    # If only an open HTM arc was passed without filesystem companions
    if bundle.htm_arc is None and arc is not None:
        # Detect GTHTML entries in current archive
        try:
            for i, f in enumerate(arc.files):
                data = arc.get_data(i)
                if is_gthtml(data):
                    bundle.htm_arc = arc
                    bundle.htm_path = getattr(arc, "path", None)
                    break
        except Exception:
            pass

    _build_pages(bundle)
    parts = []
    if bundle.htm_path:
        parts.append(Path(bundle.htm_path).name)
    if bundle.img_path:
        parts.append(Path(bundle.img_path).name)
    bundle.source_label = " + ".join(parts) if parts else (str(folder) if folder else "—")
    return bundle


def _build_pages(bundle: MenuBundle) -> None:
    bundle.pages = []
    if not bundle.htm_arc:
        return

    # TIM index by basename
    tim_by_key: Dict[str, Tuple[int, str]] = {}
    if bundle.img_arc:
        n_img = len(bundle.img_arc.files)
        for i in range(n_img):
            name = (
                bundle.images_idx[i]
                if i < len(bundle.images_idx)
                else (bundle.img_arc.files[i].get("label") or f"{i:03d}.tim")
            )
            if not str(name).lower().endswith(".tim"):
                name = f"{name}.tim"
            tim_by_key[_basename_key(str(name))] = (i, str(name))

    n = len(bundle.htm_arc.files)
    for i in range(n):
        try:
            data = bundle.htm_arc.get_data(i)
        except Exception:
            continue
        if not is_gthtml(data):
            continue
        name = (
            bundle.htmls_idx[i]
            if i < len(bundle.htmls_idx)
            else (bundle.htm_arc.files[i].get("label") or f"{i:03d}.htm")
        )
        if not str(name).lower().endswith((".htm", ".html")):
            name = f"{name}.htm"
        try:
            parsed = parse_gthtml(data)
        except Exception:
            parsed = {"hotspots": [], "widgets": [], "background_tim": None}

        tim_name = parsed.get("background_tim")
        tim_index = None
        if tim_name:
            key = _basename_key(tim_name)
            if key in tim_by_key:
                tim_index, resolved = tim_by_key[key]
                tim_name = resolved
        elif _basename_key(str(name)) in tim_by_key:
            tim_index, tim_name = tim_by_key[_basename_key(str(name))]

        bundle.pages.append(
            MenuPage(
                name=str(name),
                title=friendly_page_title(str(name)),
                htm_index=i,
                tim_index=tim_index,
                tim_name=tim_name,
                parsed=parsed,
            )
        )


def page_tim_image(bundle: MenuBundle, page: MenuPage):
    """Return PIL Image or None for the page background."""
    if not bundle.img_arc or page.tim_index is None:
        return None
    try:
        data = bundle.img_arc.get_data(int(page.tim_index))
        return tim_to_image(data)
    except Exception:
        return None
