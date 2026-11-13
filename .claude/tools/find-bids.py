#!/usr/bin/env python3
"""find-bids.py: search public bid sources for work that fits CQI's service lines.

Stdlib only. Run with:  python3 -I .claude/tools/find-bids.py [options] > candidates.jsonl

Prints one JSON object per line (stdout):
  {source, number, title, agency, city, state, posted, due, set_aside, type,
   url, matched_keyword}
A per-source summary goes to stderr.

Sources built in:
  sam  SAM.gov public search API (no key). Detail endpoint adds set-aside, NAICS, place.
  tx   Texas ESBD (txsmartbuy.gov) public service behind the ESBD page.
  fl   Florida Vendor Bid System public search API.
Plug-in sources: if bid_sources_extra.py sits next to this file and defines a
SOURCES dict {name: function(keywords, min_due_date) -> list[dict]}, those are
added too (same dict keys as above).

Filters: due date >= today + --min-days; drops set-asides CQI cannot bid
(8(a), HUBZone, SDVOSB/VOSB, WOSB/EDWOSB, Indian/ISBEE); drops award notices,
justifications, special notices, sole-source intents; drops supply-only /
construction titles; dedupes by number; --exclude-file drops numbers (or SAM
opportunity ids) already on the campFIRE chart.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "cqi-find-bids/1.0 (python-urllib)"
TIMEOUT = 90

# Service lines from the CQI Agent Playbook (laundry/linen, janitorial, solid
# waste, groundskeeping, pressure washing, security, courier, staffing) plus
# the kinds of bids Vernon logs on campFIRE (septic, pump-out, shredding, mats,
# shop towels, snow removal, pest control, armored car, etc.).
DEFAULT_KEYWORDS = [
    # laundry / linen (812320, 812332)
    "laundry", "linen", "dry cleaning", "dry-cleaning", "uniform rental", "scrubs",
    "shop towel", "mat rental", "mop", "floor mat", "towel",
    # janitorial (561720)
    "janitorial", "custodial", "housekeeping", "cleaning services", "window cleaning",
    "carpet cleaning", "floor stripping", "floor care", "hood cleaning", "duct cleaning",
    "pressure washing", "power washing", "sanitation",
    # solid waste (562111, 562119)
    "solid waste", "refuse", "trash", "garbage", "recycling", "recycle", "waste removal",
    "waste disposal", "waste collection", "dumpster", "roll-off", "rolloff", "compactor",
    "hauling", "scrap metal", "medical waste", "grease trap", "used cooking oil",
    # septic / portable toilets
    "septic", "sewage", "pump out", "pumpout", "pumping", "portable toilet",
    "vault toilet", "porta-john", "porta john", "restroom cleaning",
    # shredding
    "shredding", "shred", "document destruction",
    # grounds (561730)
    "grounds maintenance", "groundskeeping", "landscaping", "landscape maintenance",
    "mowing", "lawn", "snow removal", "snow and ice", "tree trimming", "tree removal", "hazardous tree", "snow hauling", "snow plowing", "winter trucking", "vegetation",
    "herbicide", "weed",
    # pest
    "pest control", "pest management", "rodent", "termite",
    # security, courier, staffing (561612 via sub, 492110/492210, 561320)
    "security guard", "guard services", "unarmed guard", "armed guard", "armored car",
    "courier", "staffing",
    # other facility support (561210 / 561790 / 561990)
    "facility support", "facilities maintenance", "street sweeping", "parking lot sweeping",
    "trauma cleaning", "biohazard",
]

# CQI NAICS from Playbook + SAM reps (Agent Memory, Nov 8 2026)
CQI_NAICS = ["812332", "812320", "562111", "562119", "561720", "561730", "561210",
             "561320", "492210", "492110", "561790", "561990", "491110", "561612"]

# Set-aside codes CQI can bid (small business, full & open). Everything else drops.
OK_SET_ASIDES = {"", "NONE", "SBA", "SBP"}
SET_ASIDE_NAMES = {
    "": "", "NONE": "None (full & open)", "SBA": "Total Small Business",
    "SBP": "Partial Small Business", "8A": "8(a)", "8AN": "8(a) sole source",
    "HZC": "HUBZone", "HZS": "HUBZone sole source", "SDVOSBC": "SDVOSB",
    "SDVOSBS": "SDVOSB sole source", "WOSB": "WOSB", "WOSBSS": "WOSB sole source",
    "EDWOSB": "EDWOSB", "EDWOSBSS": "EDWOSB sole source", "VSA": "VOSB",
    "VSS": "VOSB sole source", "LAS": "Local Area Set-Aside", "IEE": "Indian Economic Enterprise",
    "ISBEE": "Indian Small Business Economic Enterprise", "BICIV": "Buy Indian",
}

# SAM notice types kept: o=Solicitation, k=Combined Synopsis/Solicitation,
# p=Presolicitation, r=Sources Sought.
SAM_NOTICE_TYPES = "o,k,p,r"

NOISE_TITLE = re.compile(
    r"\b(award notice|notice of award|justification|j\s*&\s*a|intent to (sole|award)|"
    r"sole[- ]source|brand name|special notice|cancel+ed|cancellation|notice of intent)\b",
    re.I)
# Supply-only or construction titles (the subcontract model is services).
OFF_MODEL_TITLE = re.compile(
    r"\b(supplies|products|chemicals|purchase of|procurement of|construction|renovat\w*|"
    r"design[- ]build|roofing|paving|hvac|install\w*|replacement|repair of|generators?|"
    r"vehicles?|trucks?|washers?|dryers?|equipment|software|it services|repairs?|renewal|"
    r"rehabilitation|overlay|reconstruct\w*|flatwork|pavement|slope|catalog|lockers|trailer|"
    r"cloud|fiber optic|telecommunications)\b"
    r"|^\s*\d{2,4}\s*--",  # SAM product FSC prefix (e.g. "45--COMPACTOR"): supply buy
    re.I)
# NIGP descriptions are broad; these keywords count only when they are in the title.
NIGP_WEAK = {"hauling", "recycle", "recycling", "grounds maintenance", "uniform rental",
             "towel", "mop", "lawn", "vegetation", "weed", "sanitation", "pumping"}

STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
    "guam": "GU", "virgin islands": "VI",
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def http_json(url, data=None, tries=3):
    """GET (or POST JSON when data is given) and parse JSON. Plain, honest headers."""
    body = None
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
            text = raw.decode("utf-8", "replace")
            if text.lstrip().startswith("<"):
                if re.search(r"Just a moment|captcha|cf-chl", text, re.I):
                    raise RuntimeError("blocked by bot protection (skipping)")
                raise RuntimeError("got HTML instead of JSON")
            return json.loads(text)
        except RuntimeError:
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as e:
            last = e
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404):
                break
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"request failed: {last}")


def norm_num(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def kw_regex(kw):
    k = re.escape(kw.lower()).replace(r"\ ", r"[\s-]*").replace(r"\-", r"[\s-]*")
    return re.compile(r"(?<![a-z])" + k, re.I)


def match_keyword(text, kw_res):
    for kw, rx in kw_res:
        if rx.search(text or ""):
            return kw
    return None


def guess_type(number, notice_type):
    nt = (notice_type or "").lower()
    if "sources sought" in nt:
        return "Sources Sought"
    if "presolicitation" in nt:
        return "Presolicitation"
    n = norm_num(number)
    # Federal PIIDs: 6-char office + 2-digit FY + type letter (Q/R/B) ...
    m = re.match(r"^[A-Z0-9]{6}\d{2}([QRB])", n) or re.match(r"^[A-Z0-9]{4,8}\d{2}([QRB])\d", n)
    if m:
        return {"Q": "RFQ", "R": "RFP", "B": "IFB"}[m.group(1)]
    if "combined" in nt:
        return "Combined Synopsis/Solicitation"
    return notice_type or "Solicitation"


def to_date(s):
    """Return a date from ISO strings or mm/dd/yyyy; None if blank/unparseable."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


