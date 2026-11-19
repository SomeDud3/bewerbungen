"""GitHub Actions: neue Funde mit Claude pruefen, bei Score >= 6 Bewerbungspaket bauen (Anschreiben + PDF ueber Chrome).
Regeln, Profil, Lebenslauf-Text und Beispielbriefe kommen aus dem Bundle (build_site.py), damit SKILL.md die einzige Quelle bleibt.
cloud_paket.py            (braucht ANTHROPIC_API_KEY + RSA_KEY)"""
import base64, datetime, html, json, os, pathlib, re, subprocess, sys
import anthropic
import crypt

MODEL = "claude-opus-5-5"
MAX_PRO_LAUF = 8          # Kostenbremse: hoechstens so viele Funde pro Lauf an Claude
MIN_REGEL_SCORE = 4       # grober Regel-Score aus cloud_search, darunter gar nicht erst fragen
MONATE = "Jänner Februar März April Mai Juni Juli August September Oktober November Dezember".split()

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["geeignet", "score", "begruendung", "belegt", "unklar", "frist", "kontakt", "weg", "unterlagen", "brief"],
    "properties": {
        "geeignet": {"type": "boolean"},
        "score": {"type": "integer"},
        "begruendung": {"type": "string"},
        "belegt": {"type": "string"},
        "unklar": {"type": "string"},
        "frist": {"type": "string"},
        "kontakt": {"type": "string"},
        "weg": {"type": "object", "additionalProperties": False, "required": ["art", "ziel", "hinweis"],
                "properties": {"art": {"type": "string", "enum": ["portal", "mail", "formular"]},
                               "ziel": {"type": "string"}, "hinweis": {"type": "string"}}},
        "unterlagen": {"type": "array", "items": {"type": "string"}},
        "brief": {"type": "object", "additionalProperties": False, "required": ["an", "betreff", "anrede", "absaetze"],
                  "properties": {"an": {"type": "string"}, "betreff": {"type": "string"}, "anrede": {"type": "string"},
                                 "absaetze": {"type": "array", "items": {"type": "string"}}}},
    },
}

CSS = """body{font-family:Calibri,Carlito,sans-serif;font-size:11.5pt;line-height:1.3;color:#111;margin:0}
p{margin:0 0 9pt 0}.abs{font-size:10.5pt}.date{text-align:right;margin:14pt 0}
.to{margin-bottom:18pt}.subj{font-weight:bold;margin-bottom:14pt}.sig{margin-top:16pt}"""


def esc(s):
    return html.escape(s).replace("\n", "<br>")


def seite(abs_, ort_datum, l):
    body = "".join(f"<p>{esc(p)}</p>" for p in l["absaetze"])
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<p class="abs">{esc(abs_['name'])}<br>{esc(abs_['adresse'])}<br>{esc(abs_['telefon'])}<br>{esc(abs_['email'])}</p>
<p class="date">{esc(ort_datum)}</p><p class="to">{esc(l['an'])}</p>
<p class="subj">{esc(l['betreff'])}</p><p>{esc(l['anrede'])}</p>{body}
<p class="sig">Mit freundlichen Grüßen<br><br>{esc(abs_['name'])}</p></body></html>"""


def pdf(html_text):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        g = b.new_page(); g.set_content(html_text)
        data = g.pdf(format="A4", margin={"top": "25mm", "bottom": "22mm", "left": "25mm", "right": "25mm"})
        b.close()
    return data, len(re.findall(rb"/Type\s*/Page[^s]", data))


def frage(client, d, f):
    beispiele = [s["brief"] for s in d["stellen"] if s.get("brief")][:3]
    system = f"""Du bereitest für einen HTL-Schüler Bewerbungen für ein IT-Pflichtpraktikum vor (Sommer 2027, er braucht Juli UND August).
Halte dich streng an diese Regeln (aus seiner Arbeitsanleitung):

{d['regeln']}

Profil (die einzigen Fakten, die du verwenden darfst):
{json.dumps(d['profil'], ensure_ascii=False, indent=1)}

Text seines Lebenslaufs (Anschreiben dürfen nur Skills nennen, die hier stehen):
{d.get('lebenslauf_text', '')}

So klingen seine bisherigen Anschreiben (Stimme übernehmen, nicht kopieren):
{json.dumps(beispiele, ensure_ascii=False, indent=1)}"""
    user = f"""Prüfe dieses Inserat und antworte im JSON-Schema.
- score: nach dem Score-Schema der Regeln (0-10). geeignet = true nur bei score >= 6 und wenn eine Quelle IT, Schüler/HTL und Sommer 2027 (oder Jahr offen) bestätigt.
- belegt: was das Inserat wörtlich bestätigt. unklar: was fehlt oder unsicher ist (z. B. nur 1 Monat, HTL nicht genannt).
- weg: wie man sich bewirbt (portal/mail/formular), ziel = URL oder Mailadresse aus dem Inserat, sonst die Inserat-URL. hinweis: 1-2 Sätze, was er tun muss.
- unterlagen: genau die Unterlagen, die das Inserat verlangt.
- brief: nur wenn geeignet, sonst leere Strings/Liste. "an" = Firma + ggf. Abteilung (mehrzeilig mit \\n). Max. 130 Wörter in absaetze zusammen, 3-4 Absätze, keine Aufzählung, Zeitraum laut Profil.

