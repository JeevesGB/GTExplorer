GTExplorer — tools folder
=========================

Place third-party binaries here. GTExplorer does NOT ship mkpsxiso;
you download it yourself and drop the files in this folder.

mkpsxiso (disc rebuild)
-----------------------
1. Download the latest release for your OS:
   https://github.com/Lameguy64/mkpsxiso/releases/latest

2. Unzip and copy into this folder so you have something like:

   tools/
     mkpsxiso.exe      (Windows)  or  mkpsxiso  (Linux/macOS)
     dumpsxiso.exe    (Windows)  or  dumpsxiso
     (any DLLs that came with the release)

3. In GTExplorer: File → Setup / Workspace…
   - Enable "Set up mkpsxiso…"
   - Executable should auto-fill to this folder; browse if needed
   - Set Disc project XML + Disc files folder from your dumpsxiso dump
   - Set ISO/BIN output folder for built images

4. One-time disc dump (example, run from a terminal):

   dumpsxiso -x "D:\GT1\disc_files" -s "D:\GT1\gt1.xml" "D:\ISOs\GT1.bin"

   Then point Setup at gt1.xml and disc_files.

Do not commit large binaries to git if you prefer; each user drops
their own copy of the official release into tools/.
