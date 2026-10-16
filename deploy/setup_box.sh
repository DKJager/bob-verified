#!/bin/bash
# Set up the dashboard on a fresh Ubuntu 24.04 server. Run as root:  bash setup_box.sh <public hostname>
# Expects these files in /tmp/bv: app.tar.gz (the repository), run.tar.gz (the run folder),
# simple_api_modernized.bundle (the modernized demo target as a git bundle).
# The host needs no credentials of any kind: nothing here reads or writes a secret.
set -euo pipefail
HOST=${1:?usage: setup_box.sh <public hostname>}
B=/srv/bob-verified
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3-venv nginx certbot python3-certbot-nginx curl
id bobverified >/dev/null 2>&1 || useradd --system --home-dir "$B" --shell /usr/sbin/nologin bobverified
mkdir -p "$B/app" "$B/run" "$B/work"
tar -xzf /tmp/bv/app.tar.gz -C "$B/app"
tar -xzf /tmp/bv/run.tar.gz -C "$B/run"
rm -rf "$B/work/simple_api"
git clone -q -b modernize /tmp/bv/simple_api_modernized.bundle "$B/work/simple_api"
python3 -m venv "$B/target-venv"
"$B/target-venv/bin/pip" install -q -r "$B/work/simple_api/requirements.txt" pytest
chown -R bobverified:bobverified "$B"
install -m 644 "$B/app/deploy/bob-verified-dashboard.service" /etc/systemd/system/bob-verified-dashboard.service
sed "s/HOSTNAME/$HOST/" "$B/app/deploy/nginx-bob-verified.conf" > /etc/nginx/sites-available/bob-verified
ln -sf /etc/nginx/sites-available/bob-verified /etc/nginx/sites-enabled/bob-verified
rm -f /etc/nginx/sites-enabled/default
systemctl daemon-reload
systemctl enable --now bob-verified-dashboard
nginx -t
systemctl reload nginx
certbot --nginx -d "$HOST" --non-interactive --agree-tos --register-unsafely-without-email --redirect
systemctl is-active bob-verified-dashboard nginx
