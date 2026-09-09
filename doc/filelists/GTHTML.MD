[← Back to index](index.md)
# GTHTML Documentation

Based on reverse-engineering all **36** pages in `MENU/MENU_HTM.ARC` (PAL-era disc layout). This is **not** HTML; it is a compact binary **menu page / hotspot script** used by the GT1 front-end.

---

## 1. Role in the game

GTHTML files describe **one menu screen**:

- Which **background TIM** to draw
- **Clickable regions** (rectangles) and what they do
- Links to **other pages** (`.HTM`) or **engine actions** (`LIST_GARAGE`, `SHOW_SPEC`, …)

They live in `MENU/MENU_HTM.ARC`, named by `MENU/HTMLS.IDX`. Backgrounds come from `MENU/MENU_IMG.ARC` / `IMAGES.IDX` (e.g. `home.htm` → `HOME.tim`).

---

## 2. File layout (overview)

```
Offset  Size   Description
──────  ─────  ───────────────────────────────────────────
0x00    12     Magic: "@(#)GTHTML\0\0"
0x0C     4     Padding / reserved (always 00 00 00 00 in MENU_HTM)
0x10    …      Body (commands)
EOF-3    3     End marker: AF 8D 00
```

Total size is typically **60–350 bytes**. No embedded images or text paragraphs—only structure and names.

---

## 3. Header

```
40 28 23 29 47 54 48 54 4D 4C 00 00   ; "@(#)GTHTML\0\0"
00 00 00 00                           ; reserved
```

Detection: `data.startswith(b"@(#)GTHTML")`.

---

## 4. Body command stream

Body starts at **offset 0x10**. It is a sequence of records. Known records:

### 4.1 Page background (`0x0D 0x02`) — always first

```
0D 02
<u8 len> <len bytes ASCII TIM name>
2F                                      ; '/'
<u8 len> <len bytes ASCII mode>         ; always "bgmap" in MENU_HTM
```

**Example** (`home.htm`):

```
0D 02 08 48 4F 4D 45 2E 74 69 6D 2F 05 62 67 6D 61 70
        |  H  O  M  E  .  t  i  m  /  |  b  g  m  a  p
```

| Field | Meaning |
|--------|---------|
| TIM name | Background texture, e.g. `HOME.tim`, `TRD.tim` (matched case-insensitively to `MENU_IMG`) |
| `/` | Literal separator |
| Mode | Always `bgmap` in this archive (background map mode) |

---

### 4.2 Hotspot — type 1 (`0x05 0x01`)

Rectangular click target in **screen coordinates**.

```
05 01
04          ; parameter count (always 4 for x0,y0,x1,y1)
00          ; padding / flags (always 00 here)
<u16 le x0> <u16 le y0> <u16 le x1> <u16 le y1>
<u8 len> <len bytes ASCII target>
```

**Coordinates:** corners of a box in PS1 display space (origin top-left; full screen often **640×480**, e.g. title page uses `(0,0)–(640,480)` = `00 00 00 00 80 02 E0 01`).

**Example** (`home.htm` → Garage):

```
05 01 04 00 A4 00 FC 00 08 01 60 01 0A 47 41 52 41 47 45 2E 48 54 4D
              x0=164 y0=252 x1=264 y1=352     | GARAGE.HTM
```

**Target string** is either:

| Kind | Examples | Meaning |
|------|----------|---------|
| Page link | `MAP.HTM`, `HOME.HTM`, `TRD-BRAKE.HTM` | Navigate to another GTHTML page |
| Action | `LIST_GARAGE`, `SHOW_SPEC`, `BUY`, `ARCADE` | Call game logic (not a file) |
| Submenu id | `menu1`…`menu4`, `CHAMP1`… | Local / mode-specific ids |

Names are **ASCII**, length-prefixed (max practical length ≤ 64). Case is as stored (`MAP.HTM`, `HOME.tim`).

---

### 4.3 Widget / compact control — type 2 (`0x05 0x02`)

Smaller control, often sidebar / icon-style navigation (exact engine semantics partly inferred).

