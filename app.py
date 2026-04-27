"""
NGO Unified System
==================
Merges NGOSystem (public crisis/donor forms) + SmartAlloc (resource allocation engine).

Roles:
  - Public: Submit crisis request, submit donation offer
  - Admin:  Add members, view all requests, run auto-allocation

Auto-allocation:
  - Crisis requests → members matched by district & skills
  - Donor resources → allocated to crises in same / nearby district
"""

import os
import json
import sqlite3
from datetime import datetime, timezone
from contextlib import closing
from functools import wraps

from flask import (
    Flask, render_template, request, jsonify, g,
    redirect, url_for, session, abort
)
import time
from collections import defaultdict
_rate_store = defaultdict(list)
def rate_limit(key, max_c, secs):
    now=time.time()
    _rate_store[key][:]=[t for t in _rate_store[key] if now-t<secs]
    if len(_rate_store[key])>=max_c: return False
    _rate_store[key].append(now); return True

# --------------------------------------------------------------------------- #
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH  = os.path.join(BASE_DIR, "instance", "ngo_unified.db")

app = Flask(__name__)
app.secret_key = "ngo-unified-secret-2025"



ADMIN_PASSWORD = "admin1234"   # Change in production

WB_DISTRICTS = [
    "Alipurduar", "Bankura", "Birbhum", "Cooch Behar", "Dakshin Dinajpur",
    "Darjeeling", "Hooghly", "Howrah", "Jalpaiguri", "Jhargram",
    "Kalimpong", "Kolkata", "Malda", "Murshidabad", "Nadia",
    "North 24 Parganas", "Paschim Bardhaman", "Paschim Medinipur",
    "Purba Bardhaman", "Purba Medinipur", "Purulia", "South 24 Parganas",
    "Uttar Dinajpur",
]

CRISIS_CATEGORIES = ["flood", "fire", "earthquake", "medical", "drought", "cyclone", "other"]

SKILL_TAGS = [
    "medical", "first_aid", "logistics", "construction", "water_sanitation",
    "food_distribution", "counseling", "rescue", "teaching", "communication",
]

# --------------------------------------------------------------------------- #
#                                  SCHEMA                                     #
# --------------------------------------------------------------------------- #

SCHEMA = """
CREATE TABLE IF NOT EXISTS crisis_request (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    phone         TEXT    NOT NULL,
    address       TEXT    NOT NULL,
    district      TEXT    NOT NULL,
    pin_code      TEXT    NOT NULL,
    category      TEXT    NOT NULL DEFAULT 'other',
    description   TEXT    NOT NULL,
    urgency       INTEGER NOT NULL DEFAULT 3,
    people_affected INTEGER NOT NULL DEFAULT 1,
    status        TEXT    NOT NULL DEFAULT 'pending',
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS donor_submission (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL,
    phone         TEXT    NOT NULL,
    address       TEXT    NOT NULL,
    district      TEXT    NOT NULL,
    resource_type TEXT    NOT NULL,
    resource_desc TEXT    NOT NULL,
    quantity      TEXT    NOT NULL DEFAULT '1',
    status        TEXT    NOT NULL DEFAULT 'pending',
    allocated_to  INTEGER,
    created_at    TEXT    NOT NULL,
    FOREIGN KEY (allocated_to) REFERENCES crisis_request(id)
);

CREATE TABLE IF NOT EXISTS member (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    phone         TEXT    NOT NULL,
    skills        TEXT    NOT NULL DEFAULT '[]',
    district      TEXT    NOT NULL,
    availability  TEXT    NOT NULL DEFAULT 'flexible',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS member_assignment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    crisis_id     INTEGER NOT NULL,
    member_id     INTEGER NOT NULL,
    score         REAL    NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'assigned',
    created_at    TEXT    NOT NULL,
    FOREIGN KEY (crisis_id)  REFERENCES crisis_request(id) ON DELETE CASCADE,
    FOREIGN KEY (member_id)  REFERENCES member(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS resource_allocation (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id      INTEGER NOT NULL,
    crisis_id     INTEGER NOT NULL,
    note          TEXT,
    created_at    TEXT    NOT NULL,
    FOREIGN KEY (donor_id)  REFERENCES donor_submission(id) ON DELETE CASCADE,
    FOREIGN KEY (crisis_id) REFERENCES crisis_request(id) ON DELETE CASCADE
);
"""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.executescript(SCHEMA)
        db.commit()


