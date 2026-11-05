"""data.bin (v2, JSON): Daten mit Zufallsschluessel K (AES-256-GCM).
K liegt zweimal drin: per Passwort (PBKDF2-SHA256 600k, fuer den Browser) und per RSA-OAEP-SHA256 (privater Schluessel nur
auf dem PC + als Actions-Secret RSA_KEY). Passwort aendern = Browser macht neues K, PC/Runner brauchen das Passwort nie."""
import base64, json, os, pathlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

IT = 600_000
OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
KEYFILE = pathlib.Path.home() / ".config/bewerbungen/rsa.pem"
b64, ub = (lambda b: base64.b64encode(b).decode()), base64.b64decode


def private_key():
    pem = os.environ.get("RSA_KEY") or (KEYFILE.read_text() if KEYFILE.exists() else None)
    if pem:
        return serialization.load_pem_private_key(pem.encode(), None)
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    KEYFILE.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return k


def public_spki(k):
    return b64(k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))


def open_(b, pw=None, priv=None):
    """-> (daten, K, meta). Mit priv (RSA) oder pw."""
    j = json.loads(b)
    if priv is not None:
        K = priv.decrypt(ub(j["rsa"]), OAEP)
    else:
        w = j["pw"]
        K = AESGCM(PBKDF2HMAC(hashes.SHA256(), 32, ub(w["salt"]), IT).derive(pw.encode())).decrypt(ub(w["iv"]), ub(w["ct"]), None)
    return json.loads(AESGCM(K).decrypt(ub(j["iv"]), ub(j["ct"]), None)), K, j


def seal(obj, K, meta):
    """Neu verschluesseln mit vorhandenem K, Passwort- und RSA-Huelle bleiben."""
    iv = os.urandom(12)
    ct = AESGCM(K).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), None)
    return json.dumps({"v": 2, "pw": meta["pw"], "rsa": meta["rsa"], "iv": b64(iv), "ct": b64(ct)}).encode()


def new(obj, pw, priv):
    """Erstes Bundle (oder Migration): neues K, mit Passwort und RSA verpackt."""
    K, salt, iv = os.urandom(32), os.urandom(16), os.urandom(12)
    wrap = AESGCM(PBKDF2HMAC(hashes.SHA256(), 32, salt, IT).derive(pw.encode())).encrypt(iv, K, None)
    meta = {"pw": {"salt": b64(salt), "iv": b64(iv), "ct": b64(wrap)}, "rsa": b64(priv.public_key().encrypt(K, OAEP))}
    return seal(obj, K, meta)
