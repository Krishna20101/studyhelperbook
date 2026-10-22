#!/usr/bin/env python3
"""
Book PDF library  -  Telegram admin bot + website in ONE script.

SETUP - Option A: Termux (phone):
    pkg install python
    pip install -r requirements.txt
    pip install "telethon[tqdm]"        # optional: big PDFs (20 MB -> 2 GB)
    export BOT_TOKEN="..." ADMIN_IDS="..."
    export API_ID="..." API_HASH="..."  # optional, free at my.telegram.org
    # Firebase (optional on Termux): an Email/Password user created in the
    # Firebase console -> FIREBASE_EMAIL + FIREBASE_PASSWORD
    python bot_server.py
Open  http://localhost:8080  in the browser.

SETUP - Option B: Render (24/7 - phone can stay OFF):
    1. Firebase is REQUIRED on Render (its disk is temporary). Create a project
       with a Realtime Database + an Email/Password Auth user. Set the env vars:
       BOT_TOKEN, ADMIN_IDS, FIREBASE_DB_URL, FIREBASE_API_KEY,
       FIREBASE_EMAIL, FIREBASE_PASSWORD  (see README-RENDER.md).
       NO service account needed.
    2. Push this folder to GitHub -> New > Web Service in Render (render.yaml
       has the build/start commands) -> deploy.
    3. Point a free pinger (UptimeRobot) at  https://YOUR-SERVICE.onrender.com/ping
       every 1 minute so the free instance never sleeps.

First time: press /start in the bot -> it shows your Telegram ID ->
put it in ADMIN_IDS (comma separated, e.g. 111111,222222) -> redeploy/restart.
Admin commands (no keyboard - normal users see nothing):
    /add /manage /stats /key /backup /cancel

Storage: books + stats are always mirrored to data.json. On Termux that file IS
your database. On Render the disk is temporary, so keep Firebase enabled there,
otherwise data is lost on every deploy/restart. The PDFs themselves always live
in Telegram storage; the server only keeps a small cache.
"""
import base64
import hashlib
import json
import math
import os
import queue
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ============================ SETTINGS ============================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8770772998:AAHMFGXNb3fCu_2FvBgSBzDFB2kPB1fMJso")
# Who can use the bot menu. The env var (comma separated) wins over the list:
_env_admin = os.environ.get("ADMIN_IDS", "7191422858,8898541371").replace(" ", "")
ADMIN_IDS = [int(x) for x in _env_admin.split(",") if x.lstrip("-").isdigit()]
STORAGE_CHAT_ID = int(os.environ.get("STORAGE_CHAT_ID", 0))   # 0 = merged PDFs go to the admin's chat
PORT = int(os.environ.get("PORT", 8080))                      # Render sets PORT automatically

# --- Firebase Realtime Database (REQUIRED on Render - see header) ---
# Setup: Firebase console par ek Email/Password user banao (Authentication ->
# Sign-in method -> Email/Password) aur uska email/password yahan do.
# Service account ki zaroorat NAHI hai.
FIREBASE_DB_URL = os.environ.get("FIREBASE_DB_URL", "https://studyhelperbooks-default-rtdb.asia-southeast1.firebasedatabase.app")        # https://xxxx-default-rtdb.firebaseio.com
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "AIzaSyDaeOMUqgAqeDLKDqwTdS1OEJaSU_B9DBs")       # Project settings -> Web API key
FIREBASE_EMAIL = os.environ.get("FIREBASE_EMAIL", "studyhelper@gmail.com")
FIREBASE_PASSWORD = os.environ.get("FIREBASE_PASSWORD", "Krishna@2010")

# --- limits & protection ---
MAX_PDF_MB = int(os.environ.get("MAX_PDF_MB", 20))        # Bot API can download files up to 20 MB
PAGE_SIZE = 10                                            # books per page in Manage
CACHE_LIMIT_MB = int(os.environ.get("CACHE_LIMIT_MB", 150))  # kept on this device (Render free disk is 512 MB; set 500 on Termux)
TRUST_PROXY = False         # True only if you run behind Cloudflare/Nginx (uses X-Forwarded-For)

# --- big file support (optional, MTProto) ---
# Free at https://my.telegram.org  ->  with both set + telethon installed, the bot
# downloads/uploads PDFs up to ~2 GB instead of the 20 MB Bot API limit.
API_ID = os.environ.get("API_ID", "36349735")
API_HASH = os.environ.get("API_HASH", "373122633b75d964ca4a168c7b79e683")
try:
    from telethon.sync import TelegramClient  # noqa
    HAVE_TELETHON = True
except Exception:
    HAVE_TELETHON = False
TG_BIG = bool(API_ID) and bool(API_HASH) and HAVE_TELETHON
EF_MAX_MB = MAX_PDF_MB if (not TG_BIG or MAX_PDF_MB > 20) else 2000

# --- website key system (VPLINK download shortlinks) ---
# Each book gets ONE vplink.in shortlink whose destination is the bot's
# download deeplink (t.me/<bot>?start=dl_<id>). User completes the shortlink
# page and lands in the bot, which sends them the PDF.
# VPLINK API token (vplink.in -> Developers API). Pre-filled - override via env if needed.
VPLINK_API = os.environ.get("VPLINK_API_TOKEN", "23a35248e9fd9c07cba6ea618b508f726f518080")
# ==================================================================

BASE = os.path.dirname(os.path.abspath(__file__))
try:  # safety: if the script dir is read-only (some hosts), fall back to /tmp
    _probe = os.path.join(BASE, ".w")
    os.makedirs(_probe, exist_ok=True)
    os.rmdir(_probe)
except OSError:
    BASE = tempfile.gettempdir()
    print("NOTE: script dir is read-only - using %s for data.json and cache" % BASE)
DATA_FILE = os.path.join(BASE, "data.json")
OLD_DB_FILE = os.path.join(BASE, "books.json")
CACHE_DIR = os.path.join(BASE, "cache")
WEB_FILE = os.path.join(BASE, "index.html")
os.makedirs(CACHE_DIR, exist_ok=True)

