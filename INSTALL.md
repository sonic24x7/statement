# RMBC CCTV Statement Generator — Installation Guide
### Ubuntu 24.04 LTS · Password Authentication Only · Reboot Resistant

---

## What You Need Before Starting

- `cctv_app.py` — the Flask application (on your Windows Desktop)
- Your Anthropic API key (starts with `sk-ant-...`) — have it ready, do not paste it here
- SSH access to the server via Tailscale or local IP
- Server user: `rmbc` with sudo privileges

> **Important:** This guide uses password authentication only. No SSH keys. No `-i` flags. No root SCP.

---

## Key Facts About This Install

| Detail | Value |
|--------|-------|
| App directory | `/opt/CCTV_Statement/` |
| Python environment | `/opt/CCTV_Statement/venv/` |
| Service name | `cctv-statement` |
| Port | `5000` |
| Runs as | `root` (via systemd) |
| Auto-starts on reboot | Yes — systemd handles this |

---

## Step 1 — Connect to the Server

From your Windows machine (PowerShell or Command Prompt):

```
ssh rmbc@100.69.64.113
```

Enter your password when prompted.

Then switch to root:

```
sudo -i
```

Enter your password again when prompted.

---

## Step 2 — Update the Server

```
apt update && apt upgrade -y
```

This may take a few minutes on a fresh server.

---

## Step 3 — Install Python and Virtual Environment Support

> **Do NOT use `pip3 install` directly on Ubuntu 24.04 — it will fail or conflict.**
> Always use a virtual environment. This is the correct method.

```
apt install -y python3 python3-pip python3-venv
```

---

## Step 4 — Create the App Directory

```
mkdir -p /opt/CCTV_Statement
```

---

## Step 5 — Upload the App File

Open a **second terminal window** on your Windows machine (keep SSH open in the first).

Run this SCP command — no `-i` flag, password only:

```
scp C:\Users\Dane\Desktop\cctv_app.py rmbc@100.69.64.113:/home/rmbc/cctv_app.py
```

Enter your password when prompted.

Then back in your SSH terminal, move it into place:

```
mv /home/rmbc/cctv_app.py /opt/CCTV_Statement/cctv_app.py
```

Verify it arrived correctly:

```
wc -l /opt/CCTV_Statement/cctv_app.py
```

Should say **1007**. If lower, the transfer cut short — repeat the SCP.

Check routes are present:

```
grep -n "@app.route" /opt/CCTV_Statement/cctv_app.py
```

Should show 5 routes: `/login` `/logout` `/` `/form` `/server-time`

---

## Step 6 — Create the Virtual Environment and Install Dependencies

```
python3 -m venv /opt/CCTV_Statement/venv
/opt/CCTV_Statement/venv/bin/pip install flask python-docx requests
```

Verify Flask is installed:

```
/opt/CCTV_Statement/venv/bin/python3 -c "import flask; print(flask.__version__)"
```

Should print a version number with no errors.

---

## Step 7 — Test It Runs Manually First

```
cd /opt/CCTV_Statement
/opt/CCTV_Statement/venv/bin/python3 cctv_app.py
```

You should see:

```
🎥 RMBC CCTV Statement Generator
   http://0.0.0.0:5000
 * Running on http://0.0.0.0:5000
```

Test in browser: `http://100.69.64.113:5000`

If it loads, press `Ctrl+C` to stop it before continuing.

---

## Step 8 — Open the Firewall Port

> This step is required. Port 5000 is not open by default.

```
ufw allow 5000/tcp
ufw reload
ufw status
```

You should see `5000/tcp ALLOW Anywhere` in the list.

---

## Step 9 — Create the Systemd Service

> We use `sudo bash -c` because writing to `/etc/systemd/system/` requires root.
> Replace `YOUR_API_KEY` with your actual `sk-ant-...` key before running.

```
sudo bash -c 'cat > /etc/systemd/system/cctv-statement.service << EOF
[Unit]
Description=RMBC CCTV Witness Statement Generator
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/CCTV_Statement
Environment="ANTHROPIC_API_KEY=YOUR_API_KEY"
ExecStart=/opt/CCTV_Statement/venv/bin/python3 /opt/CCTV_Statement/cctv_app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF'
```

---

## Step 10 — Enable and Start the Service

```
systemctl daemon-reload
systemctl enable cctv-statement
systemctl start cctv-statement
systemctl status cctv-statement
```

Should show **active (running)** in green.

The `enable` command ensures the service **automatically starts on every reboot or restart** — no manual intervention needed.

---

## Step 11 — Reboot Test

```
reboot
```

Wait 30 seconds, then open your browser:

```
http://100.69.64.113:5000
```

If it loads without you doing anything — the install is complete and reboot resistant.

---

## Accessing the App

| URL | Use |
|-----|-----|
| `http://100.69.64.113:5000` | Tailscale (remote) |
| `http://192.168.60.50:5000` | Local network |

Login credentials:

| Username | Password |
|----------|----------|
| dane.plant | Cctv2026! |
| admin | Admin2026! |

---

## Updating the App (Future Versions)

When you have a new `cctv_app.py`:

From Windows — upload it:

```
scp C:\Users\Dane\Desktop\cctv_app.py rmbc@100.69.64.113:/home/rmbc/cctv_app.py
```

Then in SSH:

```
sudo mv /home/rmbc/cctv_app.py /opt/CCTV_Statement/cctv_app.py
sudo systemctl restart cctv-statement
sudo systemctl status cctv-statement
```

---

## Useful Maintenance Commands

| Task | Command |
|------|---------|
| Watch live logs | `journalctl -u cctv-statement -f` |
| Restart service | `systemctl restart cctv-statement` |
| Stop service | `systemctl stop cctv-statement` |
| Check status | `systemctl status cctv-statement` |
| Check port open | `ss -tlnp \| grep 5000` |
| Check firewall | `ufw status` |
| Check line count | `wc -l /opt/CCTV_Statement/cctv_app.py` |
| Check routes | `grep -n "@app.route" /opt/CCTV_Statement/cctv_app.py` |
| Test Flask import | `/opt/CCTV_Statement/venv/bin/python3 -c "import flask; print(flask.__version__)"` |

---

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `No module named 'flask'` | pip installed to wrong Python | Reinstall using venv pip: `/opt/CCTV_Statement/venv/bin/pip install flask python-docx requests` |
| `Permission denied` writing service file | Not using sudo | Use `sudo bash -c 'cat > ...'` as shown in Step 9 |
| Browser refuses to connect | Port 5000 not open | Run `ufw allow 5000/tcp && ufw reload` |
| Service shows `failed` | API key not set or wrong path | Check `Environment=` line in service file and that ExecStart points to venv python |
| Service not starting after reboot | Not enabled | Run `systemctl enable cctv-statement` |

---

## Note on NVR Clock Feature

The server time comparison uses the **Linux server's system clock** — not the Nx Witness NVR clock.

To test with a deliberately wrong time:

```
timedatectl set-ntp false
date -s "14:50:00"
```

To restore correct time:

```
timedatectl set-ntp true
```

---

## Note on the SQLite Database

The app reads bookmarks from:

```
/opt/networkoptix/mediaserver/var/mserver.sqlite
```

On a development or test server this file will not exist — the bookmark list will be empty. This is expected. The app will still load and run correctly. Bookmarks will appear once the server is pointed at a real Nx Witness installation.

---

## What's Next — Docker Streamlined Install

Once the script is finalised, the install process will be streamlined using Docker so that deploying to any server is a minimal number of commands. This will make deploying to multiple servers significantly faster with no manual dependency management required.
