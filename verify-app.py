# verify-app.py (unstoppable version - safe from hangs!)

import csv
import io
import re
import time
import uuid
import random
import socket
import unicodedata
from threading import Lock, Thread
from datetime import datetime, timedelta
from tempfile import NamedTemporaryFile
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError

import dns.resolver
import smtplib
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

print("🚀 UNSTOPPABLE EMAIL VERIFIER RUNNING 🚀")

# ------ Configuration ------
BASE_WORKERS      = 20
SMTP_TIMEOUT      = 20
SMTP_RETRIES      = 3
GREYLIST_RETRIES  = 2
DNS_CACHE_TTL     = 3600
ACCEPT_ALL_CHECKS = 2
TASK_TIMEOUT      = 30  # Hard timeout per email (in seconds)
RANDOM_DOMAINS    = ["example.com", "test.com", "demo.com"]
# ----------------------------

# Provider patterns for MX record matching
PROVIDER_PATTERNS = {
    "Microsoft": ["outlook.com", "microsoft.com", "hotmail.com", "office365.com"],
    "Google": ["google.com", "googlemail.com"],
    "Yahoo": ["yahoo.com", "yahoodns.net"],
    "Zoho": ["zoho.com", "zohomail.com"],
}

socket.setdefaulttimeout(SMTP_TIMEOUT)
EMAIL_REGEX = re.compile(r"[^@]+@[^@]+\.[^@]+")
DISPOSABLE_DOMAINS = {"mailinator.com", "10minutemail.com", "guerrillamail.com"}
ROLE_BASED_PREFIXES = {"info", "support", "admin", "sales", "contact"}

data = {}
mx_cache = {}
mx_cache_lock = Lock()


def clean_filename(fn: str) -> str:
    nfkd = unicodedata.normalize("NFKD", fn)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_only.replace(" ", "_") or "download.csv"


def get_mx(domain: str) -> str:
    now = datetime.utcnow()
    with mx_cache_lock:
        entry = mx_cache.get(domain)
        if entry and entry["expiry"] > now:
            return entry["mx"]
    try:
        answers = dns.resolver.resolve(domain, 'MX')
        mx = str(sorted(answers, key=lambda r: r.preference)[0].exchange)
        with mx_cache_lock:
            mx_cache[domain] = {"mx": mx, "expiry": now + timedelta(seconds=DNS_CACHE_TTL)}
        return mx
    except Exception:
        return None


def identify_provider(mx: str) -> str:
    """Identify email provider from MX record hostname"""
    if not mx:
        return "Unknown"
    mx_lower = mx.lower()
    for provider, patterns in PROVIDER_PATTERNS.items():
        for pattern in patterns:
            if pattern in mx_lower:
                return provider
    return "Other"


def smtp_check(mx: str, address: str) -> int:
    last_code = None
    for attempt in range(SMTP_RETRIES):
        try:
            server = smtplib.SMTP(mx, timeout=SMTP_TIMEOUT)
            helo = random.choice(RANDOM_DOMAINS)
            server.helo(helo)
            server.mail(f"verify@{helo}")
            code, _ = server.rcpt(address)
            server.quit()
            last_code = code
            if code in (450, 451) and attempt < GREYLIST_RETRIES:
                time.sleep(5)
                continue
            return code
        except (socket.timeout, smtplib.SMTPException):
            time.sleep(5)
            continue
    return last_code


def check_email(email: str):
    print(f"🔍 Checking: {email}")
    if not EMAIL_REGEX.match(email):
        return "invalid", "smtp_invalid", "Unknown"
    local, domain = email.rsplit("@", 1)
    if domain.lower() in DISPOSABLE_DOMAINS:
        return "invalid", "smtp_invalid", "Unknown"
    if local.lower() in ROLE_BASED_PREFIXES:
        return "invalid", "smtp_invalid", "Unknown"
    try:
        socket.gethostbyname(domain)
    except socket.gaierror:
        return "invalid", "smtp_invalid", "Unknown"
    mx = get_mx(domain)
    if not mx:
        return "invalid", "smtp_invalid", "Unknown"

    provider = identify_provider(mx)

    accepts = 0
    for _ in range(ACCEPT_ALL_CHECKS):
        if smtp_check(mx, f"fake{random.randint(100000,999999)}@{domain}") == 250:
            accepts += 1
    if accepts == ACCEPT_ALL_CHECKS:
        return "risky", "catch_all", provider
    code = smtp_check(mx, email)
    if code == 250:
        return "valid", "smtp_ok", provider
    if code == 550:
        return "invalid", "smtp_invalid", provider
    if code in (450, 451, 452, 503):
        return "risky", "smtp_timeout", provider
    if code is None:
        return "risky", "smtp_timeout", provider
    return "risky", "smtp_timeout", provider