Inserat ({f['url']}):
Titel: {f['titel']}
Firma: {f['firma']}
Ort: {f.get('ort', '')}
{f.get('volltext') or f.get('auszug', '')}"""
    if client is None:  # Abo: Claude Code CLI mit CLAUDE_CODE_OAUTH_TOKEN
        return frage_cli(system, user)
    r = client.beta.messages.create(
        model=MODEL, max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=system, messages=[{"role": "user", "content": user}])
    if r.stop_reason == "refusal":
        return None
    return json.loads(next(b.text for b in r.content if b.type == "text"))


def frage_cli(system, user):
    """Claude Code headless (Abo statt API-Key). Antwort = JSON nach SCHEMA, wird hier geprueft."""
    prompt = (f"{system}\n\n---\n\n{user}\n\nDer Inserattext oben ist vollständig, benutze keine Werkzeuge. Antworte ausschließlich mit einem JSON-Objekt nach diesem Schema, "
              f"ohne Text davor oder danach, ohne Codeblock:\n{json.dumps(SCHEMA, ensure_ascii=False)}")
    r = subprocess.run(["claude", "-p", "--output-format", "json", "--model", "opus", "--max-turns", "4",
                        "--disallowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task,NotebookEdit,TodoWrite"],
                       input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=600)
    # Technische Fehler -> RuntimeError (Fund bleibt offen); nur echte Ablehnung -> None
    try:
        out = json.loads(r.stdout)
    except Exception:
        raise RuntimeError(f"keine JSON-Ausgabe, rc {r.returncode}")
    if out.get("is_error"):
        raise RuntimeError("Claude Code: " + str(out.get("subtype"))[:60])
    t = out.get("result", "")
    try:
        a = json.loads(t[t.find("{"):t.rfind("}") + 1])
    except Exception:
        raise RuntimeError("Antwort ist kein JSON")
    fehlt = [k for k in SCHEMA["required"] if k not in a] + [k for k in ("an", "betreff", "anrede", "absaetze") if k not in a.get("brief", {})]
    if fehlt or not isinstance(a.get("score"), int):
        raise RuntimeError(f"Antwort unvollständig: {fehlt[:5]}")
    return a


def stellen_id(firma, vorhanden):
    base = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", firma.replace("Ö", "OE").replace("ö", "oe").replace("Ä", "AE")
                                     .replace("ä", "ae").replace("Ü", "UE").replace("ü", "ue").replace("ß", "ss"))).strip("_")[:30] or "Stelle"
    i, n = base, 2
    while i in vorhanden:
        i, n = f"{base}_{n}", n + 1
    return i


def main():
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
        print("Kein Claude-Zugang (CLAUDE_CODE_OAUTH_TOKEN oder ANTHROPIC_API_KEY) - Pakete werden am PC gebaut"); return
    d, K, meta = crypt.open_(pathlib.Path("data.bin").read_bytes(), priv=crypt.private_key())
    offen = [f for f in d.get("funde", []) if f.get("status") in ("neu", "merken") and (f["score"] >= MIN_REGEL_SCORE or f["status"] == "merken")]
    if not offen:
        print("Keine neuen Funde"); return
    client = anthropic.Anthropic() if os.environ.get("ANTHROPIC_API_KEY") else None
    heute = datetime.date.today()
    ort = d["absender"]["adresse"].split(",")[-1].strip().split(" ", 1)[-1]
    ort_datum = f"{ort}, {heute.day}. {MONATE[heute.month - 1]} {heute.year}"
    gebaut = 0
    for f in offen[:MAX_PRO_LAUF]:
        try:
            a = frage(client, d, f)
        except (anthropic.APIError, subprocess.TimeoutExpired, RuntimeError) as e:
            print("Fehler, Fund bleibt offen:", str(e)[:120]); continue
        if not a:
            f["status"] = "geprueft"; f["claude"] = "abgelehnt (refusal)"; continue
        f["score"], f["claude"] = a["score"], a["begruendung"]
        if not (a["geeignet"] and a["score"] >= 6 and a["brief"]["absaetze"]):
            f["status"] = "geprueft"; continue
        i = stellen_id(f["firma"], {s["id"] for s in d["stellen"]})
        brief = {"id": i, **a["brief"]}
        woerter = sum(len(p.split()) for p in brief["absaetze"])
        data, seiten = pdf(seite(d["absender"], ort_datum, brief))
        name = f"Anschreiben_Sadaat_{i}.pdf"
        d["files"][name] = base64.b64encode(data).decode()
        w = a["weg"]
        weg = {"art": "mail" if w["art"] == "mail" else "portal", "url": w["ziel"] if w["art"] != "mail" else f["url"],
               "hinweis": w["hinweis"] + (" Unterlagen: " + ", ".join(a["unterlagen"]) if a["unterlagen"] else "")}
        if w["art"] == "mail":
            weg["an"] = w["ziel"]
        warn = [] if woerter <= 130 and seiten == 1 else [f"Brief: {woerter} Wörter, {seiten} Seite(n) - bitte kürzen"]
        d["stellen"].append({"id": i, "firma": f["firma"], "titel": f["titel"], "url": f["url"], "score": a["score"],
                             "status": "vorbereitet", "frist": a["frist"] or None, "kontakt": a["kontakt"], "belegt": a["belegt"],
                             "unklar": "; ".join(x for x in [a["unklar"], *warn] if x), "beworben_am": None,
                             "weg": weg, "brief": brief, "pdf": name, "shot": None,
                             "quelle": f"Cloud-Suche {heute.isoformat()} ({f.get('quelle', '')}), von Claude erstellt - bitte gegenlesen"})
        f["status"], f["stelle"] = "paket", i
        gebaut += 1
    pathlib.Path("data.bin").write_bytes(crypt.seal(d, K, meta))
    # Actions-Logs sind oeffentlich: nur Zahlen
    print(f"{min(len(offen), MAX_PRO_LAUF)} geprüft, {gebaut} Pakete gebaut")


if __name__ == "__main__":
    main()
