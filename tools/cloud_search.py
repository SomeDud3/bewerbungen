"""GitHub Actions: Jobseiten nach neuen IT-Praktika fuer Schueler durchsuchen, Treffer verschluesselt ins Bundle.
Nur Regeln, keine KI: der Score ist grob, pruefen und Paket bauen passiert am PC.
Phasen (= Workflow-Schritte, damit die Handy-Seite live mitzeigt):
  karriere | jobsat | portale   -> kand_<phase>.json (Links, ohne Browser)
  browser                       -> kand_browser.json (Stadtwerke, Stadt Wien, OeBB, AMS; fertig gelesene Inserate)
  pruefen                       -> liest alle kand_*.json, bewertet, schreibt data.bin
Lokal testen: CS_DRY=1 BROWSER=<brave.exe> python cloud_search.py   (alles, nur Ausgabe)"""
import datetime, difflib, html, json, os, pathlib, re, sys, time, urllib.parse, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
KQ = ["pflichtpraktikum", "ferialpraktikum", "sommerpraktikum", "ferialjob", "it-praktika", "praktikum-it",
      "praktikum-informatik", "praktikum-softwareentwicklung"]
JQ = ["pflichtpraktikum", "ferialpraktikum", "praktikum-it", "praktikum-informatik", "sommerpraktikum"]
SR_FIRMEN = ["BoschGroup"]  # SmartRecruiters-Firmen
ORTE = re.compile(r"(?i)wien|vienna|remote|home.?office|bruck an der leitha|hainburg|bad deutsch-altenburg|schwechat")
IT = re.compile(r"(?i)informatik|software|\bIT\b|IT-|programmier|entwickl|java|c#|\.net|web|netzwerk|daten|devops|cloud|app")
SCHULE = re.compile(r"(?i)\bHTL\b|schüler|\bschul(e|leistung|ausbildung)|\bTGM\b")
PRAKT = re.compile(r"(?i)prakti|ferial|sommer|schüler|htl")
TECH = re.compile(r"(?i)java\b|c#|\bsql\b|typescript|react|netzwerktechnik|cisco")
EIN_MONAT = re.compile(r"(?i)\b(1|ein(en)?)\s*monat|einmonatig|4[- ]?wöchig|4 wochen")


def get(u):
    for _ in range(2):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept-Language": "de"}),
                                          timeout=25).read().decode("utf-8", "replace")
        except Exception:
            time.sleep(2)
    return ""