# --------------------------------------------------------------------------- #
#                          SMART MATCHING ENGINE                              #
# --------------------------------------------------------------------------- #

CRISIS_SKILL_MAP = {
    "flood":      ["rescue", "logistics", "water_sanitation", "first_aid"],
    "fire":       ["rescue", "first_aid", "medical"],
    "earthquake": ["rescue", "construction", "medical", "first_aid"],
    "medical":    ["medical", "first_aid", "counseling"],
    "drought":    ["water_sanitation", "food_distribution", "logistics"],
    "cyclone":    ["rescue", "logistics", "construction", "first_aid"],
    "other":      ["logistics", "communication", "first_aid"],
}


def score_member(crisis_row, member_row):
    """
    Score 0-100:
      - District match: 40 pts (same district = full, else 0)
      - Skill overlap:  40 pts proportional
      - Urgency boost:  20 pts
    Returns (score, breakdown) or (None, reason).
    """
    if not member_row["active"]:
        return None, "inactive"

    # District component
    district_score = 40.0 if member_row["district"] == crisis_row["district"] else 0.0

    # Skill component
    try:
        m_skills = set(json.loads(member_row["skills"]))
    except Exception:
        m_skills = set()
    relevant = set(CRISIS_SKILL_MAP.get(crisis_row["category"], CRISIS_SKILL_MAP["other"]))
    overlap  = m_skills & relevant
    skill_score = 40.0 * (len(overlap) / max(len(relevant), 1))

    # Urgency boost
    urgency_score = 20.0 * (int(crisis_row["urgency"]) / 5.0)

    total = district_score + skill_score + urgency_score
    return round(total, 1), {
        "district":       round(district_score, 1),
        "skills":         round(skill_score, 1),
        "urgency":        round(urgency_score, 1),
        "matched_skills": sorted(overlap),
    }


def auto_assign_members(crisis_id, db, top_n=3):
    """Assign best-fit members to a crisis. Returns count assigned."""
    crisis = db.execute("SELECT * FROM crisis_request WHERE id=?", (crisis_id,)).fetchone()
    if not crisis:
        return 0
    members = db.execute("SELECT * FROM member WHERE active=1").fetchall()
    ranked = []
    for m in members:
        s, br = score_member(crisis, m)
        if s is not None:
            ranked.append((dict(m), s))
    ranked.sort(key=lambda x: x[1], reverse=True)
    count = 0
    for m, score in ranked[:top_n]:
        existing = db.execute(
            "SELECT id FROM member_assignment WHERE crisis_id=? AND member_id=? AND status!='completed'",
            (crisis_id, m["id"])
        ).fetchone()
        if existing:
            continue
        db.execute(
            "INSERT INTO member_assignment(crisis_id,member_id,score,status,created_at) VALUES(?,?,?,'assigned',?)",
            (crisis_id, m["id"], score, now_iso())
        )
        count += 1
    if count:
        db.execute("UPDATE crisis_request SET status='assigned' WHERE id=? AND status='pending'", (crisis_id,))
    return count


def auto_allocate_resources(donor_id, db):
    """Allocate a donor's resources to the best-matching open crisis. Returns crisis_id or None."""
    donor = db.execute("SELECT * FROM donor_submission WHERE id=?", (donor_id,)).fetchone()
    if not donor:
        return None
    # Prefer same district, then any open/assigned crisis by urgency
    crises = db.execute(
        "SELECT * FROM crisis_request WHERE status IN ('pending','assigned') ORDER BY district=? DESC, urgency DESC LIMIT 1",
        (donor["district"],)
    ).fetchone()
    if not crises:
        return None
    crisis_id = crises["id"]
    db.execute(
        "INSERT INTO resource_allocation(donor_id,crisis_id,note,created_at) VALUES(?,?,?,?)",
        (donor_id, crisis_id, f"Auto-allocated from {donor['district']}", now_iso())
    )
    db.execute("UPDATE donor_submission SET status='allocated', allocated_to=? WHERE id=?",
               (crisis_id, donor_id))
    return crisis_id


