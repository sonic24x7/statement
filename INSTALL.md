# RMBC CCTV Statement Generator — Installation Guide
### Ubuntu 24.04 LTS · Password Authentication Only · Reboot Resistant

---

## What You Need Before Starting

- `cctv_app.py` — the Flask application (on your Windows Desktop)
- Your Anthropic API key (starts with `sk-ant-...`) — have it ready
- SSH access to the server via Tailscale or local IP
- Server user: `rmbc` with sudo privileges

> **Important:** Password authentication only. No SSH keys. No `-i` flags. No root SCP.

---

## Key Facts About This Install

| Detail | Value |
|--------|-------|
| App directory | `/opt/CCTV_Statement/` |
| Python environment | `/opt/CCTV_Statement/venv/` |
| API key file | `/opt/CCTV_Statement/.env` |
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

Enter your password when prompted. Then switch to root:

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

> **Do NOT use `pip3 install` directly on Ubuntu 24.04 — it will fail.**
> Always use a virtual environment.

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

Should say **2297**. If lower, the transfer cut short — repeat the SCP.

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

Verify Flask installed correctly:

```
/opt/CCTV_Statement/venv/bin/python3 -c "import flask; print(flask.__version__)"
```

Should print a version number with no errors.

---

## Step 6b — (Optional) Install Ollama for Local AI

> **Skip this step if using Anthropic.** Use this instead if you want no data to leave the building — removes any third-party data processing concern.

```
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3
```

Verify Ollama is running:

```
curl http://localhost:11434
```

Should return `Ollama is running`.

Then in your `.env` file (Step 7), set:

```
AI_BACKEND=ollama
OLLAMA_MODEL=llama3
```

And **remove or leave blank** the `ANTHROPIC_API_KEY` line — it is not needed.

**Minimum server spec for Ollama:**

| Resource | Minimum |
|----------|---------|
| RAM | 16 GB |
| CPU | 4-core modern |
| GPU | Not required (faster if present) |

---

## Step 7 — Create the Environment File

> **This is the correct method for Ubuntu 24.04.**
> Do NOT put the key directly in the systemd service file using Environment= — it will not be passed to the process reliably.
> Always use EnvironmentFile= pointing to a .env file.

```
nano /opt/CCTV_Statement/.env
```

Add these lines — replace the values with your actual credentials:

```
AI_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-YOUR_FULL_KEY_HERE
GMAIL_USER=rmbcvms@gmail.com
GMAIL_APP_PASSWORD=your-16-char-app-password
```

> **Note:** `GMAIL_USER` and `GMAIL_APP_PASSWORD` are required for the email feature (v6.1+). If you leave them blank the app will still run and generate statements, but the "Send by Email" button will return an error.
>
> **Ollama (local AI):** To run without sending data to Anthropic, see **Step 6b** below.

Save with `Ctrl+X` then `Y` then `Enter`

Lock down the file so only root can read it:

```
chmod 600 /opt/CCTV_Statement/.env
```

---

## Step 8 — Test It Runs Manually First

```
cd /opt/CCTV_Statement
set -a && source /opt/CCTV_Statement/.env && set +a
/opt/CCTV_Statement/venv/bin/python3 cctv_app.py
```

> **Why `set -a`?** Without it, `source` sets the variables only as shell variables — they are **not** exported to child processes. Python would read them as empty. `set -a` turns on auto-export so every variable set by `source` is automatically exported.

You should see:

```
🎥 RMBC CCTV Statement Generator
   http://0.0.0.0:5000
 * Running on http://0.0.0.0:5000
```

Test in browser: `http://100.69.64.113:5000`

If it loads, press `Ctrl+C` to stop it before continuing.

---

## Step 9 — Open the Firewall Port

> This step is required. Port 5000 is not open by default on Ubuntu 24.04.

```
ufw allow 5000/tcp
ufw reload
ufw status
```

You should see `5000/tcp ALLOW Anywhere` in the list.

---

## Step 10 — Create the Systemd Service

