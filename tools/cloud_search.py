"""GitHub Actions: karriere.at + jobs.at nach neuen IT-Praktika fuer Schueler durchsuchen, Treffer verschluesselt ins Bundle.
Nur Regeln, keine KI: der Score ist grob, pruefen und Paket bauen passiert am PC.
cloud_search.py   (lokal testen: CS_DRY=1 python cloud_search.py  -> liest ../data.bin nicht, druckt nur)"""
import datetime, difflib, html, json, os, pathlib, re, sys, time, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
KQ = ["pflichtpraktikum", "ferialpraktikum", "sommerpraktikum", "ferialjob", "it-praktika", "praktikum-it",
      "praktikum-informatik", "praktikum-softwareentwicklung"]
JQ = ["pflichtpraktikum", "ferialpraktikum", "praktikum-it", "praktikum-informatik", "sommerpraktikum"]
ORTE = re.compile(r"(?i)wien|remote|home.?office|bruck an der leitha|hainburg|bad deutsch-altenburg|schwechat")
IT = re.compile(r"(?i)informatik|software|\bIT\b|IT-|programmier|entwickl|java|c#|\.net|web|netzwerk|daten|devops|cloud|app")
SCHULE = re.compile(r"(?i)\bHTL\b|schüler|\bschul(e|leistung|ausbildung)|\bTGM\b")
TECH = re.compile(r"(?i)java\b|c#|\bsql\b|typescript|react|netzwerktechnik|cisco")
EIN_MONAT = re.compile(r"(?i)\b(1|ein(en)?)\s*monat|einmonatig|4[- ]?wöchig|4 wochen")


def get(u):
    for _ in range(2):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=25).read().decode("utf-8", "replace")
        except Exception:
            time.sleep(2)
    return ""


