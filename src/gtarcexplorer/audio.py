"""PSX SPU-ADPCM decoding and INST/ENGN sample-bank helpers."""
import struct
from pathlib import Path
# PSX SPU-ADPCM 

_XA_TABLE = [(0, 0), (60, 0), (115, -52), (98, -55), (122, -60)]


def decode_adpcm_frame(frame: bytes, s1: int, s2: int):
    shift = frame[0] & 0x0F
    filt = min((frame[0] >> 4) & 0x0F, 4)
    f0, f1 = _XA_TABLE[filt]
    out = []
    for i in range(2, 16):
        b = frame[i]
        for nibble in (b & 0x0F, b >> 4):
            if nibble & 8:
                nibble -= 16
            val = nibble << 12
            val >>= shift if shift < 13 else 15
            val = val + (s1 * f0 + s2 * f1) // 64
            val = max(-32768, min(32767, val))
            out.append(val)
            s2, s1 = s1, val
    return out, s1, s2


def decode_adpcm(data: bytes) -> list:
    pcm, s1, s2 = [], 0, 0
    for off in range(0, len(data) - 15, 16):
        samples, s1, s2 = decode_adpcm_frame(data[off:off + 16], s1, s2)
        pcm.extend(samples)
        if data[off + 1] & 1:
            break
    return pcm


def write_wav(path, pcm, rate=22050):
    import wave
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", s) for s in pcm))


def parse_sample_bank(data: bytes):
    """
    Parse INST/ENGN bank → list of (start, end) sample offsets.
    Returns (sample_start, samples_list) or ([], []) on failure.
    """
    if len(data) < 0x20 or data[:4] not in (b"INST", b"ENGN"):
        return 0, []
    meta_size = struct.unpack_from("<I", data, 0x08)[0]
    hint = min(meta_size, len(data))

    def plausible(off):
        if off + 16 > len(data):
            return False
        fr = data[off:off + 16]
        if fr[2:16] == b"\x00" * 14:
            return False
        shift, filt = fr[0] & 0x0F, (fr[0] >> 4) & 0x0F
        return filt <= 4 and shift <= 12

    sample_start = hint
    for off in range(max(0x20, hint - 0x20), min(len(data) - 64, hint + 0x100), 16):
        if sum(plausible(off + i * 16) for i in range(4)) >= 3:
            sample_start = off
            break

    samples = []
    cur = sample_start
    pos = sample_start
    while pos + 16 <= len(data):
        flags = data[pos + 1]
        pos += 16
        if flags & 1:
            if pos - cur >= 32:
                samples.append((cur, pos))
            cur = pos
    if pos - cur >= 32 and cur < len(data):
        samples.append((cur, len(data)))
    return sample_start, samples


def expand_sample_bank(data: bytes, out_dir, rate=22050) -> int:
    """Write sample_XXX.wav (+ .adpcm) into out_dir. Returns count."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _, samples = parse_sample_bank(data)
    for i, (s, e) in enumerate(samples):
        blob = data[s:e]
        pcm = decode_adpcm(blob)
        write_wav(out_dir / f"sample_{i:03d}.wav", pcm, rate)
        (out_dir / f"sample_{i:03d}.adpcm").write_bytes(blob)
    return len(samples)


