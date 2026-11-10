"""Tool and guardrail layer of the HR helpdesk agent prototype (synthetic data only).
The LLM agents call these functions; the functions enforce identity scoping, arithmetic,
input filtering, deny-lists, retries and escalation in ordinary code."""
import re, sqlite3, datetime

AUDIT = []                      # append-only audit log (in memory for the prototype)
def log(event, **kw): AUDIT.append({"t": datetime.datetime.now().isoformat(timespec="seconds"), "event": event, **kw})

# ---------- synthetic database ----------
def build_db():
    db = sqlite3.connect(":memory:")
    db.executescript("""
    CREATE TABLE employees(employee_id TEXT PRIMARY KEY, grade TEXT, location TEXT);
    CREATE TABLE payslips(employee_id TEXT, month TEXT, basic INT, hra INT, special INT, reimbursement INT,
        gross INT, pf INT, pt INT, tds INT, total_deductions INT, net_pay INT);
    CREATE TABLE leave(employee_id TEXT, leave_type TEXT, entitlement INT, taken INT, balance INT);
    CREATE TABLE tickets(ticket_id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT, category TEXT,
        priority TEXT, summary TEXT, status TEXT);
    """)
    db.executemany("INSERT INTO employees VALUES(?,?,?)", [("E0042","G5","Hyderabad"),("E0107","G6","Pune"),("E0150","G4","Bengaluru")])
    P = lambda e,m,b,h,s,r,pf,pt,tds,net=None: (e,m,b,h,s,r,b+h+s+r,pf,pt,tds,pf+pt+tds,(b+h+s+r)-(pf+pt+tds) if net is None else net)
    db.executemany("INSERT INTO payslips VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [
        P("E0042","2026-09",40000,16000,20000,8000,4800,200,7580),
        P("E0042","2026-10",40000,16000,20000,0,4800,200,6130),
        P("E0107","2026-10",55000,22000,30000,0,6600,200,14200),
        P("E0150","2026-09",40000,16000,20000,0,4800,200,6130),
        P("E0150","2026-10",40000,16000,20000,0,4800,200,6130,net=59870),   # stored net does not match components
    ])
    db.executemany("INSERT INTO leave VALUES(?,?,?,?,?)", [("E0042","casual",12,5,7),("E0107","casual",12,2,10)])
    return db

class Session:
    def __init__(self, db, employee_id): self.db, self.employee_id = db, employee_id

# ---------- read-only tools (employee_id always comes from the session) ----------
def _own(session, employee_id):
    if employee_id and employee_id != session.employee_id:
        log("id_override_blocked", session=session.employee_id, attempted=employee_id)
    return session.employee_id

def get_payslip(session, month, employee_id=None):
    e = _own(session, employee_id)
    cur = session.db.execute("SELECT basic,hra,special,reimbursement,gross,pf,pt,tds,total_deductions,net_pay FROM payslips WHERE employee_id=? AND month=?", (e, month))
    r = cur.fetchone()
    if not r: return None
    k = ["basic","hra","special","reimbursement","gross","pf","pt","tds","total_deductions","net_pay"]
    log("tool_call", tool="get_payslip", employee=e, month=month)
    return dict(zip(k, r))

def compare_months(session, a, b):
    pa, pb = get_payslip(session, a), get_payslip(session, b)
    comp = ["basic","hra","special","reimbursement","pf","pt","tds"]
    earn = {"basic","hra","special","reimbursement"}
    changes = {c: pb[c]-pa[c] for c in comp if pb[c]-pa[c] != 0}
    net_diff = pb["net_pay"]-pa["net_pay"]
    explained = sum(v if c in earn else -v for c, v in changes.items())
    return {"changes": changes, "net_diff": net_diff, "explained": explained}

def arithmetic_check(result):                      # used by the Verifier
    return result["explained"] == result["net_diff"]

def get_leave_balance(session, leave_type, employee_id=None):
    e = _own(session, employee_id)
    r = session.db.execute("SELECT entitlement,taken,balance FROM leave WHERE employee_id=? AND leave_type=?", (e, leave_type)).fetchone()
    log("tool_call", tool="get_leave_balance", employee=e)
    return dict(zip(["entitlement","taken","balance"], r)) if r else None

def create_ticket(session, category, priority, summary):
    cur = session.db.execute("INSERT INTO tickets(employee_id,category,priority,summary,status) VALUES(?,?,?,?,'open')", (session.employee_id, category, priority, summary))
    log("ticket_created", ticket=cur.lastrowid, category=category, priority=priority)
    return cur.lastrowid

TOOLS = {"get_payslip": get_payslip, "compare_months": compare_months, "get_leave_balance": get_leave_balance, "create_ticket": create_ticket}
WRITE_TOOLS = {"create_ticket"}                    # no tool can change payroll, bank or personal data

# ---------- guardrails ----------
INJECTION = re.compile(r"ignore (all |any )?(previous|prior) instructions|admin mode|reveal (your |the )?(system )?prompt|print all payslips|list every employee", re.I)
EMP_ID = re.compile(r"\bE\d{4}\b")
DENY = re.compile(r"(update|change|modify)\s+(my\s+)?(bank|salary|pan|address|tax regime)|approve (my|the) (loan|advance|exception)", re.I)

def input_filter(session, text):
    reasons = []
    if INJECTION.search(text): reasons.append("prompt_injection")
    if any(i != session.employee_id for i in EMP_ID.findall(text)): reasons.append("other_person_request")
    if reasons: log("input_flagged", session=session.employee_id, reasons=reasons)
    return {"flagged": bool(reasons), "reasons": reasons}

def chunk_filter(text):                            # applied to retrieved policy text before the model sees it
    bad = bool(INJECTION.search(text))
    if bad: log("chunk_dropped", reason="instruction_in_document")
    return not bad

def deny_list(text):
    hit = bool(DENY.search(text))
    if hit: log("level3_blocked")
    return hit

def pii_scan(session, draft):
    others = [i for i in EMP_ID.findall(draft) if i != session.employee_id]
    long_digits = re.findall(r"\b\d{9,}\b", draft)
    return {"leak": bool(others or long_digits), "others": others, "digits": long_digits}

def with_retries(fn, retries=2):
    attempts = 0
    while True:
        attempts += 1
        try: return {"ok": True, "value": fn(), "attempts": attempts}
        except TimeoutError:
            log("tool_timeout", attempt=attempts)
            if attempts > retries: return {"ok": False, "attempts": attempts}
