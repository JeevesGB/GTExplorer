# CARINF.DAT

**Path:** `CARINF.DAT` (disc root)  
**Format:** Compressed GT-ARC (mangled `@(#)GT-A` / `RC` style header possible)

## Role

Car **information database**: performance SPEC records, part tables (brakes, gears, suspension, tyres, …), and string tables (maker, model, grade, aspiration, layout).

## GTExplorer

Opened via the **Car Database** canvas for browsing and light editing of tables; joins SPEC rows to part codes where possible.

## Notes

- SPEC records are fixed-size binary rows (dense fields: power, torque, weight, dimensions, gear ratios, etc.).
- Part tables use short codes that embed the car code for joining.
