# Public bid sources: survey and adapter catalog

Surveyed 2026-11-12 from a cloud container through an egress proxy, using an honest
User-Agent (`CQI-BidFinder/1.0`). Adapters live in `bid_sources_extra.py`
(`SOURCES` dict). Texas ESBD, Florida VBS, SAM.gov and DemandStar are handled in
`find-bids.py` and are not repeated here.

Rules we followed: public pages only (no login), no CAPTCHA or Cloudflare work-arounds,
no browser impersonation, and no paths that the site's robots.txt disallows.

Status key:
- **adapter**: works, and `bid_sources_extra.py` has an adapter for it
- **works**: public data reachable, but no adapter yet
- **blocked**: a WAF or bot check answered (Cloudflare challenge, AWS/CloudFront 403, "browser check" page, UA check)
- **robots**: robots.txt disallows the path, so we do not use it
- **login**: listings need an account
- **JS app**: listings only render through a JavaScript app with no public data URL we could confirm
- **unreachable**: DNS, TLS or proxy error from this environment (may work from an office PC)
- **not found**: the URL we tried was wrong or retired, and the current page was not located

## Live results (2026-11-12, default CQI keywords, due on/after today)

| Adapter | Results | Time |
|---|---|---|
| ma_commbuys | 21 | 14 s |
| il_bidbuy | 5 | 8 s |
| nj_njstart | 0 (14 for "service, maintenance, cleaning") | 6 s |
| nv_epro | 3 | 8 s |
| or_oregonbuys | 3 | 9 s |
| ar_arbuy | 0 (portal shows 0 open bids today) | 7 s |
| pa_philadelphia | 1 | 9 s |
| az_app | 2 | 6 s |
| nyc_passport | 0 (no matching open RFx today) | 8 s |
| nc_evp | 35 | 31 s |
| wa_webs | 1 (pages are slow, so it reads only 2 to 3 of about 6 pages) | 52 s |
| ia_bids | 0 (31 for "roof, tile, service, maintenance, cleaning") | 0.5 s |
| sc_scbo | 12 | 2 s |
| la_lapac | 3 | 12 s |
| nyc_city_record | 6 | 5 s |
| la_ramp | 4 | 0.4 s |
| de_open_bids | 1 | 5 s |
| md_montgomery_county | 7 | 0.3 s |
| tx_san_antonio | 1 | 1 s |
| sba_subnet | 19 | 4 s |
| bidnet_direct | 159 (nationwide; reads 1 page per keyword with a 5 s gap) | 50 s |

Total: about 290 matching open opportunities. Sources overlap: for example, BidNet Direct
repeats some NC, MA and VA items.

## State central portals (50 + DC)

