#!/usr/bin/env bash
# Runs ON the VM. Expects /tmp/baddy.tar.gz to be present.
set -euo pipefail

APT="sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 -y -qq"
echo ">> [vm] waiting for boot-time apt locks, then installing packages"
$APT update
$APT install ffmpeg python3-venv fonts-dejavu-core caddy >/dev/null

echo ">> [vm] unpacking code"
sudo mkdir -p /opt/baddy
sudo tar xzf /tmp/baddy.tar.gz -C /opt/baddy
cd /opt/baddy
[ -d venv ] || sudo python3 -m venv venv
sudo ./venv/bin/pip install -q --upgrade pip
sudo ./venv/bin/pip install -q -r requirements.txt

echo ">> [vm] installing on-device vision deps (YOLO11 pose; CPU torch)"
# CPU-only torch wheel (the default index pulls the ~2GB CUDA build).
sudo ./venv/bin/pip install -q torch torchvision \
  --index-url https://download.pytorch.org/whl/cpu || \
  echo ">> [vm] WARNING: torch install failed; on-device pose disabled (shuttle still uses Runpod GPU)"
sudo ./venv/bin/pip install -q -r requirements-vision.txt || \
  echo ">> [vm] WARNING: vision deps install failed; on-device pose disabled"
sudo mkdir -p /opt/baddy/data/models

echo ">> [vm] configuring service user and permissions"
sudo useradd -r -s /usr/sbin/nologin baddy 2>/dev/null || true
sudo mkdir -p /opt/baddy/data
sudo chown -R baddy:baddy /opt/baddy

echo ">> [vm] installing systemd unit + caddy config"
sudo cp /opt/baddy/deploy/baddy.service /etc/systemd/system/baddy.service
sudo cp /opt/baddy/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl daemon-reload
sudo systemctl enable baddy >/dev/null 2>&1
sudo systemctl restart baddy
sudo systemctl reload caddy 2>/dev/null || sudo systemctl restart caddy
sleep 3
echo ">> [vm] service status:"
sudo systemctl --no-pager -l status baddy | head -5
sudo systemctl --no-pager -l status caddy | head -5
curl -s --max-time 5 http://127.0.0.1:8000/api/health && echo " <- app healthy"
