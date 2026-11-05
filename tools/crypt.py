"""data.bin = salt(16) | iv(12) | AES-256-GCM(json), Schluessel per PBKDF2-SHA256 600k. Gleiches Format wie index.html.
crypt.py open <data.bin> <out.json>   |   crypt.py seal <in.json> <data.bin>   (Passwort in env SITE_PASSWORD)"""
import json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

IT = 600_000


def key(pw, salt):
    return PBKDF2HMAC(hashes.SHA256(), 32, salt, IT).derive(pw.encode())


def seal(obj, pw):
    salt, iv = os.urandom(16), os.urandom(12)
    return salt + iv + AESGCM(key(pw, salt)).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), None)


def open_(b, pw):
    return json.loads(AESGCM(key(pw, b[:16])).decrypt(b[16:28], b[28:], None))


if __name__ == "__main__":
    pw = os.environ["SITE_PASSWORD"]
    cmd, a, b = sys.argv[1:4]
    if cmd == "open":
        open(b, "w", encoding="utf8").write(json.dumps(open_(open(a, "rb").read(), pw), ensure_ascii=False))
    else:
        open(b, "wb").write(seal(json.load(open(a, encoding="utf8")), pw))