| Source | Covers | Status | How | Notes |
|---|---|---|---|---|
| AL STAARS Vendor Self Service | Alabama state agencies | JS app | CGI Advantage VSS | Guessed URL 404; VSS is JS-only. Free vendor registration gives email alerts. |
| AK Online Public Notices / IRIS VSS | Alaska state | blocked | HTML | Notices search returns 403 with CAPTCHA; IRIS VSS needs a login. |
| AZ Arizona Procurement Portal (app.az.gov) | AZ state + cities (e.g. Chandler) and tribes | adapter `az_app` | Ivalua public RFx browse, form postback | Keyword search filtered to "Open for Bidding". |
| AR ARBuy | Arkansas state | adapter `ar_arbuy` | Periscope BuySpeed (BSO), JSF AJAX | Public list showed 0 open bids today. |
| CA Cal eProcure | California state | blocked | PeopleSoft | 403 from AWS ELB for non-browser clients. |
| CO Colorado VSS / osc.colorado.gov | Colorado state | blocked | CGI VSS (JS) | VSS is JS-only; the OSC page returns a CloudFront 403. |
| CT CTsource (WebProcure/Proactis) | Connecticut state + some towns | unreachable | Angular app plus JSON | Server TLS chain incomplete from here (needs AIA fetch); may work from a normal PC. |
| DE Delaware MMP (mmp.delaware.gov) | Delaware state | adapter `de_open_bids` | Socrata dataset 2hnj-zwix (open data) | Same data as MMP, as JSON. |
| DC OCP | District of Columbia | blocked | n/a | Cloudflare challenge. |
| FL Vendor Bid System | Florida | in find-bids.py | | Not repeated here. |
| GA Georgia Procurement Registry | Georgia state + many locals | blocked | DataTables JSON | Redirects non-browser User-Agents to "unsupported browser". |
| HI HANDS / HIePRO | Hawaii state + counties | blocked | n/a | 403 from AWS ELB. |
| ID Luma / purchasing.idaho.gov | Idaho state | JS app | Infor Luma supplier portal | Info page loads; bid list is inside Luma. Not verified. |
| IL BidBuy | Illinois state | adapter `il_bidbuy` | BSO | |
| IN IDOA Current Business Opportunities | Indiana state | works | HTML page | Page loads; table not parsed yet. Candidate for a later adapter. |
| IA bidopportunities.iowa.gov | Iowa state + some locals | adapter `ia_bids` | JSON (DataTables endpoint) | About 46 active bids, fetched in one call. |
| KS Supplier portal (PeopleSoft) | Kansas state | login | PeopleSoft | Redirects to login/error page. |
| KY eMARS VSS | Kentucky state | unreachable | CGI VSS | TLS hostname mismatch from here. |
| LA LaPAC | LA state, universities, parishes, New Orleans, RTA, school boards | adapter `la_lapac` | HTML lists by UNSPSC segment | 8 service segments, about 4 s each. The keyword form did not run without a session. |
| ME Maine BBM RFPs | Maine state | blocked | n/a | CloudFront 403. |
| MD eMMA | Maryland state + locals | blocked | Ivalua | Every request lands on a "Browser check" page. |
| MA COMMBUYS | MA state, towns, schools, housing authorities, transit | adapter `ma_commbuys` | BSO | About 930 open bids; largest BSO tenant. |
| MI SIGMA VSS | Michigan state | JS app | CGI VSS | |
| MN SWIFT supplier portal | Minnesota state | unreachable | PeopleSoft | Proxy 502; the mn.gov solicitations URL returns 404. |
| MS Bid search (ms.gov/dfa) | Mississippi state | blocked | n/a | Cloudflare challenge. |
| MO MissouriBUYS (MOVERS) | Missouri state | JS app | CGI Advantage | The bid-board page only links to the app. |
| MT eMACS / Jaggaer | Montana state | robots | Jaggaer public events | bids.sciquest.com robots.txt: Disallow: /. |
| NE DAS Materiel | Nebraska state | not found | HTML | bidopps.html returned a 105-byte stub. |
| NV NevadaEPro | Nevada state + locals | adapter `nv_epro` | BSO | Had occasional connection resets; the adapter retries once. |
| NH Statewide Bids (apps.das.nh.gov) | New Hampshire state | blocked | ASP.NET HTML | First request 200, later requests 403. |
| NJ NJSTART | New Jersey state | adapter `nj_njstart` | BSO | |
| NM GSD Active ITBs and RFPs | New Mexico state | works | WordPress HTML | Page loads; not parsed yet. |
| NY Contract Reporter | NY state, authorities, NYC agencies | login | n/a | Search results need a (free) NYSCR account. |
| NC eVP | NC state, counties, cities, community colleges, universities, school districts | adapter `nc_evp` | Power Pages entity-grid JSON | One of the richest sources: 35 matches today. |
| ND NDBuys | North Dakota state | JS app | n/a | Redirects to an OMB info page. |
| OH OhioBuys | Ohio state | blocked | Ivalua | "Browser check" page. |
| OK OMES Central Purchasing | Oklahoma state | works | HTML | Info page loads; the solicitation list was not located. |
| OR OregonBuys | OR state + locals (water districts, housing authorities) | adapter `or_oregonbuys` | BSO | |
| PA eMarketplace | Pennsylvania state | robots | ASP.NET | robots.txt: Disallow: /. Philadelphia is covered separately. |
| RI Ocean State Procures / RIDOP | Rhode Island state | blocked | Ivalua | Cloudflare on ridop.ri.gov; TLS hostname mismatch on the Ivalua host. |
| SC SCBO | SC state, counties, cities, schools, colleges | adapter `sc_scbo` | HTML "online edition" per category | /search is robots-disallowed, so the adapter reads 5 service categories. |
| SD ESM Posting Board | South Dakota state | JS app | ESM Solutions | Page is a 2.5 KB JS shell. |
| TN Central Procurement Office | Tennessee state | blocked | n/a | 403 from AWS ELB. |
| TX ESBD | Texas state + locals | in find-bids.py | | San Antonio city has its own adapter. |
| UT U3P (utah.bonfirehub.com) | Utah state + locals | robots | Bonfire JSON | Bonfire robots.txt: Disallow: /. |
| VT Vermont Business Registry / Bid System | Vermont state + towns | works (partly) | ASP.NET | vermontbusinessregistry.com BidSearch loads; vermontbidsystem.com gave proxy 502. Not parsed yet. |
| VA eVA | Virginia state + locals | blocked | n/a | AWS WAF challenge (HTTP 202). VA items do show up in BidNet Direct. |
| WA WEBS | WA state, universities, school districts, PUDs, transit | adapter `wa_webs` | ASP.NET grid, postback paging | About 20 s per page, so the adapter reads 2 to 3 of about 6 pages within 60 s. |
| WV wvOASIS / Purchasing Bids | West Virginia state | unreachable | CGI VSS | VSS returns 503; the Purchasing page is an archive of received bids. |
| WI VendorNet / eSupplier | Wisconsin state | JS app | n/a | VendorNet Bids.aspx 404; eSupplier is a JS shell. |
| WY Public Purchase | Wyoming state | login | Public Purchase | Public page has no rows; search returns 401. |

