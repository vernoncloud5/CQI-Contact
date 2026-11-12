#!/usr/bin/env python3
"""Extra public bid sources for CQI's bid finder.

Exposes SOURCES = {name: fn(keywords, min_due_date) -> list[dict]}.
Each dict has: source, number, title, agency, city, state, posted, due,
set_aside, type, url, matched_keyword.

Rules this module follows:
  * Python 3 stdlib only; runs under `python3 -I`.
  * Only public pages that work without a login. No CAPTCHA/Cloudflare
    work-arounds, no browser impersonation (honest User-Agent), and only
    paths that the site's robots.txt does not disallow.
  * Every source fails soft (returns [] on any error) and stops issuing
    requests after ~55 s.

Survey notes and the list of sources that were checked but are blocked or
need a login live in bid-sources.md next to this file.

Run directly to test:  python3 -I bid_sources_extra.py [source ...] [-k kw,kw] [-d YYYY-MM-DD]
"""

import base64
import datetime as _dt
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "CQI-BidFinder/1.0 (small-business public bid search)"
TIME_BUDGET = 55.0  # seconds per source

DEFAULT_KEYWORDS = [
    "janitorial", "custodial", "laundry", "linen", "refuse", "recycling",
    "solid waste", "septic", "pump-out", "portable toilet", "shredding",
    "pest control", "grounds maintenance", "landscap", "mowing", "hauling",
    "armored car",
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

class Budget:
    def __init__(self, seconds=TIME_BUDGET):
        self.end = time.time() + seconds

    def left(self):
        return self.end - time.time()

    def ok(self, need=3.0):
        return self.left() > need


def _opener(cookies=True):
    handlers = []
    if cookies:
        handlers.append(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op = urllib.request.build_opener(*handlers)
    op.addheaders = [("User-Agent", UA), ("Accept-Language", "en-US,en;q=0.8")]
    return op


def _fetch(op, url, data=None, headers=None, budget=None, timeout=25, raw=False):
    if budget is not None:
        timeout = max(3.0, min(timeout, budget.left()))
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    elif isinstance(data, str):
        data = data.encode()
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with op.open(req, timeout=timeout) as r:
            b = r.read()
    except (urllib.error.URLError, ConnectionError) as e:
        # one polite retry on a dropped connection (not on HTTP errors such as 403)
        if isinstance(e, urllib.error.HTTPError) or (budget is not None and not budget.ok(8)):
            raise
        time.sleep(2)
        with op.open(req, timeout=timeout) as r:
            b = r.read()
    if raw:
        return b
    return b.decode("utf-8", "replace")


def _text(s):
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _date(s):
    """Best-effort parse of many date formats to 'YYYY-MM-DD' ('' if none)."""
    if not s:
        return ""
    s = str(s).strip()
    m = re.search(r"/Date\((\d+)", s)
    if m:
        return _dt.datetime.fromtimestamp(int(m.group(1)) / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return "%s-%s-%s" % m.groups()
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        mo, d, y = (int(x) for x in m.groups())
        if y < 100:
            y += 2000
        try:
            return _dt.date(y, mo, d).isoformat()
        except ValueError:
            return ""
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1)[:3].lower() in _MONTHS:
        try:
            return _dt.date(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2))).isoformat()
        except ValueError:
            return ""
    return ""


def _match(text, keywords):
    t = (text or "").lower()
    for k in keywords:
        if k and k.lower() in t:
            return k
    return ""


def _rec(source, **kw):
    r = {k: "" for k in ("source", "number", "title", "agency", "city", "state", "posted",
                         "due", "set_aside", "type", "url", "matched_keyword")}
    r["source"] = source
    for k, v in kw.items():
        if k in r:
            r[k] = (v if isinstance(v, str) else ("" if v is None else str(v))).strip()
    for k in ("posted", "due"):  # drop placeholder dates like 9999-09-09 / 2099-12-31
        if r[k] and not ("2000" <= r[k] < "2090"):
            r[k] = ""
    if len(r["state"]) > 2:
        r["state"] = _STATE_ABBR.get(r["state"].lower(), r["state"])
    return r


def _keep(r, min_due):
    """Keep if due date unknown or on/after min_due."""
    return not r["due"] or not min_due or r["due"] >= min_due


