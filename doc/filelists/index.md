# GT1 Disc Filetype Index

Reference docs for the archive/`.DAT` filetypes found on the Gran Turismo 1 disc, as extracted by GTExplorer. Each page lists that archive's real folder/file structure; long, repetitive runs (sequential numbers, paired model/texture sets) are collapsed into ranges or tables so the full contents stay scannable.

## Filetypes

| Archive | Files | Description |
|---|---|---|
| [ARCADE.DAT](ARCADE.DAT.MD) | 68 | Texture set for the Arcade mode UI — car-select icons, screen backgrounds, and similar front-end art, stored as sequentially numbered `.tim` images. The final entry (`067.seq`) is an animation/sequence script rather than an image. |
| [ARCADE2.DAT](ARCADE2.DAT.MD) | 8 | A small supplementary Arcade-mode archive: a few extra `.tim` images plus one `.car`/`.tex` model pair. |
| [BG.DAT](BG.DAT.MD) | 20 | Track background environments (skyboxes). `.tpk` files are texture packs that skin the sky dome/backdrop, and `.sky` files describe how those textures are placed and animated. `018.bin` is an unclassified raw entry. |
| [CAR.DAT](CAR.DAT.MD) | 1353 | The full car garage — every drivable car in the game, stored as a `.car` 3D model plus a matching `.tex` (GT-CTEX) texture. Most cars also have a `_night` variant with different, headlight-lit textures for night races. `manifest.txt` is GTExplorer's own generated index, not a game asset. |
| [CARCADE.DAT](CARCADE.DAT.MD) | 80 | Cars available in Arcade mode, stored the same way as CAR.DAT (`.car` model + `.tex` texture) but addressed by numeric index rather than name, since Arcade mode only needs a fixed, small roster. |
| [CARINF.DAT](CARINF.DAT.MD) | — | Car information database (compressed GT-ARC): SPEC records, part tables (brake, gear, suspension, …), string tables for makers/models/grades. Used by the Car Database editor in GTExplorer. |
| [COURSE.DAT](COURSE.DAT.MD) | 9088 | Every racetrack in the game. Each course has a `.dat` (layout/logic) and `.ps` (polygon/collision mesh) file at the top level, plus a matching `<track>_tims/` folder holding all the scenery, signage, and road-texture `.tim` images used to render that circuit. |
| [GAMEMENU.DAT](GAMEMENU.DAT.MD) | 15 | `.tim` images for the main front-end menu screens (title, mode select, etc.). |
| [MENU/MENU_HTM.ARC](MENU_HTM.ARC.MD) | 36 | GT-mode menu **page scripts** (GTHTML). Each file is a small binary hotspot layout: background TIM name, clickable rectangles, links to other pages or engine actions (`LIST_GARAGE`, `SHOW_SPEC`, …). Names from `MENU/HTMLS.IDX`. See [GTHTML format notes](GTHTML.md). |
| [MENU/MENU_IMG.ARC](MENU_MENU_IMG.ARC.MD) | 41 | TIM **backgrounds** for the GT-mode shell pages above (`home`, `garage`, `gtf`, `toyota`, `trd`, …). Named by `MENU/IMAGES.IDX`. Companion to `MENU_HTM.ARC`, not the large root `MENU_IMG.ARC`. |
| [MENU/MENU_SND.ARC](MENU_SND.ARC.MD) | — | Menu sound bank for the GT-mode shell; indexed by `MENU/SOUNDS.IDX` (`gt.ins`, `gt.seq`). |
| [MENU_IMG.ARC](MENU_IMG.ARC.MD) | 6 nested × ~1043 | **Root** bulk menu-image container (~121 MB). One uncompressed outer GT-ARC holding **six nested language packs** (~19–21 MB each). Each nested ARC is compressed and contains on the order of **1043** files (mainly TIMs for dealers, licence centre, and the full in-game menu set). |
| [MENU_RAW.ARC](MENU_RAW.ARC.MD) | 6 | Companion to root `MENU_IMG.ARC`: large **filename lists** (~1043 `.htm` names, ~1043 image/sound names, 14 `.seq` names), used-car listing data, and nested support ARCs. |
| [PITMENU.DAT](PITMENU.DAT.MD) | 24 | `.tim` images for the pit-stop / garage menu screens. |
| [REPLAY.DAT](REPLAY.DAT.MD) | 1 | Almost empty — a single `REPLAY/` folder containing one file, `REPLAY.DAT`. This looks like a placeholder slot the game writes replay data into at runtime rather than a populated asset archive. |
| [SOUND.DAT](SOUND.DAT.MD) | 4076 | The game's audio bank. Top-level `.ins` (VAB instrument headers) and `.es` (engine/event sound definitions) files drive the sound engine, while 249 numbered `<n>_samples/` folders each hold one sound bank's raw waveform data as paired `.adpcm` (PlayStation ADPCM audio) and `.wav` files. |

### MENU folder (disc path `MENU/`)

Self-contained **GT Home / map / garage / Toyota / TRD** shell:

| File | Role |
|---|---|
| `HTMLS.IDX` | Ordered list of 36 `.htm` page names |
| `MENU_HTM.ARC` | [GTHTML](GTHTML.MD) page scripts  |
| `IMAGES.IDX` | Ordered list of 40 `.tim` names |
| `MENU_IMG.ARC` | Page background TIMs |
| `SOUNDS.IDX` | `gt.ins` / `gt.seq` |
| `MENU_SND.ARC` | Menu sounds |

Background TIM for a page is resolved by basename (e.g. `home.htm` ↔ `HOME.tim` / `home.tim`).

---

## Format glossary

Quick reference for extensions used across these archives:

| Extension | Meaning |
|---|---|
| `.adpcm` | PlayStation ADPCM — compressed audio sample. |
| `.arc` | GT-ARC container (may be nested). |
| `.bin` | Unclassified/raw binary blob. |
| `.car` | 3D car model/mesh (GT-CAR). |
| `.dat` | Course layout / game logic data, or generic archive. |
| `.es` | Engine/event sound definition. |
| `.htm` | **GTHTML** menu page script (`@(#)GTHTML`) — not web HTML. Hotspots, TIM name, links/actions. |
| `.idx` | Index file listing names for a sibling `.ARC` (e.g. `HTMLS.IDX`, `IMAGES.IDX`). |
| `.ins` | VAB instrument header (sound engine patch data). |
| `.ps` | Course polygon or collision mesh data. |
| `.seq` | Animation or playback sequence script. |
| `.sky` | Skybox placement/animation data. |
| `.tex` / GT-CTEX | Car colour/texture package (palettes + 4bpp image), paired with `.car`. |
| `.tim` | PlayStation TIM — PS1 image/texture format. |
| `.tpk` | Texture pack (grouped set of textures), used for skyboxes here. |
| `.txt` | Plain-text index or manifest (GTExplorer metadata, not a game asset). |
| `.usedcar` | Used-car dealership listing data. |
| `.wav` | Uncompressed PCM audio sample. |

---

## Related docs

- [GTHTML Format Documentation](GTHTML.md) — binary layout of menu page scripts (`MENU_HTM.ARC`).

---

#### [Go Back](../../README.md)