VID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# --- at-rest encryption: data.json / Firebase mein PDF ka file_id KABHI plain
# --- nahi hota. Koi bhi database read karke direct download link nahi nikaal
# --- sakta - sirf is server (is key ke saath) decrypt kar sakta hai.
DATA_KEY = (os.environ.get("DATA_KEY") or "studyhelper-books-vp-key-v2").encode()


def _keystream(n):
    out = b""
    i = 0
    while len(out) < n:
        out += hashlib.sha256(DATA_KEY + i.to_bytes(4, "big")).digest()
        i += 1
    return out[:n]


def enc_secret(s):
    """Encrypt a string for storage (data.json / Firebase)."""
    if not s:
        return s
    raw = s.encode()
    ks = _keystream(len(raw))
    return "enc1:" + base64.b64encode(bytes(a ^ b for a, b in zip(raw, ks))).decode()


def dec_secret(v):
    """Decrypt a stored string. Plain values (old data) pass through."""
    if not isinstance(v, str) or not v.startswith("enc1:"):
        return v
    try:
        raw = base64.b64decode(v[5:])
        ks = _keystream(len(raw))
        return bytes(a ^ b for a, b in zip(raw, ks)).decode()
    except Exception:
        return v


def storage_book(b):
    """A copy of the book dict safe to write to disk/Firebase (file_id encrypted)."""
    c = dict(b)
    if c.get("file_id"):
        c["file_id"] = enc_secret(c["file_id"])
    return c


def live_book(b):
    """Decrypt a book dict read from disk/Firebase."""
    if b.get("file_id"):
        b["file_id"] = dec_secret(b["file_id"])
    return b


FB_ON = (not FIREBASE_DB_URL.startswith("PUT_")) and \
    (not FIREBASE_EMAIL.startswith("PUT_")) and \
    (not FIREBASE_PASSWORD.startswith("PUT_"))

try:
    import pypdf  # noqa
    HAVE_PYPDF = True
except Exception:
    HAVE_PYPDF = False


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# =================================================================
#  Firebase Realtime Database over plain REST (no extra libraries)
# =================================================================
class Firebase:
    def __init__(self):
        self.base = FIREBASE_DB_URL.rstrip("/")
        self.tok = None
        self.exp = 0
        self.lock = threading.Lock()

    def token(self):
        # Simple email/password sign-in (one user created in the Firebase console)
        with self.lock:
            if self.tok and time.time() < self.exp - 120:
                return self.tok
            body = json.dumps({"email": FIREBASE_EMAIL, "password": FIREBASE_PASSWORD,
                               "returnSecureToken": True}).encode()
            url = ("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key="
                   + urllib.parse.quote(FIREBASE_API_KEY))
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode())
            self.tok, ttl = d["idToken"], int(d.get("expiresIn", 3600))
            self.exp = time.time() + ttl
            return self.tok

    def call(self, method, path, data=None):
        url = "%s/%s.json?auth=%s" % (self.base, path, urllib.parse.quote(self.token()))
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode() or "null")

    def get(self, path): return self.call("GET", path)
    def put(self, path, data): return self.call("PUT", path, data)
    def delete(self, path): return self.call("DELETE", path)


# =================================================================
#  Store: books + stats  (local file always, Firebase when enabled)
# =================================================================
def new_stats():
    return {"visits": 0, "opens": 0, "visitors": {}, "days": {}, "clicks": {}}


def new_settings():
    return {"keygen": True}


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.books = {}
        self.stats = new_stats()
        self.settings = new_settings()
        self.dirty = False
        self.fb = Firebase() if FB_ON else None
        self.load()

    # ---- loading
    def _read_local(self):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d.get("books") or {}, d.get("stats") or new_stats(), d.get("settings") or new_settings()
        except Exception:
            pass
        books = {}
        try:  # migrate the old test version (books.json was a list)
            with open(OLD_DB_FILE, "r", encoding="utf-8") as f:
                for b in json.load(f):
                    bid = str(b["id"])
                    books[bid] = {"id": bid, "name": b.get("name", "Test"), "file_id": b["file_id"],
                                  "size": b.get("size", 0), "pages": 0, "cover": None,
                                  "hidden": False, "created": int(time.time())}
        except Exception:
            pass
        return books, new_stats(), new_settings()

    def load(self):
        lbooks, lstats, lset = self._read_local()
        for b in lbooks.values():
            live_book(b)
        self.books, self.stats, self.settings = lbooks, lstats, new_settings()
        self.settings.update(lset)
        if self.fb:
            try:
                rbooks = self.fb.get("books") or {}
                for b in rbooks.values():          # file_id comes back encrypted
                    live_book(b)
                rstats = self.fb.get("stats")
                rset = self.fb.get("settings")
                if rbooks:
                    self.books = rbooks
                    self.stats = rstats or new_stats()
                    self.settings = new_settings()
                    if rset:
                        self.settings.update(rset)
                elif lbooks:                       # first time: push local data up
                    self.fb.put("books", {k: storage_book(b) for k, b in lbooks.items()})
                    self.fb.put("stats", lstats)
                    self.fb.put("settings", lset)
                print("Firebase connected (%d books)." % len(self.books))
            except Exception as e:
                print("Firebase problem, using local data only:", e)
        for k in ("visits", "opens", "visitors", "days", "clicks"):
            self.stats.setdefault(k, 0 if k in ("visits", "opens") else {})
        self._save_local()

    # ---- saving
    def _save_local(self):
        # file_id is encrypted at rest, so a plain read of data.json never
        # reveals the direct Telegram file id.
        safe_books = {k: storage_book(b) for k, b in self.books.items()}
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"books": safe_books, "stats": self.stats, "settings": self.settings},
                      f, ensure_ascii=False)
        os.replace(tmp, DATA_FILE)

    def save_settings(self):
        with self.lock:
            self._save_local()
            self._fb(lambda: self.fb.put("settings", self.settings))

    def _fb(self, fn):
        if not self.fb:
            return
        try:
            fn()
        except Exception as e:
            print("Firebase write failed (saved locally):", e)

    def next_id(self):
        with self.lock:
            nums = [int(k) for k in self.books if str(k).isdigit()]
            return str(max(nums, default=0) + 1)

    def save_book(self, b):
        with self.lock:
            self.books[b["id"]] = b
            self._save_local()
            self._fb(lambda: self.fb.put("books/" + b["id"], storage_book(b)))

    def delete_book(self, bid):
        with self.lock:
            self.books.pop(bid, None)
            self.stats["clicks"].pop(bid, None)
            self.dirty = True
            self._save_local()
            self._fb(lambda: self.fb.delete("books/" + bid))

    def ordered(self, include_hidden=True):
        with self.lock:
            items = [b for b in self.books.values() if include_hidden or not b.get("hidden")]
        return sorted(items, key=lambda b: (b.get("created", 0), int(b["id"]) if str(b["id"]).isdigit() else 0))

    # ---- stats
    def record_visit(self, vid):
        with self.lock:
            s = self.stats
            s["visits"] += 1
            s["visitors"].setdefault(vid, int(time.time()))
            day = s["days"].setdefault(today(), {"v": 0, "o": 0})
            day["v"] += 1
            self.dirty = True

    def flush(self):
        with self.lock:
            if not self.dirty:
                return
            for d in sorted(self.stats["days"])[:-60]:
                self.stats["days"].pop(d, None)
            self.dirty = False
            self._save_local()
            self._fb(lambda: self.fb.put("stats", self.stats))