```
05 02
03          ; parameter count (always 3 in MENU_HTM)
00          ; padding
<u16 le a> <u16 le b> <u16 le c>
<u8 len> <len bytes ASCII target>
```

**Example** (many pages — “back” control toward parent):

```
05 02 03 00 30 00 64 00 19 00 07 48 4F 4D 45 2E 48 54 4D
              48     100    25       HOME.HTM
```

| Field | Typical use (inferred) |
|--------|-------------------------|
| `a`, `b` | Position (e.g. x=48, y=100) |
| `c` | Size / icon id / hit padding (e.g. 25) |
| target | Page or action (`HOME.HTM`, `CARINFO_BACK`, `CHANGE_CAR`) |

Same target string rules as hotspots. Common on pages that share the left **Map / Home** chrome.

---

### 4.4 End marker

```
AF 8D 00
```

Always present at end of MENU_HTM pages. Treat as EOF for the command stream.

---

## 5. String encoding

All names use the same scheme:

```
<u8 length N> <N bytes ASCII>
```

- No null terminator inside the string
- Characters are printable ASCII (letters, digits, `.`, `_`, `-`)
- TIM names often end in `.tim`; pages in `.HTM`
- Actions have **no** extension (`LIST_PARTS`, `REPLAY_DEMO`)

---

## 6. Coordinate system

- **u16 little-endian**
- Screen space roughly **0…640** × **0…480** (NTSC/PAL menu rendering)
- Hotspot type 1: axis-aligned box `(x0,y0)–(x1,y1)`
- Type 2: point-like / compact hit area, not a full box in the file

Overlays for tools should draw type-1 rects; type-2 can be shown as a marker at `(a,b)` with radius from `c` or a fixed pad.

---

## 7. Semantic target catalogue (MENU_HTM)

### Page links (subset)

`HOME.HTM`, `MAP.HTM`, `GTF.HTM`, `GARAGE.HTM`, `TOYOTA.HTM`, `TRD.HTM`, `GAMEMODE.HTM`, `GTF-CHAMP.HTM`, `GTF-LICENCE.HTM`, `GTF-SPECIAL*.HTM`, `TOYOTA-NEW.HTM`, `TOYOTA-USED*.HTM`, `TRD-*.HTM`, …

### Engine actions (subset)

| Action | Role |
|--------|------|
| `LIST_GARAGE` | Show owned cars |
| `LIST_CAR_TOYOTA` | Toyota car list |
| `LIST_PARTS` | Parts list for TRD category |
| `SHOW_SPEC` | Spec sheet |
| `CHANGE_CAR` | Change car in garage |
| `BUY` / `USED_SELL` / `MOREINFO` | Dealership flows |
| `ARCADE` / `REPLAY_DEMO` | Mode launch |
| `SINGLE_RACE` / `FREE_RUN` / `VS` | GT mode race types |
| `CHAMP1`…`CHAMP11` | Championship entries |
| `LICENCE1`…`LICENCE8` | Licence tests |
| `menu1`…`menu4` | Garage2 submenu rows |
| `CARINFO_BACK` / `CARINFO_RIDE` | Garage info chrome |

Rule of thumb: if the target contains `.HTM`, it is a **page**; otherwise it is an **action id**.

---

## 8. Full page example (`title.htm`, 63 bytes)

```
0000  40 28 23 29 47 54 48 54 4D 4C 00 00   @(#)GTHTML\0\0
000C  00 00 00 00                           reserved
0010  0D 02                                 background cmd
0012  09 "TITLE.tim" 2F 05 "bgmap"          TIM + mode
0022  05 01 04 00
      00 00  00 00  80 02  E0 01            rect (0,0)-(640,480)
      0C "GAMEMODE.HTM"                     entire screen → gamemode
003D  AF 8D 00                              end
```

Meaning: show `TITLE.tim`; any click goes to `GAMEMODE.HTM`.

---

## 9. Full page example (`home.htm`)