# --------------------------------------------------------------------------- #
#                               ADMIN AUTH                                    #
# --------------------------------------------------------------------------- #

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# --------------------------------------------------------------------------- #
#                             PUBLIC ROUTES                                   #
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    return render_template("index.html", districts=WB_DISTRICTS)


@app.route("/needhelp")
def needhelp():
    return render_template("needhelp.html", districts=WB_DISTRICTS, categories=CRISIS_CATEGORIES)


@app.route("/submit-crisis", methods=["POST"])
def submit_crisis():
    data = request.json or {}
    required = ["fullName", "phone", "address", "district", "pincode", "category", "crisis"]
    if not all(data.get(k, "").strip() for k in required):
        return jsonify({"error": "All fields are required."}), 400
    if data["district"] not in WB_DISTRICTS:
        return jsonify({"error": "Invalid district."}), 400

    db = get_db()
    db.execute("""
        INSERT INTO crisis_request(full_name,phone,address,district,pin_code,category,description,urgency,people_affected,status,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,'pending',?)
    """, (
        data["fullName"].strip(), data["phone"].strip(), data["address"].strip(),
        data["district"], data["pincode"].strip(), data["category"],
        data["crisis"].strip(),
        int(data.get("urgency", 3)), int(data.get("people_affected", 1)),
        now_iso()
    ))
    crisis_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Auto-assign members immediately
    assigned = auto_assign_members(crisis_id, db)
    db.commit()
    return jsonify({
        "status": "success",
        "message": f"Your request has been received. {assigned} team member(s) have been auto-assigned.",
    }), 200


@app.route("/joinus")
def joinus():
    return render_template("join.html")


@app.route("/donor-info")
def donor_info_page():
    return render_template("donor_info.html", districts=WB_DISTRICTS)


@app.route("/submit-donor-info", methods=["POST"])
def submit_donor_info():
    data = request.json or {}
    required = ["full_name", "email", "phone", "address", "district", "resource_type", "resource_desc", "quantity"]
    if not all(data.get(k, "").strip() for k in required):
        return jsonify({"error": "All fields are required."}), 400
    if "@" not in data["email"] or "." not in data["email"].split("@")[-1]:
        return jsonify({"error": "Invalid email address."}), 400
    digits = "".join(c for c in data["phone"] if c.isdigit())
    if not (7 <= len(digits) <= 15):
        return jsonify({"error": "Invalid phone number."}), 400
    if data["district"] not in WB_DISTRICTS:
        return jsonify({"error": "Invalid district."}), 400

    db = get_db()
    db.execute("""
        INSERT INTO donor_submission(full_name,email,phone,address,district,resource_type,resource_desc,quantity,status,created_at)
        VALUES(?,?,?,?,?,?,?,?,'pending',?)
    """, (
        data["full_name"].strip(), data["email"].strip(), data["phone"].strip(),
        data["address"].strip(), data["district"],
        data["resource_type"].strip(), data["resource_desc"].strip(),
        data["quantity"].strip(), now_iso()
    ))
    donor_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Auto-allocate to best crisis
    allocated_to = auto_allocate_resources(donor_id, db)
    db.commit()

    if allocated_to:
        crisis = db.execute("SELECT full_name, district FROM crisis_request WHERE id=?", (allocated_to,)).fetchone()
        msg = f"Thank you! Your donation has been auto-allocated to a crisis in {crisis['district']} district."
    else:
        msg = "Thank you! Your donation details have been received. Our team will contact you shortly."
    return jsonify({"status": "success", "message": msg}), 200


# --------------------------------------------------------------------------- #
#                              ADMIN ROUTES                                   #
# --------------------------------------------------------------------------- #

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        error = "Incorrect password."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        "crises_total":   db.execute("SELECT COUNT(*) FROM crisis_request").fetchone()[0],
        "crises_pending": db.execute("SELECT COUNT(*) FROM crisis_request WHERE status='pending'").fetchone()[0],
        "crises_assigned":db.execute("SELECT COUNT(*) FROM crisis_request WHERE status='assigned'").fetchone()[0],
        "crises_resolved":db.execute("SELECT COUNT(*) FROM crisis_request WHERE status='resolved'").fetchone()[0],
        "donors_total":   db.execute("SELECT COUNT(*) FROM donor_submission").fetchone()[0],
        "donors_pending": db.execute("SELECT COUNT(*) FROM donor_submission WHERE status='pending'").fetchone()[0],
        "donors_allocated":db.execute("SELECT COUNT(*) FROM donor_submission WHERE status='allocated'").fetchone()[0],
        "members_total":  db.execute("SELECT COUNT(*) FROM member").fetchone()[0],
        "members_active": db.execute("SELECT COUNT(*) FROM member WHERE active=1").fetchone()[0],
        "assignments":    db.execute("SELECT COUNT(*) FROM member_assignment").fetchone()[0],
    }
    return render_template("admin_dashboard.html", stats=stats)


