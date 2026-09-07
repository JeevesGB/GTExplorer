# GT1 Disc Filetype Index

Reference docs for the archive/`.DAT` filetypes found on the Gran Turismo 1 disc, as extracted by GTExplorer. Each page lists that archive's real folder/file structure; long, repetitive runs (sequential numbers, paired model/texture sets) are collapsed into ranges or tables so the full contents stay scannable.

## Filetypes

| Archive | Files | Description |
|---|---|---|
| [ARCADE.DAT](ARCADE.DAT.MD) | 68 | Texture set for the Arcade mode UI — car-select icons, screen backgrounds, and similar front-end art, stored as sequentially numbered `.tim` images. The final entry (`067.seq`) is an animation/sequence script rather than an image. |
| [ARCADE2.DAT](ARCADE2.DAT.MD) | 8 | A small supplementary Arcade-mode archive: a few extra `.tim` images plus one `.car`/`.tex` model pair. |
| [BG.DAT](BG.DAT.MD) | 20 | Track background environments (skyboxes). `.tpk` files are texture packs that skin the sky dome/backdrop, and `.sky` files describe how those textures are placed and animated. `018.bin` is an unclassified raw entry. |
| [CAR.DAT](CAR.DAT.MD) | 1353 | The full car garage — every drivable car in the game, stored as a `.car` 3D model plus a matching `.tex` texture. Most cars also have a `_night` variant with different, headlight-lit textures for night races. `manifest.txt` is GTExplorer's own generated index, not a game asset. |
| [CARCADE.DAT](CARCADE.DAT.MD) | 80 | Cars available in Arcade mode, stored the same way as CAR.DAT (`.car` model + `.tex` texture) but addressed by numeric index rather than name, since Arcade mode only needs a fixed, small roster. |
| [COURSE.DAT](COURSE.DAT.MD) | 9088 | Every racetrack in the game. Each course has a `.dat` (layout/logic) and `.ps` (polygon/collision mesh) file at the top level, plus a matching `<track>_tims/` folder holding all the scenery, signage, and road-texture `.tim` images used to render that circuit. |
| [GAMEMENU.DAT](GAMEMENU.DAT.MD) | 15 | `.tim` images for the main front-end menu screens (title, mode select, etc.). |
| [MENU_IMG.ARC](MENU_IMG.ARC.MD) | 1148 | The bulk image archive behind the in-game HTML-style menu system (License Center, car dealers, and similar screens): thousands of numbered `.arc` sub-archives — most likely one per menu page — plus a smaller shared pool of `.tim` images and one `.ins` instrument file. |
| [MENU_RAW.ARC](MENU_RAW.ARC.MD) | 7 | Companion archive to MENU_IMG.ARC holding the menu system's supporting data: the used-car listing (`.usedcar`), the menu HTML index (`htmls.idx`), a sound-effect index (`sounds.idx`), an unidentified index, and two `.arc` sub-archives. |
| [PITMENU.DAT](PITMENU.DAT.MD) | 24 | `.tim` images for the pit-stop / garage menu screens. |
| [REPLAY.DAT](REPLAY.DAT.MD) | 1 | Almost empty — a single `REPLAY/` folder containing one file, `REPLAY.DAT`. This looks like a placeholder slot the game writes replay data into at runtime rather than a populated asset archive. |
| [SOUND.DAT](SOUND.DAT.MD) | 4076 | The game's audio bank. Top-level `.ins` (VAB instrument headers) and `.es` (engine/event sound definitions) files drive the sound engine, while 249 numbered `<n>_samples/` folders each hold one sound bank's raw waveform data as paired `.adpcm` (PlayStation ADPCM audio) and `.wav` files. |

## Format glossary

Quick reference for extensions used across these archives:

| Extension | Meaning |
|---|---|
| `.adpcm` | PlayStation ADPCM — compressed audio sample. |
| `.arc` | Generic sub-archive (container of further files). |
| `.bin` | Unclassified/raw binary blob. |
| `.car` | 3D car model/mesh. |
| `.dat` | Course layout / game logic data. |
| `.es` | Engine/event sound definition. |
| `.idx` | Index file pointing into another archive. |
| `.ins` | VAB instrument header (sound engine patch data). |
| `.ps` | Course polygon or collision mesh data. |
| `.seq` | Animation or playback sequence script. |
| `.sky` | Skybox placement/animation data. |
| `.tex` | Texture map for a `.car` model. |
| `.tim` | PlayStation TIM — a raw PS1 image/texture format. |
| `.tpk` | Texture pack (grouped set of textures), used for skyboxes here. |
| `.txt` | Plain-text index or manifest (GTExplorer metadata, not a game asset). |
| `.usedcar` | Used-car dealership listing data. |
| `.wav` | Uncompressed PCM audio sample. |

---

#### [Go Back](../../README.md)
