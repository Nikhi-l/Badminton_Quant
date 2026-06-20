"""Guard upstream TrackNetV3's Video_IterableDataset against the empty-frame_list
boundary crash: it runs one phantom iteration past the end when the clip's frame
count is an exact multiple of seq_len, then indexes an empty list -> IndexError.
Device-independent (bites the GPU worker too). Idempotent. Run inside the image.
"""
from pathlib import Path

P = Path("/opt/TrackNetV3/dataset.py")
ANCHOR = ("            # Form a sequence\n"
          "            data_idx = [(0, i) for i in range(start_f_id, end_f_id)]")
MARKER = "# baddy: video ended on a window boundary"

if not P.exists():
    print("dataset.py not found (INSTALL_TRACKNET=0?) — nothing to patch")
else:
    src = P.read_text()
    if MARKER in src:
        print("dataset.py: already patched")
    elif ANCHOR in src:
        guard = ("            " + MARKER + " -> no frames left, stop.\n"
                 "            if not frame_list:\n"
                 "                break\n\n" + ANCHOR)
        P.write_text(src.replace(ANCHOR, guard, 1))
        print("dataset.py: patched")
    else:
        raise SystemExit("dataset.py: boundary-guard anchor not found (upstream changed?)")