STORE = None  # created in main()


def flush_loop():
    while True:
        time.sleep(30)
        try:
            STORE.flush()
        except Exception as e:
            print("flush error:", e)


# =================================================================
#  MTProto (big files) - one Telethon client in a dedicated thread
# =================================================================
class _MTProto:
    """Telethon's sync client is bound to its creating thread, so all calls are
    queued to a single worker thread - safe to use from bot AND web threads."""

    def __init__(self, session_path, api_id, api_hash, token):
        self._err = None
        self._ready = threading.Event()
        self._q = queue.Queue()
        threading.Thread(target=self._run, args=(session_path, api_id, api_hash, token),
                         daemon=True).start()

    def _run(self, session_path, api_id, api_hash, token):
        try:
            self._client = TelegramClient(session_path, api_id, api_hash)
            self._client.start(bot_token=token)   # bot login - no phone number involved
        except Exception as e:
            self._err = e
        self._ready.set()
        if self._err:
            print("MTProto connect failed (big files stay OFF):", self._err)
            return
        print("MTProto connected - PDFs up to ~2 GB can now be added and served.")
        while True:
            self._q.get()()

    def call(self, fn, timeout=1800):
        if not self._ready.wait(90):
            raise RuntimeError("MTProto not ready")
        if self._err:
            raise self._err
        holder, ev = {}, threading.Event()

        def wrap():
            try:
                holder["v"] = fn(self._client)
            except Exception as e:
                holder["e"] = e
            ev.set()
        self._q.put(wrap)
        if not ev.wait(timeout):
            raise RuntimeError("MTProto operation timed out")
        if "e" in holder:
            raise holder["e"]
        return holder["v"]


_MT = None  # created in main() when TG_BIG


# =================================================================
#  Telegram helpers
# =================================================================
def tg(method, params=None, timeout=30):
    url = "https://api.telegram.org/bot%s/%s" % (BOT_TOKEN, method)
    data = urllib.parse.urlencode(params or {}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        res = json.loads(e.read().decode() or "{}")
    if not res.get("ok"):
        raise RuntimeError("Telegram error: %s" % res.get("description", res))
    return res["result"]


def tg_download(file_id, dest):
    if _MT:  # MTProto first: handles any size up to ~2 GB
        try:
            # NOTE: no big_file kwarg - newer Telethon versions (>=1.36) removed it
            _MT.call(lambda c: c.download_media(file_id, file=dest))
            if os.path.getsize(dest) > 0:
                return dest
        except Exception as e:
            print("MTProto download failed, trying Bot API:", e)
    info = tg("getFile", {"file_id": file_id})
    url = "https://api.telegram.org/file/bot%s/%s" % (BOT_TOKEN, info["file_path"])
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, dest)
    return dest


def tg_upload_document(chat_id, path, filename, caption=""):
    if _MT and os.path.getsize(path) > 20 * 1048576:  # Bot API only sends up to 20 MB
        msg = _MT.call(lambda c: c.send_file(chat_id, path, caption=caption), timeout=3600)
        doc = getattr(msg, "document", None)
        if doc is None or not getattr(doc, "file_id", None):
            raise RuntimeError("Upload failed: no document in response")
        return {"document": {"file_id": doc.file_id}}
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", str(chat_id)), ("caption", caption)):
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode())
    parts.append(('--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
                  'Content-Type: application/pdf\r\n\r\n' % (boundary, filename)).encode())
    with open(path, "rb") as f:
        parts.append(f.read())
    parts.append(("\r\n--%s--\r\n" % boundary).encode())
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendDocument" % BOT_TOKEN,
                                 data=b"".join(parts),
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        res = json.loads(e.read().decode() or "{}")
    if not res.get("ok"):
        raise RuntimeError("Upload failed: %s" % res.get("description", res))
    return res["result"]


def markup_rows(rows):
    return json.dumps({"keyboard": [[{"text": t} for t in row] for row in rows], "resize_keyboard": True})


