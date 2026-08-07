# Usage

## Open an archive

**Open…** — select a `.DAT` / `.ARC`.

Large files show status + progress while reading and identifying types.

### Nested archives

Select a **Nested GT-ARC** entry and use **Open Nested ARC** (or double-click) to browse inside it.

## File names

Use the **Names** dropdown (or **Load list…**) to apply a region list.

- Bundled lists: `src/gtarcexplorer/filelists/`
- If no list matches and the archive contains an embedded name list of the same length, those names are used automatically.

## Extract

| Action | Behaviour |
|--------|-----------|
| **Extract All** | Every entry → folder |
| **Extract Selected** | Only selected rows |

A `manifest.txt` is written for future lossless repack.

### Expand TIM packs

Enable **Also extract TIMs from packs**.

```
000.tpk
000_tims/
  refrect.tim
  circuit.tim
  …
```

The original `.tpk` is always kept.

### Expand INST / ENGN

Enable **Also extract samples from INST/ENGN**.  
Banks stay intact; samples can be written for editing.

## Asset Viewer

| Content | What you get |
|---------|----------------|
| **TIM** | Texture preview, zoom / fit |
| **TIM pack** | List of TIMs; click to view |
| **GT-CTEX** | 4bpp car texture; **Pal ±** / **CLUT ±** |
| **GT-PS** | Course model info / point cloud |

Supported TIM formats: 4-bit + CLUT, 8-bit + CLUT, 16-bit, 24-bit.

## Preview tab

Headers, hex, text, filename lists, GTHTML strings, and structured car-part tables (`SPEC`, `COLOR`, `EQUIP`, `TIRE`, …).