@app.route("/admin/crises")
@admin_required
def admin_crises():
    db = get_db()
    crises = db.execute(
        "SELECT * FROM crisis_request ORDER BY urgency DESC, created_at DESC"
    ).fetchall()
    return render_template("admin_crises.html", crises=crises, districts=WB_DISTRICTS)


@app.route("/admin/donors")
@admin_required
def admin_donors():
    db = get_db()
    donors = db.execute(
        "SELECT d.*, c.full_name AS crisis_name, c.district AS crisis_district "
        "FROM donor_submission d LEFT JOIN crisis_request c ON c.id=d.allocated_to "
        "ORDER BY d.created_at DESC"
    ).fetchall()
    return render_template("admin_donors.html", donors=donors)


@app.route("/admin/members")
@admin_required
def admin_members():
    db = get_db()
    members = db.execute("SELECT * FROM member ORDER BY full_name ASC").fetchall()
    return render_template("admin_members.html", members=members,
                           districts=WB_DISTRICTS, skills=SKILL_TAGS)


@app.route("/admin/assignments")
@admin_required
def admin_assignments():
    db = get_db()
    rows = db.execute("""
        SELECT a.id, a.score, a.status, a.created_at,
               c.id AS crisis_id, c.full_name AS crisis_name, c.district AS crisis_district,
               c.category, c.urgency,
               m.id AS member_id, m.full_name AS member_name, m.district AS member_district
        FROM member_assignment a
        JOIN crisis_request c ON c.id = a.crisis_id
        JOIN member m         ON m.id = a.member_id
        ORDER BY a.created_at DESC
    """).fetchall()
    return render_template("admin_assignments.html", assignments=rows)


# ---- Admin API endpoints -------------------------------------------------- #

@app.route("/api/admin/members", methods=["POST"])
@admin_required
def api_add_member():
    data = request.json or {}
    required = ["full_name", "email", "phone", "skills", "district", "availability"]
    if not all(data.get(k) for k in required):
        return jsonify({"error": "All fields required."}), 400
    skills = data["skills"]
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    db = get_db()
    try:
        db.execute("""
            INSERT INTO member(full_name,email,phone,skills,district,availability,active,created_at)
            VALUES(?,?,?,?,?,?,1,?)
        """, (
            data["full_name"].strip(), data["email"].strip().lower(),
            data["phone"].strip(), json.dumps(skills),
            data["district"], data["availability"], now_iso()
        ))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Member with this email already exists."}), 409
    return jsonify({"status": "success", "message": "Member added successfully."})


@app.route("/api/admin/members/<int:mid>/toggle", methods=["POST"])
@admin_required
def api_toggle_member(mid):
    db = get_db()
    row = db.execute("SELECT active FROM member WHERE id=?", (mid,)).fetchone()
    if not row:
        return jsonify({"error": "Member not found."}), 404
    new = 0 if row["active"] else 1
    db.execute("UPDATE member SET active=? WHERE id=?", (new, mid))
    db.commit()
    return jsonify({"status": "success", "active": bool(new)})


@app.route("/api/admin/members/<int:mid>", methods=["DELETE"])
@admin_required
def api_delete_member(mid):
    db = get_db()
    db.execute("DELETE FROM member WHERE id=?", (mid,))
    db.commit()
    return jsonify({"status": "success"})


@app.route("/api/admin/crises/<int:cid>/status", methods=["POST"])
@admin_required
def api_update_crisis_status(cid):
    data = request.json or {}
    status = data.get("status")
    if status not in {"pending", "assigned", "resolved"}:
        return jsonify({"error": "Invalid status."}), 400
    db = get_db()
    db.execute("UPDATE crisis_request SET status=? WHERE id=?", (status, cid))
    db.commit()
    return jsonify({"status": "success"})


