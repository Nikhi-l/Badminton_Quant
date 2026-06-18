#!/usr/bin/env bash
# Create (if needed) and deploy to the GCP VM. Run from the repo root:
#   bash deploy/deploy.sh
set -euo pipefail

ZONE="${ZONE:-us-central1-a}"
VM="${VM:-baddy-agent}"
MACHINE="${MACHINE:-e2-standard-4}"

if ! gcloud compute instances describe "$VM" --zone "$ZONE" >/dev/null 2>&1; then
  echo ">> creating VM $VM ($MACHINE) in $ZONE"
  gcloud compute instances create "$VM" \
    --zone "$ZONE" \
    --machine-type "$MACHINE" \
    --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
    --boot-disk-size 60GB --boot-disk-type pd-balanced \
    --tags http-server
  echo ">> waiting for SSH to come up"
  sleep 25
fi

if gcloud compute firewall-rules describe baddy-allow-http >/dev/null 2>&1; then
  gcloud compute firewall-rules update baddy-allow-http --allow tcp:80,tcp:443
else
  gcloud compute firewall-rules create baddy-allow-http \
    --allow tcp:80,tcp:443 --target-tags http-server --direction INGRESS
fi

echo ">> packaging code"
TAR=$(mktemp /tmp/baddy.XXXXXX.tar.gz)
tar czf "$TAR" --exclude .venv --exclude data --exclude __pycache__ \
  --exclude 'vendor/TrackNetV3/.git' --exclude '*.pyc' \
  --exclude 'runpod_worker/models/*.pt' --exclude 'runpod_worker/models/**/*.pt' \
  --exclude 'runpod_worker/models/*.pth' --exclude 'runpod_worker/models/**/*.pth' \
  app web requirements.txt requirements-vision.txt .env deploy scripts \
  runpod_worker vendor docs README.md

echo ">> pushing to VM"
for i in 1 2 3 4 5; do
  gcloud compute scp --zone "$ZONE" "$TAR" deploy/remote_setup.sh "$VM:/tmp/" && break
  echo "   ssh not ready yet, retrying ($i)"; sleep 15
done
mv "$TAR" /tmp/baddy_last_push.tar.gz 2>/dev/null || true
gcloud compute ssh "$VM" --zone "$ZONE" --command "mv /tmp/$(basename "$TAR") /tmp/baddy.tar.gz 2>/dev/null || true; bash /tmp/remote_setup.sh"

IP=$(gcloud compute instances describe "$VM" --zone "$ZONE" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
echo ">> deployed. checking health:"
sleep 2
curl -s --max-time 10 "http://$IP/api/health" && echo
echo ">> live at: http://$IP"
