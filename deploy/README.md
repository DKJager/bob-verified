# Putting the dashboard on a live URL (AWS)

Status: the demo is deployed at https://18-216-235-168.sslip.io/ using exactly the steps and files below (deploy/setup_box.sh automates steps 5 to 8). The host has no credentials of any kind: no instance profile, no cloud keys, one deploy key used only for the installation, and a service user without a login shell. Re-verify is limited to one run at a time, 6 runs per hour per visitor and a 120 second hard stop (flags --exclusive-reverify, --rate-limit-per-hour, --reverify-timeout of the dashboard).

This gives the hackathon submission a live, working URL. Nothing here has been run for you; the steps are exact so they can be followed in about 20 minutes. DEPLOY.md in this folder has the longer reference.

## What the page needs

- The repository (standard library only, Python 3.12).
- The finished run folder (docs/run in this repository contains the published copy).
- For the "Re-verify now" button to do real work: the modernized demo target on the same machine and its virtual environment. Without them the page still shows the run, but re-verify will report an error.

## Owner steps (AWS console)

1. EC2, Launch instance: Ubuntu Server 24.04 LTS, type t3.small, a key pair you hold, 20 GB disk. Security group: allow inbound TCP 22 from your address, TCP 80 and 443 from anywhere.
2. Allocate an Elastic IP and associate it with the instance.
3. In DNS, create an A record, for example bob-verified.<your domain>, pointing to the Elastic IP.
4. Send the Elastic IP and the key pair name to the session, which does the rest (steps 5 to 8) over SSH, or follow steps 5 to 8 yourself.

## Server steps

5. `sudo apt-get update && sudo apt-get install -y git python3.12 python3.12-venv nginx certbot python3-certbot-nginx`
6. `sudo useradd -m -s /usr/sbin/nologin bobverified; sudo mkdir -p /srv/bob-verified; sudo chown bobverified /srv/bob-verified`
7. As that user: clone the repository into /srv/bob-verified/app; copy docs/run to /srv/bob-verified/run; create `python3.12 -m venv /srv/bob-verified/target-venv`; fetch the target with `bash scripts/fetch_target.sh targets/simple_api.json /srv/bob-verified/work/simple_api`; then bring in the modernized tree with `git -C /srv/bob-verified/work/simple_api pull <bundle file> modernize` (the bundle simple_api_modernized.bundle is delivered by the session, not stored in the public repository), then `/srv/bob-verified/target-venv/bin/pip install -r /srv/bob-verified/work/simple_api/requirements.txt pytest`.
8. Install deploy/bob-verified-dashboard.service into /etc/systemd/system, then `sudo systemctl daemon-reload && sudo systemctl enable --now bob-verified-dashboard`. Add an nginx site that proxies / to 127.0.0.1:8080 and run `sudo certbot --nginx -d bob-verified.<your domain>`.

## Check

Open https://bob-verified.<your domain>, see three accepted steps and MATCH, press "Re-verify now" and wait about two minutes: a new timestamped log appears with every check ACCEPT.

## Cost

One small instance, a few dollars a month. Stop the instance after judging.
