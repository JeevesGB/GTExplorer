from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import Optional

PATHS_FILENAME = "user_paths.json"

# (field name, folder name used in "Create Automatically" mode, description shown to the user)
FOLDER_SPECS = [
    ("disk_dir", "Disk",
     "Place your original Gran Turismo disc image (.bin / .cue) here."),
    ("original_files_dir", "ORIGINAL FILES",
     "Files extracted from the disc live here (use the optional mkpsxiso / dumpsxiso "
     "tools to extract and save them here, or copy them in manually)."),
    ("extracted_dir", "EXTRACTED",
     "GTExplorer extracts individual archive contents here for editing."),
    ("modified_disks_dir", "Modified Disks",
     "Rebuilt / modified disc images (.bin / .cue) are written here."),
    ("tools_dir", "tools",
     "Place mkpsxiso / dumpsxiso here (optional, only needed for disc dump/rebuild)."),
]

FOLDER_FIELDS = [f for f, _, _ in FOLDER_SPECS]


def app_root() -> Path:
    """Folder the GTExplorer executable / repo lives in."""
    if getattr(sys, "frozen", False):
        # Always next to the .exe (portable), never _MEIPASS temp
        return Path(sys.executable).resolve().parent
    # Dev: utils/user_paths.py → utils → gtarcexplorer → src → repo root
    return Path(__file__).resolve().parent.parent.parent.parent


def paths_file() -> Path:
    return app_root() / PATHS_FILENAME


@dataclass
class UserPaths:
    disk_dir: str = ""
    original_files_dir: str = ""
    extracted_dir: str = ""
    modified_disks_dir: str = ""
    tools_dir: str = ""
    mkpsxiso_exe: str = ""
    mkpsxiso_enabled: bool = False
    last_dump_image: str = ""
    last_dump_xml: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    def is_complete(self) -> bool:
        return all(getattr(self, f) for f in FOLDER_FIELDS)

    def get_path(self, field: str) -> Optional[Path]:
        val = getattr(self, field, "") or ""
        return Path(val) if val else None


def load_user_paths() -> Optional[UserPaths]:
    """Returns None if user_paths.json doesn't exist or can't be read."""
    f = paths_file()
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    up = UserPaths()
    valid_fields = {fld.name for fld in fields(UserPaths)}
    for key, val in data.items():
        if key in valid_fields:
            if key == "mkpsxiso_enabled":
                setattr(up, key, bool(val))
            elif isinstance(val, str):
                setattr(up, key, val)
    return up


def save_user_paths(up: UserPaths) -> None:
    f = paths_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(up.as_dict(), indent=2), encoding="utf-8")


def default_auto_paths(root: Optional[Path] = None) -> UserPaths:
    """Paths used when the user chooses 'Create Automatically'."""
    root = root or app_root()
    up = UserPaths()
    for field_name, folder_name, _desc in FOLDER_SPECS:
        setattr(up, field_name, str(root / folder_name))
    return up


def create_missing_folders(up: UserPaths) -> list[str]:
    """Create any of the 5 workspace folders that don't already exist.
    Returns the list of paths that were created."""
    created: list[str] = []
    for field_name in FOLDER_FIELDS:
        val = getattr(up, field_name, "")
        if not val:
            continue
        p = Path(val)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p))
    return created
