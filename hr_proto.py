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
INJECTION = re.compile(r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier)?\s*(instructions|rules)|admin mode|reveal\s+(your\s+|the\s+)?(system\s+)?prompt|print\s+all\s+payslips|list\s+every\s+employee|(show|print|list)\s+all\s+(the\s+)?(salaries|payslips)|pretend\s+(you\s+are|to\s+be)|you\s+are\s+now\s+(the\s+)?(admin|payroll)", re.I)
OTHER_PERSON = re.compile(r"\b(colleague|coworker|co-worker|teammate|manager|boss|someone|somebody|everyone|all (the )?employees?)\b.*\b(salary|pay|payslip|earn)|what\s+\w+\s+earns|\b(his|her|their)\s+(salary|payslip|pay)\b", re.I)
EMP_ID = re.compile(r"\bE\d{4}\b")
DENY = re.compile(r"(update|change|modify)\s+(my\s+)?(bank|salary|pan|address|tax regime)|approve (my|the) (loan|advance|exception)", re.I)

def input_filter(session, text):
    reasons = []
    if INJECTION.search(text): reasons.append("prompt_injection")
    if any(i != session.employee_id for i in EMP_ID.findall(text)) or OTHER_PERSON.search(text): reasons.append("other_person_request")
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

# ---------- retrieval over the synthetic policy corpus (TF-IDF, standard library only) ----------
import math, collections
POLICY = [
    ("LEAVE-2.1", "Casual leave: each employee receives 12 days of casual leave per calendar year, credited on 1 January. Casual leave cannot be carried forward; unused days lapse on 31 December."),
    ("LEAVE-3.2", "Earned leave: each employee earns 18 days of earned leave per year. Up to 30 unused days can be carried forward to the next year."),
    ("WFH-1.1", "Work from home: employees may work from home up to 8 days in a month with prior approval from the reporting manager."),
    ("REIMB-4.1", "Reimbursement: claims must be submitted within 30 days of the expense with receipts. Approved claims are paid with the next payroll."),
    ("PAY-5.1", "Payroll calendar: the payroll cut-off is the 20th of every month. Salary is credited on the last working day of the month."),
    ("TAX-6.1", "Tax declaration: investment declarations can be revised once per quarter. Tax deducted at source is recalculated from the next payroll after the revision is processed."),
    ("PF-7.1", "Provident fund: the employee contribution to provident fund is 12 percent of basic salary and is shown as a deduction on the payslip."),
]
_STOP = set("a an the is are do i my me can how many what and or of to in on for it be get when with about".split())
def _tok(t):
    out = []
    for w in re.findall(r"[a-z]+", t.lower()):
        if w in _STOP: continue
        if w.endswith("s") and len(w) > 3: w = w[:-1]
        out.append(w)
    return out
_DOCS = [(cid, _tok(txt), txt) for cid, txt in POLICY]
_DF = collections.Counter(w for _, toks, _ in _DOCS for w in set(toks))
def search_policy(query, top_k=1, threshold=0.12):
    q = collections.Counter(_tok(query)); n = len(_DOCS); hits = []
    for cid, toks, txt in _DOCS:
        d = collections.Counter(toks)
        w = lambda c, t: c[t] * (math.log((n + 1) / (_DF.get(t, 0) + 1)) + 1)
        num = sum(w(q, t) * w(d, t) for t in q if t in d)
        den = math.sqrt(sum(w(q, t) ** 2 for t in q)) * math.sqrt(sum(w(d, t) ** 2 for t in d)) or 1
        hits.append((num / den, cid, txt))
    hits = [h for h in sorted(hits, reverse=True) if h[0] >= threshold][:top_k]
    log("policy_search", query=query, hits=[h[1] for h in hits])
    return hits          # empty list means "not found"; the agent must say so

# ---------- sensitive-topic check and router (rule layer that runs before the model) ----------
SENSITIVE = re.compile(r"harass|bully|bullied|discriminat|threaten|abus(e|ed|ive)|grievance|legal action|forced to resign|molest", re.I)
def sensitive_check(text):
    hit = bool(SENSITIVE.search(text))
    if hit: log("sensitive_detected")
    return {"sensitive": hit, "priority": "high" if hit else "normal"}

MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
def route(text, year=2026):
    t = text.lower()
    month = next((n for k, n in MONTHS.items() if re.search(r"\b" + k, t)), None)
    payroll = bool(re.search(r"salary|payslip|pay\b|take-home|deduction|tds|net pay", t))
    lower = bool(re.search(r"lower|less|kam|reduced|dropped|why", t))
    leave = bool(re.search(r"leave|chutti", t))
    if sensitive_check(text)["sensitive"]: return {"route": "case", "intent": "grievance_sensitive"}
    if payroll and lower:
        if month is None: return {"route": "payroll", "intent": "payroll_variance", "needs_clarification": True,
                                  "question": "Which month's salary are you asking about?"}
        return {"route": "payroll", "intent": "payroll_variance", "needs_clarification": False,
                "months": (f"{year}-{month-1:02d}", f"{year}-{month:02d}")}
    return {"route": "leave" if leave else "policy", "intent": "leave_balance" if leave else "policy_faq"}