def text(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def ldjson(s):
    """JobPosting aus JSON-LD (karriere.at, viele Firmenportale)."""
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', s, re.S):
        try:
            j = json.loads(m.group(1))
        except Exception:
            continue
        for x in (j if isinstance(j, list) else j.get("@graph", [j])):
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                loc = x.get("jobLocation") or []
                loc = loc if isinstance(loc, list) else [loc]
                ort = ", ".join((l.get("address") or {}).get("addressLocality", "") for l in loc if isinstance(l, dict))
                return {"titel": html.unescape(x.get("title", "")), "firma": (x.get("hiringOrganization") or {}).get("name", ""),
                        "ort": ort, "text": text(x.get("description", ""))}
    return None


def generisch(u, firma="", ort=""):
    s = get(u)
    if not s:
        return None
    x = ldjson(s)
    if x:
        x["firma"] = x["firma"] or firma; x["ort"] = x["ort"] or ort
        return x
    h = [re.split(r" - Job ?Detail| \| ", text(m))[0] for m in re.findall(r"<h1[^>]*>(.*?)</h1>", s, re.S) + re.findall(r"<title[^>]*>(.*?)</title>", s, re.S)]
    h = [t for t in h if t and not re.fullmatch(r"(?i)job ?details?|stellenangebot", t)]
    return {"titel": h[0] if h else "","firma": firma, "ort": ort, "text": text(s)[:6000]}


def jobsat(u):
    s = get(u)
    if not s or "nicht mehr verfügbar" in s:
        return None
    t = re.search(r"<title>(.*?) bei (.*?) - jobs\.at</title>", s, re.S)
    if not t:
        return None
    body = text(s)
    a, b = body.find("Stelleninserat"), body.find("Jetzt bewerben")
    ort = re.search(r"(Wien[^-]{0,25}|[A-ZÄÖÜ][\w .]+?) - vor \d", body)
    return {"titel": html.unescape(t.group(1)).strip(), "firma": html.unescape(t.group(2)).strip(),
            "ort": ort.group(1).strip() if ort else "", "text": body[a:b] if 0 <= a < b else body[:4000]}


def smartrecruiters(u):
    j = json.loads(get(u) or "{}")
    if not j:
        return None
    sec = (j.get("jobAd") or {}).get("sections") or {}
    loc = j.get("location") or {}
    return {"titel": j.get("name", ""), "firma": (j.get("company") or {}).get("name", ""), "ort": loc.get("city", ""),
            "text": text(" ".join((v or {}).get("text", "") for v in sec.values()))}


def lesen(k):
    """Kandidat -> Inserat-Dict oder None."""
    if "x" in k:
        return k["x"]
    u, src = k["url"], k["src"]
    if src == "jobsat":
        return jobsat(u)
    if src == "smartrecruiters":
        return smartrecruiters(k["api"])
    return generisch(u, k.get("firma", ""), k.get("ort", ""))


def ids(url, pat):
    return list(dict.fromkeys(re.findall(pat, get(url))))


# ---------- Listen ohne Browser ----------
def liste_karriere():
    return [{"src": "karriere", "url": f"https://www.karriere.at/jobs/{i}"} for q in KQ for p in (1, 2, 3)
            for i in ids(f"https://www.karriere.at/jobs/{q}/wien?page={p}", r'href="https://www\.karriere\.at/jobs/(\d+)"')]


def liste_jobsat():
    return [{"src": "jobsat", "url": f"https://www.jobs.at/i/{i}"} for q in JQ for i in ids(f"https://www.jobs.at/j/{q}/wien", r"jobs\.at/i/(\d+)")]


def liste_portale():
    k = []
    for f in SR_FIRMEN:  # SmartRecruiters: offene API
        for q in ("praktikum", "ferialpraktikum"):
            j = json.loads(get(f"https://api.smartrecruiters.com/v1/companies/{f}/postings?q={q}&country=at&limit=100") or "{}")
            k += [{"src": "smartrecruiters", "url": f"https://jobs.smartrecruiters.com/{f}/{p['id']}",
                   "api": f"https://api.smartrecruiters.com/v1/companies/{f}/postings/{p['id']}"} for p in j.get("content", [])]
    for q in ("praktikum", "ferialpraktikum", "pflichtpraktikum"):
        k += [{"src": "siemens", "url": u, "firma": "Siemens"} for u in
              ids(f"https://jobs.siemens.com/de_DE/externaljobs/SearchJobs/{q}?folderRecordsPerPage=50",
                  r'href="(https://jobs\.siemens\.com/de_DE/externaljobs/JobDetail/\d+)"')]
    for q in ("praktikum", "ferialpraktikum", "praktikum%20informatik"):
        k += [{"src": "devjobs", "url": "https://devjobs.at" + u} for u in ids(f"https://devjobs.at/jobs/search?q={q}", r'href="(/job/[0-9a-f]{32})"')]
        k += [{"src": "willhaben", "url": "https://www.willhaben.at" + u} for u in
              ids(f"https://www.willhaben.at/jobs/suche?keyword={q}&location=wien", r'href="(/jobs/job/[^"]+/\d+)"')]
    k += [{"src": "flughafen", "url": "https://karriere.viennaairport.com/" + html.unescape(u), "firma": "Flughafen Wien AG", "ort": "Schwechat"}
          for u in ids("https://karriere.viennaairport.com/jobboerse", r'href="(main\.jart\?[^"]*?job_id=[0-9a-f]+)')]
    return k


# ---------- Listen + Inserate mit Browser (SPAs) ----------
def liste_browser():
    from playwright.sync_api import sync_playwright
    exe = os.environ.get("BROWSER")
    quellen = [  # (src, Listen-URL, Link-Regex, Firma, Ort, Suchwort fuers Suchfeld)
        ("wienerstadtwerke", "https://jobs.wienerstadtwerke.at/de/jobs", r"/de/jobs/\d+/[^\"#?]+", "Wiener Stadtwerke-Gruppe", "Wien", None),
        ("stadtwien", "https://jobs.wien.gv.at/stellenangebote/", r"details\.html\?jobTitle=[^\"]*jobId=\d+", "Stadt Wien", "Wien", None),
        ("oebb", "https://oebb.csod.com/ux/ats/careersite/4/home?c=oebb", r"/ux/ats/careersite/4/home/requisition/\d+\?c=oebb", "ÖBB-Konzern", "", None),
        ("ams", "https://jobs.ams.at/public/emps/jobs?query=praktikum%20informatik&location=Wien", r"/public/emps/jobs/[0-9a-f-]{36}", "", "Wien", None),
        ("ams", "https://jobs.ams.at/public/emps/jobs?query=ferialpraktikum&location=Wien", r"/public/emps/jobs/[0-9a-f-]{36}", "", "Wien", None),
        ("siemens-energy", "https://jobs.siemens-energy.com/de_DE/jobs/Jobs", r"/de_DE/jobs/FolderDetail/", "Siemens Energy", "", "Praktikum"),
    ]
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True) if exe else p.chromium.launch(channel="chrome", headless=True)
        g = b.new_page(user_agent=UA, locale="de-AT")
        for src, lu, pat, firma, ort, wort in quellen:
            try:
                g.goto(lu, timeout=45000); g.wait_for_timeout(6000)
                if wort:  # Seite ohne Such-URL: ins Suchfeld tippen
                    g.locator("input[type=search], input[name*=keyword i], input[placeholder*=such i]").first.fill(wort)
                    g.keyboard.press("Enter"); g.wait_for_timeout(6000)
                links = g.eval_on_selector_all("a[href]", "as=>as.map(a=>[a.href,a.innerText])")
            except Exception:
                continue
            seen = set()
            for href, label in links:
                if not re.search(pat, href) or href in seen:
                    continue
                seen.add(href)
                if not PRAKT.search(label + " " + urllib.parse.unquote(href)):
                    continue  # nur Praktika im Detail lesen
                try:
                    g.goto(href, timeout=45000); g.wait_for_timeout(4000)
                    body = re.sub(r"\s+", " ", g.inner_text("body"))
                    h1 = g.locator("h1").first.inner_text(timeout=3000) if g.locator("h1").count() else label
                except Exception:
                    continue
                titel, _, bei = h1.strip().partition("\nbei ")  # AMS: "Titel\nbei Firma\nVermittler"
                titel, bei = titel.split("\n")[0], bei.split("\n")[0]
                out.append({"src": src, "url": href, "x": {"titel": titel.strip()[:200], "firma": firma or bei.strip() or src,
                                                           "ort": ort, "text": body[:6000], "browser": 1}})
        b.close()
    return out


