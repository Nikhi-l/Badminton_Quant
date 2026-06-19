ARG BASE_IMAGE=pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
FROM ${BASE_IMAGE}

ARG INSTALL_TRACKNET=0
ARG TRACKNET_REPO_URL=https://github.com/qaz812345/TrackNetV3.git

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /worker

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ffmpeg git libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /worker/requirements.txt
RUN pip install --upgrade pip && pip install -r /worker/requirements.txt

RUN if [ "$INSTALL_TRACKNET" = "1" ]; then \
      git clone --depth 1 "$TRACKNET_REPO_URL" /opt/TrackNetV3; \
    fi

# Patch upstream's Video_IterableDataset: it runs one phantom iteration past the
# end when frame_count is an exact multiple of seq_len, then indexes an empty
# list -> IndexError. Guard it. Idempotent; device-independent (bites GPU too).
RUN if [ -f /opt/TrackNetV3/dataset.py ]; then python - <<'PY'; fi
from pathlib import Path
p = Path("/opt/TrackNetV3/dataset.py")
src = p.read_text()
anchor = ("            # Form a sequence\n"
          "            data_idx = [(0, i) for i in range(start_f_id, end_f_id)]")
marker = "# baddy: video ended on a window boundary"
if marker not in src and anchor in src:
    guard = ("            " + marker + " -> no frames left, stop.\n"
             "            if not frame_list:\n"
             "                break\n\n" + anchor)
    p.write_text(src.replace(anchor, guard, 1))
    print("dataset.py patched")
else:
    print("dataset.py: already patched or anchor missing")
PY

COPY models /models

ENV TRACKNET_REPO=/opt/TrackNetV3 \
    TRACKNET_TRACKNET_FILE=/models/tracknet/TrackNet_best.pt

COPY handler.py /worker/handler.py

CMD ["python", "-u", "/worker/handler.py"]
