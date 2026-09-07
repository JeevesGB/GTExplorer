# SOUND.DAT

[← Back to index](index.md)

The game's audio bank. Top-level `.ins` (VAB instrument headers) and `.es` (engine/event sound definitions) files drive the sound engine, while 249 numbered `<n>_samples/` folders each hold one sound bank's raw waveform data as paired `.adpcm` (PlayStation ADPCM audio) and `.wav` files.

**4076** files · **249** subfolders · **5** file types

| Extension | Count | What it is |
|---|---|---|
| `.adpcm` | 1913 | PlayStation ADPCM — compressed audio sample. |
| `.wav` | 1913 | Uncompressed PCM audio sample. |
| `.es` | 246 | Engine/event sound definition. |
| `.ins` | 3 | VAB instrument header (sound engine patch data). |
| `.txt` | 1 | Plain-text index or manifest (GTExplorer metadata, not a game asset). |

## Structure

<details><summary><b>Files here (250)</b> — click to expand</summary>

- `003.es` → `248.es` (246 files)

Other files: `000.ins`, `001.ins`, `002.ins`, `manifest.txt`

</details>

<details><summary><code>000_samples/</code> → <code>248_samples/</code> &mdash; 249 folders</summary>

Each folder follows the same pattern. Example — contents of `000_samples/`:

**Files here (58):**

- `sample_000.adpcm` → `sample_028.adpcm` (29 files)
- `sample_000.wav` → `sample_028.wav` (29 files)

*(file count per folder ranges 8–122 across the 249 folders)*

</details>

---
[← Back to index](index.md)