> We use `sudo bash -c` because writing to `/etc/systemd/system/` requires root.
> EnvironmentFile= is used — this is the only reliable way to pass the API key to the process on Ubuntu 24.04.

```
sudo bash -c 'cat > /etc/systemd/system/cctv-statement.service << EOF
[Unit]
Description=RMBC CCTV Witness Statement Generator
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/CCTV_Statement
EnvironmentFile=/opt/CCTV_Statement/.env
ExecStart=/opt/CCTV_Statement/venv/bin/python3 /opt/CCTV_Statement/cctv_app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF'
```

---

## Step 11 — Enable and Start the Service

```
systemctl daemon-reload
systemctl enable cctv-statement
systemctl start cctv-statement
systemctl status cctv-statement
```

Should show **active (running)** in green.

The `enable` command ensures the service **automatically starts on every reboot** — no manual intervention needed.

---

## Step 12 — Verify the API Key Is Reaching the Process

```
sudo cat /proc/$(pgrep -f cctv_app)/environ | tr '\0' '\n' | grep ANTHROPIC
```

Should print your full API key. If blank — the `.env` file has a problem. Check Step 7.

---

## Step 13 — Reboot Test

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

When you have a new `cctv_app.py`, from Windows:

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
| Verify API key live | `sudo cat /proc/$(pgrep -f cctv_app)/environ \| tr '\0' '\n' \| grep ANTHROPIC` |
| Check line count | `wc -l /opt/CCTV_Statement/cctv_app.py` |
| Check routes | `grep -n "@app.route" /opt/CCTV_Statement/cctv_app.py` |
| Test Flask import | `/opt/CCTV_Statement/venv/bin/python3 -c "import flask; print(flask.__version__)"` |

---

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `No module named 'flask'` | pip installed to wrong Python | Use venv pip: `/opt/CCTV_Statement/venv/bin/pip install flask python-docx requests` |
| `Permission denied` writing service file | Not using sudo | Use `sudo bash -c 'cat > ...'` as shown in Step 10 |
| Browser refuses to connect | Port 5000 not open | Run `ufw allow 5000/tcp && ufw reload` |
| 500 error generating statement | API key not reaching process | Check `.env` file exists, run Step 12 to verify |
| API key blank in process | Used `Environment=` instead of `EnvironmentFile=` | Rewrite service file using `EnvironmentFile=` as shown in Step 10 |
| 401 Unauthorized from Anthropic | Wrong or expired API key | Test key with curl, regenerate at console.anthropic.com if needed |
| 500 error with Ollama | Ollama not running or model not pulled | Run `ollama serve` and `ollama pull llama3` |
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

On a development or test server this file will not exist — the bookmark list will be empty. This is expected. The app will still load and run correctly. Bookmarks will appear once pointed at a real Nx Witness installation.

---

## What's Next — Docker Streamlined Install

Once the script is finalised, the install process will be streamlined using Docker so that deploying to any server takes just a couple of commands — no manual dependency management required.

---

## Uninstall Guide

### Remove the CCTV Statement app

```bash
sudo systemctl stop cctv-statement
sudo systemctl disable cctv-statement
sudo rm /etc/systemd/system/cctv-statement.service
sudo systemctl daemon-reload
sudo rm -rf /opt/CCTV_Statement
```

### Remove Ollama and all downloaded models

```bash
sudo systemctl stop ollama
sudo systemctl disable ollama
sudo rm /etc/systemd/system/ollama.service
sudo systemctl daemon-reload
sudo rm -rf /usr/local/bin/ollama
sudo rm -rf /root/.ollama
```

> **This deletes all downloaded models** including llama3.1 (~4.7GB). If you want to keep Ollama but just remove a specific model:
> ```
> ollama rm llama3.1
> ```

### Remove Python virtual environment only

```bash
sudo rm -rf /opt/CCTV_Statement/venv
```

### Firewall — close port 5000

```bash
ufw delete allow 5000/tcp
ufw reload
```
