"""
cctv_app.py  (v5 — speed & convenience update)
================================================
Changes from v4:
- Bookmark creator field — dropdown pre-filled with logged-in user, changeable
- Complete Later is now DEFAULT handover option
- Complete Later generates proper blanks in statement + storage narrative
- DEMS leaves blanks if details not yet known
- Auto-fill today's date on all date fields
- Exhibit reference auto-suggested from operator initials
- Work address field removed (witness_base dropdown covers it)
- Handover location pre-filled with Rawmarsh when In Person selected
- debug=False restored, traceback shown in browser on error

Install:
    pip3 install flask python-docx requests --break-system-packages

Run:
    source ~/.bashrc && python3 cctv_app.py

Access:
    http://192.168.150.50:5000
"""

import os, io, sqlite3, hashlib, secrets, requests
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, session, send_file
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

NX_SQLITE      = "/opt/networkoptix/mediaserver/var/mserver.sqlite"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-6"
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

USERS = {
    "dane.plant": {"hash": hashlib.sha256(b"Cctv2026!").hexdigest(),  "name": "Dane Plant",    "role": "CCTV Engineer",  "initials": "DP"},
    "admin":      {"hash": hashlib.sha256(b"Admin2026!").hexdigest(), "name": "Administrator", "role": "CCTV Manager",   "initials": "AD"},
}

LOCATIONS = [
    "Rawmarsh Police Station, Green Lane, Rawmarsh, Rotherham, S62 6JU",
    "Riverside House, Main Street, Rotherham, S60 1AE",
]

# ── Auth ──────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def check_password(username, password):
    user = USERS.get(username)
    if not user: return False
    return user["hash"] == hashlib.sha256(password.encode()).hexdigest()

# ── SQLite ────────────────────────────────────

def get_bookmarks():
    try:
        con = sqlite3.connect(NX_SQLITE)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT record_id, start_time, duration, name, description, created FROM bookmarks WHERE duration > 0 ORDER BY start_time DESC LIMIT 50")
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        for r in rows:
            s = datetime.fromtimestamp(r["start_time"] / 1000, tz=timezone.utc)
            e = datetime.fromtimestamp((r["start_time"] + r["duration"]) / 1000, tz=timezone.utc)
            d = r["duration"] / 1000
            r["start_fmt"]    = s.strftime("%d/%m/%Y %H:%M:%S")
            r["end_fmt"]      = e.strftime("%d/%m/%Y %H:%M:%S")
            r["duration_fmt"] = f"{int(d//60)}m {int(d%60)}s"
        return rows
    except Exception as e:
        print(f"SQLite error: {e}"); return []