# --------------------------------------------------------------------------- SAM
SAM_SEARCH = "https://sam.gov/api/prod/sgs/v1/search/"
SAM_DETAIL = "https://sam.gov/api/prod/opps/v2/opportunities/{}"


def sam_search(params, max_pages):
    out = []
    for page in range(max_pages):
        q = dict(index="opp", page=page, size=100, sort="-modifiedDate", mode="search",
                 is_active="true", notice_type=SAM_NOTICE_TYPES, **params)
        d = http_json(SAM_SEARCH + "?" + urllib.parse.urlencode(q))
        res = (d.get("_embedded") or {}).get("results") or []
        out.extend(res)
        tp = (d.get("page") or {}).get("totalPages", 0)
        if page + 1 >= tp or not res:
            break
    return out


def sam_detail(oid):
    try:
        d = http_json(SAM_DETAIL.format(oid))
    except RuntimeError as e:
        return {"_error": str(e)}
    d2 = d.get("data2") or {}
    sol = d2.get("solicitation") or {}
    pop = d2.get("placeOfPerformance") or {}
    naics = []
    for n in d2.get("naics") or []:
        naics.extend(n.get("code") or [])
    return {
        "set_aside": (sol.get("setAside") or "").upper(),
        "naics": naics,
        "pop_city": ((pop.get("city") or {}).get("name") or "").strip(),
        "pop_state": ((pop.get("state") or {}).get("code") or "").strip(),
        "pop_zip": (pop.get("zip") or "").strip(),
        "psc": d2.get("classificationCode") or "",
    }