| Element | Target | Notes |
|---------|--------|--------|
| Background | `HOME.tim` / `bgmap` | |
| Widget | `MAP.HTM` | vals `(48,100,25)` — side control |
| Hotspot | `MAP.HTM` | small rect ~`(31,150)–(63,183)` |
| Hotspot | `HOME.HTM` | ~`(31,233)–(63,266)` |
| Hotspot | `HOME.HTM` | larger middle rect |
| Hotspot | `GARAGE.HTM` | `(164,252)–(264,352)` |

---

## 10. Relationship to other MENU files

```
MENU/
  HTMLS.IDX      ← ordered list of .htm names (36 lines)
  MENU_HTM.ARC   ← GTHTML binaries in that order
  IMAGES.IDX     ← ordered list of .tim names (40 lines)
  MENU_IMG.ARC   ← TIM binaries in that order
  MENU_SND.ARC   ← sounds (separate)
```

- GTHTML **does not** store image pixels; it only stores the **TIM file name**.
- Loader resolves `HOME.tim` via IDX / archive binding.
- Root disc `MENU_IMG.ARC` (large, 6 language packs) is a **different** asset set; the small `MENU/MENU_IMG.ARC` is what these pages use.

---

## 11. Editing implications

Safe, high-value edits:

1. **Retarget** — change length-prefixed string (same length, or rewrite record and shift tail).
2. **Swap background TIM name** — same length easiest (`HOME.tim` → other 8-char name); longer names require memmove of the body.
3. **Move hotspot** — rewrite the four `u16` values; keep `05 01 04 00` prefix.

Harder:

- Insert/delete records (must fix stream and file size; ARC in-place slot may not fit if larger).
- New pages (need new ARC entry + IDX line + matching TIM).

Preserve:

- Magic + 4 zero bytes
- Leading `0D 02` background block
- Trailing `AF 8D 00`
- `05 01` / `05 02` layouts unless the engine is fully re-verified

---

## 12. Unknown / open questions

| Topic | Status |
|--------|--------|
| Reserved dword at `0x0C` | Always zero in this ARC; purpose unknown |
| Meaning of `0x0D 0x02` opcode values | Fixed as “set background”; other opcodes not seen here |
| Type `0x02` fields `a,b,c` | Position + size/id inferred; not fully confirmed |
| Byte after count (`00`) | Always zero here; may be flags in other ARCs |
| Hit-test inclusion rules | Whether edges are inclusive unknown |
| Large menu GTHTML (root 1043-page set) | May share this format; not verified in this pass |

---

## 13. Minimal parser pseudocode

```
assert data[0:12] == "@(#)GTHTML\0\0"
i = 16
assert data[i:i+2] == 0x0D 0x02; i += 2
tim = read_pascal_string(data, i); i = after
assert data[i] == '/'; i += 1
mode = read_pascal_string(data, i); i = after

while i < len:
  if data[i:i+3] == AF 8D 00: break
  if data[i] == 0x05 and data[i+1] == 0x01:
    i += 2
    assert data[i] == 4; i += 1
    assert data[i] == 0; i += 1
    x0,y0,x1,y1 = u16le×4; i += 8
    target = read_pascal_string(data, i); i = after
    emit HOTSPOT(rect, target)
  elif data[i] == 0x05 and data[i+1] == 0x02:
    i += 2
    assert data[i] == 3; i += 1
    assert data[i] == 0; i += 1
    a,b,c = u16le×3; i += 6
    target = read_pascal_string(data, i); i = after
    emit WIDGET(a,b,c, target)
  else:
    error unknown opcode
```

---

## 14. Summary

GTHTML is a **tiny hotspot script**:

1. Header magic
2. Background TIM + `bgmap`
3. List of **hotspots** (rect + target) and **widgets** (compact control + target)
4. End marker `AF 8D 00`

Targets are either **other menu pages** or **hard-coded game actions**. For tooling, parsing to `{background, hotspots[], widgets[]}` is enough for preview, navigation graph, link retargeting, and TIM pairing—without treating the file as real HTML.

---

*Document generated from MENU/MENU_HTM.ARC analysis (36 pages).*

---

[← Back to index](index.md)