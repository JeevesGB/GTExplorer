# MENU_RAW.ARC

**Path:** `MENU_RAW.ARC` (disc root)  
**Files:** 6  
**Format:** GT-ARC (`0x0001`)

## Role

Companion data for the **large** menu system (root `MENU_IMG.ARC`), not the small `MENU/` shell alone.

## Entries (typical)

| Index | Type | Notes |
|---|---|---|
| 0 | Filename list | ~1043 `.htm`-style menu page names |
| 1 | Filename list | ~1043 image / sound-style names |
| 2 | Filename list | ~14 `.seq` sequence names |
| 3 | Nested GT-ARC | Small support archive (~14 files) |
| 4 | Used-car data | Dealership listing blob |
| 5 | Nested GT-ARC | Large support archive (~1043 files) |

## Related

- Images: root `MENU_IMG.ARC` (six language packs)
- GT Home shell only: `MENU/MENU_HTM.ARC` + `MENU/MENU_IMG.ARC`