def source_sam(keywords, min_due, args):
    kw_res = [(k, kw_regex(k)) for k in keywords]
    date_param = {} if args.include_undated else {"response_date.from": min_due.isoformat() + "-06:00"}
    raw = {}
    queries = [("q", k) for k in keywords] + [("naics", ",".join(CQI_NAICS))]
    for kind, val in queries:
        try:
            res = sam_search({kind: val, **date_param}, args.sam_pages if kind == "q" else args.sam_pages * 4)
        except RuntimeError as e:
            log(f"[sam] {kind}={val}: {e}")
            continue
        for r in res:
            rid = r.get("_id")
            if not rid or r.get("isCanceled"):
                continue
            ent = raw.setdefault(rid, {"r": r, "hits": set()})
            ent["hits"].add(f"{kind}:{val}")
    log(f"[sam] {len(raw)} unique notices from {len(queries)} queries")

    pre = []
    for rid, ent in raw.items():
        r = ent["r"]
        title = html.unescape(r.get("title") or "")
        ntype = ((r.get("type") or {}).get("value") or "")
        if NOISE_TITLE.search(title) or ntype.lower() in ("award notice", "justification", "special notice", "sale of surplus property", "intent to bundle requirements (dod-funded)"):
            continue
        due = to_date(r.get("responseDateActual") or r.get("responseDate"))
        if due and due < min_due:
            continue
        if not due and not args.include_undated:
            continue
        kw = match_keyword(title, kw_res)
        pre.append((rid, r, title, ntype, due, kw))

    details = {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(sam_detail, rid): rid for rid, *_ in pre}
        for f in cf.as_completed(futs):
            details[futs[f]] = f.result()

    out = []
    for rid, r, title, ntype, due, kw in pre:
        det = details.get(rid) or {}
        naics_hit = [n for n in det.get("naics", []) if n in CQI_NAICS]
        if not kw:
            if naics_hit and not args.strict_title:
                kw = "NAICS " + naics_hit[0]
            else:
                continue  # keyword only in description: too noisy
        sa = det.get("set_aside", "")
        org = r.get("organizationHierarchy") or []
        names = [o.get("name") for o in sorted(org, key=lambda o: o.get("level", 0)) if o.get("name")]
        agency = " / ".join(names[-2:]) if names else ""
        off = (org[-1].get("address") or {}) if org else {}
        city = det.get("pop_city") or (off.get("city") or "").title()
        state = det.get("pop_state") or (off.get("state") or "")
        out.append({
            "source": "sam",
            "number": (r.get("solicitationNumber") or "").strip(),
            "sam_id": rid,
            "title": title,
            "agency": agency,
            "city": city,
            "state": state,
            "posted": (r.get("publishDate") or "")[:10],
            "due": due.isoformat() if due else "",
            "set_aside": SET_ASIDE_NAMES.get(sa, sa),
            "set_aside_code": sa,
            "type": guess_type(r.get("solicitationNumber"), ntype),
            "url": f"https://sam.gov/opp/{rid}/view",
            "matched_keyword": kw,
            "naics": ",".join(det.get("naics", [])),
        })
    return out


# ---------------------------------------------------------------------- Texas
TX_SERVICE = "https://www.txsmartbuy.gov/app/extensions/CPA/CPAMain/1.0.0/services/ESBD.Service.ss"


