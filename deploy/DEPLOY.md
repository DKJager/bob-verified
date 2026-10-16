# Deploying the Bob Verified Dashboard

The dashboard serves a read-only HTML summary of a finished `bobverified` run
and exposes a **Re-verify now** button.  The page is read-only except for that
button, which re-runs the stored verification commands against the fetched
target checkout and never calls an AI model.

## Steps

1. **Copy the repository** to the server:

   ```bash
   git clone <repo-url> /srv/bob-verified/app
   cd /srv/bob-verified/app
   ```

2. **Copy the finished run directory** (the evidence folder produced by a
   `bobverified` run) to the server:

   ```bash
   cp -r /local/path/to/run /srv/bob-verified/run
   ```

3. **Create the target virtual environment** (used by the Re-verify action) and
   fetch the target so the re-verify button has a real checkout to verify.  The
   run directory's `target.json` records where the checkout should live:

   ```bash
   python3.12 -m venv /srv/bob-verified/target-venv
   source /srv/bob-verified/target-venv/bin/activate
   bash /srv/bob-verified/app/scripts/fetch_target.sh /srv/bob-verified/run
   deactivate
   ```

   `TARGET_VENV` in the systemd unit points the dashboard at this venv.
   The `reverify` directory inside the run directory stores the timestamped
   results written by the re-verify action.

4. **Install the systemd unit**:

   ```bash
   sudo cp /srv/bob-verified/app/deploy/bob-verified-dashboard.service \
           /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo useradd --system --no-create-home bobverified
   sudo chown -R bobverified /srv/bob-verified/run
   sudo systemctl enable --now bob-verified-dashboard
   ```

5. **Put a reverse proxy in front on port 443** and forward to port 8080.

   *nginx example* (add to your server block):

   ```nginx
   location / {
       proxy_pass http://127.0.0.1:8080;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
   }
   ```

   For a cloud load balancer, configure it to forward HTTPS (443) to the
   instance on port 8080 (`--port 8080`).

6. **Check it**:
   - Open the dashboard URL in a browser.
   - Press **Re-verify now** and watch the timestamped log that appears beneath
     the button.  It shows the result of re-running the stored `--run` directory
     checks with no AI model call.

---

## Docker alternative

Build the image from the repository root:

```bash
docker build -f deploy/Dockerfile -t bob-verified-dashboard .
```

Run it, mounting the run directory **read-write** at `/data/run` (the re-verify
action saves its log there) and publishing port 8080:

```bash
docker run --rm \
  -v /srv/bob-verified/run:/data/run:rw \
  -p 8080:8080 \
  bob-verified-dashboard
```

Then place your reverse proxy or cloud load balancer in front on port 443 as
described in step 5 above.

> **No secrets:** do not pass `BOB_API_KEY` or any other credential to the
> container.  The dashboard and the re-verify action use only the files in the
> run directory and the `TARGET_VENV` virtual environment.