def inline_rows(rows):
    return json.dumps({"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]})


def say(chat_id, text, markup=None):
    p = {"chat_id": chat_id, "text": text}
    if markup:
        p["reply_markup"] = markup
    try:
        return tg("sendMessage", p)
    except Exception as e:
        print("send failed:", e)


def edit(chat_id, mid, text, markup=None):
    p = {"chat_id": chat_id, "message_id": mid, "text": text}
    if markup:
        p["reply_markup"] = markup
    try:
        tg("editMessageText", p)
    except Exception as e:
        if "not modified" not in str(e):
            print("edit failed:", e)


# =================================================================
#  PDF helpers
# =================================================================
def open_reader(path):
    from pypdf import PdfReader
    r = PdfReader(path)
    if r.is_encrypted:
        try:
            ok = r.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            raise ValueError("password protected")
    return r


def pdf_pages(path):
    return len(open_reader(path).pages)


def merge_pdfs(paths, out):
    from pypdf import PdfWriter
    w = PdfWriter()
    for p in paths:
        for pg in open_reader(p).pages:
            w.add_page(pg)
    with open(out, "wb") as f:
        w.write(f)
    return len(w.pages)


def human(n):
    return "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%d KB" % max(1, round(n / 1024.0))


def sniff_image(path):
    with open(path, "rb") as f:
        h = f.read(12)
    if h.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if h.startswith(b"\x89PNG"):
        return "image/png"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "image/webp"
    if h[:3] == b"GIF":
        return "image/gif"
    return "application/octet-stream"


dl_lock = threading.Lock()


def trim_cache(keep=None):
    try:
        files = []
        for n in os.listdir(CACHE_DIR):
            p = os.path.join(CACHE_DIR, n)
            if os.path.isfile(p) and p != keep:
                files.append((os.path.getatime(p), os.path.getsize(p), p))
        total = sum(f[1] for f in files)
        files.sort()
        while files and total > CACHE_LIMIT_MB * 1048576:
            _, sz, p = files.pop(0)
            os.remove(p)
            total -= sz
    except Exception as e:
        print("cache trim:", e)


def ensure_pdf(book):
    path = os.path.join(CACHE_DIR, "pdf_%s.pdf" % book["id"])
    with dl_lock:
        if not (os.path.isfile(path) and os.path.getsize(path) > 0):
            tg_download(book["file_id"], path)
            trim_cache(keep=path)
    os.utime(path, None)
    return path


def ensure_cover(book):
    c = book.get("cover")
    if not c or c.get("type") != "tg":
        return None
    path = os.path.join(CACHE_DIR, "cover_%s_%s" % (book["id"], hashlib.md5(c["value"].encode()).hexdigest()[:8]))
    with dl_lock:
        if not (os.path.isfile(path) and os.path.getsize(path) > 0):
            tg_download(c["value"], path)
    return path


def drop_cache(bid):
    for n in os.listdir(CACHE_DIR):
        if n == "pdf_%s.pdf" % bid or n.startswith("cover_%s_" % bid):
            try:
                os.remove(os.path.join(CACHE_DIR, n))
            except OSError:
                pass


# =================================================================
#  Admin bot
# =================================================================
B_DONE, B_CANCEL, B_SKIP = "\u2705 Done", "\u274C Cancel", "\u23ED Skip"
STATES = {}

# NOTE: no reply keyboard anymore - admin options are COMMANDS (/add /manage
# /stats /key /backup) so normal users never see admin options at all.
ADMIN_CMDS = ("Add a book: /add   Manage books: /manage   Stats: /stats\n"
              "Key system: /key   Backup: /backup   Cancel: /cancel")


def menu(chat, text):
    STATES.pop(chat, None)
    say(chat, text)


def parse_cover(msg):
    """returns ({'type':..,'value':..}, None) or (None, error text)"""
    if msg.get("photo"):
        return {"type": "tg", "value": msg["photo"][-1]["file_id"]}, None
    doc = msg.get("document")
    if doc:
        if (doc.get("mime_type") or "").startswith("image/"):
            return {"type": "tg", "value": doc["file_id"]}, None
        return None, "That is not an image. Please send a photo or an image link (or type Skip)."
    t = (msg.get("text") or "").strip()
    if re.match(r"^https?://\S+$", t):
        return {"type": "url", "value": t}, None
    return None, "Please send a photo, or a link starting with http:// or https:// (or type Skip)."


def show_stats(chat):
    s = STORE.stats
    with STORE.lock:
        books = STORE.ordered()
        t = today()
        td = s["days"].get(t, {"v": 0, "o": 0})
        lines = ["\U0001F4CA Stats", "",
                 "\U0001F465 Unique visitors: %d" % len(s["visitors"]),
                 "\U0001F440 Total visits: %d  (today: %d)" % (s["visits"], td["v"]),
                 "\U0001F4D6 PDF downloads (bot): %d  (today: %d)" % (s["opens"], td["o"]),
                 "\U0001F4DA Books: %d  (hidden: %d)" % (len(books), sum(1 for b in books if b.get("hidden")))]
        top = sorted(((s["clicks"].get(b["id"], 0), b) for b in books), key=lambda x: -x[0])[:10]
        top = [x for x in top if x[0] > 0]
        if top:
            lines += ["", "\U0001F525 Top books"]
            lines += ["%d. %s - %d opens" % (i, b["name"][:40], n) for i, (n, b) in enumerate(top, 1)]
        days = sorted(s["days"])[-7:]
        if days:
            lines += ["", "Last days (visits / downloads)"]
            lines += ["%s: %d / %d" % (d, s["days"][d]["v"], s["days"][d]["o"]) for d in reversed(days)]
    say(chat, "\n".join(lines))


def manage_view(page):
    books = STORE.ordered()
    kg_on = bool(STORE.settings.get("keygen"))
    if not books:
        rows = [[("🔑 Keys: %s — tap to switch" % ("ON" if kg_on else "OFF"), "kg:toggle")]]
        return "No books yet. Tap \u2795 Add Book.", inline_rows(rows)
    pages = max(1, math.ceil(len(books) / PAGE_SIZE))
    page = min(max(1, page), pages)
    chunk = books[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    rows = [[("🔑 Keys: %s — tap to switch" % ("ON" if kg_on else "OFF"), "kg:toggle")]]
    for b in chunk:
        label = "%s%s (%d)" % ("\U0001F648 " if b.get("hidden") else "", b["name"][:32], STORE.stats["clicks"].get(b["id"], 0))
        rows.append([("#%s  %s" % (b["id"], label), "bk:%s:%d" % (b["id"], page))])
    nav = []
    if page > 1:
        nav.append(("\u25C0 Page %d" % (page - 1), "pg:%d" % (page - 1)))
    if page < pages:
        nav.append(("Page %d \u25B6" % (page + 1), "pg:%d" % (page + 1)))
    if nav:
        rows.append(nav)
    return "\U0001F4DA Books - page %d of %d  (%d total)\nTap a book to manage it." % (page, pages, len(books)), inline_rows(rows)


def detail_view(bid, page):
    b = STORE.books.get(bid)
    if not b:
        return "Book not found.", inline_rows([[("\u25C0 Back", "pg:%d" % page)]])
    c = b.get("cover")
    text = ("\U0001F4D6 %s\nID: %s\nSize: %s%s\nCover: %s\nStatus: %s\nOpens: %d" % (
        b["name"], b["id"], human(b.get("size", 0)),
        ("  |  Pages: %d" % b["pages"]) if b.get("pages") else "",
        {"tg": "uploaded image", "url": "link"}.get((c or {}).get("type"), "none"),
        "hidden" if b.get("hidden") else "visible",
        STORE.stats["clicks"].get(bid, 0)))
    if STORE.settings.get("keygen"):
        text += ("\n\n\u2B07\uFE0F Download key: %s" % (b.get("dl_link") or "(not created yet)"))
    return text, inline_rows([
        [("\u270F\uFE0F Rename", "ren:%s:%d" % (bid, page)), ("\U0001F5BC Cover", "cov:%s:%d" % (bid, page))],
        [("Show" if b.get("hidden") else "\U0001F648 Hide", "hid:%s:%d" % (bid, page)),
         ("\U0001F5D1 Delete", "del:%s:%d" % (bid, page))],
        [("\U0001F511 Create / refresh keys", "key:%s:%d" % (bid, page))],
        [("\u25C0 Back", "pg:%d" % page)]])


def regen_keys_cb(chat, mid, bid, page):
    k = keygen_book(bid)
    if k and k["dl_link"]:
        say(chat, "\U0001F511 Key ready:\n\u2B07\uFE0F Download: %s" % k["dl_link"])
    else:
        say(chat, "\u26A0\uFE0F Could not create the key. Check the VPLINK token/balance "
                  "in the script and tap the key button again.")
    t, m = detail_view(bid, page)
    try:
        edit(chat, mid, t, m)
    except Exception:
        pass


def handle_callback(cb):
    chat = cb["message"]["chat"]["id"]
    mid = cb["message"]["message_id"]
    uid = cb["from"]["id"]
    try:
        tg("answerCallbackQuery", {"callback_query_id": cb["id"]})
    except Exception:
        pass
    if uid not in ADMIN_IDS:
        return
    parts = (cb.get("data") or "").split(":")
    act = parts[0]
    if act == "pg":
        t, m = manage_view(int(parts[1]))
        edit(chat, mid, t, m)
        return
    bid, page = parts[1], int(parts[2]) if len(parts) > 2 else 1
    if act == "bk":
        t, m = detail_view(bid, page)
        edit(chat, mid, t, m)
    elif act == "hid":
        b = STORE.books.get(bid)
        if b:
            b["hidden"] = not b.get("hidden")
            STORE.save_book(b)
        t, m = detail_view(bid, page)
        edit(chat, mid, t, m)
    elif act == "del":
        b = STORE.books.get(bid)
        name = b["name"] if b else "this book"
        edit(chat, mid, "Delete \"%s\"? This cannot be undone." % name,
             inline_rows([[("Yes, delete", "dely:%s:%d" % (bid, page)), ("Cancel", "bk:%s:%d" % (bid, page))]]))
    elif act == "dely":
        STORE.delete_book(bid)
        drop_cache(bid)
        t, m = manage_view(page)
        edit(chat, mid, "\U0001F5D1 Deleted.\n\n" + t, m)
    elif act == "ren":
        STATES[chat] = {"step": "rename", "data": {"id": bid}}
        say(chat, "Send the new book name (text only). Type /cancel to stop.")
    elif act == "cov":
        STATES[chat] = {"step": "newcover", "data": {"id": bid}}
        say(chat, "Send the new cover: a photo, or an image link. Type /cancel to stop.")
    elif act == "kg":
        on = {"on": True, "off": False}.get(parts[1])
        if on is None:                       # "toggle"
            on = not STORE.settings.get("keygen")
        note = set_keygen(on)
        edit(chat, mid, keygen_message() + "\n\n" + note, keygen_buttons())
    elif act == "key":
        edit(chat, mid, "\U0001F511 Creating keys for this book...",
             inline_rows([[(("\u25C0 Back", "bk:%s:%d" % (bid, page)))]]))
        threading.Thread(target=regen_keys_cb, args=(chat, mid, bid, page), daemon=True).start()


def handle_message(msg):
    if not msg:
        return
    chat = msg["chat"]["id"]
    uid = (msg.get("from") or {}).get("id", 0)
    text = (msg.get("text") or "").strip()

    if text.startswith("/start"):
        parts = text.split()
        if len(parts) > 1 and parts[1].startswith("dl_") and parts[1][3:].isdigit():
            # Public download link: vplink -> t.me/bot?start=dl_<book id> -> PDF.
            bid = parts[1][3:]
            b = STORE.books.get(bid)
            if not b or b.get("hidden"):
                say(chat, "😕 This book link is not valid anymore. Sorry!")
                return
            say(chat, "⬇️ Preparing your PDF \"%s\"...\nBig files can take a minute." % b["name"][:50])
            threading.Thread(target=send_book_pdf, args=(chat, bid), daemon=True).start()
            return
        if uid in ADMIN_IDS:
            menu(chat, "Welcome back!\n" + ADMIN_CMDS)
        else:
            say(chat, "Your Telegram ID: %s\n\nPut it in ADMIN_IDS inside bot_server.py and restart the script "
                      "to use this bot." % uid)
        return
    if uid not in ADMIN_IDS:
        say(chat, "You are not allowed to use this bot. Your ID: %s" % uid)
        return

    # --- commands (admin only - checked above)
    if text in (B_CANCEL, "/cancel"):
        menu(chat, "Cancelled.")
        return
    if text == "/add":
        STATES[chat] = {"step": "name", "data": {}}
        say(chat, "Step 1/3 - Send the book name (text only).\nType /cancel to stop.")
        return
    if text in ("/manage", "/list"):
        STATES.pop(chat, None)
        t, m = manage_view(1)
        say(chat, t, m)
        return
    if text == "/stats":
        STATES.pop(chat, None)
        show_stats(chat)
        return
    if text == "/key":
        STATES.pop(chat, None)
        say(chat, keygen_message(), keygen_buttons())
        return
    if text == "/backup":
        try:
            STORE.flush()
            tmp = os.path.join(CACHE_DIR, "backup.json")
            shutil.copy(DATA_FILE, tmp)
            tg_upload_document(chat, tmp, "backup.json", "Backup of books and stats")
            os.remove(tmp)
        except Exception as e:
            say(chat, "Backup failed: %s" % e)
        return

    st = STATES.get(chat)
    if not st:
        say(chat, "Use these commands:\n" + ADMIN_CMDS)
        return
    step, d = st["step"], st["data"]

    if step == "name":
        if not text or text.startswith("/") or msg.get("document") or msg.get("photo"):
            say(chat, "Please enter the book name - text only. No files or photos.")
            return
        if len(text) > 80:
            say(chat, "Name is too long (max 80 characters). Please send a shorter name.")
            return
        d["name"] = text
        st["step"] = "cover"
        say(chat, "Step 2/3 - Send the cover: a photo (upload it here) or an image link.\nOr type Skip.")

    elif step == "cover":
        if text in (B_SKIP, "Skip", "skip", "/skip"):
            d["cover"] = None
        else:
            c, err = parse_cover(msg)
            if err:
                say(chat, err)
                return
            d["cover"] = c
        d["pdfs"] = []
        st["step"] = "pdfs"
        say(chat, "Step 3/3 - Send the PDF file(s).\nSeveral PDFs are merged in the order you send them "
                  "(forwarded files work too). Type Done when finished.")

    elif step == "pdfs":
        if text in (B_DONE, "Done", "done", "/done"):
            if not d["pdfs"]:
                say(chat, "Please send at least one PDF first.")
                return
            st["step"] = "busy"
            threading.Thread(target=finish_add, args=(chat, st), daemon=True).start()
            return
        doc = msg.get("document")
        if not doc:
            say(chat, "Only PDF files are accepted here. Send a PDF, or type Done / /cancel.")
            return
        fname = doc.get("file_name") or "book.pdf"
        if not (doc.get("mime_type") == "application/pdf" or fname.lower().endswith(".pdf")):
            say(chat, "\"%s\" is not a PDF. Please send PDF files only." % fname[:60])
            return
        size = doc.get("file_size", 0)
        if size > EF_MAX_MB * 1048576:
            say(chat, "That file is %s. Each PDF must be under %d MB." % (human(size), EF_MAX_MB))
            return
        d["pdfs"].append({"mid": msg.get("message_id", 0), "file_id": doc["file_id"], "name": fname, "size": size})
        say(chat, "\u2705 PDF %d received: %s (%s)\nSend more, or tap Done." % (len(d["pdfs"]), fname[:50], human(size)))

    elif step == "busy":
        say(chat, "\u23F3 Still processing, please wait...")

    elif step == "rename":
        if not text or text.startswith("/") or msg.get("document") or msg.get("photo"):
            say(chat, "Please send the new name as text only.")
            return
        b = STORE.books.get(d["id"])
        if b:
            b["name"] = text[:80]
            STORE.save_book(b)
        menu(chat, "\u270F\uFE0F Renamed to \"%s\"." % text[:80])

    elif step == "newcover":
        c, err = parse_cover(msg)
        if err:
            say(chat, err.replace(" (or tap Skip)", ""))
            return
        b = STORE.books.get(d["id"])
        if b:
            b["cover"] = c
            STORE.save_book(b)
        menu(chat, "\U0001F5BC Cover updated.")


def finish_add(chat, st):
    d = st["data"]
    files = sorted(d["pdfs"], key=lambda x: x["mid"])
    say(chat, "\u23F3 Processing %d PDF(s)..." % len(files))
    tmp = tempfile.mkdtemp(dir=CACHE_DIR)
    try:
        paths = []
        for i, f in enumerate(files, 1):
            p = os.path.join(tmp, "%d.pdf" % i)
            tg_download(f["file_id"], p)
            paths.append(p)
        pages = 0
        if HAVE_PYPDF:
            for i, p in enumerate(paths, 1):
                try:
                    pages += pdf_pages(p)
                except Exception as e:
                    say(chat, "\u274C PDF %d (%s) cannot be read (%s). Nothing was saved.\nTap Add Book to try again."
                        % (i, files[i - 1]["name"][:40], e))
                    return
        if len(paths) == 1:
            final, file_id, size = paths[0], files[0]["file_id"], files[0]["size"]
        else:
            if not HAVE_PYPDF:
                say(chat, "\u274C Merging needs the pypdf library. Run:  pip install pypdf\nthen restart the script.")
                return
            final = os.path.join(tmp, "merged.pdf")
            pages = merge_pdfs(paths, final)
            size = os.path.getsize(final)
            if size > EF_MAX_MB * 1048576:
                say(chat, "\u274C The merged PDF is %s, above the %d MB limit. Nothing was saved. "
                          "Send fewer or smaller PDFs." % (human(size), EF_MAX_MB))
                return
            res = tg_upload_document(STORAGE_CHAT_ID or chat, final, "book.pdf", "Merged: %s" % d["name"][:60])
            file_id = res["document"]["file_id"]
        bid = STORE.next_id()
        book = {"id": bid, "name": d["name"], "file_id": file_id, "size": size, "pages": pages,
                "cover": d.get("cover"), "hidden": False, "created": int(time.time())}
        STORE.save_book(book)
        try:
            shutil.copy(final, os.path.join(CACHE_DIR, "pdf_%s.pdf" % bid))
        except Exception:
            pass
        extra = ""
        if STORE.settings.get("keygen"):
            k = keygen_book(bid)
            if k and k["dl_link"]:
                extra = ("\n\n\u2705 Download key created:\n"
                         "\u2B07\uFE0F %s\n    opens \u2192 %s" % (k["dl_link"], k["dl_ep"]))
            else:
                extra = ("\n\n\u26A0\uFE0F Book saved, but VPLINK key creation failed. "
                         "Retry any time: Manage \u2192 book \u2192 \u2711 Create / refresh keys.")
        say(chat, "\u2705 Book added!\n%s\nID %s - %s%s%s" % (
            d["name"], bid, human(size), (" - %d pages" % pages) if pages else "", extra))
    except Exception as e:
        print("finish_add error:", e)
        say(chat, "\u274C Something went wrong: %s\nNothing was saved. Use /add to try again." % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        STATES.pop(chat, None)


def poll_loop():
    try:
        tg("deleteWebhook")
    except Exception as e:
        print("deleteWebhook:", e)
    offset = 0
    while True:
        try:
            ups = tg("getUpdates", {"offset": offset, "timeout": 30,
                                    "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=45)
            for u in ups:
                offset = u["update_id"] + 1
                try:
                    if u.get("callback_query"):
                        handle_callback(u["callback_query"])
                    else:
                        handle_message(u.get("message"))
                except Exception as e:
                    print("handler error:", e)
        except Exception as e:
            print("poll error:", e)
            time.sleep(5)


# =================================================================
#  VPLINK key system: per-book DOWNLOAD shortlink
# =================================================================
BOT_USERNAME = ""  # filled in main() from getMe


def dl_endpoint(bid):
    """The real target behind the DOWNLOAD shortlink: the bot with the book id."""
    return "https://t.me/%s?start=dl_%s" % (BOT_USERNAME or "YourBotUsername", bid)


def vplink_shorten(url, alias=None):
    """Create one VPLINK shortlink. Returns the short URL or None."""
    if not VPLINK_API:
        return None
    u = ("https://vplink.in/api?api=%s&url=%s"
         % (urllib.parse.quote(VPLINK_API, safe=""), urllib.parse.quote(url, safe="")))
    if alias:
        u += "&alias=%s" % urllib.parse.quote(alias, safe="")
    try:
        with urllib.request.urlopen(u, timeout=30) as r:
            d = json.loads(r.read().decode() or "{}")
        if d.get("status") == "success":
            return (d.get("shortenedUrl") or "").strip() or None
        print("VPLINK error (%s): %s" % (alias or url, d.get("message")))
    except Exception as e:
        print("VPLINK request failed (%s): %s" % (alias or url, e))
    return None


def keygen_book(bid):
    """Create the DOWNLOAD shortlink for one book and store it on the book.
    Alias is fixed per book so links stay stable across restarts; on alias
    failure (already taken) we retry without an alias."""
    if not STORE or not STORE.books:
        return None
    b = STORE.books.get(bid)
    if not b:
        return None
    dep = dl_endpoint(bid)
    dl = vplink_shorten(dep, "bk%s_d" % bid) or vplink_shorten(dep)
    with STORE.lock:
        b2 = STORE.books.get(bid)
        if b2:
            b2["dl_link"] = dl or ""
            STORE.save_book(b2)
    return {"dl_link": dl or "", "dl_ep": dep}


def backfill_links(ids):
    for bid in ids:
        try:
            keygen_book(bid)
        except Exception as e:
            print("keygen backfill error for", bid, ":", e)
        time.sleep(1)
    print("Key backfill done for %d book(s)." % len(ids))
    if ADMIN_IDS:
        try:
            say(ADMIN_IDS[0], "🔑 Key backfill finished for %d book(s)." % len(ids))
        except Exception:
            pass


def keygen_message():
    on = bool(STORE.settings.get("keygen"))
    return ("🔑 Key system: %s\n\n"
            "When ON, every book on the website has its own VPLINK DOWNLOAD shortlink:\n"
            "• user taps ⬇ Download → the shortlink page opens (vplink.in)\n"
            "• when it completes, the user lands in THIS bot\n"
            "• the bot sends them the PDF right away\n\n"
            "When OFF, the website uses the direct bot link (no shortlink page).\n\n"
            "Downloads go to: https://t.me/%s?start=dl_<book id>" % ("ON ✅" if on else "OFF ❌",
                                                                      BOT_USERNAME or "yourbot"))


def keygen_buttons():
    return inline_rows([
        [("✅ Turn ON", "kg:on"), ("❌ Turn OFF", "kg:off")],
        [("📖 Back to Manage", "pg:1")],
    ])


def set_keygen(on):
    with STORE.lock:
        STORE.settings["keygen"] = bool(on)
        STORE.save_settings()
    if on:
        missing = [b["id"] for b in STORE.ordered() if not b.get("dl_link")]
        if missing:
            threading.Thread(target=backfill_links, args=(missing,), daemon=True).start()
            return "Creating VPLINK keys for %d book(s) in the background..." % len(missing)
        return "All books already have keys."
    return "Website now uses the direct bot link for downloads."


def send_book_pdf(chat, bid):
    """Public /start dl_<bid> handler: send the whole PDF to any user."""
    b = STORE.books.get(bid)
    if not b:
        return
    try:
        fpath = ensure_pdf(b)
        fname = re.sub(r"[^\w.\- ]", "", b["name"])[:60].strip().replace(" ", "_") or ("book_%s" % bid)
        tg_upload_document(chat, fpath, fname + ".pdf", "📚 %s\n(Study Helper Books)" % b["name"])
        with STORE.lock:
            s = STORE.stats
            s["clicks"][bid] = s["clicks"].get(bid, 0) + 1
            s["opens"] += 1
            s["days"].setdefault(today(), {"v": 0, "o": 0})["o"] += 1
            STORE.dirty = True
    except Exception as e:
        print("send_book_pdf error:", e)
        try:
            say(chat, "⚠️ Could not send the PDF right now. Please try again in a few minutes.")
        except Exception:
            pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # keep-alive: pdf.js ki range requests ke liye faster

    def log_message(self, *a):
        pass

    def ip(self):
        if TRUST_PROXY:
            xf = self.headers.get("X-Forwarded-For")
            if xf:
                return xf.split(",")[0].strip()
        return self.client_address[0]

    def reply(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def foreign_origin(self):
        host = self.headers.get("Host", "")
        site = self.headers.get("Sec-Fetch-Site")
        if site in ("cross-site", "same-site", "none"):
            return True
        for h in ("Origin", "Referer"):
            v = self.headers.get(h)
            if v and urllib.parse.urlparse(v).netloc != host:
                return True
        return False

    def read_json(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(min(n, 4096)).decode() or "{}")
        except Exception:
            return {}

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if self.foreign_origin():
                return self.reply(403, {"error": "forbidden"})
            body = self.read_json()
            vid = str(body.get("vid", ""))
            if not VID_RE.match(vid):
                return self.reply(400, {"error": "bad visitor id"})
            if path == "/api/visit":
                STORE.record_visit(vid)
                return self.reply(200, {"ok": True})
            self.reply(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print("POST error:", e)
            try:
                self.reply(500, {"error": "server"})
            except Exception:
                pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        try:
            if path == "/ping":  # keep-alive endpoint for the pinger (not rate limited, not counted)
                return self.reply(200, {"ok": True})
            if path in ("/", "/index.html"):
                with open(WEB_FILE, "rb") as f:
                    return self.reply(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/books":
                # Key system: with keygen ON each book carries its own VPLINK
                # download shortlink; when OFF (or a link is missing) the
                # direct bot link is returned so the site always works.
                kg = bool(STORE.settings.get("keygen"))
                out = []
                for b in STORE.ordered(include_hidden=False):
                    c = b.get("cover") or {}
                    cover = c.get("value") if c.get("type") == "url" else ("/api/cover/%s" % b["id"] if c.get("type") == "tg" else "")
                    dl = b.get("dl_link") if (kg and b.get("dl_link")) else dl_endpoint(b["id"])
                    out.append({"id": b["id"], "name": b["name"], "cover": cover, "dl": dl})
                return self.reply(200, out)
            if path.startswith("/api/cover/"):
                b = STORE.books.get(path[len("/api/cover/"):])
                if not b or b.get("hidden"):
                    return self.reply(404, "Not found", "text/plain")
                p = ensure_cover(b)
                if not p:
                    return self.reply(404, "Not found", "text/plain")
                with open(p, "rb") as f:
                    return self.reply(200, f.read(), sniff_image(p), {"Cache-Control": "public, max-age=3600"})
            self.reply(404, "Not found", "text/plain")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print("GET error:", e)
            try:
                self.reply(500, "Server error", "text/plain")
            except Exception:
                pass


def main():
    global STORE, _MT, BOT_USERNAME
    if BOT_TOKEN.startswith("PUT_"):
        print("Please set the BOT_TOKEN environment variable first (see README-RENDER.md).")
        return
    if not FB_ON:
        print("WARNING: Firebase is OFF - books and stats live only in the local data.json.")
        print("         On Render the disk is TEMPORARY: data is LOST on every deploy/restart.")
        print("         Set FIREBASE_DB_URL + FIREBASE_API_KEY + FIREBASE_EMAIL + FIREBASE_PASSWORD")
        print("         (an Email/Password user created in the Firebase console).")
    STORE = Store()
    try:
        BOT_USERNAME = tg("getMe").get("username") or ""
        print("Bot connected: @%s" % BOT_USERNAME)
    except Exception as e:
        BOT_USERNAME = ""
        print("Could not connect to Telegram:", e)
    try:
        tg("setMyCommands", {"commands": [
            {"command": "add", "description": "Add a new book"},
            {"command": "manage", "description": "Manage books"},
            {"command": "stats", "description": "Show stats"},
            {"command": "key", "description": "VPLINK key system ON/OFF"},
            {"command": "backup", "description": "Download data backup"},
            {"command": "cancel", "description": "Cancel current action"},
        ]})
    except Exception:
        pass
    if STORE.settings.get("keygen"):
        if not BOT_USERNAME:
            print("NOTE: download links need the bot username - Telegram connection failed,")
            print("      they will use the placeholder until the bot is reachable.")
        missing = [b["id"] for b in STORE.ordered() if not b.get("dl_link")]
        if missing:
            print("Key system: ON - creating VPLINK download keys for %d book(s) in the background..." % len(missing))
            threading.Thread(target=backfill_links, args=(missing,), daemon=True).start()
        else:
            print("Key system: ON - every book already has a VPLINK download key.")
    else:
        print("Key system: OFF - the website uses the direct bot link (no VPLINK shortlinks).")
    if TG_BIG:
        _MT = _MTProto(os.path.join(BASE, "bot_session"), API_ID, API_HASH, BOT_TOKEN)
        # warm up in the background: first big-file operation won't wait for login
        threading.Thread(target=lambda: _MT.call(lambda c: None, timeout=120), daemon=True).start()
        print("Big files: ON - MTProto (PDFs up to ~2 GB). Connecting in background...")
    elif API_ID or API_HASH:
        print("NOTE: API_ID and API_HASH must be set TOGETHER (both from my.telegram.org),")
        print('      and telethon must be installed:  pip install "telethon[tqdm]"')
    else:
        print("Big files: OFF - each PDF is limited to 20 MB (Bot API).")
        print('      To go up to 2 GB: set API_ID + API_HASH (free at my.telegram.org) and')
        print('      pip install "telethon[tqdm]"')
    if not ADMIN_IDS:
        print("NOTE: ADMIN_IDS is empty. Send /start to your bot, copy the ID it shows into ADMIN_IDS, restart.")
    if not HAVE_PYPDF:
        print("NOTE: pypdf not installed - merging several PDFs will not work.  Run: pip install pypdf")
    print("Firebase: %s" % ("ON" if FB_ON else "OFF (using local data.json)"))
    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=flush_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("Website running: http://localhost:%d   (Ctrl+C to stop)" % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STORE.flush()
        print("Stopped.")


if __name__ == "__main__":
    main()
