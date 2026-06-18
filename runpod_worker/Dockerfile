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

COPY models /models

ENV TRACKNET_REPO=/opt/TrackNetV3 \
    TRACKNET_TRACKNET_FILE=/models/tracknet/TrackNet_best.pt

COPY handler.py /worker/handler.py

CMD ["python", "-u", "/worker/handler.py"]