def source_tx(keywords, min_due, args):
    kw_res = [(k, kw_regex(k)) for k in keywords]
    lines, page, total = [], 1, None
    while True:
        d = http_json(TX_SERVICE, {"lines": [], "page": page, "urlRoot": "esbd", "status": "1"})
        got = d.get("lines") or []
        lines.extend(got)
        total = d.get("totalRecordsFound", 0)
        per = d.get("recordsPerPage") or 24
        if not got or page * per >= total or page >= args.tx_pages:
            break
        page += 1
    log(f"[tx] {len(lines)} open ESBD postings read (of {total})")
    out = []
    for l in lines:
        title = html.unescape(l.get("title") or "")
        kw = match_keyword(title, kw_res) or match_keyword(
            l.get("nigpCodes") or "", [x for x in kw_res if x[0] not in NIGP_WEAK])
        if not kw:
            continue
        due = to_date(l.get("responseDue"))
        if not due or due < min_due:
            continue
        sid = (l.get("solicitationId") or "").strip()
        out.append({
            "source": "tx", "number": sid, "title": title,
            "agency": l.get("agencyName") or "", "city": "", "state": "TX",
            "posted": (to_date(l.get("postingDate")) or dt.date.min).isoformat().replace("0001-01-01", ""),
            "due": due.isoformat(), "set_aside": "", "type": guess_tx_type(sid, title),
            "url": "https://www.txsmartbuy.gov/esbd/" + urllib.parse.quote(sid),
            "matched_keyword": kw, "nigp": l.get("nigpCodes") or "",
        })
    return out


def guess_tx_type(sid, title):
    t = (sid + " " + title).upper()
    for pat, name in (("RFQ", "RFQ"), ("RFP", "RFP"), ("IFB", "IFB"), ("ITB", "IFB"),
                      ("RFO", "RFO"), ("RFI", "RFI"), ("RFA", "RFA")):
        if re.search(r"\b" + pat, t):
            return name
    return "Solicitation"


# --------------------------------------------------------------------- Florida
FL_SEARCH = "https://vendor.myfloridamarketplace.com/mfmp/pub/search/bids"
FL_TYPES_KEEP = {"4": "IFB", "5": "ITN", "6": "RFP", "8": "RFI", "9": "RSQ"}


def source_fl(keywords, min_due, args):
    kw_res = [(k, kw_regex(k)) for k in keywords]
    ads, page = [], 1
    while page <= 30:
        d = http_json(FL_SEARCH, {"pageSize": 100, "type": [], "status": ["OPEN"], "agency": [],
                                  "adNumber": "", "agencyAdvertisementNumber": "", "title": "",
                                  "publishedDate": "", "openDate": "", "endDate": "",
                                  "commodityCodes": [], "page": page})
        if not isinstance(d, list) or not d:
            break
        ads.extend(d)
        if len(d) < 100:
            break
        page += 1
    log(f"[fl] {len(ads)} open VBS advertisements read")
    out = []
    for a in ads:
        tid = str(a.get("typeId") or "")
        if tid not in FL_TYPES_KEEP:
            continue
        title = html.unescape(a.get("title") or "")
        kw = match_keyword(title, kw_res)
        if not kw:
            continue
        due = to_date(a.get("closeDate"))
        if not due or due < min_due:
            continue
        out.append({
            "source": "fl", "number": a.get("agencyAdNumber") or a.get("uniqueName") or "",
            "title": title, "agency": a.get("agency") or "", "city": "", "state": "FL",
            "posted": (a.get("publishDate") or "")[:10], "due": due.isoformat(),
            "set_aside": "", "type": FL_TYPES_KEEP[tid],
            "url": f"https://vendor.myfloridamarketplace.com/search/bids/detail/{a.get('advertisementId')}",
            "matched_keyword": kw,
        })
    return out


BUILTIN = {"sam": source_sam, "tx": source_tx, "fl": source_fl}