def get_bookmark(record_id):
    try:
        con = sqlite3.connect(NX_SQLITE)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT record_id, hex(guid) as guid, start_time, duration, name, description, created FROM bookmarks WHERE record_id=?", (record_id,))
        r = dict(cur.fetchone()); con.close()
        s = datetime.fromtimestamp(r["start_time"] / 1000, tz=timezone.utc)
        e = datetime.fromtimestamp((r["start_time"] + r["duration"]) / 1000, tz=timezone.utc)
        d = r["duration"] / 1000
        r["start_dt"] = s; r["end_dt"] = e
        r["start_fmt"]    = s.strftime("%d/%m/%Y %H:%M:%S")
        r["end_fmt"]      = e.strftime("%d/%m/%Y %H:%M:%S")
        hours = int(d // 3600)
        mins  = int((d % 3600) // 60)
        secs  = int(d % 60)
        if hours > 0:
            r["duration_fmt"] = f"{hours} hours, {mins} minutes and {secs} seconds"
        else:
            r["duration_fmt"] = f"{mins} minutes and {secs} seconds"
        r["created_fmt"]  = datetime.fromtimestamp(r["created"]/1000, tz=timezone.utc).strftime("%H:%M:%S on %d/%m/%Y") if r.get("created") else "Unknown"
        r["created_time"] = datetime.fromtimestamp(r["created"]/1000, tz=timezone.utc).strftime("%H:%M:%S") if r.get("created") else ""
        r["created_date"] = datetime.fromtimestamp(r["created"]/1000, tz=timezone.utc).strftime("%d/%m/%Y") if r.get("created") else ""
        return r
    except Exception as e:
        print(f"SQLite error: {e}"); return None

# ── Claude prompt ─────────────────────────────

def generate_statement(bm, form, download_time):

    # Reference line
    ref_parts = []
    if form.get("crime_name"):   ref_parts.append(form["crime_name"])
    if form.get("crime_number"): ref_parts.append(f"crime reference {form['crime_number']}")
    if form.get("foi_ref"):      ref_parts.append(f"FOI reference {form['foi_ref']}")
    ref_line = " / ".join(ref_parts) if ref_parts else None

    # Bookmark creator
    bookmark_creator = form.get("bookmark_creator", "").strip()
    witness_name_val = form.get("witness_name", "").strip()
    if not bookmark_creator or bookmark_creator == witness_name_val:
        creator_phrase = "I"
    else:
        creator_phrase = bookmark_creator

    # Clock narrative
    clock_date      = form.get("clock_check_date", download_time.strftime("%d/%m/%Y"))
    bt_time         = form.get("bt_clock_time", "")
    nvr_time        = form.get("nvr_clock_time", "")
    clock_diff      = form.get("clock_difference", "")
    clock_fast_slow = form.get("clock_fast_slow", "fast")

    if form.get("clock_checked") == "yes" and bt_time and nvr_time:
        if clock_fast_slow == "accurate":
            clock_conclusion = "showing the system time to be correct."
        elif clock_fast_slow == "fast":
            clock_conclusion = f"showing the system time to be approximately {clock_diff} fast."
        else:
            clock_conclusion = f"showing the system time to be approximately {clock_diff} slow."
        clock_para = (
            f"On {clock_date} I checked the NVR system clock against the BT Speaking Clock. "
            f"At {bt_time} on the BT Speaking Clock, the NVR system displayed {nvr_time}, "
            f"{clock_conclusion}"
        )
    else:
        clock_para = (
            "I was unable to verify the NVR system clock against the BT Speaking Clock at the time "
            "of this statement. The investigating officer should treat all timestamps as approximate "
            "and confirm NTP synchronisation status with the CCTV team."
        )

    # Export
    export_date = form.get("export_date", download_time.strftime("%d/%m/%Y"))
    export_time = form.get("export_time", download_time.strftime("%H:%M:%S"))

    # Export, storage and handover
    exhibit_ref   = form.get("exhibit_ref", "DCP1")
    media_type    = form.get("media_type", "DVD disc")
    is_electronic = media_type in ("Wasabi Cloud Storage", "South Yorkshire Police DEMS Portal")
    secure_store  = "Rawmarsh Police Station, Green Lane, Rawmarsh, Rotherham"

    export_para = (
        f"On {export_date} I exported the bookmarked footage from the Nx Witness system. "
        f"The footage was exported in MP4 format and saved to the following transferable media: {media_type}. "
        f"The footage was assigned exhibit reference {exhibit_ref}."
    )

    if not is_electronic:
        storage_para = (
            f"Exhibit {exhibit_ref} was placed into secure storage at {secure_store}, "
            f"awaiting collection by or handover to the investigating officer."
        )
    else:
        eu_date  = form.get("electronic_date", "").strip() or "______________________"
        eu_time  = form.get("electronic_time", "").strip() or "______________________"
        eu_by    = form.get("electronic_by", "").strip() or "______________________"
        eu_recip = form.get("electronic_recipient", "").strip() or "______________________"
        eu_ref   = form.get("electronic_ref", "").strip() or "______________________"
        storage_para = (
            f"The footage was transferred electronically via {media_type}.\n"
            f"Electronic Transfer Details:\n"
            f"Date of upload/transfer: {eu_date}\n"
            f"Time of upload/transfer: {eu_time}\n"
            f"Uploaded by: {eu_by}\n"
            f"Recipient / access provided to: {eu_recip}\n"
            f"Reference / job number: {eu_ref}"
        )

    handover_type = form.get("handover_type", "blank")
    if handover_type == "person":
        officer_name   = form.get("officer_name", "").strip() or "______________________"
        officer_number = form.get("officer_number", "").strip() or "______________________"
        h_location     = form.get("handover_location", "").strip() or "______________________"
        h_date         = form.get("handover_date", "").strip() or "______________________"
        h_time         = form.get("handover_time", "").strip() or "______________________"
        handover = (f"I handed exhibit {exhibit_ref} to {officer_name}, "
                    f"collar number {officer_number}, at {h_location} "
                    f"on {h_date} at {h_time}.")
    else:
        handover = (
            f"Handover details to be completed when exhibit is collected:\n"
            f"Officer name: ______________________\n"
            f"Collar / warrant number: ______________________\n"
            f"Date of handover: ______________________\n"
            f"Time of handover: ______________________\n"
            f"Location of handover: ______________________"
        )

    prompt = f"""You are producing a short, factual MG11 technical CCTV witness statement for a CCTV engineer at Rotherham Metropolitan Borough Council.

STRICT RULES:
- Plain, professional English — NOT overly formal or legalistic
- Maximum 7 short paragraphs, NO headings or titles between paragraphs
- First person, past tense
- The engineer does NOT describe what happened in the footage — technical witness only
- Use the EXACT wording provided below for system description, bookmark creation, clock check and handover — do not rephrase
- Do NOT add bold text, section labels, or any headings — plain flowing paragraphs only
- End with the Section 9 CJA 1967 declaration

STRUCTURE:
Para 1 — Who I am, my role, where I am currently based, purpose of this statement{f' in relation to: {ref_line}' if ref_line else ''}
Para 2 — The CCTV system and camera (USE VERBATIM TEXT BELOW)
Para 3 — How the footage was identified; who created the bookmark (USE VERBATIM BOOKMARK TEXT BELOW)
Para 4 — Clock check (USE VERBATIM TEXT BELOW)
Para 5 — Export and storage (USE VERBATIM EXPORT & STORAGE TEXT BELOW — reproduce exactly)
Para 6 — Handover / custody (USE VERBATIM HANDOVER TEXT BELOW — reproduce exactly, blanks as underscores)
Para 7 — Section 9 CJA 1967 declaration

=== WITNESS ===
Name: {form.get('witness_name')}
Role: {form.get('witness_role')}
Organisation: Rotherham Metropolitan Borough Council
Currently based at: {form.get('witness_base')}
Contact: {form.get('witness_contact')}
Date of statement: {form.get('statement_date')}

=== INCIDENT ===
Start: {bm.get('start_fmt')}
End: {bm.get('end_fmt')}
Duration: {bm.get('duration_fmt')}
Bookmark name: {bm.get('name')}
Bookmark created: {bm.get('created_fmt')}
=== EXPORT & STORAGE — USE VERBATIM, REPRODUCE EXACTLY ===
{export_para}

{storage_para}

=== SYSTEM DESCRIPTION — VERBATIM ===
The CCTV edge server located at 151 Dalton Lane, Rotherham is referenced as RMBC-150. The system is owned and operated by Rotherham Metropolitan Borough Council and comprises networked Hikvision cameras integrated with the Nx Witness video management system developed by Network Optix. At the time of review, the system was operating on software version 6.1.0.42176.
The footage referred to in this statement was captured by a Hikvision DS-2CD2387G2H-LIU camera (MAC address 54-8C-81-52-68-FE), which forms part of this system and is installed on {form.get('camera_location', 'lighting column number 5')} at the above location.

=== BOOKMARK CREATION — VERBATIM ===
{creator_phrase} created a bookmark within the system named "{bm.get('name')}" at {bm.get('created_time')} on {bm.get('created_date')} to preserve the relevant footage for export.

=== CLOCK CHECK — VERBATIM ===
{clock_para}

=== HANDOVER — VERBATIM (reproduce blanks as underscores, do not alter) ===
{handover}"""

    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 2000,
        "system": "You produce short factual UK MG11 technical CCTV witness statements. Plain professional English. Maximum 7 paragraphs. No footage description. Reproduce verbatim sections exactly as provided.",
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(CLAUDE_API_URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["content"][0]["text"]

# ── Word doc ──────────────────────────────────

def build_docx(statement_text, witness_name, bookmark_name, download_time):
    doc = Document()
    for sec in doc.sections:
        sec.top_margin = Inches(1); sec.bottom_margin = Inches(1)
        sec.left_margin = Inches(1.25); sec.right_margin = Inches(1.25)

    hp = doc.sections[0].header.paragraphs[0]
    hp.text = "OFFICIAL SENSITIVE — WITNESS STATEMENT — NOT FOR DISTRIBUTION"
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hp.runs[0].font.size = Pt(8)
    hp.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    fp = doc.sections[0].footer.paragraphs[0]
    fp.text = f"Generated: {download_time.strftime('%d/%m/%Y %H:%M')} | RMBC CCTV | Prepared by: {witness_name}"
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.runs[0].font.size = Pt(8)
    fp.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    # Title box
    t = doc.add_paragraph(); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("WITNESS STATEMENT"); r.bold = True; r.font.size = Pt(18)

    # Subtitle — acts on one line
    sub = doc.add_paragraph(); sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run("CJ Act 1967, s.9  ·  MC Act 1980, ss.5A(3)(a) and 5B  ·  Police and Criminal Evidence Act 1984")
    sr.italic = True; sr.font.size = Pt(9); sr.font.color.rgb = RGBColor(0x60, 0x60, 0x60)

    # Horizontal rule effect
    rule = doc.add_paragraph()
    rule.paragraph_format.space_before = Pt(2)
    rule.paragraph_format.space_after  = Pt(8)
    rule_run = rule.add_run("─" * 80)
    rule_run.font.size = Pt(8); rule_run.font.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)
    doc.add_paragraph()

    for line in statement_text.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("---"):
            doc.add_paragraph()
        elif line.startswith("### "):
            p = doc.add_paragraph(); r = p.add_run(line[4:])
            r.bold = True; r.font.size = Pt(11)
            r.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("| "):
            pass
        elif line.startswith("- ") or line.startswith("* "):
            p = doc.add_paragraph(style="List Bullet"); p.add_run(line[2:])
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            parts = line.split("**"); bold = False
            for part in parts:
                if part:
                    run = p.add_run(part); run.bold = bold; run.font.size = Pt(11)
                bold = not bold

    doc.add_paragraph(); doc.add_paragraph()
    s = doc.add_paragraph(); s.add_run("Signed: ").bold = True; s.add_run("_" * 50)
    d = doc.add_paragraph(); d.add_run("Date: ").bold = True; d.add_run("_" * 20)
    n = doc.add_paragraph(); n.add_run("Print Name: ").bold = True; n.add_run(witness_name.upper())

    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    return buf

# ── Templates ─────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html><head><title>RMBC CCTV — Sign In</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'DM Sans',sans-serif;background:#0d1117;min-height:100vh;display:flex;align-items:center;justify-content:center;}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:40px;width:420px;}
.logo{text-align:center;margin-bottom:32px;}
.logo .icon{font-size:40px;margin-bottom:12px;}
.logo h1{color:#e6edf3;font-size:22px;font-weight:700;}
.logo p{color:#8b949e;font-size:13px;margin-top:4px;}
.badge{background:#1f4068;color:#58a6ff;padding:3px 10px;border-radius:20px;font-size:11px;font-family:'DM Mono',monospace;display:inline-block;margin-bottom:16px;}
label{display:block;font-size:12px;color:#8b949e;font-weight:500;margin-bottom:6px;margin-top:16px;text-transform:uppercase;letter-spacing:0.5px;}
input{width:100%;padding:10px 14px;background:#0d1117;border:1px solid #30363d;border-radius:6px;font-size:14px;color:#e6edf3;font-family:'DM Sans',sans-serif;}
input:focus{outline:none;border-color:#58a6ff;}
button{width:100%;padding:12px;background:#238636;color:white;border:none;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer;margin-top:20px;font-family:'DM Sans',sans-serif;}
button:hover{background:#2ea043;}
.error{background:#3d1a1a;border:1px solid #f85149;color:#f85149;padding:10px 14px;border-radius:6px;margin-bottom:16px;font-size:13px;}
.footer{text-align:center;margin-top:20px;font-size:11px;color:#484f58;}
</style></head>
<body><div class="card">
<div class="logo">
    <div class="icon">🎥</div>
    <span class="badge">OFFICIAL SENSITIVE</span>
    <h1>RMBC CCTV</h1>
    <p>Witness Statement Generator</p>
</div>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="POST">
    <label>Username</label>
    <input type="text" name="username" placeholder="e.g. dane.plant" autofocus required>
    <label>Password</label>
    <input type="password" name="password" required>
    <button type="submit">Sign In →</button>
</form>
<div class="footer">Rotherham Metropolitan Borough Council · CCTV Evidence Unit</div>
</div></body></html>"""

BOOKMARKS_HTML = """<!DOCTYPE html>
<html><head><title>RMBC CCTV — Select Incident</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'DM Sans',sans-serif;background:#0d1117;min-height:100vh;color:#e6edf3;}
.topbar{background:#161b22;border-bottom:1px solid #30363d;padding:14px 30px;display:flex;justify-content:space-between;align-items:center;}
.topbar h1{font-size:16px;font-weight:700;}
.topbar .right{font-size:13px;color:#8b949e;}
.topbar a{color:#58a6ff;text-decoration:none;margin-left:16px;font-size:13px;}
.container{max-width:860px;margin:30px auto;padding:0 20px;}
.page-title{font-size:22px;font-weight:700;margin-bottom:6px;}
.page-sub{color:#8b949e;font-size:14px;margin-bottom:24px;}
.bm{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:20px 24px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;border-left:3px solid #238636;}
.bm:hover{border-left-color:#58a6ff;}
.bm-name{font-size:16px;font-weight:600;margin-bottom:4px;}
.bm-desc{font-size:13px;color:#8b949e;margin-bottom:6px;}
.bm-time{font-size:12px;color:#484f58;font-family:'DM Mono',monospace;}
.bm-right{text-align:right;min-width:160px;}
.dur{font-size:15px;font-weight:700;color:#58a6ff;margin-bottom:10px;font-family:'DM Mono',monospace;}
.btn{background:#238636;color:white;padding:8px 18px;border-radius:6px;font-size:13px;font-weight:600;text-decoration:none;display:inline-block;}
.btn:hover{background:#2ea043;}
.id-badge{background:#1f2937;color:#484f58;padding:2px 8px;border-radius:4px;font-size:11px;font-family:'DM Mono',monospace;margin-left:8px;}
.empty{text-align:center;padding:60px;color:#484f58;}
</style></head>
<body>
<div class="topbar">
    <h1>🎥 RMBC CCTV — Witness Statement Generator</h1>
    <div class="right">{{ session.user_name }} · {{ session.user_role }}<a href="/logout">Sign out</a></div>
</div>
<div class="container">
    <div class="page-title">Select Incident Bookmark</div>
    <div class="page-sub">Choose the Nx Witness bookmark to generate a statement for.</div>
    {% if bookmarks %}
        {% for bm in bookmarks %}
        <div class="bm">
            <div>
                <div class="bm-name">{{ bm.name or "(No name)" }}<span class="id-badge">ID {{ bm.record_id }}</span></div>
                <div class="bm-desc">{{ bm.description or "No description" }}</div>
                <div class="bm-time">{{ bm.start_fmt }} → {{ bm.end_fmt }}</div>
            </div>
            <div class="bm-right">
                <div class="dur">⏱ {{ bm.duration_fmt }}</div>
                <a href="/form/{{ bm.record_id }}" class="btn">Create Statement →</a>
            </div>
        </div>
        {% endfor %}
    {% else %}
        <div class="empty">No bookmarks found. Create one in Nx Witness first.</div>
    {% endif %}
</div></body></html>"""

FORM_HTML = """<!DOCTYPE html>
<html><head><title>RMBC CCTV — Statement Form</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'DM Sans',sans-serif;background:#0d1117;color:#e6edf3;}
.topbar{background:#161b22;border-bottom:1px solid #30363d;padding:14px 30px;display:flex;justify-content:space-between;align-items:center;}
.topbar h1{font-size:16px;font-weight:700;}
.topbar a{color:#58a6ff;text-decoration:none;font-size:13px;margin-left:16px;}
.container{max-width:820px;margin:30px auto;padding:0 20px 80px;}
.clock-box{background:#0d1117;border:1px solid #238636;border-radius:10px;padding:20px 24px;margin-bottom:24px;text-align:center;}
.clock-label{font-size:11px;color:#484f58;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;font-family:'DM Mono',monospace;}
.clock-date{font-size:17px;font-weight:600;color:#8b949e;margin-bottom:6px;font-family:'DM Mono',monospace;}
.clock-time{font-size:48px;font-weight:700;color:#58a6ff;letter-spacing:3px;font-family:'DM Mono',monospace;line-height:1;}
.clock-utc{font-size:11px;color:#484f58;margin-top:6px;font-family:'DM Mono',monospace;}
.incident{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:18px 22px;margin-bottom:20px;border-left:3px solid #58a6ff;}
.incident h3{font-size:13px;font-weight:700;color:#58a6ff;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;}
.incident p{font-size:13px;color:#8b949e;line-height:1.8;font-family:'DM Mono',monospace;}
.section{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:24px;margin-bottom:16px;}
.section h3{font-size:12px;font-weight:700;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:20px;padding-bottom:10px;border-bottom:1px solid #21262d;}
.green-section{background:#0a1f0a;border:1px solid #238636;border-radius:10px;padding:24px;margin-bottom:16px;}
.green-section h3{font-size:12px;font-weight:700;color:#3fb950;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;padding-bottom:10px;border-bottom:1px solid #1a3a1a;}
.hint{font-size:13px;color:#8b949e;margin-bottom:16px;line-height:1.5;}
label{display:block;font-size:12px;color:#8b949e;font-weight:500;margin-bottom:6px;margin-top:14px;text-transform:uppercase;letter-spacing:0.4px;}
label span{font-weight:400;text-transform:none;color:#484f58;margin-left:4px;}
input,select,textarea{width:100%;padding:10px 14px;background:#0d1117;border:1px solid #30363d;border-radius:6px;font-size:14px;color:#e6edf3;font-family:'DM Sans',sans-serif;}
input:focus,select:focus,textarea:focus{outline:none;border-color:#58a6ff;}
select option{background:#161b22;}
textarea{resize:vertical;min-height:80px;}
.row{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;}
.toggle-row{display:flex;align-items:center;gap:12px;margin-top:14px;}
.toggle-row input[type=checkbox]{width:auto;margin:0;}
.toggle-row label{margin:0;text-transform:none;font-size:13px;color:#8b949e;letter-spacing:0;}
.handover-opts{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:10px;}
.h-opt{border:1px solid #30363d;border-radius:8px;padding:14px;text-align:center;cursor:pointer;background:#0d1117;}
.h-opt:hover{border-color:#58a6ff;}
.h-opt.active{border-color:#238636;background:#0d2b0d;}
.h-opt input[type=radio]{display:none;}
.h-opt .icon{font-size:24px;margin-bottom:6px;}
.h-opt .title{font-size:13px;font-weight:600;color:#e6edf3;}
.h-opt .sub{font-size:11px;color:#484f58;margin-top:2px;}
.submit-btn{width:100%;padding:16px;background:#238636;color:white;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer;margin-top:10px;font-family:'DM Sans',sans-serif;}
.submit-btn:hover{background:#2ea043;}
.submit-btn:disabled{background:#21262d;color:#484f58;cursor:not-allowed;}
#loadingBox{display:none;background:#161b22;border:1px solid #30363d;border-radius:10px;padding:30px;text-align:center;margin-top:16px;}
#successBox{display:none;}
</style></head>
<body>
<div class="topbar">
    <h1>🎥 RMBC CCTV — Witness Statement</h1>
    <div><a href="/">← Bookmarks</a><a href="/logout">Sign out</a></div>
</div>
<div class="container">

    <div class="clock-box">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:center;">
            <div>
                <div class="clock-label">📅 UK Official Time (Browser)</div>
                <div class="clock-date" id="liveDate">Loading...</div>
                <div class="clock-time" id="liveTime">--:--:--</div>
                <div class="clock-utc" id="tzLabel">Loading...</div>
            </div>
            <div>
                <div class="clock-label">🖥️ NVR Server Time</div>
                <div class="clock-date" id="serverDate">Loading...</div>
                <div class="clock-time" style="font-size:36px;">
                    <span id="serverTimeHHMM">--:--:</span><span id="serverTimeSS" style="transition:color 1.5s ease;color:#58a6ff;">--</span>
                </div>
                <div class="clock-utc" id="serverDiff">Fetching...</div>

            </div>
        </div>
        <button type="button" onclick="useTheseTimesForClockCheck()" style="margin-top:16px;background:#238636;color:white;border:none;border-radius:6px;padding:10px 24px;font-size:13px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;">
            ✅ Use These Times for Clock Check
        </button>
    </div>

    <div class="incident">
        <h3>📋 Incident: {{ bm.name }}</h3>
        <p>
            Start &nbsp;&nbsp;&nbsp;&nbsp;: {{ bm.start_fmt }}<br>
            End &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;: {{ bm.end_fmt }}<br>
            Duration &nbsp;: {{ bm.duration_fmt }}<br>
            Bookmark created : {{ bm.created_fmt }}<br>
            Description : {{ bm.description or "None" }}
        </p>
    </div>

    <form id="stmtForm" method="POST">

        <!-- 1. YOUR DETAILS -->
        <div class="section">
            <h3>👤 Your Details</h3>
            <div class="row">
                <div><label>Full Name</label><input type="text" name="witness_name" value="{{ session.user_name }}" required></div>
                <div><label>Role / Job Title</label><input type="text" name="witness_role" value="{{ session.user_role }}" required></div>
            </div>
            <div class="row">
                <div><label>Organisation</label><input type="text" name="witness_org" value="Rotherham Metropolitan Borough Council" required></div>
                <div>
                    <label>Currently Based At</label>
                    <select name="witness_base" id="witnessBase">
                        {% for loc in locations %}
                        <option value="{{ loc }}">{{ loc }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>
            <div class="row">
                <div><label>Contact Number / Email</label><input type="text" name="witness_contact" required></div>
                <div><label>Date of Statement</label><input type="text" name="statement_date" id="statementDate" value="{{ today }}" required></div>
            </div>
        </div>

        <!-- 2. INCIDENT REFERENCE -->
        <div class="section">
            <h3>📁 Incident Reference</h3>
            <div class="toggle-row">
                <input type="checkbox" id="no_ref_check" onchange="toggleRef(this)">
                <label for="no_ref_check">No crime / incident reference available — skip this section</label>
            </div>
            <div id="ref_fields" style="margin-top:4px;">
                <div class="row">
                    <div><label>Incident / Crime Name</label><input type="text" name="crime_name" placeholder="e.g. Criminal Damage"></div>
                    <div><label>Crime Reference Number <span>(if known)</span></label><input type="text" name="crime_number" placeholder="e.g. 22/12345/24"></div>
                </div>
                <div><label>FOI Reference <span>(if applicable — leave blank if not)</span></label><input type="text" name="foi_ref" placeholder="Leave blank if not applicable"></div>
            </div>
        </div>

        <!-- 3. LOCATION & CAMERA -->
        <div class="section">
            <h3>📍 Location &amp; Camera</h3>
            <div class="row">
                <div><label>Incident Location / Site Name</label><input type="text" name="incident_location" placeholder="e.g. Johns Street, Eastwood, Rotherham" required></div>
                <div><label>Post / Mounting Position</label><input type="text" name="camera_location" placeholder="e.g. lighting column post 5" required></div>
            </div>
        </div>

        <!-- 4. BOOKMARK CREATOR -->
        <div class="section">
            <h3>🔖 Bookmark Creator</h3>
            <p class="hint" style="margin-top:0;">Who created the bookmark in Nx Witness? Usually the same person writing this statement, but not always.</p>
            <div class="row">
                <div>
                    <label>Bookmark Created By</label>
                    <select name="bookmark_creator" id="bookmarkCreator">
                        <option value="{{ session.user_name }}">{{ session.user_name }} (me)</option>
                        <option value="__other__">Someone else — enter name below</option>
                    </select>
                </div>
                <div id="other_creator_field" style="display:none;">
                    <label>Creator's Full Name</label>
                    <input type="text" name="bookmark_creator_other" placeholder="Full name of person who created the bookmark">
                </div>
            </div>
        </div>

        <!-- 5. BT SPEAKING CLOCK -->
        <div class="green-section">
            <h3>🕐 NVR Clock Check</h3>

            <div class="toggle-row">
                <input type="checkbox" id="clock_checked_box" name="clock_checked" value="yes">
                <label for="clock_checked_box">I have checked the NVR clock against the BT Speaking Clock</label>
            </div>
            <div id="clock_fields" style="display:none;margin-top:14px;">
                <div class="row">
                    <div><label>Date of Clock Check</label><input type="text" name="clock_check_date" id="clockDateField" value="{{ today }}"></div>
                    <div><label>BT Speaking Clock Time</label><input type="text" name="bt_clock_time" placeholder="e.g. 08:50:07"></div>
                </div>
                <div class="row">
                    <div><label>NVR System Displayed</label><input type="text" name="nvr_clock_time" placeholder="e.g. 08:45:07"></div>
                    <div><label>Difference</label><input type="text" name="clock_difference" placeholder="e.g. 5 minutes"></div>
                </div>
                <div>
                    <label>NVR Clock Is</label>
                    <select name="clock_fast_slow">
                        <option value="fast">Fast (NVR shows a later time than BT clock)</option>
                        <option value="slow">Slow (NVR shows an earlier time than BT clock)</option>
                        <option value="accurate">Accurate (within acceptable range)</option>
                    </select>
                </div>
            </div>
        </div>

        <!-- 6. EXPORT & CUSTODY -->
        <div class="section">
            <h3>🔗 Export &amp; Chain of Custody</h3>
            <div class="row">
                <div><label>Date Footage Exported</label><input type="text" name="export_date" id="exportDateField" value="{{ today }}"></div>
                <div><label>Time Footage Exported</label><input type="text" name="export_time" id="exportTimeField" placeholder="e.g. 09:30:00"></div>
            </div>
            <div class="row">
                <div><label>Exhibit Reference</label><input type="text" name="exhibit_ref" id="exhibitRef" value="{{ initials }}1" required></div>
                <div>
                    <label>Transferable Media Used</label>
                    <select name="media_type" id="mediaTypeSelect" onchange="toggleElectronic(this.value)">
                        <option value="DVD disc">DVD disc</option>
                        <option value="USB device">USB device</option>
                        <option value="Wasabi Cloud Storage">Wasabi Cloud Storage</option>
                        <option value="South Yorkshire Police DEMS Portal">South Yorkshire Police DEMS Portal</option>
                    </select>
                </div>
            </div>
            <div id="electronic_fields" style="display:none;margin-top:14px;background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px;">
                <div style="font-size:12px;color:#58a6ff;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px;">📡 Electronic Transfer Details</div>
                <div class="row">
                    <div><label>Date of Upload/Transfer</label><input type="text" name="electronic_date" placeholder="e.g. 01/03/2026"></div>
                    <div><label>Time of Upload/Transfer</label><input type="text" name="electronic_time" placeholder="e.g. 09:30"></div>
                </div>
                <div><label>Uploaded By</label><input type="text" name="electronic_by" value="{{ session.user_name }}" placeholder="Full name of person who uploaded"></div>
                <div><label>Recipient / Access Provided To</label><input type="text" name="electronic_recipient" placeholder="e.g. DS Smith, South Yorkshire Police"></div>
                <div><label>Reference / Job Number <span>(if applicable)</span></label><input type="text" name="electronic_ref" placeholder="Leave blank if not applicable"></div>
            </div>

        </div>

        <!-- 7. HANDOVER -->
        <div class="section">
            <h3>🤝 Handover Method</h3>
            <div class="handover-opts">
                <div class="h-opt" id="opt_person" onclick="setHandover('person')">
                    <input type="radio" name="handover_type" value="person">
                    <div class="icon">👮</div>
                    <div class="title">In Person</div>
                    <div class="sub">Handed to an officer</div>
                </div>
                <div class="h-opt" id="opt_dems" onclick="setHandover('dems')">
                    <input type="radio" name="handover_type" value="dems">
                    <div class="icon">💻</div>
                    <div class="title">DEMS Upload</div>
                    <div class="sub">SYP Digital Evidence System</div>
                </div>
                <div class="h-opt active" id="opt_blank" onclick="setHandover('blank')">
                    <input type="radio" name="handover_type" value="blank" checked>
                    <div class="icon">📦</div>
                    <div class="title">Stored — Complete Later</div>
                    <div class="sub">DVD in secure storage, handover TBC</div>
                </div>
            </div>

            <div id="fields_person" style="display:none;margin-top:16px;">
                <div class="row">
                    <div><label>Officer Name</label><input type="text" name="officer_name" id="officerName" placeholder="Full name"></div>
                    <div><label>Collar / Warrant Number</label><input type="text" name="officer_number" placeholder="e.g. 1234"></div>
                </div>
                <div class="row3">
                    <div><label>Handover Location</label><input type="text" name="handover_location" id="handoverLocation" value="Rawmarsh Police Station"></div>
                    <div><label>Handover Date</label><input type="text" name="handover_date" id="handoverDate" value="{{ today }}"></div>
                    <div><label>Handover Time</label><input type="text" name="handover_time" id="handoverTime" placeholder="e.g. 09:15"></div>
                </div>
            </div>

            <div id="fields_dems" style="display:none;margin-top:12px;">
                <p style="font-size:13px;color:#8b949e;padding:12px;background:#0d1117;border-radius:6px;border:1px solid #238636;">
                    💻 DEMS selected — complete the Electronic Transfer Details in the Export section above.
                </p>
            </div>

            <div id="fields_blank" style="margin-top:12px;">
                <p style="font-size:13px;color:#8b949e;padding:12px;background:#0d1117;border-radius:6px;border:1px solid #21262d;">
                    📦 The statement will record that exhibit is currently held in secure CCTV storage awaiting collection or DEMS upload. Handover details will be completed by hand when available.
                </p>
            </div>
        </div>

        <button type="submit" class="submit-btn" id="submitBtn">⚡ Generate Witness Statement</button>

        <div id="loadingBox">
            <div style="font-size:36px;margin-bottom:12px;">⏳</div>
            <div style="font-size:16px;font-weight:700;color:#e6edf3;margin-bottom:8px;">Generating Statement...</div>
            <div style="font-size:13px;color:#8b949e;">Please wait — approximately 30 seconds.</div>
        </div>

        <div id="successBox">
            <div style="background:#0d2b0d;border:1px solid #238636;border-radius:10px;padding:30px;text-align:center;">
                <div style="font-size:44px;margin-bottom:12px;">✅</div>
                <div style="font-size:20px;font-weight:700;color:#3fb950;margin-bottom:6px;">Statement Generated</div>
                <div style="font-size:13px;color:#8b949e;margin-bottom:24px;">Your Word document is downloading now.</div>
                <a href="/" style="background:#21262d;color:#e6edf3;padding:14px 22px;border-radius:6px;font-size:14px;font-weight:600;text-decoration:none;display:inline-block;">← New Statement</a>
            </div>
        </div>

    </form>
</div>

<script>
// ── UK Official Time (browser) ──────────────────────────────────────────────
function getUKTime() {
    const now = new Date();
    function lastSunday(year, month) {
        const d = new Date(Date.UTC(year, month, 31));
        d.setUTCDate(31 - d.getUTCDay());
        return d;
    }
    const year = now.getUTCFullYear();
    const isBST = now >= lastSunday(year, 2) && now < lastSunday(year, 9);
    const uk = new Date(now.getTime() + (isBST ? 1 : 0) * 3600000);
    const days   = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    var hh = String(uk.getUTCHours()).padStart(2,'0');
    var mm = String(uk.getUTCMinutes()).padStart(2,'0');
    var ss = String(uk.getUTCSeconds()).padStart(2,'0');
    document.getElementById('liveDate').textContent = days[uk.getUTCDay()] + ' ' + uk.getUTCDate() + ' ' + months[uk.getUTCMonth()] + ' ' + uk.getUTCFullYear();
    document.getElementById('liveTime').textContent = hh + ':' + mm + ':' + ss;
    document.getElementById('tzLabel').textContent  = (isBST ? 'British Summer Time (BST)' : 'Greenwich Mean Time (GMT)') + ' · Updates every second';
    // Export time placeholder
    var et = document.getElementById('exportTimeField');
    if (et && !et.dataset.touched && !et.value) et.placeholder = hh + ':' + mm + ':' + ss + ' (now)';
    // Handover time placeholder
    var ht = document.getElementById('handoverTime');
    if (ht && !ht.dataset.touched && !ht.value) ht.placeholder = hh + ':' + mm + ' (now)';
}
getUKTime();
setInterval(getUKTime, 1000);

// ── NVR Server Time ──────────────────────────────────────────────────────────
function fetchServerTime() {
    fetch('/server-time')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('serverDate').textContent = data.date;
            var parts   = data.time.split(':');
            var hhmmStr = parts[0] + ':' + parts[1] + ':';
            var secStr  = parts[2];
            document.getElementById('serverTimeHHMM').textContent = hhmmStr;
            var secEl = document.getElementById('serverTimeSS');
            secEl.textContent = secStr;
            // Flash green
            secEl.style.transition = 'none';
            secEl.style.color = '#3fb950';
            secEl.style.textShadow = '0 0 12px #3fb950';
            setTimeout(function() {
                secEl.style.transition = 'color 1.5s ease, text-shadow 1.5s ease';
                secEl.style.color = '#58a6ff';
                secEl.style.textShadow = 'none';
            }, 200);
            // Diff
            var btText = document.getElementById('liveTime').textContent;
            if (btText && btText !== '--:--:--') {
                var b = btText.split(':').map(Number);
                var s = data.time.split(':').map(Number);
                var diffSecs = (s[0]*3600 + s[1]*60 + s[2]) - (b[0]*3600 + b[1]*60 + b[2]);
                var absDiff  = Math.abs(diffSecs);
                var dMins = Math.floor(absDiff / 60);
                var dSecs = absDiff % 60;
                var diffStr;
                if (absDiff < 10)   diffStr = 'Within 10 seconds — accurate';
                else if (dMins > 0) diffStr = 'Server is ' + (diffSecs > 0 ? 'fast' : 'slow') + ' by ' + dMins + 'm ' + dSecs + 's';
                else                diffStr = 'Server is ' + (diffSecs > 0 ? 'fast' : 'slow') + ' by ' + dSecs + ' seconds';
                document.getElementById('serverDiff').textContent = diffStr;
            }
        })
        .catch(function() {
            document.getElementById('serverDate').textContent = 'Unavailable';
            document.getElementById('serverTimeHHMM').textContent = '--:--:';
            document.getElementById('serverTimeSS').textContent  = '--';
            document.getElementById('serverDiff').textContent    = 'Could not reach server';
        });
}
fetchServerTime();
setInterval(fetchServerTime, 5000);

// ── Use These Times button ───────────────────────────────────────────────────
function useTheseTimesForClockCheck() {
    var btTime  = document.getElementById('liveTime').textContent;
    var hhmm    = document.getElementById('serverTimeHHMM').textContent;
    var secPart = document.getElementById('serverTimeSS').textContent;
    var srvTime = hhmm + secPart;
    if (btTime === '--:--:--' || srvTime === '--:--:--') {
        alert('Times not yet loaded — wait a moment and try again.');
        return;
    }
    var cb = document.getElementById('clock_checked_box');
    if (cb) { cb.checked = true; toggleClock(cb); }
    var cd = document.querySelector('[name="clock_check_date"]');
    var bf = document.querySelector('[name="bt_clock_time"]');
    var nf = document.querySelector('[name="nvr_clock_time"]');
    var df = document.querySelector('[name="clock_difference"]');
    var fs = document.querySelector('[name="clock_fast_slow"]');
    var sd = document.getElementById('statementDate');
    if (cd) cd.value = sd ? sd.value : document.getElementById('serverDate').textContent;
    if (bf) bf.value = btTime;
    if (nf) nf.value = srvTime;
    var b = btTime.split(':').map(Number);
    var s = srvTime.split(':').map(Number);
    var diffSecs = (s[0]*3600 + s[1]*60 + s[2]) - (b[0]*3600 + b[1]*60 + b[2]);
    var absDiff  = Math.abs(diffSecs);
    var dMins = Math.floor(absDiff / 60);
    var dSecs = absDiff % 60;
    if (df) {
        if (absDiff < 10)   df.value = 'less than 10 seconds';
        else if (dMins > 0) df.value = dMins + ' minute' + (dMins > 1 ? 's' : '') + ' and ' + dSecs + ' seconds';
        else                df.value = dSecs + ' seconds';
    }
    if (fs) {
        if (absDiff < 10)       fs.value = 'accurate';
        else if (diffSecs > 0)  fs.value = 'fast';
        else                    fs.value = 'slow';
    }
    var gs = document.querySelector('.green-section');
    if (gs) gs.scrollIntoView({behavior:'smooth', block:'center'});
}

// ── Handover toggle ──────────────────────────────────────────────────────────
function setHandover(type) {
    var types = ['person','dems','blank'];
    for (var i = 0; i < types.length; i++) {
        var opt = document.getElementById('opt_' + types[i]);
        if (opt) opt.classList.remove('active');
        var f = document.getElementById('fields_' + types[i]);
        if (f) f.style.display = 'none';
    }
    var activeOpt = document.getElementById('opt_' + type);
    if (activeOpt) activeOpt.classList.add('active');
    var radio = document.querySelector('input[name="handover_type"][value="' + type + '"]');
    if (radio) radio.checked = true;
    var show = document.getElementById('fields_' + type);
    if (show) show.style.display = 'block';
    if (type === 'person') {
        setTimeout(function() { var n = document.getElementById('officerName'); if (n) n.focus(); }, 100);
    }
}
setHandover('blank');

// ── Clock checkbox toggle ────────────────────────────────────────────────────
function toggleClock(cb) {
    var f = document.getElementById('clock_fields');
    if (f) f.style.display = cb.checked ? 'block' : 'none';
}
var clockCb = document.getElementById('clock_checked_box');
if (clockCb) clockCb.addEventListener('change', function() { toggleClock(this); });

// ── Reference section toggle ─────────────────────────────────────────────────
function toggleRef(cb) {
    var f = document.getElementById('ref_fields');
    if (f) f.style.display = cb.checked ? 'none' : 'block';
}

// ── Bookmark creator toggle ──────────────────────────────────────────────────
var bcEl = document.getElementById('bookmarkCreator');
if (bcEl) bcEl.addEventListener('change', function() {
    var f = document.getElementById('other_creator_field');
    if (f) f.style.display = this.value === '__other__' ? 'block' : 'none';
});

// ── Electronic transfer toggle ───────────────────────────────────────────────
function toggleElectronic(val) {
    var f = document.getElementById('electronic_fields');
    if (f) f.style.display = (val === 'Wasabi Cloud Storage' || val === 'South Yorkshire Police DEMS Portal') ? 'block' : 'none';
}

// ── Mark inputs as touched ───────────────────────────────────────────────────
var allInputs = document.querySelectorAll('input');
for (var i = 0; i < allInputs.length; i++) {
    allInputs[i].addEventListener('input', function() { this.dataset.touched = '1'; });
}

// ── Form submit ──────────────────────────────────────────────────────────────
var stmtForm = document.getElementById('stmtForm');
if (stmtForm) stmtForm.addEventListener('submit', function(e) {
    e.preventDefault();
    var creatorSel = document.getElementById('bookmarkCreator');
    if (creatorSel && creatorSel.value === '__other__') {
        var otherInput = document.querySelector('input[name="bookmark_creator_other"]');
        creatorSel.value = (otherInput && otherInput.value.trim()) ? otherInput.value.trim() : 'Unknown';
    }
    var btn = document.getElementById('submitBtn');
    btn.disabled = true; btn.textContent = '⏳ Generating...';
    document.getElementById('loadingBox').style.display = 'block';
    fetch(window.location.href, {method:'POST', body: new FormData(this)})
        .then(function(r) { if (!r.ok) throw new Error('Server error ' + r.status); return r.blob(); })
        .then(function(blob) {
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a'); a.href = url;
            a.download = 'witness_statement.docx';
            document.body.appendChild(a); a.click();
            document.body.removeChild(a); URL.revokeObjectURL(url);
            document.getElementById('loadingBox').style.display = 'none';
            document.getElementById('stmtForm').style.display   = 'none';
            document.getElementById('successBox').style.display = 'block';
        })
        .catch(function(err) {
            document.getElementById('loadingBox').innerHTML =
                '<div style="color:#f85149;font-size:15px;margin-bottom:12px;">❌ Error: ' + err.message + '</div>' +
                '<button onclick="location.reload()" style="background:#21262d;color:#e6edf3;padding:10px 20px;border-radius:6px;border:none;cursor:pointer;">Try Again</button>';
        });
});
</script>
</body></html>"""
# ── Routes ────────────────────────────────────

@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username","").strip().lower()
        password = request.form.get("password","")
        if check_password(username, password):
            session["username"]  = username
            session["user_name"] = USERS[username]["name"]
            session["user_role"] = USERS[username]["role"]
            session["initials"]  = USERS[username]["initials"]
            return redirect(url_for("index"))
        error = "Invalid username or password."
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    return render_template_string(BOOKMARKS_HTML, bookmarks=get_bookmarks(), session=session)

@app.route("/form/<int:bookmark_id>", methods=["GET","POST"])
@login_required
def form(bookmark_id):
    bm = get_bookmark(bookmark_id)
    if not bm: return redirect(url_for("index"))
    if request.method == "POST":
        form_data     = request.form.to_dict()
        download_time = datetime.now(timezone.utc)
        try:
            statement_text = generate_statement(bm, form_data, download_time)
            witness_name   = form_data.get("witness_name", "Officer")
            bookmark_name  = bm.get("name", "statement")
            docx_buf       = build_docx(statement_text, witness_name, bookmark_name, download_time)
            date_str  = download_time.strftime("%Y-%m-%d_%H-%M")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in witness_name)
            safe_bm   = "".join(c if c.isalnum() or c in "-_" else "_" for c in bookmark_name)
            filename  = f"{date_str}_{safe_name}_{safe_bm}.docx"
            return send_file(docx_buf, as_attachment=True, download_name=filename,
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        except Exception as e:
            import traceback; traceback.print_exc()
            return (f"<html><body style='font-family:Arial;padding:40px;background:#0d1117;color:#f85149;'>"
                    f"<h2>Error: {str(e)}</h2>"
                    f"<pre style='color:#f85149;font-size:12px;margin-top:20px;white-space:pre-wrap;'>{traceback.format_exc()}</pre>"
                    f"<a href='/form/{bookmark_id}' style='color:#58a6ff;'>← Try again</a>"
                    f"</body></html>"), 500
    today    = datetime.now().strftime("%d/%m/%Y")
    initials = session.get("initials", "XX")
    return render_template_string(FORM_HTML, bm=bm, session=session, today=today, locations=LOCATIONS, initials=initials)

@app.route("/server-time")
def server_time():
    from flask import jsonify
    now = datetime.now()
    return jsonify({"date": now.strftime("%d/%m/%Y"), "time": now.strftime("%H:%M:%S")})

if __name__ == "__main__":
    if not ANTHROPIC_KEY:
        print("\n⚠️  WARNING: ANTHROPIC_API_KEY not set.\n")
    print("\n🎥 RMBC CCTV Statement Generator")
    print("   http://0.0.0.0:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
