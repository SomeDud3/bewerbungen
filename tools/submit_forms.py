"""Fuellt die Formulare und sendet sie EINMAL ab. Nur starten, wenn der User das ausdruecklich sagt.
Aufruf: submit_forms.py <playwright-dir> <screenshot-dir> [docolution] [web]
Leer gelassen: Anrede, Staatsbuergerschaft/Arbeitserlaubnis, Marketing-Einwilligung, Honeypot 'website'.
Bei Captcha oder Fehler bleibt das Fenster offen, es wird nichts umgangen."""
import json, os, pathlib, re, sys, time
sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright

B = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
P = pathlib.Path(os.environ.get("BEW_DIR") or pathlib.Path.home() / "Documents/Job/Pflichtpraktikum2027")
CLOUD = os.environ.get("PW_HEADLESS") == "1"  # GitHub Actions: eigenes Chromium, kein Fenster
OUT = pathlib.Path(sys.argv[2])
WHICH = sys.argv[3:] or ["docolution", "web"]
# Persoenliche Daten nie im Code (Repo ist oeffentlich): formdata.json im Datenordner
F = json.loads((P / "formdata.json").read_text(encoding="utf8"))
CV = str(P / F["cv"])
MAIL = F["mail"]
OK = ["danke", "vielen dank", "erfolgreich", "thank you", "eingegangen", "erhalten"]


def log(*a):
    print(*a, flush=True)


def result(g, name):
    g.wait_for_timeout(9000)
    g.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    t = g.locator("body").inner_text()
    hit = [k for k in OK if k in t.lower()]
    log(name, "URL", g.url, "TREFFER", hit)
    log(" ".join(t.split())[:700])
    return bool(hit)


def captcha(g):
    return any(k in f.url for f in g.frames for k in ("recaptcha", "hcaptcha", "turnstile"))


def docolution(c):
    g = c.new_page()
    g.goto("https://careers.docolution.com/jobs/6091809-initiativ-bewerbung", timeout=45000)
    g.wait_for_timeout(3000)
    x = g.get_by_role("button", name="Cookies ablehnen").first
    if x.count():
        x.click()
    g.wait_for_timeout(1000)
    g.get_by_text("Bewirb dich jetzt!").first.click(timeout=5000)
    g.wait_for_timeout(7000)
    g.fill('input[name="candidate[first_name]"]', F["vorname"])
    g.fill('input[name="candidate[last_name]"]', F["nachname"])
    g.fill('input[name="candidate[email]"]', MAIL)
    g.fill('input[name="candidate[phone]"]', F["telefon"])
    g.set_input_files("#candidate_resume_remote_url", CV)
    g.wait_for_timeout(4000)
    g.fill('textarea[name="candidate[job_applications_attributes][0][cover_letter]"]',
           (P / ".doco_msg.txt").read_text(encoding="utf8"))
    g.locator('input[type=checkbox][name="candidate[consent_given]"]').last.check(force=True)
    log("doco captcha-frame:", captcha(g))
    g.locator('input[name="commit"]').click()
    return result(g, "docolution")


def web(c):
    g = c.new_page()
    g.goto("https://jobs.diamir.io/Sommer-Praktikum-fuer-Schuelerinnen-Web-Development-all-Ge-de-f64.html", timeout=45000)
    g.wait_for_timeout(2500)
    x = g.get_by_role("button", name="Anpassung speichern")
    for i in range(x.count()):
        if x.nth(i).is_visible():
            x.nth(i).click()
            break
    N = "bewerbung_form"
    for k, v in dict(vorname=F["vorname"], nachname=F["nachname"], telefon=F["telefon"], mail=MAIL, geburtsdatum=F["geburtsdatum"],
                     ort=F["ort"], plz=F["plz"], eintrittsdatum=F["eintritt"]).items():
        g.fill(f'input[name="{N}[{k}]"]', v)
    g.set_input_files('input[name="anschreiben"]', str(P / F["anschreiben_web"]))
    g.set_input_files('input[name="lebenslauf"]', CV)
    g.wait_for_timeout(2000)
    cb = g.locator('input[name="agbs_check"]')
    cb.scroll_into_view_if_needed()
    for how in ("label", "js"):
        if cb.is_checked():
            break
        if how == "label" and g.locator('label[for="agb_checkbox"]').count():
            g.locator('label[for="agb_checkbox"]').first.click(position={"x": 5, "y": 5})
        elif how == "js":
            cb.evaluate("e=>{e.checked=true;e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}")
        g.wait_for_timeout(500)
    if not cb.is_checked():
        raise RuntimeError("Einwilligung liess sich nicht setzen")
    log("web captcha-frame:", captcha(g))
    form = g.locator('form:has(input[name="bewerbung_form[vorname]"])')
    b = form.locator('button, input[type=submit], a')  # diamir: Absenden ist ein <a>Senden</a>
    names = [((b.nth(i).inner_text() or b.nth(i).get_attribute("value") or "").strip()[:30], b.nth(i).is_visible()) for i in range(b.count())]
    log("web buttons:", names)
    hits = [i for i, (n, v) in enumerate(names) if v and re.fullmatch(r"(?i)(bewerbung )?(ab)?senden|submit", n)]
    if len(hits) != 1:
        raise RuntimeError("Absende-Button nicht eindeutig: " + str(names))
    b.nth(hits[0]).click()
    return result(g, "web_und_soehne")


with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True) if CLOUD else p.chromium.launch(executable_path=B, headless=False, args=["--start-maximized"])
    c = br.new_context(viewport={"width": 1280, "height": 900}, locale="de-AT") if CLOUD else br.new_context(no_viewport=True)
    done = {}
    for name, fn in (("docolution", docolution), ("web", web)):
        if name not in WHICH:
            continue
        try:
            done[name] = fn(c)
        except Exception as e:
            done[name] = False
            log(name, "FEHLER", str(e)[:300])
    log("ERGEBNIS", done)
    if not all(done.values()) and not CLOUD:
        log("Fenster bleibt offen")
        end = time.time() + 3 * 3600
        while br.is_connected() and c.pages and time.time() < end:
            try:
                c.pages[0].wait_for_timeout(2000)
            except Exception:
                break
    br.close()
    sys.exit(0 if all(done.values()) else 1)