## Multi-agency platforms and aggregators

| Source | Covers | Status | How | Notes |
|---|---|---|---|---|
| Periscope BuySpeed (BSO) tenants | MA, IL, NJ, NV, OR, AR, Philadelphia | adapter (7) | JSF/PrimeFaces AJAX: one keyword search per keyword, status "Sent" | Same code for every tenant, so new tenants are one line in `BSO_SITES`. Baltimore CitiBuy gave a proxy 502. |
| Ivalua public RFx browse | AZ APP, NYC PASSPort | adapter (2) | Form postback with keyword + status "val" | MD eMMA and OhioBuys show a browser check, so they are not used. |
| BidNet Direct (public open solicitations) | Nationwide: about 25,000 open state and local bids | adapter `bidnet_direct` | HTML search `?keywords=` | robots.txt allows this path for `*` but disallows `?page=`/`?sort=` and asks Crawl-delay 5, so the adapter reads 1 page per keyword, 5 s apart. Bid documents need a free login. robots.txt also blocks named AI crawlers (ClaudeBot etc.); our tool identifies as CQI-BidFinder, run by CQI. |
| SBA SubNet | Subcontracting opportunities posted by large primes | adapter `sba_subnet` | Drupal view, `?keyword=` | Fits CQI's subcontracting model; many listings are construction. |
| Bonfire (*.bonfirehub.com) | Thousands of cities/counties/ISDs (Dallas, Utah U3P, ...) | robots | Public JSON endpoint exists | robots.txt Disallow: / on agency subdomains, so not used. |
| IonWave (*.ionwave.net) | Many TX cities and school districts, SC counties | robots | HTML | robots.txt Disallow: /. |
| Jaggaer / SciQuest public events | Universities (TAMU, ...), Montana | robots | HTML | robots.txt Disallow: /. |
| OpenGov Procurement | Phoenix and many cities | blocked | SPA | The portal answers with a Cloudflare challenge. A separate API host answered without one, but we did not use it because that would sidestep the challenge. |
| PlanetBids | Many CA/TX cities, ports, transit | blocked | Angular | AWS WAF challenge (HTTP 202). |
| Public Purchase | WY and many locals | login | n/a | Search returns 401. |
| ProcureWare | San Antonio-area and other agencies | blocked | n/a | 403 WAF. |
| VendorRegistry / VendorLink | Various | not usable | n/a | VendorRegistry is a marketing site; VendorLink gave proxy 502. |
| BidExpress (Infotech) | DOT construction lettings | login | n/a | Redirects to login. |
| Negometrix | (now Mercell, EU) | n/a | n/a | Not a US public bid source. |
| eBidExchange | Various | unreachable | n/a | Connection reset. |
| Periscope S2G / BidSync, GovSpend | Aggregators | login/paid | n/a | |
| WebProcure / Proactis | CT, legacy MissouriBUYS | unreachable | JSON | TLS chain problem from here. |
| CGI Advantage VSS | AL, AK, CO, KY, MI, MO, WV | JS app | n/a | No public data URL confirmed. |