@app.route("/api/admin/crises/<int:cid>/auto-assign", methods=["POST"])
@admin_required
def api_auto_assign(cid):
    db = get_db()
    count = auto_assign_members(cid, db)
    db.commit()
    return jsonify({"status": "success", "assigned": count,
                    "message": f"{count} member(s) assigned to this crisis."})


@app.route("/api/admin/run-allocation", methods=["POST"])
@admin_required
def api_run_full_allocation():
    """Run auto-assignment for all pending crises + resource allocation for pending donors."""
    db = get_db()
    pending_crises = db.execute(
        "SELECT id FROM crisis_request WHERE status='pending'"
    ).fetchall()
    total_assigned = 0
    for row in pending_crises:
        total_assigned += auto_assign_members(row["id"], db)

    pending_donors = db.execute(
        "SELECT id FROM donor_submission WHERE status='pending'"
    ).fetchall()
    total_allocated = 0
    for row in pending_donors:
        result = auto_allocate_resources(row["id"], db)
        if result:
            total_allocated += 1

    db.commit()
    return jsonify({
        "status": "success",
        "members_assigned": total_assigned,
        "resources_allocated": total_allocated,
        "message": f"Auto-allocation complete: {total_assigned} member assignment(s), {total_allocated} resource allocation(s)."
    })


@app.route("/api/admin/assignments/<int:aid>/status", methods=["POST"])
@admin_required
def api_update_assignment_status(aid):
    data = request.json or {}
    status = data.get("status")
    if status not in {"assigned", "completed"}:
        return jsonify({"error": "Invalid status."}), 400
    db = get_db()
    asg = db.execute("SELECT crisis_id FROM member_assignment WHERE id=?", (aid,)).fetchone()
    if not asg:
        return jsonify({"error": "Not found."}), 404
    db.execute("UPDATE member_assignment SET status=? WHERE id=?", (status, aid))
    if status == "completed":
        # If all assignments for this crisis are complete, mark it resolved
        pending = db.execute(
            "SELECT COUNT(*) FROM member_assignment WHERE crisis_id=? AND status!='completed'",
            (asg["crisis_id"],)
        ).fetchone()[0]
        if pending == 0:
            db.execute("UPDATE crisis_request SET status='resolved' WHERE id=?", (asg["crisis_id"],))
    db.commit()
    return jsonify({"status": "success"})


@app.route("/api/admin/stats")
@admin_required
def api_stats():
    db = get_db()
    return jsonify({
        "crises":  {
            "total":    db.execute("SELECT COUNT(*) FROM crisis_request").fetchone()[0],
            "pending":  db.execute("SELECT COUNT(*) FROM crisis_request WHERE status='pending'").fetchone()[0],
            "assigned": db.execute("SELECT COUNT(*) FROM crisis_request WHERE status='assigned'").fetchone()[0],
            "resolved": db.execute("SELECT COUNT(*) FROM crisis_request WHERE status='resolved'").fetchone()[0],
        },
        "donors":  {
            "total":     db.execute("SELECT COUNT(*) FROM donor_submission").fetchone()[0],
            "pending":   db.execute("SELECT COUNT(*) FROM donor_submission WHERE status='pending'").fetchone()[0],
            "allocated": db.execute("SELECT COUNT(*) FROM donor_submission WHERE status='allocated'").fetchone()[0],
        },
        "members": {
            "total":  db.execute("SELECT COUNT(*) FROM member").fetchone()[0],
            "active": db.execute("SELECT COUNT(*) FROM member WHERE active=1").fetchone()[0],
        },
        "assignments": db.execute("SELECT COUNT(*) FROM member_assignment").fetchone()[0],
    })

@app.route("/gallery")
def gallery():
    return render_template("gallery.html")

# --------------------------------------------------------------------------- #
#                             ERROR HANDLERS                                  #
# --------------------------------------------------------------------------- #

@app.errorhandler(429)
def handle_ratelimit(e):
    return jsonify({"error": "Too many requests. Please wait before trying again."}), 429


@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint not found."}), 404
    return redirect(url_for("index"))


@app.after_request
def no_cache_api(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# --------------------------------------------------------------------------- #
# Jinja2 filter for parsing JSON strings in templates
@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value)
    except Exception:
        return []


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
