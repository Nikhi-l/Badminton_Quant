#!/usr/bin/env python3
"""Make the vendored TrackNetV3 repo device-agnostic so it runs on-device.

Upstream hardcodes `.cuda()` and `torch.load()` without map_location, which
crashes on any machine without an NVIDIA GPU. We rewrite inference files
(predict.py, test.py) to honor a resolved device: CUDA when available, else
MPS (Apple Silicon), else CPU — controllable via TRACKNET_DEVICE. Idempotent.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "vendor" / "TrackNetV3"
TARGETS = ["predict.py", "test.py"]
MARKER = "# >>> baddy device shim"
DATASET_MARKER = "# baddy: video ended on a window boundary"

SHIM = f'''{MARKER}
import os as _os


def _baddy_device():
    d = _os.environ.get("TRACKNET_DEVICE", "").strip().lower()
    if d:
        return torch.device(d)
    if torch.cuda.is_available():
        return torch.device("cuda")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


_DEV = _baddy_device()
# <<< baddy device shim
'''


def patch(path: Path) -> bool:
    src = path.read_text()
    if MARKER in src:
        return False  # already patched

    # 1. Insert the shim right after the first `import torch` line.
    lines = src.splitlines(keepends=True)
    out, inserted = [], False
    for line in lines:
        out.append(line)
        if not inserted and re.match(r"^\s*import torch\s*$", line):
            out.append("\n" + SHIM + "\n")
            inserted = True
    if not inserted:
        raise RuntimeError(f"no `import torch` line found in {path.name}")
    text = "".join(out)

    # 2. .cuda()  ->  .to(_DEV)
    text = text.replace(".cuda()", ".to(_DEV)")

    # 3. torch.load(X)  ->  torch.load(X, map_location=_DEV)   (only single-arg calls)
    text = re.sub(
        r"torch\.load\(([^,\)]+)\)",
        r"torch.load(\1, map_location=_DEV)",
        text,
    )

    path.write_text(text)
    return True


def patch_dataset() -> bool:
    """Guard Video_IterableDataset against the empty-frame_list boundary crash.

    Upstream's __iter__ runs one phantom iteration past the end when the clip's
    frame count is an exact multiple of seq_len, then does `frame_list[-1]` on an
    empty list -> IndexError. We stop the loop when no frames remain. Idempotent.
    """
    p = REPO / "dataset.py"
    if not p.exists():
        print("warning: dataset.py missing", file=sys.stderr)
        return False
    src = p.read_text()
    if DATASET_MARKER in src:
        return False
    anchor = ("            # Form a sequence\n"
              "            data_idx = [(0, i) for i in range(start_f_id, end_f_id)]")
    if anchor not in src:
        raise RuntimeError("dataset.py: __iter__ anchor not found (upstream changed?)")
    guard = ("            " + DATASET_MARKER + " -> no frames left, stop.\n"
             "            if not frame_list:\n"
             "                break\n\n" + anchor)
    p.write_text(src.replace(anchor, guard, 1))
    return True


def main() -> int:
    if not REPO.exists():
        print(f"TrackNetV3 repo not found at {REPO}", file=sys.stderr)
        return 1
    changed = []
    for name in TARGETS:
        p = REPO / name
        if not p.exists():
            print(f"warning: {name} missing", file=sys.stderr)
            continue
        if patch(p):
            changed.append(name)
    if patch_dataset():
        changed.append("dataset.py")
    print(f"patched: {changed or 'nothing (already device-agnostic)'}")
    # Verify no bare .cuda() remain in inference files.
    leftover = []
    for name in TARGETS:
        p = REPO / name
        if p.exists() and ".cuda()" in p.read_text():
            leftover.append(name)
    if leftover:
        print(f"ERROR: bare .cuda() still in {leftover}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
