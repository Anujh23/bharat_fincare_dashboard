"""
Fetch + normalize the 6 report APIs across 4 loan products.

Two schema families are merged into one canonical shape:
  - CP / LR  -> JSON body,   camelCase keys, numbers,   data[] + totals{}
  - ELI / NBL-> form body,    PascalCase keys, strings,   data[] OR data.records[]+summary{}
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import calendar
import glob
import json
import os
import tempfile
import certifi
import requests


def _build_ca_bundle():
    """certifi roots + any intermediate certs in ./certs/*.pem, combined into one PEM.

    Fixes hosts that serve an incomplete chain (Lending Rupee omits its GoDaddy G2
    intermediate). Unlike a platform trust store this works identically on Windows
    and on Render/Linux, with full certificate verification kept on.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    extras = sorted(glob.glob(os.path.join(here, "certs", "*.pem")))
    if not extras:
        return certifi.where()
    data = open(certifi.where(), "rb").read()
    for path in extras:
        data += b"\n" + open(path, "rb").read()
    out = os.path.join(tempfile.gettempdir(), "loan_dashboard_ca_bundle.pem")
    with open(out, "wb") as fh:
        fh.write(data)
    return out


CA_BUNDLE = _build_ca_bundle()

# ---------------------------------------------------------------- config
PRODUCTS = [
    {
        "key": "CP", "name": "Credit Pey", "color": "#4f46e5", "type": "json",
        "base": "https://app.creditpey.in/api",
        "endpoints": {
            "sanction":        "sanction-fresh-vs-repeated",
            "sanction_target": "sanction-target-vs-achivement",
            "branch_target":   "branch-wise-target-vs-achivement",
            "branch_fresh":    "branch-fresh-vs-repeated",
            "collection":      "collection-manager-report-api",
            "rm":              "rm-performance-api",
        },
    },
    {
        "key": "LR", "name": "Lending Rupee", "color": "#0d9488", "type": "json",
        "base": "https://app.lendingrupee.in/api",
        "endpoints": {
            "sanction":        "sanction-fresh-vs-repeated",
            "sanction_target": "sanction-target-vs-achivement",
            "branch_target":   "branch-wise-target-vs-achivement",
            "branch_fresh":    "branch-fresh-vs-repeated",
            "collection":      "collection-manager-report-api",
            "rm":              "rm-performance-api",
        },
    },
    {
        "key": "ELI", "name": "EveryDay Loan India", "color": "#ea580c", "type": "form",
        "base": "https://app.everydayloanindia.co.in/admin/ApiController",
        "endpoints": {
            "sanction":        "sanctionDashboardApi",
            "sanction_target": "sanctionTargetVsAchievementApi",
            "branch_target":   "branchTargetVsAchievementApi",
            "branch_fresh":    "freshVsRepeatedBranchApi",
            "collection":      "collectionManagerReportApi",
        },
    },
    {
        "key": "NBL", "name": "NextBig Loan", "color": "#9333ea", "type": "form",
        "base": "https://app.nextbigloan.co.in/admin/ApiController",
        "endpoints": {
            "sanction":        "sanctionDashboardApi",
            "sanction_target": "sanctionTargetVsAchievementApi",
            "branch_target":   "branchTargetVsAchievementApi",
            "branch_fresh":    "freshVsRepeatedBranchApi",
            "collection":      "collectionManagerReportApi",
        },
    },
]

TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "30"))

# ELI / NBL sit behind a WAF that 403s the default "python-requests" User-Agent.
# A normal browser UA is required; harmless for CP/LR.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
}

# ---------------------------------------------------------------- helpers
def num(v):
    """Coerce numbers-as-strings ('155000.00'), None, '' -> float."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def pick(row, *keys, default=None):
    """Case-insensitive lookup over candidate key names."""
    lower = {k.lower(): val for k, val in row.items()}
    for k in keys:
        if k.lower() in lower:
            return lower[k.lower()]
    return default


def loads_lenient(text):
    """Parse JSON even when the server prepends PHP notices / HTML before the body.

    ELI & NBL intermittently echo a mysqli 'Runtime Notice' <div> ahead of the
    real JSON (HTTP 200, content-type application/json). Scan for the first '{'
    or '[' that decodes to a complete JSON value and return it.
    """
    try:
        return json.loads(text)
    except ValueError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                obj, _ = dec.raw_decode(text, i)
                return obj
            except ValueError:
                continue
    raise ValueError("no JSON value found in response")


def records_of(payload):
    """data may be a bare list, or {records:[...], summary:{...}}."""
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("records", []) or []
    return []


# ---------------------------------------------------------------- row normalizers
def n_sanction(r):
    return {
        "name":         pick(r, "displayName", "SanctionOfficer", "name"),
        "fresh_cases":  num(pick(r, "freshCases", "FreshCases")),
        "fresh_amount": num(pick(r, "freshLoanAmount", "LoanAmount")),   # ELI/NBL LoanAmount = fresh
        "repeat_cases": num(pick(r, "repeatCases", "RepeatCases")),
        "repeat_amount":num(pick(r, "repeatLoanAmount", "RepeatLoanAmount")),
        "total_cases":  num(pick(r, "grandTotalCases", "GrandTotalCases")),
        "total_amount": num(pick(r, "grandTotalLoanAmount", "GrandTotalLoanAmount")),
    }


def n_sanction_target(r):
    return {
        "name":        pick(r, "displayName", "SancationName", "SanctionOfficer", "name"),
        "target":      num(pick(r, "target", "Target")),
        "achievement": num(pick(r, "achievement", "currentMonthloanAmount", "Achievement")),
        "ach_pct":     num(pick(r, "achievementPercentage", "Achievementper")),
        "deficit":     num(pick(r, "deficit", "Deficit")),
    }


def n_branch_target(r):
    return {
        "branch":      pick(r, "branchName", "BranchName", "branch"),
        "target":      num(pick(r, "target", "Target")),
        "achievement": num(pick(r, "achievement", "Achievement")),
        "ach_pct":     num(pick(r, "achievementPercentage", "Achievementper")),
        "deficit":     num(pick(r, "deficit", "Deficit")),
    }


def n_branch_fresh(r):
    return {
        "branch":       pick(r, "branchName", "BranchName", "branch"),
        "fresh_cases":  num(pick(r, "freshCases", "FreshCases")),
        "fresh_amount": num(pick(r, "freshLoanAmount", "LoanAmount")),
        "repeat_cases": num(pick(r, "repeatCases", "RepeatCases")),
        "repeat_amount":num(pick(r, "repeatLoanAmount", "RepeatLoanAmount")),
        "total_cases":  num(pick(r, "grandTotalCases", "GrandTotalCases")),
        "total_amount": num(pick(r, "grandTotalLoanAmount", "GrandTotalLoanAmount")),
    }


def n_collection(r):
    return {
        "manager":          pick(r, "creditManager", "CreditManager", "manager"),
        "total_cases":      num(pick(r, "totalCases", "TotalCases")),
        "loan_amount":      num(pick(r, "loanAmount", "LoanAmount")),
        "repay_amount":     num(pick(r, "repayAmount", "RepayAmount")),
        "collected_amount": num(pick(r, "collectedAmount", "CollectedAmount")),
    }


def n_rm(r):
    return {
        "name":             pick(r, "rmName", "name"),
        "doc_received":     num(pick(r, "docReceived")),
        "fresh_converted":  num(pick(r, "freshConverted")),
        "amount_disbursed": num(pick(r, "amountDisbursed")),
    }


NORMALIZERS = {
    "sanction": n_sanction,
    "sanction_target": n_sanction_target,
    "branch_target": n_branch_target,
    "branch_fresh": n_branch_fresh,
    "collection": n_collection,
    "rm": n_rm,
}


# ---------------------------------------------------------------- fetch
def fetch_endpoint(product, key, from_date, to_date):
    ep = product["endpoints"].get(key)
    if not ep:
        return key, None, None            # product doesn't expose this API
    url = f"{product['base']}/{ep}"
    body = {"fromDate": from_date, "toDate": to_date}
    try:
        if product["type"] == "json":
            resp = requests.post(url, json=body, timeout=TIMEOUT, verify=CA_BUNDLE, headers=HEADERS)
        else:
            resp = requests.post(url, data=body, timeout=TIMEOUT, verify=CA_BUNDLE, headers=HEADERS)
        resp.raise_for_status()
        payload = loads_lenient(resp.text)
        rows = [NORMALIZERS[key](r) for r in records_of(payload)]
        return key, rows, None
    except Exception as exc:                # noqa: BLE001 - report, don't crash
        return key, None, str(exc)


def summarize(prod):
    sanction = prod.get("sanction") or []
    bt = prod.get("branch_target") or []
    st = prod.get("sanction_target") or []
    coll = prod.get("collection") or []

    tgt_rows = bt if bt else st            # fall back to officer targets if branch missing
    target = sum(r["target"] for r in tgt_rows)
    achievement = sum(r["achievement"] for r in tgt_rows)

    return {
        "disbursed":    sum(r["total_amount"] for r in sanction),
        "fresh_amount": sum(r["fresh_amount"] for r in sanction),
        "repeat_amount":sum(r["repeat_amount"] for r in sanction),
        "fresh_cases":  sum(r["fresh_cases"] for r in sanction),
        "repeat_cases": sum(r["repeat_cases"] for r in sanction),
        "total_cases":  sum(r["total_cases"] for r in sanction),
        "target":       target,
        "achievement":  achievement,
        "ach_pct":      (achievement / target * 100) if target else 0,
        "deficit":      target - achievement,
        "collected":    sum(r["collected_amount"] for r in coll),
        "officers":     len(sanction),
        "branches":     len(bt),
    }


def build_dashboard(from_date, to_date):
    """Fetch every product x endpoint in parallel, normalize, summarize."""
    jobs = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {}
        for prod in PRODUCTS:
            for key in prod["endpoints"]:
                futures[pool.submit(fetch_endpoint, prod, key, from_date, to_date)] = (prod["key"], key)
        results = {p["key"]: {} for p in PRODUCTS}
        errors = {p["key"]: {} for p in PRODUCTS}
        for fut in futures:
            pkey, ekey = futures[fut]
            k, rows, err = fut.result()
            if err:
                errors[pkey][k] = err
            results[pkey][k] = rows or []

    products_out = []
    for prod in PRODUCTS:
        entry = {
            "key": prod["key"], "name": prod["name"], "color": prod["color"], "type": prod["type"],
            "errors": errors[prod["key"]],
        }
        for key in ("sanction", "sanction_target", "branch_target", "branch_fresh", "collection", "rm"):
            entry[key] = results[prod["key"]].get(key, []) if key in prod["endpoints"] else None
        entry["summary"] = summarize(entry)
        products_out.append(entry)

    # consolidated totals
    tot_target = sum(p["summary"]["target"] for p in products_out)
    tot_ach = sum(p["summary"]["achievement"] for p in products_out)
    totals = {
        "disbursed":   sum(p["summary"]["disbursed"] for p in products_out),
        "target":      tot_target,
        "achievement": tot_ach,
        "ach_pct":     (tot_ach / tot_target * 100) if tot_target else 0,
        "deficit":     tot_target - tot_ach,
        "collected":   sum(p["summary"]["collected"] for p in products_out),
        "fresh_cases": sum(p["summary"]["fresh_cases"] for p in products_out),
        "repeat_cases":sum(p["summary"]["repeat_cases"] for p in products_out),
        "total_cases": sum(p["summary"]["total_cases"] for p in products_out),
    }

    return {"products": products_out, "totals": totals,
            "meta": {"from": from_date, "to": to_date}}


# ================================================================ executive board
PRODUCT_MAP = {p["key"]: p for p in PRODUCTS}

# the two comparison pairs the board toggles between
PAIRS = {
    "eli_nbl": ["ELI", "NBL"],
    "lr_cp":   ["LR", "CP"],
}


def daily_total(pkey, day_iso):
    """Disbursed amount for a single day (sum of sanction rows' grand total)."""
    prod = PRODUCT_MAP[pkey]
    _, rows, err = fetch_endpoint(prod, "sanction", day_iso, day_iso)
    if err or not rows:
        return 0.0
    return sum(r["total_amount"] for r in rows)


def _product_block(pkey, ms_iso, to_iso, days, days_iso, days_left):
    prod = PRODUCT_MAP[pkey]
    _, bt, bt_err = fetch_endpoint(prod, "branch_target", ms_iso, to_iso)
    _, st, st_err = fetch_endpoint(prod, "sanction_target", ms_iso, to_iso)
    _, sc, sc_err = fetch_endpoint(prod, "sanction", ms_iso, to_iso)
    _, cm, cm_err = fetch_endpoint(prod, "collection", ms_iso, to_iso)
    bt = bt or []
    st = st or []
    sc = sc or []
    cm = cm or []

    # Target & achievement come from sanctionTargetVsAchievementApi (officer roll-up).
    # branch_target is kept only for the per-branch leaderboard below.
    target = sum(r["target"] for r in st)
    achievement = sum(r["achievement"] for r in st)
    loans = int(sum(r["total_cases"] for r in sc))
    remaining = max(target - achievement, 0)

    ranked = sorted(bt, key=lambda r: r["achievement"], reverse=True)
    top_branches = [{"branch": r["branch"], "amount": r["achievement"],
                     "target": r["target"], "pct": r["ach_pct"]} for r in ranked[:6]]

    # top credit managers by loan amount handled
    cm_ranked = sorted(cm, key=lambda r: r["loan_amount"], reverse=True)
    top_cms = [{"name": r["manager"], "amount": r["loan_amount"],
                "cases": int(r["total_cases"]), "collected": r["collected_amount"]}
               for r in cm_ranked[:3]]

    # per-day disbursement series
    daily = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(daily_total, pkey, di): i for i, di in enumerate(days_iso)}
        for f in futs:
            daily[futs[f]] = f.result()
    daily_series = [{"day": days[i], "date": days_iso[i], "amount": daily.get(i, 0.0)}
                    for i in range(len(days_iso))]

    return {
        "key": pkey, "name": prod["name"],
        "target": target, "achievement": achievement,
        "pct": (achievement / target * 100) if target else 0,
        "loans": loans, "remaining": remaining,
        "need_per_day": (remaining / days_left) if days_left else 0,
        "top_branches": top_branches,
        "top_cms": top_cms,
        "daily": daily_series,
        "errors": {k: v for k, v in (("sanction_target", st_err), ("branch_target", bt_err), ("sanction", sc_err), ("collection", cm_err)) if v},
    }


def build_board(pair_key, ref_today=None):
    """Executive board data for a product pair, current month to date."""
    keys = PAIRS.get(pair_key, PAIRS["eli_nbl"])
    today = ref_today or date.today()
    dim = calendar.monthrange(today.year, today.month)[1]
    month_start = today.replace(day=1)
    day_nums = list(range(1, today.day + 1))
    days_iso = [today.replace(day=d).isoformat() for d in day_nums]
    ms_iso, to_iso = month_start.isoformat(), today.isoformat()
    days_left = dim - today.day + 1          # inclusive of today

    with ThreadPoolExecutor(max_workers=2) as pool:
        blocks = list(pool.map(
            lambda k: _product_block(k, ms_iso, to_iso, day_nums, days_iso, days_left), keys))

    ctarget = sum(b["target"] for b in blocks)
    cach = sum(b["achievement"] for b in blocks)
    return {
        "pair": pair_key, "keys": keys,
        "today": to_iso, "days_in_month": dim, "days_left": days_left, "day_of_month": today.day,
        "company": {"target": ctarget, "achievement": cach,
                    "pct": (cach / ctarget * 100) if ctarget else 0,
                    "remaining": max(ctarget - cach, 0)},
        "products": blocks,
    }
