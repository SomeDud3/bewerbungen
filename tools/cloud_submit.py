"""GitHub Actions: Bundle entschluesseln, Formular abschicken, Ergebnis + Screenshot ins Bundle, neu verschluesseln.
cloud_submit.py <stellen-id>"""
import base64, datetime, json, os, pathlib, subprocess, sys
import crypt

i = sys.argv[1]
pw = os.environ["SITE_PASSWORD"]
d = crypt.open_(pathlib.Path("data.bin").read_bytes(), pw)
s = next(x for x in d["stellen"] if x["id"] == i)
auto = s["weg"].get("auto")
w = pathlib.Path("work")
(w / "screens").mkdir(parents=True, exist_ok=True)
for n, b64 in d["files"].items():
    if not n.startswith("screens/"):
        (w / n).write_bytes(base64.b64decode(b64))
ok = False
if s["status"] == "beworben":
    log = "Schon beworben, nichts gesendet."
elif not auto:
    log = "Kein automatisches Formular fuer diese Stelle."
else:
    r = subprocess.run([sys.executable, str(pathlib.Path(__file__).parent / "submit_forms.py"), "", str(w / "screens"), auto],
                       env={**os.environ, "BEW_DIR": str(w), "PW_HEADLESS": "1"}, capture_output=True, text=True, timeout=600)
    log = (r.stdout + r.stderr)[-6000:]
    ok = r.returncode == 0 and "TREFFER []" not in log
    shot = w / "screens" / f"{'web_und_soehne' if auto == 'web' else auto}.png"
    if shot.exists():
        d["files"][f"screens/{shot.name}"] = base64.b64encode(shot.read_bytes()).decode()
        s["shot"] = f"screens/{shot.name}"
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
if ok:
    s["status"] = "beworben"
    s["bewerben"] = f"{now[:10]} per Formular (Handy/GitHub), Bestätigungsseite erkannt"
d.setdefault("laeufe", []).insert(0, {"id": i, "zeit": now, "ok": ok, "log": log})
d["laeufe"] = d["laeufe"][:10]
pathlib.Path("data.bin").write_bytes(crypt.seal(d, pw))
# Log nur verschluesselt speichern: Actions-Logs sind oeffentlich
print("OK" if ok else "NICHT ABGESCHICKT")