def text(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def karriere(i):
    s = get(f"https://www.karriere.at/jobs/{i}")
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', s, re.S)
    if not m:
        return None
    try:
        j = json.loads(m.group(1)); j = j[0] if isinstance(j, list) else j
    except Exception:
        return None
    loc = j.get("jobLocation") or []
    loc = loc if isinstance(loc, list) else [loc]
    ort = ", ".join(x.get("address", {}).get("addressLocality", "") for x in loc if isinstance(x, dict))
    return {"titel": html.unescape(j.get("title", "")), "firma": (j.get("hiringOrganization") or {}).get("name", ""),
            "ort": ort, "text": text(j.get("description", ""))}


def jobsat(i):
    s = get(f"https://www.jobs.at/i/{i}")
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


def bewerten(x):
    t, tt = x["text"], x["titel"] + " " + x["text"]
    if not IT.search(x["titel"]) and len(IT.findall(t)) < 3:
        return None, "kein IT"
    if not ORTE.search(x["ort"] + " " + t[:600]):
        return None, "Ort"
    schule = SCHULE.search(tt)
    if not schule:
        return None, "nicht fuer Schueler"
    sc, why = 0, []
    if re.search(r"(?i)\bHTL\b|schüler", tt): sc += 3; why.append("HTL/Schüler genannt")
    elif schule: sc += 1; why.append("Schule erwähnt")
    if "2027" in tt and re.search(r"(?i)sommer|juli|august|ferial", tt): sc += 2; why.append("Sommer 2027")
    elif re.search(r"(?i)sommer|juli|august|ferial", tt): sc += 1; why.append("Sommer, Jahr offen")
    tech = sorted({m.lower() for m in TECH.findall(tt)})
    if tech: sc += 2; why.append("Tech: " + ", ".join(tech))
    geld = [int(g.replace(".", "")) for g in re.findall(r"(\d\.\d{3})(?:,\d\d)?\s*(?:€|EUR)", tt)]
    if geld and max(geld) >= 1000: sc += 1; why.append(f"ab {max(geld)} €")
    if EIN_MONAT.search(tt) and not re.search(r"(?i)2 monate|zwei monate|juli und august", tt):
        sc -= 2; why.append("evtl. nur 1 Monat")
    return {**{k: x[k] for k in ("titel", "firma", "ort")}, "score": max(sc, 0), "gruende": why,
            "auszug": t[:700]}, None


def key(titel, firma):
    t = re.sub(r"(?i)\((?:[mwdfx]|all|div|gender)[^)]*\)|[^a-zäöü0-9]", "", titel.lower())
    stop = ("gmbh", "gruppe", "konzern", "österreich", "aktiengesellschaft")
    return t, {w for w in re.findall(r"[a-zäöü]{4,}", firma.lower()) if w not in stop}


def doppelt(k, seen):
    return any(difflib.SequenceMatcher(None, k[0], t).ratio() >= 0.85 and (k[1] & f or not f or not k[1]) for t, f in seen)


def ids(url, pat):
    return list(dict.fromkeys(re.findall(pat, get(url))))


def liste_karriere():
    return [("k", i) for q in KQ for p in (1, 2, 3)
            for i in ids(f"https://www.karriere.at/jobs/{q}/wien?page={p}", r'href="https://www\.karriere\.at/jobs/(\d+)"')]


def liste_jobsat():
    return [("j", i) for q in JQ for i in ids(f"https://www.jobs.at/j/{q}/wien", r"jobs\.at/i/(\d+)")]


def suche(bekannt, alt=(), kand=None):
    seen = [key(s.get("titel", ""), s.get("firma", "")) for s in alt]
    kand = list(dict.fromkeys(tuple(x) for x in (kand if kand is not None else liste_karriere() + liste_jobsat())))
    funde, neu_bekannt = [], []
    for src, i in kand:
        url = f"https://www.karriere.at/jobs/{i}" if src == "k" else f"https://www.jobs.at/i/{i}"
        if url in bekannt:
            continue
        x = karriere(i) if src == "k" else jobsat(i)
        neu_bekannt.append(url)
        if not x or not re.search(r"(?i)prakti|ferial|sommer", x["titel"] + x["text"][:300]):
            continue
        f, _ = bewerten(x)
        k = key(x["titel"], x["firma"])
        if f and not doppelt(k, seen):
            seen.append(k)
            funde.append({"url": url, **f})
    return funde, neu_bekannt, len(kand)


def bekannte_urls(d):
    u = set(d.get("bekannt", []))
    for s in d.get("stellen", []):
        u.update(v for v in (s.get("url"), (s.get("weg") or {}).get("url")) if v)
    u.update(f["url"] for f in d.get("funde", []))
    return u


if __name__ == "__main__":
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if os.environ.get("CS_DRY"):
        tr = json.load(open(pathlib.Path.home() / "Documents/Job/Pflichtpraktikum2027/tracker.json", encoding="utf-8"))
        f, b, n = suche({s["url"] for s in tr["stellen"]}, tr["stellen"])
        print(n, "Inserate,", len(f), "Treffer"); [print(x["score"], x["firma"], "|", x["titel"], "|", x["gruende"]) for x in f]
        sys.exit(0)
    # Phasen = eigene Workflow-Schritte, damit die Handy-Seite den Fortschritt live zeigt
    phase = sys.argv[1] if len(sys.argv) > 1 else "alles"
    if phase in ("karriere", "jobsat"):
        k = liste_karriere() if phase == "karriere" else liste_jobsat()
        pathlib.Path(f"kand_{phase}.json").write_text(json.dumps(k))
        print(len(k), "Links"); sys.exit(0)
    kand = None
    if phase == "pruefen":
        kand = [x for n in ("karriere", "jobsat") if pathlib.Path(f"kand_{n}.json").exists()
                for x in json.loads(pathlib.Path(f"kand_{n}.json").read_text())]
    import crypt
    d, K, meta = crypt.open_(pathlib.Path("data.bin").read_bytes(), priv=crypt.private_key())
    f, b, n = suche(bekannte_urls(d), d.get("stellen", []) + d.get("funde", []), kand)
    for x in f:
        x.update(gefunden=now[:10], status="neu")
    d["funde"] = sorted(f, key=lambda x: -x["score"]) + d.get("funde", [])
    d["bekannt"] = d.get("bekannt", []) + b
    d["suche"] = {"zeit": now, "inserate": n, "neu": len(f)}
    pathlib.Path("data.bin").write_bytes(crypt.seal(d, K, meta))
    # Actions-Logs sind oeffentlich: nur Zahlen ausgeben
    print(f"{n} Inserate gesehen, {len(f)} neue Treffer")