def load_extra():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bid_sources_extra.py")
    if not os.path.exists(path):
        return {}
    try:
        spec = importlib.util.spec_from_file_location("bid_sources_extra", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return dict(getattr(mod, "SOURCES", {}) or {})
    except Exception as e:  # never let a plug-in break the core run
        log(f"[extra] could not load bid_sources_extra.py: {e}")
        return {}


def main():
    ap = argparse.ArgumentParser(description="Find bids that fit CQI (prints JSON lines).")
    ap.add_argument("--sources", default="all", help="comma list (sam,tx,fl,<extra names>) or 'all'")
    ap.add_argument("--keywords", help="text file, one keyword per line (default: built-in list)")
    ap.add_argument("--states", help="comma list of 2-letter states to keep (blank state kept for multi-site)")
    ap.add_argument("--min-days", type=int, default=7, help="due date at least N days out (default 7)")
    ap.add_argument("--exclude-file", help="text file of solicitation numbers / SAM ids already on campFIRE")
    ap.add_argument("--max", type=int, default=0, help="stop after N candidates (0 = no limit)")
    ap.add_argument("--include-undated", action="store_true", help="keep SAM notices with no response date")
    ap.add_argument("--strict-title", action="store_true", help="SAM: require keyword in title (ignore NAICS-only hits)")
    ap.add_argument("--include-overseas", action="store_true", help="keep places of performance outside the US")
    ap.add_argument("--allow-off-model", action="store_true", help="keep supply/construction-looking titles")
    ap.add_argument("--sam-pages", type=int, default=3, help="max 100-row pages per SAM keyword (default 3)")
    ap.add_argument("--tx-pages", type=int, default=60, help="max ESBD pages (24 rows each)")
    args = ap.parse_args()

    keywords = DEFAULT_KEYWORDS
    if args.keywords:
        with open(args.keywords) as f:
            keywords = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    min_due = dt.date.today() + dt.timedelta(days=args.min_days)

    excl = set()
    if args.exclude_file:
        with open(args.exclude_file) as f:
            excl = {norm_num(l) for l in f if l.strip()}
    states = {s.strip().upper() for s in args.states.split(",")} if args.states else None

    extra = load_extra()
    available = dict(BUILTIN)
    for name, fn in extra.items():
        if name in available:
            log(f"[extra] '{name}' clashes with a built-in source; skipped")
            continue
        available[name] = (lambda f: (lambda kws, md, _a: f(kws, md)))(fn)
    wanted = list(available) if args.sources == "all" else [s.strip() for s in args.sources.split(",") if s.strip()]

    seen, stats, emitted = set(), {}, 0
    for name in wanted:
        fn = available.get(name)
        if not fn:
            log(f"[{name}] unknown source; available: {', '.join(available)}")
            continue
        st = stats.setdefault(name, {"raw": 0, "kept": 0, "error": ""})
        try:
            cands = fn(keywords, min_due, args) or []
        except Exception as e:
            st["error"] = str(e)[:200]
            log(f"[{name}] FAILED: {e}")
            continue
        st["raw"] = len(cands)
        for c in sorted(cands, key=lambda c: c.get("due") or "9999"):
            title = c.get("title") or ""
            if NOISE_TITLE.search(title):
                continue
            if not args.allow_off_model and OFF_MODEL_TITLE.search(title):
                continue
            sa = (c.get("set_aside_code") or c.get("set_aside") or "").upper()
            if c.get("source") == "sam":
                if sa not in OK_SET_ASIDES:
                    continue
            elif re.search(r"8\(A\)|HUBZONE|SDVOSB|VOSB|WOSB|INDIAN|ISBEE|VETERAN", sa):
                continue
            # set-aside named only in the title (any source)
            if re.search(r"\b(8\(a\)|hubzone|sdvosb|vosb|wosb|edwosb|isbee|indian (small )?business|"
                         r"buy indian|service[- ]disabled|veteran[- ]owned)\b", title, re.I):
                continue
            d = to_date(c.get("due"))
            if d and d < min_due:
                continue
            st_code = (c.get("state") or "").strip().upper()
            if not args.include_overseas and st_code and (not re.fullmatch(r"[A-Z]{2}", st_code)
                                                          or st_code in ("AP", "AE", "AA")):
                continue  # outside the US (embassies, overseas bases)
            if states and c.get("state") and c["state"].upper() not in states:
                continue
            key = norm_num(c.get("number")) or norm_num(c.get("url"))
            if key in seen or key in excl or norm_num(c.get("sam_id")) in excl:
                continue
            seen.add(key)
            c.pop("set_aside_code", None)
            print(json.dumps(c, ensure_ascii=False), flush=True)
            st["kept"] += 1
            emitted += 1
            if args.max and emitted >= args.max:
                break
        if args.max and emitted >= args.max:
            break
    log("[summary] " + json.dumps(stats))


if __name__ == "__main__":
    main()
