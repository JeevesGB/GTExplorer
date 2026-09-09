# MENU_IMG.ARC (disc root)

**Path:** `MENU_IMG.ARC` (disc root, not under `MENU/`)  
**Size:** ~121 MB  
**Format:** Outer GT-ARC uncompressed (`0x0001`) containing **6 nested** GT-ARCs

## Role

Bulk **localized menu image** store for the full in-game menu system (dealers, licence centre, and related screens beyond the small GT Home shell).

## Structure

| Outer slot | Approx. size | Contents |
|---|---|---|
| 0–5 | ~19–21 MB each | Nested GT-ARC, `0x8001`, ~**1043** files each |

The six nested archives are treated as **language packs** (e.g. ENG / USA / FRA / GER / ITA / SPA). File counts and layouts are parallel across packs; pixel content differs by language where text is baked into art.

## Related

- Name tables and support data: `MENU_RAW.ARC`
- Small GT-shell backgrounds only: `MENU/MENU_IMG.ARC`
