# Detected file types

## Core / graphics / sound

| Magic / content | Ext | Description |
|-----------------|-----|-------------|
| `@(#)GT-PS` | `.ps` | Course / track model |
| `@(#)GT-CAR` | `.car` | Car model |
| `@(#)GT-CTEX` | `.tex` | Car texture set |
| `@(#)GT-SKY` | `.sky` | Skybox |
| `@(#)GT-ARC` | `.arc` | Nested GT-ARC |
| `@(#)USEDCAR` | `.usedcar` | Used-car data |
| `@(#)GTHTML` | `.gthtml` | GT HTML / menu script |
| `INST` | `.ins` | Sound instrument bank |
| `ENGN` | `.es` | Engine sound bank |
| `SEQG` | `.seq` | Sequence (music / timing) |
| `10 00 00 00` | `.tim` | PlayStation TIM texture |
| TIM pack (count + `.tim` names) | `.tpk` | Named TIM container |
| Mostly printable text | `.txt` | Message / string table |
| Filename lists | `.idx` / `.lst` | Asset name lists |
| Other | `.bin` | Unknown binary |

## Car / tuning part tables (mainly CARINF)

| Magic | Ext |
|-------|-----|
| `@(#)SPEC` | `.spec` |
| `@(#)COLOR` | `.color` |
| `@(#)EQUIP` | `.equip` |
| `@(#)TIRE` / `TIRECMP` / `TIRESIZ` | `.tire` / `.tirecmp` / `.tiresiz` |
| `@(#)BRAKE` / `BRKCTRL` | `.brake` / `.brkctrl` |
| `@(#)GEAR` / `CLUTCH` / `FLYWHEL` | `.gear` / `.clutch` / `.flywhel` |
| `@(#)SUSPENS` / `STABILZ` | `.suspens` / `.stabilz` |
| `@(#)TURBINE` / `NATUNE` / `MUFFLER` / … | matching |

When a **file list** is loaded, list names override these fallback extensions.

## TIM Pack format (COURSE / BG)

```
Offset  Size   Description
0x00    4      Number of TIMs (uint32 LE)
0x04    20×N   Directory:
                 16 bytes  Name (null-padded ASCII)
                  4 bytes  Offset of TIM data (uint32 LE)
…       …      TIM blobs at listed offsets
```

## Archive kinds

| Kind | Detection | Behaviour |
|------|-----------|-----------|
| `gtarc` | `@(#)GT-ARC` | Multi-file; GT-ZIP when `content_type = 0x8001` |
| `gtarc_compressed` | Mangled `@(#)GT-A` / `RC` | Whole-archive compression |
| `gtzip_raw` | No ARC header | Single GT-ZIP stream |
