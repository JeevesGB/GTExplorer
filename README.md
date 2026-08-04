# GTArcExplorer

Extractor / repacker for **Gran Turismo 1** (PlayStation) archive files, with optional TIM-pack expansion and a built-in asset viewer for textures.

Files are written **exactly as stored** — only GT-ZIP decompression is applied on extract. No format conversion and no header rewriting unless you opt into TIM-pack rebuild on repack.

![](img/bg.png)
![](/img/course.png)


---

## Requirements

- Python 3.8+
- [Pillow](https://python-pillow.org/) (Asset Viewer)

```bash
pip install Pillow
```

---

## Usage

```bash
python GTArcExplorer.py
```

### Open an archive

**Open .DAT…** — select a `.DAT` / `.ARC` file.

| Kind | Detection | Examples |
|------|-----------|----------|
| Standard GT-ARC | Header `@(#)GT-ARC` | `COURSE.DAT`, `CAR.DAT`, `TITLE.DAT`, `SOUND.DAT`, `GAMEMENU.DAT`, `ARCADE.DAT`, `BG.DAT`, `PITMENU.DAT`, `MENU_RAW.ARC`, … |
| Compressed GT-ARC | Mangled header (`@(#)GT-A` / `RC`) | `CARINF.DAT` |
| Raw GT-ZIP | No ARC wrapper | `GAMEFONT.DAT` |

### Extract

- **Extract All** — decompress every entry into a folder  
- **Extract Selected** — decompress only selected rows  

Extensions are chosen from content magic (see below). A `manifest.txt` is written for lossless repacking.

#### Optional: expand TIM packs

Tick **Also extract TIMs from packs** before extracting.  
Each `.tpk` is still written intact, and a subfolder is added:

```
000.tpk
000_tims/
  refrect.tim
  circuit.tim
  1kabe1.tim
  …
```

### Repack

**Repack…** builds a new archive from an extract folder + `manifest.txt`.

- If a `NNN_tims/` folder exists next to a `.tpk`, the pack is **rebuilt from those TIM files** first (so texture edits are preserved).
- You can force an **uncompressed** archive (`content_type = 0x0001`) or keep **GT-ZIP** compression (`0x8001`).
- Progress is shown per file (`rebuild-tpk` / `compress` / `copy`).

### Asset Viewer

Select a **TIM Texture** (`.tim`) or **TIM Pack** (`.tpk`) in the archive list, then open the **Asset Viewer** tab.

| Control | Action |
|---------|--------|
| Texture list | For packs — click a name to view that TIM |
| Canvas | Dark background, scrollable |
| Zoom + / − | Scale preview (nearest-neighbor) |
| 1:1 | Native resolution |
| Fit | Scale to window |
| Info bar | Size, bit depth, CLUT, VRAM position |

Supported TIM formats: 4-bit + CLUT, 8-bit + CLUT, 16-bit, 24-bit.

---

## Detected file types

| Magic / content | Extension | Description |
|-----------------|-----------|-------------|
| `@(#)GT-PS` | `.gtps` | Course / track model |
| `@(#)GT-CAR` | `.gtcar` | Car model |
| `@(#)GT-CTEX` | `.ctex` | Car texture set |
| `@(#)GT-SKY` | `.gtsky` | Skybox |
| `@(#)GT-ARC` | `.arc` | Nested GT-ARC |
| `@(#)USEDCAR` | `.usedcar` | Used-car data |
| `INST` | `.inst` | Sound instrument bank |
| `ENGN` | `.engn` | Engine sound bank |
| `10 00 00 00` | `.tim` | PlayStation TIM texture |
| TIM pack (count + `.tim` names) | `.tpk` | Named TIM container |
| Mostly printable text | `.txt` | Message / string table |
| Filename lists | `.lst` | Text lists of asset names |
| Other | `.bin` | Unknown binary |

---

## Archive kinds

| Kind | Detection | Behaviour |
|------|-----------|-----------|
| `gtarc` | Header `@(#)GT-ARC` | Multi-file archive; GT-ZIP decompress when `content_type = 0x8001` |
| `gtarc_compressed` | Mangled header (`@(#)GT-A` / `RC`) | Whole-archive compression (e.g. `CARINF.DAT`) |
| `gtzip_raw` | No ARC header | Single GT-ZIP stream (e.g. `GAMEFONT.DAT`) |

---

## TIM Pack format (COURSE / BG)

```
Offset  Size   Description
0x00    4      Number of TIMs (uint32 LE)
0x04    20×N   Directory:
                 16 bytes  Name (null-padded ASCII)
                  4 bytes  Offset of TIM data (uint32 LE)
…       …      TIM blobs at listed offsets
```

---

## Known GT1 archives

| Archive | Typical contents |
|---------|------------------|
| `COURSE.DAT` | Track TIM packs (`.tpk`), course models (`.gtps`) |
| `CAR.DAT` / `CARCADE.DAT` | Car textures (`.ctex`), car models (`.gtcar`) |
| `CARINF.DAT` | Compressed GT-ARC (car info) |
| `BG.DAT` | Background TIM packs, skyboxes (`.gtsky`) |
| `GAMEMENU.DAT` / `PITMENU.DAT` | Menu TIM textures |
| `ARCADE.DAT` / `ARCADE2.DAT` | Arcade mode assets |
| `TITLE.DAT` | Title screen assets |
| `MENU_RAW.ARC` | Menu lists, nested ARCs, used-car data |
| `MESSAGES.DAT` | UI / race message strings |
| `SOUND.DAT` | Instrument and engine sound banks |
| `GAMEFONT.DAT` | Raw GT-ZIP font data |
| `MENU_IMG.ARC` / `MUSIC.DAT` | Large GT-ARC assets (open locally) |

---

## Requirements

- Python 3.8+
- [Pillow](https://python-pillow.org/) (Asset Viewer)

```bash
pip install Pillow
```

---

## Notes

- Extract keeps **original bytes** (only GT-ZIP decompression).
- Repack can rebuild `.tpk` files from `*_tims/` when present; otherwise packs files as extracted.