# ---------- Bewerten ----------
def bewerten(x):
    t, tt = x["text"], x["titel"] + " " + x["text"]
    if not IT.search(x["titel"]) and (x.get("browser") or len(IT.findall(t)) < 3):  # Browser-Seiten: Menue verfaelscht
        return None, "kein IT"
    if not ORTE.search(x["ort"] + " " + t[:2000]):
        return None, "Ort"
    schule = SCHULE.search(tt)
    if re.search(r"(?i)laufend\w* (technisch\w* )?studium|immatrikul", tt) and not re.search(r"(?i)schüler", tt):
        return None, "nur Studium"
    if not schule:
        return None, "nicht fuer Schueler"
    sc, why = 0, []
    if re.search(r"(?i)\bHTL\b|schüler", tt): sc += 3; why.append("HTL/Schüler genannt")
    else: sc += 1; why.append("Schule erwähnt")
    if "2027" in tt and re.search(r"(?i)sommer|juli|august|ferial", tt): sc += 2; why.append("Sommer 2027")
    elif re.search(r"(?i)sommer|juli|august|ferial", tt): sc += 1; why.append("Sommer, Jahr offen")
    tech = sorted({m.lower() for m in TECH.findall(tt)})
    if tech: sc += 2; why.append("Tech: " + ", ".join(tech))
    geld = [int(g.replace(".", "")) for g in re.findall(r"(\d\.\d{3})(?:,\d\d)?\s*(?:€|EUR)", tt)]
    geld = [g for g in geld if 900 <= g <= 4000]  # Monatsentgelt, keine Jahresgehaelter/Zufallszahlen
    if geld and max(geld) >= 1000: sc += 1; why.append(f"ab {max(geld)} €")
    if EIN_MONAT.search(tt) and not re.search(r"(?i)2 monate|zwei monate|juli und august", tt):
        sc -= 2; why.append("evtl. nur 1 Monat")
    return {**{k: x[k] for k in ("titel", "firma", "ort")}, "score": max(sc, 0), "gruende": why, "auszug": t[:700], "volltext": t[:6000]}, None


