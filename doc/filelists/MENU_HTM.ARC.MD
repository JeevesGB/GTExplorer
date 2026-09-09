# MENU/MENU_HTM.ARC

**Path:** `MENU/MENU_HTM.ARC`  
**Files:** 36  
**Format:** GT-ARC (`content_type` `0x8001`, GT-ZIP compressed entries)

## Role

GT-mode **menu page scripts** (GTHTML). Each entry is a small binary document describing one screen: background TIM name, clickable regions, and targets (other pages or engine actions).

This is **not** HTML text.

## Naming

Ordered by `MENU/HTMLS.IDX` (36 lines), for example:

- `title.htm`, `gamemode.htm`, `home.htm`, `map.htm`
- `garage.htm`, `garage2.htm`, `garage-info.htm`
- `gtf.htm`, `gtf-champ.htm`, `gtf-licence.htm`, `gtf-special*.htm`
- `toyota*.htm`, `trd*.htm`
- `loadsave.htm`, `option.htm`, `record.htm`, `theater.htm`

## Pairing

| This archive | Companion |
|---|---|
| Page script `home.htm` | Background `home.tim` in `MENU/MENU_IMG.ARC` |
| Name list | `MENU/HTMLS.IDX` |

## Format reference

See [GTHTML Format Documentation](GTHTML_Format_Documentation.md).

## Structure (summary)

```
@(#)GTHTML\0\0 + reserved
background: TIM name + "bgmap"
hotspots:  rect (x0,y0,x1,y1) + target string
widgets:   compact controls + target string
end:       AF 8D 00
```

Targets are either `.HTM` page links or action ids such as `LIST_GARAGE`, `SHOW_SPEC`, `LIST_PARTS`.