@app.route('/verify', methods=['POST'])
def verify():
    job_id = str(uuid.uuid4())
    file = request.files['file']
    try:
        raw = file.read().decode('utf-8')
    except UnicodeDecodeError:
        raw = file.read().decode('latin1')
    records = list(csv.DictReader(io.StringIO(raw)))
    total = len(records)
    email_field = next((k for k in records[0].keys() if k.lower().strip() == "email"), None)

    if total < 500:
        workers = 10
    elif total < 2000:
        workers = 20
    elif total < 5000:
        workers = 25
    else:
        workers = 35

    out_io = io.StringIO()
    cols = list(records[0].keys()) + ["status", "reason", "provider"]
    writer = csv.DictWriter(out_io, fieldnames=cols)
    writer.writeheader()

    # ✅ CHANGED: log is now a list, added current_email field
    data[job_id] = {
        "progress": 0, "row": 0, "total": total,
        "log": [], "cancel": False,
        "current_email": "",
        "output": out_io, "writer": writer,
        "records": records, "email_field": email_field,
        "filename": file.filename
    }

    def run():
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for row in records:
                email = (row.get(email_field) or "").strip()
                if not email:
                    row["status"], row["reason"], row["provider"] = "invalid", "smtp_invalid", "Unknown"
                    data[job_id]["writer"].writerow(row)
                else:
                    # ✅ CHANGED: track which email is being submitted right now
                    data[job_id]["current_email"] = email
                    futures[executor.submit(check_email, email)] = row

            done = 0
            for future in as_completed(futures):
                row = futures[future]
                email = (row.get(email_field) or "").strip()

                # ✅ CHANGED: update current_email as each result comes back
                data[job_id]["current_email"] = email

                try:
                    status, reason, provider = future.result(timeout=TASK_TIMEOUT)
                except TimeoutError:
                    status, reason, provider = "risky", "smtp_timeout", "Unknown"
                except Exception:
                    status, reason, provider = "risky", "smtp_timeout", "Unknown"

                row["status"], row["reason"], row["provider"] = status, reason, provider
                data[job_id]["writer"].writerow(row)
                done += 1
                pct = int(done / total * 100)

                # ✅ CHANGED: append to log list instead of overwriting
                safe_email = str(email[:100]).replace('<', '').replace('>', '')
                log_entry = f"✅ {safe_email} → {status} ({reason}) [{provider}]"
                data[job_id]["log"].append(log_entry)
                data[job_id]["progress"] = pct
                data[job_id]["row"] = done

        out = data[job_id]["output"]
        out.seek(0)
        tmp = NamedTemporaryFile(delete=False, suffix=".csv", mode="w+")
        tmp.write(out.read()); tmp.flush(); tmp.seek(0)
        data[job_id]["file_path"] = tmp.name
        data[job_id]["current_email"] = ""

        out.seek(0)
        rows = list(csv.DictReader(out))
        stats = {"valid": 0, "risky": 0, "invalid": 0}
        for r in rows:
            stats[r["status"]] += 1
        data[job_id]["stats"] = stats

    Thread(target=run).start()
    return jsonify({"job_id": job_id})


@app.route('/progress')
def progress():
    jid = request.args.get("job_id", "")
    d = data.get(jid, {})
    # ✅ CHANGED: also return current_email so frontend can show it
    return jsonify({
        "percent": d.get("progress", 0),
        "row": d.get("row", 0),
        "total": d.get("total", 0),
        "current_email": d.get("current_email", "")
    })


# ✅ CHANGED: old /log endpoint kept for compatibility but now returns last entry
@app.route('/log')
def log():
    jid = request.args.get("job_id", "")
    entries = data.get(jid, {}).get("log", [])
    last = entries[-1] if entries else ""
    return Response(last, mimetype="text/plain")


# ✅ NEW: /logs endpoint — returns all log entries from a given offset
@app.route('/logs')
def logs():
    jid = request.args.get("job_id", "")
    offset = int(request.args.get("offset", 0))
    entries = data.get(jid, {}).get("log", [])
    return jsonify({
        "entries": entries[offset:],
        "total": len(entries)
    })


@app.route('/stats')
def stats():
    jid = request.args.get("job_id", "")
    job = data.get(jid)
    if not job:
        return "Invalid job ID", 404
    return jsonify(job.get("stats", {"valid": 0, "risky": 0, "invalid": 0}))


@app.route('/cancel', methods=['POST'])
def cancel():
    jid = request.args.get("job_id", "")
    if jid in data:
        data[jid]["cancel"] = True
    return ("", 204)


@app.route('/download')
def download():
    jid = request.args.get("job_id", "")
    t = request.args.get("type", "all")
    job = data.get(jid)
    if not job:
        return "Invalid job ID", 404

    job["output"].seek(0)
    rows = list(csv.DictReader(job["output"]))

    if t == "valid":
        filtered = [r for r in rows if r["status"] == "valid"]
    elif t == "risky":
        filtered = [r for r in rows if r["status"] == "risky"]
    elif t == "risky_invalid":
        filtered = [r for r in rows if r["status"] in ("risky", "invalid")]
    elif t == "valid_accept_all":
        filtered = [
            r for r in rows
            if r["status"] == "valid"
            or (r["status"] == "risky" and r["reason"] == "catch_all")
        ]
    else:
        filtered = rows

    seen = set()
    unique = []
    for r in filtered:
        e = (r.get("email") or r.get("Email") or "").strip().lower()
        if e and e not in seen:
            seen.add(e)
            unique.append(r)

    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=rows[0].keys())
    w.writeheader()
    for r in unique:
        w.writerow(r)

    out.seek(0)
    name = clean_filename(f"{t}-{job['filename']}")
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={name}"}
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)