def key(titel, firma):
    t = re.sub(r"(?i)\((?:[mwdfx]|all|div|gender)[^)]*\)|[^a-zäöü0-9]", "", titel.lower())
    stop = ("gmbh", "gruppe", "konzern", "österreich", "aktiengesellschaft")
    return t, {w for w in re.findall(r"[a-zäöü]{4,}", firma.lower()) if w not in stop}


def doppelt(k, seen):
    return any(difflib.SequenceMatcher(None, k[0], t).ratio() >= 0.85 and (k[1] & f or not f or not k[1]) for t, f in seen)


def suche(bekannt, alt, kand):
    seen = [key(s.get("titel", ""), s.get("firma", "")) for s in alt]
    funde, neu_bekannt, quellen = [], [], {}
    for k in {c["url"]: c for c in kand}.values():
        if k["url"] in bekannt:
            continue
        neu_bekannt.append(k["url"])
        try:
            x = lesen(k)
        except Exception:
            x = None
        if not x or not re.search(r"(?i)prakti|ferial|sommer", x["titel"] + x["text"][:400]):
            continue
        f, _ = bewerten(x)
        kk = key(x["titel"], x["firma"])
        if f and not doppelt(kk, seen):
            seen.append(kk)
            funde.append({"url": k["url"], "quelle": k["src"], **f})
            quellen[k["src"]] = quellen.get(k["src"], 0) + 1
    return funde, neu_bekannt, quellen


def bekannte_urls(d):
    u = set(d.get("bekannt", []))
    for s in d.get("stellen", []):
        u.update(v for v in (s.get("url"), (s.get("weg") or {}).get("url")) if v)
    u.update(f["url"] for f in d.get("funde", []))
    return u


PHASEN = {"karriere": liste_karriere, "jobsat": liste_jobsat, "portale": liste_portale, "browser": liste_browser}

if __name__ == "__main__":
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    phase = sys.argv[1] if len(sys.argv) > 1 else "alles"
    if phase in PHASEN:
        try:
            k = PHASEN[phase]()
        except Exception as e:  # eine kaputte Quelle soll die Suche nicht stoppen
            k = []; print("Fehler:", type(e).__name__)
        pathlib.Path(f"kand_{phase}.json").write_text(json.dumps(k, ensure_ascii=False), encoding="utf-8")
        print(len(k), "Kandidaten"); sys.exit(0)
    if phase == "pruefen":
        kand = [x for n in PHASEN if pathlib.Path(f"kand_{n}.json").exists() for x in json.loads(pathlib.Path(f"kand_{n}.json").read_text(encoding="utf-8"))]
    else:
        kand = []
        for n, fn in PHASEN.items():
            try:
                r = fn(); kand += r; print(n, len(r), "Kandidaten")
            except Exception as e:
                print(n, "Fehler", e)
    if os.environ.get("CS_DRY"):
        tr = json.load(open(pathlib.Path.home() / "Documents/Job/Pflichtpraktikum2027/tracker.json", encoding="utf-8"))
        f, b, q = suche({s["url"] for s in tr["stellen"]}, tr["stellen"], kand)
        print(len(kand), "Kandidaten,", len(f), "Treffer", q)
        for x in f: print(x["score"], x["quelle"], x["firma"], "|", x["titel"][:70], "|", x["gruende"])
        sys.exit(0)
    import crypt
    d, K, meta = crypt.open_(pathlib.Path("data.bin").read_bytes(), priv=crypt.private_key())
    f, b, q = suche(bekannte_urls(d), d.get("stellen", []) + d.get("funde", []), kand)
    for x in f:
        x.update(gefunden=now[:10], status="neu")
    d["funde"] = sorted(f, key=lambda x: -x["score"]) + d.get("funde", [])
    d["bekannt"] = d.get("bekannt", []) + b
    d["suche"] = {"zeit": now, "inserate": len({c["url"] for c in kand}), "neu": len(f), "quellen": q}
    pathlib.Path("data.bin").write_bytes(crypt.seal(d, K, meta))
    # Actions-Logs sind oeffentlich: nur Zahlen ausgeben
    print(f"{len(kand)} Kandidaten, {len(f)} neue Treffer")