## Open-data (Socrata) and city/county sources

| Source | Covers | Status | How | Notes |
|---|---|---|---|---|
| NYC City Record Online (dg92-zbpx) | All NYC agencies incl. NYCHA, DOE, H+H | adapter `nyc_city_record` | Socrata SoQL | Filter: Solicitation + due date + keyword. |
| LA RAMP open bids (hf3r-utnq) | City of LA, LA County, LAPD, Port/LAX via RAMP | adapter `la_ramp` | Socrata | |
| Delaware open bids (2hnj-zwix) | Delaware state | adapter `de_open_bids` | Socrata | |
| Montgomery County MD solicitations (eeq6-nnwe) | Montgomery County MD | adapter `md_montgomery_county` | Socrata | |
| Mesa AZ solicitations (dfcn-ivuc) | Mesa AZ | works, not used | Socrata | No due date or open-status fields. |
| Baton Rouge upcoming procurement (e5pk-us93) | Baton Rouge | works, not used | Socrata | Stale (last update 2025). |
| Cambridge MA contracts (gp98-ja4f) | Cambridge MA | not used | Socrata | Contracts, not open bids. COMMBUYS covers MA towns. |
| City of San Antonio Bidding & Contracting | All COSA departments | adapter `tx_san_antonio` | ASP.NET grid + postback paging | Home market. |
| Phoenix solicitations | Phoenix | blocked | n/a | Moved to OpenGov (Cloudflare). |
| Austin Finance Online | Austin | works, not used | ColdFusion | Page loads; not parsed. |
| Houston purchasing | Houston | unreachable | n/a | DNS failure for purchasing.houstontx.gov. |
| Dallas | Dallas | robots | Bonfire | |
| Harris County (bids.hctx.net) | Harris County | unreachable | n/a | Proxy 502. |
| LA County (camisvr) | LA County | blocked | n/a | 403; covered through RAMP. |
| San Diego County BuyNet | San Diego County | unreachable | n/a | 503. |
| Seattle Consultant Connection | Seattle | blocked | n/a | Cloudflare. |
| Miami-Dade solicitations | Miami-Dade | works, not used | HTML | Page loads; not parsed. |
| Fort Worth bids page | Fort Worth | works, not used | HTML | Page loads; solicitations hosted elsewhere (not verified). |
| Bexar County, SAWS, Chicago, Dallas County, Travis, Tarrant, El Paso, Clark NV, King WA, Cook IL, Maricopa, Denver, Boston, Atlanta | Large cities/counties | not found | n/a | Guessed URLs returned 404 or redirected. Each needs its current bid page located by hand. |

## Gaps and what Vernon can do

1. **Bonfire, IonWave and Jaggaer (robots-disallowed)** hold most Texas city, county,
   ISD and university bids, including much of the San Antonio area. Free vendor
   registration on each agency's portal turns on email notifications by commodity code.
2. **OpenGov, PlanetBids and ProcureWare (WAF/Cloudflare)**: also free vendor accounts
   with email alerts ("follow" an agency on OpenGov).
3. **State portals behind bot checks** (CA Cal eProcure, VA eVA, GA GPR, MD eMMA,
   OhioBuys, TN, HI, MS, ME, CO, DC): each offers free vendor registration with
   commodity-code email alerts.
4. **Login-only**: NYS Contract Reporter (free account), Public Purchase (free), Kansas.
5. One option to automate these alerts: send them to one inbox and have the bid finder
   read that inbox. That depends on Gmail access and was not built here.
