# RMBC CCTV Statement Generator — Installation Guide

## Files needed
- `cctv_app.py` — the Flask application
- `cctv-statement.service` — systemd service file
- Your Anthropic API key (starts with `sk-ant-...`)

---

## Step 1 — Connect to the server

```
ssh -i "C:\Users\Dane\.ssh\id_ed25519" root@116.203.148.254
```

---

## Step 2 — Update server and install dependencies

```
apt update && apt upgrade -y
apt install -y python3 python3-pip
pip3 install flask python-docx requests --break-system-packages
```

---

## Step 3 — Create the app directory

```
mkdir -p /root/CCTV_Statement
```

---

## Step 4 — Copy files to the server

From your Windows machine (open a new terminal, not SSH):

```
scp -i "C:\Users\Dane\.ssh\id_ed25519" C:\Users\Dane\Desktop\cctv_app.py root@116.203.148.254:/root/CCTV_Statement/cctv_app.py
```

Verify it arrived correctly (back in SSH):
```
wc -l /root/CCTV_Statement/cctv_app.py
```
Should say **1007**. If lower, the transfer cut short — repeat the scp.

Also check routes are present:
```
grep -n "@app.route" /root/CCTV_Statement/cctv_app.py
```
Should show 5 routes: /login, /logout, /, /form, /server-time

---

## Step 5 — Set your Anthropic API key

```
echo 'export ANTHROPIC_API_KEY="sk-ant-YOURKEY"' >> ~/.bashrc
source ~/.bashrc
echo $ANTHROPIC_API_KEY
```

---

## Step 6 — Test it runs manually first

```
cd /root/CCTV_Statement
source ~/.bashrc
python3 cctv_app.py
```

You should see:
```
🎥 RMBC CCTV Statement Generator
   http://0.0.0.0:5000
 * Running on http://0.0.0.0:5000
```

Test in browser: `http://116.203.148.254:5000`

Press Ctrl+C to stop once confirmed working.

---

## Step 7 — Install as a permanent background service

Copy the service file to the server (from Windows terminal):
```
scp -i "C:\Users\Dane\.ssh\id_ed25519" C:\Users\Dane\Desktop\cctv-statement.service root@116.203.148.254:/etc/systemd/system/cctv-statement.service
```

Then in SSH, inject your API key into the service file:
```
KEY="sk-ant-YOURKEY"
sed -i "s|PUT_YOUR_KEY_HERE|$KEY|" /etc/systemd/system/cctv-statement.service
```

Enable and start:
```
systemctl daemon-reload
systemctl enable cctv-statement
systemctl start cctv-statement
systemctl status cctv-statement
```

Should show **active (running)**.

---

## Step 8 — Open the firewall port (if needed)

If port 5000 is blocked:
```
ufw allow 5000/tcp
ufw reload
```

Or if using iptables:
```
iptables -A INPUT -p tcp --dport 5000 -j ACCEPT
```

---

## Access the app

```
http://116.203.148.254:5000
```

Logins:
| Username   | Password   |
|------------|------------|
| dane.plant | Cctv2026!  |
| admin      | Admin2026! |

---

## Useful maintenance commands

| Task | Command |
|------|---------|
| Watch live logs | `journalctl -u cctv-statement -f` |
| Restart service | `systemctl restart cctv-statement` |
| Stop service | `systemctl stop cctv-statement` |
| Check status | `systemctl status cctv-statement` |
| Test manually | `cd /root/CCTV_Statement && source ~/.bashrc && python3 cctv_app.py` |
| Check API key set | `echo $ANTHROPIC_API_KEY` |
| Check line count | `wc -l /root/CCTV_Statement/cctv_app.py` |
| Check routes | `grep -n "@app.route" /root/CCTV_Statement/cctv_app.py` |

---

## Note on NVR clock feature

The server time comparison uses the **Linux server's system clock** — not the Nx Witness NVR clock.

To test with a wrong time:
```
timedatectl set-ntp false
date -s "14:50:00"
```

To restore:
```
timedatectl set-ntp true
```

---

## Note on the SQLite database

The app reads bookmarks from:
```
/opt/networkoptix/mediaserver/var/mserver.sqlite
```

On this test server that file won't exist — the bookmark list will be empty. That's expected. The app will still load and run — you just won't see any bookmarks until it's pointed at a real Nx Witness installation.