def _dedupe(rows):
    seen, out = set(), []
    for r in rows:
        k = (r["source"], r["number"], r["title"]) if (r["number"] or r["title"]) else (r["source"], r["url"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _soft(fn):
    """Wrap a source so it never raises."""
    def wrapper(keywords, min_due_date):
        try:
            kws = [k.strip() for k in (keywords or DEFAULT_KEYWORDS) if k and k.strip()]
            # accept a date/datetime or an ISO string
            min_due_date = str(min_due_date)[:10] if min_due_date else ""
            rows = fn(kws, min_due_date)
            return _dedupe([r for r in rows if _keep(r, min_due_date)])
        except Exception as e:  # noqa: BLE001 - fail soft by design
            if "--debug" in sys.argv:
                import traceback
                traceback.print_exc()
            sys.stderr.write("[bid_sources_extra] %s failed: %s: %s\n" % (fn.__name__, type(e).__name__, e))
            return []
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# --------------------------------------------------------------------------
# Periscope BuySpeed (BSO) portals: keyword search of open ("Sent") bids
# --------------------------------------------------------------------------

BSO_SITES = {
    "ma_commbuys": ("https://www.commbuys.com", "MA", "COMMBUYS (MA state + cities, towns, schools, housing authorities)"),
    "il_bidbuy": ("https://www.bidbuy.illinois.gov", "IL", "Illinois BidBuy"),
    "nj_njstart": ("https://www.njstart.gov", "NJ", "NJSTART"),
    "nv_epro": ("https://nevadaepro.com", "NV", "NevadaEPro (state + local)"),
    "or_oregonbuys": ("https://oregonbuys.gov", "OR", "OregonBuys (state + local)"),
    "ar_arbuy": ("https://arbuy.arkansas.gov", "AR", "ARBuy"),
    "pa_philadelphia": ("https://www.phlcontracts.phila.gov", "PA", "PHLContracts (City of Philadelphia)"),
}


def _bso_rows(fragment, base, state, source, kw, keywords):
    out = []
    for tr in re.findall(r'<tr data-ri="\d+".*?</tr>', fragment, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 8:
            continue
        cells = [_text(c) for c in tds]
        href = re.search(r'href="([^"]+)"', tds[0])
        url = urllib.parse.urljoin(base, html.unescape(href.group(1))) if href else base
        title = cells[6]
        out.append(_rec(source, number=cells[0], title=title, agency=cells[2], state=state,
                        due=_date(cells[7]), type="Bid", url=url,
                        matched_keyword=_match(title, keywords) or kw))
    return out


def _bso(source, base, state, keywords, min_due):
    b = Budget()
    op = _opener()
    page = _fetch(op, base + "/bso/view/search/external/advancedSearchBid.xhtml?openBids=true", budget=b)
    csrf = re.search(r'name="_csrf" value="([^"]+)"', page).group(1)
    vs = re.search(r'name="javax.faces.ViewState"[^>]*value="([^"]+)"', page).group(1)
    rc = re.search(r'searchNew = function\(\) \{return PrimeFaces.ab\(\{s:"([^"]+)"', page).group(1)
    post_url = base + "/bso/view/search/external/advancedSearchBid.xhtml"
    hdr = {"Faces-Request": "partial/ajax", "X-Requested-With": "XMLHttpRequest",
           "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    out = []
    for kw in keywords:
        if not b.ok(4):
            break
        data = {"bidSearchForm": "bidSearchForm", "_csrf": csrf, "bidSearchForm:desc": kw,
                "bidSearchForm:status": "2BS", "javax.faces.ViewState": vs,
                "javax.faces.partial.ajax": "true", "javax.faces.source": rc,
                "javax.faces.partial.execute": "@all", "javax.faces.partial.render": "advSearchResults",
                rc: rc}
        r = _fetch(op, post_url, data=data, headers=hdr, budget=b)
        m = re.search(r'ViewState:0"><!\[CDATA\[([^\]]+)\]\]>', r)
        if m:
            vs = m.group(1)
        out += _bso_rows(r, base, state, source, kw, keywords)
        total = re.search(r"rowCount:(\d+)", r)
        total = int(total.group(1)) if total else 0
        first = 25
        while first < min(total, 100) and b.ok(4):  # at most 4 pages per keyword
            pdata = {"javax.faces.partial.ajax": "true",
                     "javax.faces.source": "bidSearchResultsForm:bidResultId",
                     "javax.faces.partial.execute": "bidSearchResultsForm:bidResultId",
                     "javax.faces.partial.render": "bidSearchResultsForm:bidResultId",
                     "bidSearchResultsForm:bidResultId_pagination": "true",
                     "bidSearchResultsForm:bidResultId_first": str(first),
                     "bidSearchResultsForm:bidResultId_rows": "25",
                     "bidSearchResultsForm": "bidSearchResultsForm",
                     "javax.faces.ViewState": vs, "_csrf": csrf}
            r = _fetch(op, post_url, data=pdata, headers=hdr, budget=b)
            out += _bso_rows(r, base, state, source, kw, keywords)
            first += 25
    return out


def _make_bso(name, base, state):
    def fn(keywords, min_due):
        return _bso(name, base, state, keywords, min_due)
    fn.__name__ = name
    return _soft(fn)


# --------------------------------------------------------------------------
# Ivalua public RFx browse (Arizona APP, NYC PASSPort)
# --------------------------------------------------------------------------

IVALUA_SITES = {
    "az_app": ("https://app.az.gov", "AZ", ""),
    "nyc_passport": ("https://passport.cityofnewyork.us", "NY", "New York"),
}


def _form_fields(page, form_id="mainForm"):
    i = page.find('id="%s"' % form_id)
    f = page[i:] if i >= 0 else page
    j = f.find("</form>")
    f = f[:j] if j > 0 else f
    data = {}
    for m in re.finditer(r"<input\b[^>]*>", f):
        s = m.group(0)
        n = re.search(r'name="([^"]*)"', s)
        if not n:
            continue
        ty = re.search(r'type="([^"]*)"', s)
        ty = (ty.group(1) if ty else "text").lower()
        if ty in ("radio", "checkbox", "button", "submit", "image"):
            continue
        v = re.search(r'value="([^"]*)"', s)
        data[n.group(1)] = html.unescape(v.group(1)) if v else ""
    return data


def _ivalua(source, base, state, city, keywords, min_due):
    b = Budget()
    op = _opener()
    url = base + "/page.aspx/en/rfp/request_browse_public"
    page = _fetch(op, url, budget=b)
    base_fields = {k: v for k, v in _form_fields(page).items() if ":grd:tr_" not in k}
    out = []
    for kw in keywords:
        if not b.ok(4):
            break
        d = dict(base_fields)
        d["body:x:txtQuery"] = kw
        d["body:x:selStatusCode_1"] = "val"  # "Open for Bidding" / "Released"
        d["__EVENTTARGET"] = "body:x:prxFilterBar:x:cmdSearchBtn"
        d["__EVENTARGUMENT"] = ""
        r = _fetch(op, url, data=d, budget=b)
        heads = []
        th = re.search(r'<thead.*?</thead>', r[r.find('id="body_x_grid_grd"'):], re.S)
        if th:
            heads = [_text(x).lower() for x in re.findall(r"<th[^>]*>(.*?)</th>", th.group(0), re.S)]
        for tr in re.findall(r'<tr id="body_x_grid_grd_tr_\d+".*?</tr>', r, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            cells = [_text(c) for c in tds]
            # agency cells hold <li> lists: keep the first entry only
            first_li = [(_text(re.search(r"<li>(.*?)</li>", c, re.S).group(1)) if "<li>" in c else _text(c)) for c in tds]
            hs = heads[:len(cells)]

            def pick(*names):
                for n in names:  # name priority first, then first non-empty column
                    for i, h in enumerate(hs):
                        if n in h:
                            if first_li[i]:
                                return first_li[i]
                return ""

            def pick_date(*names):
                # several columns can share a name (hidden placeholders like 12/31/2099):
                # take the last real date among the matching columns
                vals = [_date(first_li[i]) for n in names for i, h in enumerate(hs) if h.startswith(n)]
                vals = [v for v in vals if v and v < "2100"]
                return vals[-1] if vals else ""
            title = pick("label", "procurement name", "name", "title")
            status = pick("status", "rfx status")
            if status and not re.search(r"open|bidding|released|active", status, re.I):
                continue
            link = re.search(r'href="(/page\.aspx/en/[^"]+)"', tr)
            out.append(_rec(source, number=pick("code", "epin"), title=title,
                            agency=pick("agency", "organization"), city=city, state=state,
                            posted=pick_date("begin", "release"),
                            due=pick_date("end (", "due"),
                            type=pick("procurement method", "rfp type") or "RFx",
                            url=(base + html.unescape(link.group(1))) if link else url,
                            matched_keyword=_match(title + " " + pick("commodity"), keywords)))
    # the portal's quick search also hits program names; keep only real matches
    return [r for r in out if r["matched_keyword"]]


def _make_ivalua(name, base, state, city):
    def fn(keywords, min_due):
        return _ivalua(name, base, state, city, keywords, min_due)
    fn.__name__ = name
    return _soft(fn)


# --------------------------------------------------------------------------
# Socrata open-data datasets of open solicitations
# --------------------------------------------------------------------------

def _soql(op, domain, dataset, params, budget):
    url = "https://%s/resource/%s.json?%s" % (domain, dataset, urllib.parse.urlencode(params))
    return json.loads(_fetch(op, url, budget=budget, headers={"Accept": "application/json"}))


def _kw_where(fields, keywords):
    ors = []
    for k in keywords:
        k = k.lower().replace("'", "''")
        for f in fields:
            ors.append("lower(%s) like '%%%s%%'" % (f, k))
    return "(" + " OR ".join(ors) + ")"


@_soft
def nyc_city_record(keywords, min_due):
    """NYC City Record Online (all NYC agencies incl. NYCHA, DOE, H+H)."""
    b, op = Budget(), _opener(False)
    since = min_due or _dt.date.today().isoformat()
    where = ("type_of_notice_description='Solicitation' AND due_date >= '%s' AND %s"
             % (since, _kw_where(["short_title", "additional_description_1"], keywords)))
    rows = _soql(op, "data.cityofnewyork.us", "dg92-zbpx",
                 {"$where": where, "$limit": 500, "$order": "start_date DESC"}, b)
    out = []
    for x in rows:
        title = x.get("short_title", "")
        out.append(_rec("nyc_city_record", number=x.get("request_id", ""), title=title,
                        agency=x.get("agency_name", ""), city="New York", state="NY",
                        posted=_date(x.get("start_date")), due=_date(x.get("due_date")),
                        type=x.get("selection_method_description", ""),
                        url="https://a856-cityrecord.nyc.gov/RequestDetail/%s" % x.get("request_id", ""),
                        matched_keyword=_match(title + " " + _text(x.get("additional_description_1", "")), keywords)))
    return out


@_soft
def la_ramp(keywords, min_due):
    """LA RAMP open bids (City of LA, LA County, LA-area agencies)."""
    b, op = Budget(), _opener(False)
    where = "stagename='Open' AND %s" % _kw_where(["title"], keywords)
    rows = _soql(op, "data.lacity.org", "hf3r-utnq", {"$where": where, "$limit": 500}, b)
    out = []
    for x in rows:
        title = x.get("title", "")
        u = x.get("url") or {}
        out.append(_rec("la_ramp", number=x.get("rampid", ""), title=title,
                        agency=x.get("department", ""), city="Los Angeles", state="CA",
                        posted=_date(x.get("bidpost")), due=_date(x.get("closedate")),
                        type=x.get("type", ""), url=u.get("url", "") if isinstance(u, dict) else str(u),
                        matched_keyword=_match(title, keywords)))
    return out


@_soft
def de_open_bids(keywords, min_due):
    """Delaware state open bids (data.delaware.gov mirror of mmp.delaware.gov)."""
    b, op = Budget(), _opener(False)
    rows = _soql(op, "data.delaware.gov", "2hnj-zwix",
                 {"$where": _kw_where(["contracttitle"], keywords), "$limit": 500}, b)
    out = []
    for x in rows:
        title = x.get("contracttitle", "")
        u = x.get("bidurl") or {}
        out.append(_rec("de_open_bids", number=x.get("contractnumber", ""), title=title,
                        agency=x.get("agencycode", ""), state="DE",
                        posted=_date(x.get("opendate")), due=_date(x.get("deadlinedate")),
                        type="Bid", url=u.get("url", "") if isinstance(u, dict) else str(u),
                        matched_keyword=_match(title, keywords)))
    return out


@_soft
def md_montgomery_county(keywords, min_due):
    """Montgomery County MD solicitations (open data)."""
    b, op = Budget(), _opener(False)
    where = "status='Active' AND %s" % _kw_where(["description"], keywords)
    rows = _soql(op, "data.montgomerycountymd.gov", "eeq6-nnwe", {"$where": where, "$limit": 500}, b)
    out = []
    for x in rows:
        title = x.get("description", "")
        out.append(_rec("md_montgomery_county", number=x.get("number", ""), title=title,
                        agency="Montgomery County MD - " + x.get("department", ""),
                        city="Rockville", state="MD",
                        posted=_date(x.get("issuancedate")), due=_date(x.get("closingdate")),
                        type=x.get("type", ""),
                        url="https://www.montgomerycountymd.gov/PRO/",
                        matched_keyword=_match(title, keywords)))
    return out


# --------------------------------------------------------------------------
# SBA SubNet: subcontracting opportunities posted by primes
# --------------------------------------------------------------------------

SUBNET_URL = "https://legacy.sba.gov/federal-contracting/contracting-guide/prime-subcontracting/subcontracting-opportunities"


@_soft
def sba_subnet(keywords, min_due):
    """SBA SubNet subcontracting opportunities (keyword search)."""
    b, op = Budget(), _opener(False)
    out = []
    for kw in keywords:
        if not b.ok(4):
            break
        page = _fetch(op, SUBNET_URL + "?" + urllib.parse.urlencode({"keyword": kw}), budget=b)
        for tr in re.findall(r"<tr>\s*<td headers=\"view-body-table-column\".*?</tr>", page, re.S):
            a = re.search(r'<span class="subnet_title"><a href="([^"]+)"[^>]*>(.*?)</a>', tr, re.S)
            if not a:
                continue
            biz = re.search(r'subnet_business_name">(.*?)</span>', tr, re.S)

            def td(name):
                m = re.search(r'headers="%s"[^>]*>(.*?)</td>' % name, tr, re.S)
                return _text(m.group(1)) if m else ""
            title = _text(a.group(2))
            body = _text(tr)
            out.append(_rec("sba_subnet", number=a.group(1).rsplit("/", 1)[-1], title=title,
                            agency=_text(biz.group(1)) if biz else "",
                            state=td("view-field-subnet-place-performance-table-column"),
                            due=_date(td("view-field-subnet-closing-timestamp-table-column")),
                            type="Subcontract (prime: " + (_text(biz.group(1)) if biz else "") + ")",
                            url=urllib.parse.urljoin(SUBNET_URL, a.group(1)),
                            matched_keyword=_match(body, keywords) or kw))
    return out


# --------------------------------------------------------------------------
# BidNet Direct public open-solicitation search (nationwide aggregator)
#   robots.txt: allows /public/solicitations/open, disallows ?page=/?sort=,
#   asks Crawl-delay: 5 -> one request per keyword, 5 s apart, first page only.
# --------------------------------------------------------------------------

_STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


@_soft
def bidnet_direct(keywords, min_due):
    """BidNet Direct public open solicitations (titles/dates public; documents need free login)."""
    b, op = Budget(), _opener()
    out = []
    for n, kw in enumerate(keywords):
        if n:
            if not b.ok(8):
                break
            time.sleep(5)  # robots.txt Crawl-delay
        page = _fetch(op, "https://www.bidnetdirect.com/public/solicitations/open?" +
                      urllib.parse.urlencode({"keywords": kw}), budget=b)
        for tr in re.findall(r'<tr\s+data-index="\d+".*?</tr>', page, re.S):
            a = re.search(r'href="([^"]+)"', tr)
            title = re.search(r'<span class="rowTitle">(.*?)</span>', tr, re.S)
            loc = re.search(r'<span class="location">(.*?)</span>', tr, re.S)
            pub = re.search(r'publicationDate.*?dateValue">(.*?)</span>', tr, re.S)
            close = re.search(r'closingDate.*?dateValue">(.*?)</span>', tr, re.S)
            if not (a and title):
                continue
            title = _text(title.group(1))
            st = _text(loc.group(1)) if loc else ""
            href = html.unescape(a.group(1)).split("?")[0]
            out.append(_rec("bidnet_direct", number=href.rstrip("/").rsplit("/", 1)[-1], title=title,
                            state=_STATE_ABBR.get(st.lower(), st),
                            posted=_date(pub.group(1)) if pub else "",
                            due=_date(close.group(1)) if close else "",
                            type="Bid", url=urllib.parse.urljoin("https://www.bidnetdirect.com", href),
                            matched_keyword=_match(title, keywords) or kw))
    return out


# --------------------------------------------------------------------------
# North Carolina eVP (state agencies, counties, cities, community colleges,
# universities, school districts)
# --------------------------------------------------------------------------

@_soft
def nc_evp(keywords, min_due):
    """NC electronic Vendor Portal solicitations (Power Pages entity grid)."""
    b, op = Budget(), _opener()
    page = _fetch(op, "https://evp.nc.gov/solicitations/", budget=b)
    lay = json.loads(base64.b64decode(html.unescape(
        re.search(r'data-view-layouts="([^"]+)"', page).group(1))))[0]
    grid_url = "https://evp.nc.gov" + html.unescape(re.search(r'data-get-url="([^"]+)"', page).group(1))
    tok = _fetch(op, "https://evp.nc.gov/_layout/tokenhtml", budget=b)
    tok = re.search(r'value="([^"]+)"', tok).group(1)
    out = []
    for kw in keywords:
        if not b.ok(4):
            break
        body = {"base64SecureConfiguration": lay["Base64SecureConfiguration"],
                "sortExpression": lay.get("SortExpression", ""), "search": kw, "page": 1,
                "pageSize": 100, "pagingCookie": "", "filter": None, "metaFilter": None,
                "nlSearchFilter": None, "timezoneOffset": 0, "customParameters": [],
                "entityName": lay["Configuration"]["EntityName"], "entityId": None}
        r = json.loads(_fetch(op, grid_url, data=json.dumps(body), budget=b, headers={
            "Content-Type": "application/json; charset=utf-8",
            "__RequestVerificationToken": tok, "X-Requested-With": "XMLHttpRequest"}))
        for rec in r.get("Records", []):
            a = {x["Name"]: x.get("DisplayValue") or "" for x in rec.get("Attributes", [])}
            if a.get("statuscode") and a["statuscode"].lower() != "open":
                continue
            title = a.get("evp_name", "")
            out.append(_rec("nc_evp", number=a.get("evp_solicitationnbr", ""), title=title,
                            agency=a.get("owningbusinessunit", ""), state="NC",
                            posted=_date(a.get("evp_posteddate")), due=_date(a.get("evp_opendate")),
                            type="Solicitation",
                            url="https://evp.nc.gov/solicitations/details/?id=" + a.get("evp_solicitationid", ""),
                            matched_keyword=_match(title + " " + a.get("evp_description", ""), keywords)))
    return [r for r in out if r["matched_keyword"]]


# --------------------------------------------------------------------------
# Washington WEBS bid calendar (state agencies + many local agencies)
# --------------------------------------------------------------------------

@_soft
def wa_webs(keywords, min_due):
    """Washington WEBS public bid calendar (single page of all current solicitations)."""
    b, op = Budget(), _opener()
    base = "https://pr-webs-vendor.des.wa.gov/"
    url = base + "BidCalendar.aspx"
    page = _fetch(op, url, budget=b)
    out, done = [], {"1"}

    def parse(p):
        for seg in re.split(r'<tr class="grid_item', p)[1:]:
            a = re.search(r'href="(Search_BidDetails\.aspx\?ID=\d+)">(.*?)</a>', seg, re.S)
            if not a:
                continue
            txt = _text(seg.split('<tr align="right">')[0])
            title = _text(a.group(2))
            kw = _match(txt, keywords)
            if not kw:
                continue
            ref = re.search(r"Ref#:\s*(\S+)", txt)
            dates = re.findall(r"\d{1,2}/\d{1,2}/\d{2}", txt)
            out.append(_rec("wa_webs", number=ref.group(1) if ref else a.group(1).split("=")[-1],
                            title=title, state="WA", due=_date(dates[0]) if dates else "",
                            type="Solicitation", url=base + a.group(1), matched_keyword=kw))
    parse(page)
    for _ in range(12):
        links = re.findall(r"__doPostBack\(&#39;(DataGrid1\$_ctl\d+\$_ctl\d+)&#39;,&#39;&#39;\)\">(\d+)</a>", page)
        nxt = [(t, n) for t, n in links if n not in done]
        if not nxt or not b.ok(5):
            break
        tgt, n = nxt[0]
        done.add(n)
        d = _form_fields(page, "Form1")
        d["__EVENTTARGET"], d["__EVENTARGUMENT"] = tgt, ""
        try:
            page = _fetch(op, url, data=d, budget=b, timeout=45)  # WEBS pages are slow (~20 s)
        except Exception:  # keep what we already have
            break
        parse(page)
    return out


# --------------------------------------------------------------------------
# Iowa DAS bid opportunities (JSON behind the public DataTable)
# --------------------------------------------------------------------------

@_soft
def ia_bids(keywords, min_due):
    """Iowa DAS active bid opportunities (state agencies + some local)."""
    b, op = Budget(), _opener(False)
    base = "https://bidopportunities.iowa.gov"
    d = json.loads(_fetch(op, base + "/Home/DT_HostedBidsSearch?agencyId=&enteredSearchText=",
                          data={"draw": "1", "start": "0", "length": "1000"}, budget=b))
    out = []
    for x in d.get("aaData", []):
        title = x.get("Solicitation") or ""
        kw = _match(title + " " + (x.get("Description") or ""), keywords)
        if not kw:
            continue
        out.append(_rec("ia_bids", number=x.get("BidNumber", ""), title=title,
                        agency=x.get("AgencyName", ""), state="IA",
                        posted=_date(x.get("EffectiveDate")), due=_date(x.get("ExpirationDate")),
                        type="Bid", url=base + "/Home/BidInfo?bidId=" + (x.get("ID") or ""),
                        matched_keyword=kw))
    return out


# --------------------------------------------------------------------------
# South Carolina Business Opportunities (state, counties, cities, schools,
# universities). /search is robots-disallowed, so read the category editions.
# --------------------------------------------------------------------------

SCBO_CATEGORIES = {"4": "Consultant/Professional", "5": "Environmental Remediation",
                   "8": "Maintenance/Repair", "11": "Services", "12": "Supplies"}


@_soft
def sc_scbo(keywords, min_due):
    """SCBO online edition (all active ads in service-type categories)."""
    b, op = Budget(), _opener(False)
    today = _dt.date.today().isoformat()
    out = []
    for c, cname in SCBO_CATEGORIES.items():
        if not b.ok(4):
            break
        url = "https://scbo.sc.gov/online-edition?c=%s-%s" % (c, today)
        page = _fetch(op, url, budget=b)
        # field labels sit in their own tags ("<strong>Ad Title:</strong>"): mark them
        marked = re.sub(r"<(strong|b|label|span|div)[^>]*>\s*([^<]{2,45}:)\s*</\1>",
                        lambda m: "\x01" + m.group(2) + "\x02", page)
        for blk in _text(marked).split("Print Ad")[:-1]:
            f = {}
            for lab, val in re.findall(r"\x01([^\x02]+)\x02([^\x01]*)", blk):
                f.setdefault(lab.strip().rstrip(":").lower(), val.strip())

            def fld(*names):
                for n in names:
                    if f.get(n):
                        return f[n]
                return ""
            title = fld("ad title", "project name")
            if not title:
                continue
            kw = _match(title + " " + fld("description"), keywords)
            if not kw:
                continue
            out.append(_rec("sc_scbo", number=fld("solicitation #", "project number"),
                            title=title, agency=fld("purchasing agent/entity", "agency/owner"),
                            state="SC", posted=_date(fld("ad publish date")),
                            due=_date(fld("bid/submittal due date", "quote due date & time")),
                            type=cname, url=url, matched_keyword=kw))
    return out


# --------------------------------------------------------------------------
# Louisiana LaPAC (state agencies, universities, parishes, New Orleans, RTA,
# school boards). The keyword search form needs a session, so read the
# service-type UNSPSC segment listings instead (~4 s per page).
# --------------------------------------------------------------------------

LAPAC_SEGMENTS = {"76000000": "Industrial cleaning services", "72000000": "Building/maintenance services",
                  "70000000": "Farming/forestry/landscape services", "77000000": "Environmental services",
                  "78000000": "Transportation/storage/mail services", "91000000": "Personal & domestic services",
                  "92000000": "Security/safety services", "83000000": "Public utilities services"}


@_soft
def la_lapac(keywords, min_due):
    """Louisiana LaPAC open bids in service segments."""
    b, op = Budget(), _opener(False)
    base = "https://wwwcfprd.doa.louisiana.gov/osp/lapac/"
    out = []
    for seg, sname in LAPAC_SEGMENTS.items():
        if not b.ok(6):
            break
        url = base + "dspBid.cfm?search=segment&term=" + seg
        page = _fetch(op, url, budget=b)
        for tr in re.findall(r'<tr class="(?:odd|even)Row">(.*?)</tr>', page, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) < 4:
                continue
            title = _text(re.split(r"<br", tds[1])[0])
            kw = _match(title, keywords)
            if not kw:
                continue
            pdf = re.search(r'href="(/osp/lapac/agency/pdf/[^"]+)"', tds[1])
            out.append(_rec("la_lapac", number=_text(tds[0]), title=title, agency="LaPAC: " + sname,
                            state="LA", posted=_date(_text(tds[2])), due=_date(_text(tds[3])),
                            type="Bid", url=("https://wwwcfprd.doa.louisiana.gov" + pdf.group(1)) if pdf else url,
                            matched_keyword=kw))
    return out


# --------------------------------------------------------------------------
# City of San Antonio bidding & contracting opportunities (home market)
# --------------------------------------------------------------------------

@_soft
def tx_san_antonio(keywords, min_due):
    """City of San Antonio open solicitations (all departments incl. Aviation, SWMD, Parks)."""
    b, op = Budget(), _opener()
    url = "https://webapp1.sanantonio.gov/BidContractOpps/Default.aspx"
    page = _fetch(op, url, budget=b)
    out, seen_pages = [], {1}

    def parse(p):
        for tr in re.findall(r"<tr>\s*<td><a href=\"(Content\.aspx\?id=\d+[^\"]*)\">(.*?)</a></td>(.*?)</tr>", p, re.S):
            href, name, rest = tr
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", rest, re.S)]
            name = _text(name)
            m = re.match(r"((?:[A-Z]{2,5} )?[\d-]{4,})\s+(.*)", name)
            num, title = (m.group(1), m.group(2)) if m else ("", name)
            dl = cells[4] if len(cells) > 4 else ""
            ext = re.search(r"Extended to\s*(\d{1,2}/\d{1,2}/\d{4})", dl)
            kw = _match(name, keywords)
            if kw:
                out.append(_rec("tx_san_antonio", number=num, title=title,
                                agency="City of San Antonio - " + (cells[1] if len(cells) > 1 else ""),
                                city="San Antonio", state="TX",
                                posted=_date(cells[2] if len(cells) > 2 else ""),
                                due=_date(ext.group(1) if ext else dl), type=cells[0] if cells else "",
                                url=urllib.parse.urljoin(url, html.unescape(href)), matched_keyword=kw))
    parse(page)
    for _ in range(8):
        pages = sorted({int(x) for x in re.findall(r"Page\$(\d+)", page)} - seen_pages)
        if not pages or not b.ok(5):
            break
        n = pages[0]
        seen_pages.add(n)
        d = _form_fields(page, "form1") if 'id="form1"' in page else _form_fields(page, "aspnetForm")
        tgt = re.search(r"__doPostBack\(&#39;([^&]+)&#39;,&#39;Page\$%d&#39;\)" % n, page)
        if not tgt:
            break
        d["__EVENTTARGET"] = tgt.group(1)
        d["__EVENTARGUMENT"] = "Page$%d" % n
        page = _fetch(op, url, data=d, budget=b)
        parse(page)
    return out


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

SOURCES = {}
for _n, (_base, _st, _desc) in BSO_SITES.items():
    SOURCES[_n] = _make_bso(_n, _base, _st)
for _n, (_base, _st, _city) in IVALUA_SITES.items():
    SOURCES[_n] = _make_ivalua(_n, _base, _st, _city)
SOURCES.update({
    "nc_evp": nc_evp,
    "wa_webs": wa_webs,
    "ia_bids": ia_bids,
    "sc_scbo": sc_scbo,
    "la_lapac": la_lapac,
    "nyc_city_record": nyc_city_record,
    "la_ramp": la_ramp,
    "de_open_bids": de_open_bids,
    "md_montgomery_county": md_montgomery_county,
    "tx_san_antonio": tx_san_antonio,
    "sba_subnet": sba_subnet,
    "bidnet_direct": bidnet_direct,
})


def _main(argv):
    names, kws, d = [], None, _dt.date.today().isoformat()
    it = iter(argv)
    for a in it:
        if a == "-k":
            kws = [x.strip() for x in next(it).split(",")]
        elif a == "-d":
            d = next(it)
        elif a == "--debug":
            pass
        else:
            names.append(a)
    for n in names or list(SOURCES):
        t = time.time()
        rows = SOURCES[n](kws or DEFAULT_KEYWORDS, d)
        print("%-22s %4d results  %5.1fs" % (n, len(rows), time.time() - t), flush=True)
        for r in rows[:int("5" if "--all" not in argv else "9999")]:
            print("    %s | %s | %s | due %s | %s" % (r["state"], r["agency"][:30], r["title"][:70], r["due"], r["matched_keyword"]))


if __name__ == "__main__":
    _main(sys.argv[1:])
