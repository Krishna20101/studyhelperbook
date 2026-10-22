# Study Helper Books — Complete Setup Guide

Ek hi website: **Books** (PDF library, Telegram bot se manage hoti) + **Tests**
(chapter-wise practice, GitHub data se). Ek hi naam, ek hi design, app jaisa feel.

```
┌────────────────────────── Study Helper Books ──────────────────────────┐
│  [SH] Study Helper Books                    ← upar fixed top bar       │
│                                                                        │
│  HOME   → "Where do you want to go?" → [Books] [Tests] do cards       │
│           (dono card par glowing Explore button)                      │
│  BOOKS  → books grid (search) → ⬇ Download → shortlink → bot → PDF   │
│  TESTS  → test library (search + categories) → chapters → quiz        │
│                                                                        │
│  ┌──────────┬──────────┬──────────┐                                    │
│  │  Home    │  Books   │  Tests   │  ← neeche FIXED bottom nav (scroll│
│  └──────────┴──────────┴──────────┘    nahi hota, app jaisa)          │
└────────────────────────────────────────────────────────────────────────┘
```

Page kholte hi **Telegram popup** aata hai (5 second mein auto-close, × se bhi band).
Poora site **phone-first** hai — 390px screen pe bhi koi side-scroll nahi.

---

## 1. Files (inhe hi upload/clone karna hai)

| File | Kaam |
|---|---|
| `bot_server.py` | Server: website + API + Telegram admin bot (ek script, sab kuch) |
| `index.html` | Puri website (home + books + tests + quiz) |
| `requirements.txt` | Python packages (`pypdf` + `telethon` bade PDF ke liye) |
| `render.yaml` | Render ko build/start instructions (Blueprint) |
| `README-RENDER.md` | Yeh file |

> `data.json` aur `cache/` **kabhi upload mat karo** — server khud banayega.

---

## 2. Website settings (index.html, sabse upar `CONFIG`)

```js
const CONFIG = {
  APP_NAME: 'Study Helper Books',
  LOGO_URL: '',                      // ←← YAHAN apna logo link paste karo
  TELEGRAM_LINK: 'https://t.me/studyhelperpw',
  GITHUB_USER: 'Krishna20101',       // tests ka data repo (public)
  GITHUB_REPO: 'studyhelperbook',
  GITHUB_BRANCH: 'main',
  INDEX_FILE: 'index.json',
  CACHE_MINUTES: 30,                 // test chapters browser cache
  POPUP_SECONDS: 5,                  // Telegram popup kitne second ke liye
  PAGE_SIZE: 10                      // kitne items ek saath (Load More)
};
```

- **Logo**: `LOGO_URL` mein link daalo. Abhi khali hai toh "SH" letter logo
  dikhayega (placeholder). Top bar, loader — sab jagah lag jayega.
- Purane naam ("Book Library", "SH Test") kahin nahi bache — sab "Study Helper Books" hai.

---

## 3. Pehla step: Termux par run karo (aapka plan)

```bash
# folder ko phone par le aao (git clone ya file manager)
pkg install python
pip install -r requirements.txt
export BOT_TOKEN="123:ABC..."          # @BotFather se
export ADMIN_IDS="123456789"           # apna Telegram ID (step neeche)
python bot_server.py
```

`http://localhost:8080` kholo — poora site chalu. Termux par `data.json` hi
database hai, Firebase optional (`FIREBASE_DB_URL` + `FIREBASE_API_KEY` +
`FIREBASE_EMAIL` + `FIREBASE_PASSWORD` export karo — Section 8 Step 1 wala
user; na chahiye toh skip, sab local hi rahega).

**Key system (section 7) Termux par bhi test ho sakta hai** — download
shortlink ka destination `t.me` (bot) hai jo public URL hai, isliye Termux
par bhi vplink shortlinks ban jaati hain. Koi `SITE_URL` ab zaroori NAHI hai.

**Apna Telegram ID kaise mile:** bot ko `/start` bhejo → woh aapka ID
dikhayega → usse `ADMIN_IDS` mein daalo → script dobara chalu karo.

### Bot ka istemal (sirf commands — keyboard NAHI)
Koi reply-keyboard nahi hai, isliye **normal user ko kuch admin ka nahi
dikhta**. Sirf aapke (ADMIN_IDS mein) liye commands kaam karte hain —
bot pehle admin ID check karta hai:

| Command | Kaam |
|---|---|
| `/add` | 3 steps: naam bhejo → cover (photo/link/Skip likho) → PDF file(s) bhejo → `Done` likho → **vplink download shortlink chat mein dikh jaati hai** |
| `/manage` | upar 🔑 Keys ON/OFF row + book list → rename / cover / hide-show / delete / 🔑 keys refresh |
| `/stats` | visitors, downloads, top books, last 7 days |
| `/key` | key system ka status (ON/OFF) + Turn ON / Turn OFF buttons |
| `/backup` | `data.json` file aapke chat mein |
| `/cancel` | chala hua flow (add/rename/cover) rokne ke liye |

Kai PDF bhejo toh merge ho kar ek book banti hai (pypdf ki wajah se).
Bina extra setup ke limit **20 MB** per PDF hai (Bot API ki limit) —
**50/100/1000 MB** ke liye neeche wala section 4 padho (2GB tak chala jata hai).

---

## 4. Bade PDFs — 50/100/1000 MB (MTProto, API ID + Hash se)

Abhi jo code hai usme yeh support **already bana hua hai** — bas 3 cheezein
lagani hain, phir bot **~2 GB tak** ki PDF le sakta hai:

1. **API ID + Hash lo** (free, 2 min): <https://my.telegram.org>
   → apne account se login → **API development tools** → "Create new application"
   → koi bhi naam daalo → `api_id` (number) aur `api_hash` (string) milega.
   ⚠️ Yeh **aapke Telegram app ka registration** hai — aapka phone number
   kahan bhi nahi jaata, aur personal account se bot login nahi hota.
2. **Telethon install karo:**
   ```bash
   pip install "telethon[tqdm]"
   ```
3. **Env vars set karke restart:**
   ```bash
   export API_ID="1234567"
   export API_HASH="abcdef0123456789abcdef0123456789"
   python bot_server.py
   ```

Chalne par terminal mein `MTProto connected - PDFs up to ~2 GB...` aana chahiye.

### Kya-kya hota hai
- **Bot se 2GB tak ki PDF bhejo** → book ban jayegi (50/100MB bilkul aaram se)
- **Wohi badi book bot se user tak** — user Download dabayega toh server
  Telegram se MTProto se download karke wapas bot se bhejta hai (pehle
  20MB se upar yahi fail hota tha)
- **Merged books** badi upload hoti hain (20MB+ merge bhi ab chalega)
- 20MB se chhoti PDFs pehle jaisi Bot API se hi (jaldi)
- Koi API_ID/API_HASH na ho → sab purane jaisa (20MB limit), kuch break nahi hota

### Dhyan rakhne wali baatein
- **`CACHE_LIMIT_MB` bada karo** agar badi books rakhi hain:
  `export CACHE_LIMIT_MB="3000"` (Termux par). 100MB ki 30 books = 3GB cache
  chahiye. Chhota rakhoge toh purani books auto-delete (dobara open par re-download).
- **Bahut bade merge (500MB+)** phone ki RAM par load hote hain — 50-100MB wale
  merge theek hain. Agar sirf 1 hi PDF bhejte ho toh merge nahi hota (seedha save).
- `bot_session` file ban jayegi folder mein — usse delete/upload mat karo.

---

## 5. Download kaise kaam karta hai (simple flow)

Site par ab **sirf Download** hai (PDF reader/site-par-padhne wala hissa
hata diya gaya hai) — isliye pura simple hai:

1. User book tile par **⬇ Download** dabata hai
2. Us book ki **VPLINK shortlink** khulti hai (vplink.in ki page)
3. Woh page complete hone par user **bot ke andar** land hota hai
   (`t.me/<bot>?start=dl_<book id>`)
4. Bot turant usse **poora PDF bhej deta hai** (2GB tak, MTProto ke saath)

Bas itna. Na koi view, na unlock timer, na verify page — **ek tap se PDF**.

---

## 6. Tests section (GitHub data) — kaise kaam karta hai

Tests ka data server se nahi, seedha **public GitHub repo** se aata hai
(isliye Render par bhi free aur fast):

```
Krishna20101/studyhelperbook  (PUBLIC repo hona zaroori hai)
├── index.json                    ← books ki list
│     { "books": [ { "book_id", "title", "folder_name",
│                    "cover_url", "categories": ["NEET", ...] } ] }
├── structure/<book_id>.json      ← har book ke chapters (fast path)
│     { "topics": [ { "topic_name", "files": [ { "name", "file", "count" } ] } ] }
└── <folder_name>/<chapter>/<exercise>.json   ← questions (fallback path)
      { "exercise_name", "questions": [
          { "question_text", "question_image",
            "options": [ { "id", "text", "image" } ],
            "correct_answer_ids": ["b"], "solution_image" } ] }
```

- Pehle `structure/<book_id>.json` try hota hai (raw file = fast, rate-limit
  nahi). Nahi mila toh GitHub API se folder scan hota hai (API rate limit:
  60 calls/hr/IP — isliye structure files banana best hai).
- Abhi **200 books** live hai — verified.
- Repo/branch badlane ho toh `CONFIG` ke `GITHUB_*` values edit karo.

---

## 7. 🔑 Key system (VPLINK download shortlink) — simple

Har book ke liye **1 VPLINK download shortlink** banti hai (vplink.in se).
Har book tile par sirf **ek button: ⬇ Download** hai — bas itna.

**Flow:**
1. User **⬇ Download** dabata hai
2. Us book ki **apni vplink shortlink** khulti hai
3. Page complete hone par user **bot ke andar** jaata hai
4. Bot **PDF bhej deta hai** (2GB tak)

Koi view / unlock timer / verify page NAHI — sab hata diya, pura simple.

**Admin ka kaam (bot, /commands):**
- **`/add`** → naam → cover → PDF → `Done` → bot **download shortlink chat mein dikhata hai**
  (link + uska asli destination URL)
- **`/manage`** → upar ek row `🔑 Keys: ON/OFF — tap to switch` + har book ke andar
  **🔑 Create / refresh keys** button
- **`/key`** → status (ON/OFF) + **Turn ON / Turn OFF** buttons
- Keygen **ON** → purani books ke missing shortlinks background mein bhi bante hain (backfill)
- Keygen **OFF** → koi shortlink nahi; site seedha bot link use karta hai (sab waise hi chalta hai)

**Private data (important):** data.json / Firebase mein PDF ka **file_id encrypted** hota hai
(`enc1:…`). Koi bhi database par direct read karke **direct PDF link/file_id nahi nikaal
sakti** — sirf server (apni key se) decrypt karta hai. Public API bhi sirf shortlink +
naam/cover deta hai, direct PDF URL kabhi nahi.

**Settings (env, optional):** `DATA_KEY` (encryption key — default built-in).

**VPLINK account:** token code mein pre-filled hai. Naya account lagana ho → `VPLINK_API_TOKEN`
env var. Har book = 1 shortlink. API fail ho toh book add ho jaati hai, bas link nahi banta —
baad mein Manage → book → 🔑 se retry. **Termux par bhi shortlink banegi** (destination
`t.me` public hai).

---

## 8. Render par deploy (24/7 — phone OFF bhi rahe)

### Step 1 — Firebase (Render par REQUIRED, 10 min, free, **simple email/password**)
Render ki disk **temporary** hai — deploy/restart par `data.json` toot jata
hai. Isliye books+stats Firebase RTDB mein save honge. (PDFs toh Telegram par
rehengi, unko koi risk nahi.) **Service account ki zaroorat NAHI** — sirf ek
normal Email/Password user banega.

1. <https://console.firebase.google.com> → **Add project** (e.g. `booklib`)
2. **Realtime Database** → Create → location `asia-south1` (Mumbai) → **locked mode**
3. RTDB → **Rules** tab (sirf logged-in user padh/likh sake):
   ```json
   { "rules": { ".read": "auth != null", ".write": "auth != null" } }
   ```
4. **Authentication → Sign-in method → Email/Password → Enable**
   → phir **Users → Add user** → apna koi bhi email + **ek password jo aap yaad
   rakh sako** banao (e.g. `server@booklib.app` / `BookLib-2026-Xyz`)
5. Kya copy karna hai (sab Project se):
   | Value | Kahan milegi |
   |---|---|
   | `FIREBASE_EMAIL` | Jo user aapne step 4 mein banaya |
   | `FIREBASE_PASSWORD` | Uska password |
   | `FIREBASE_DB_URL` | RTDB tab ka URL (`https://xxxx-default-rtdb.firebaseio.com`) |
   | `FIREBASE_API_KEY` | Project settings → General → **Web API key** |

> - Yeh email/password sirf **server ko database ke saath login** karwata hai —
>   site ke users ke liye NAHI — isliye yeh Render ke env var mein chhupa hai,
>   code/website mein kahin nahi dikhata.
> - Password yaad nahi raha toh users list se **delete + naya user bana do**
>   (password reset ka koi raasta nahi hota, isliye ek strong password likh kar
>   rakh lo).
> - Pehli baar chalne par local books auto-upload ho jayengi Firebase par.

### Step 2 — GitHub repo
1. Naya **private** repo banao (token safe rahe) — e.g. `study-helper-server`
2. Is folder ke **5 files** push karo (section 1 ki list)
3. Termux mein `data.json` ho toh woh bhi push kar do — Render pehli baar
   chalte hi usse Firebase par upload kar dega

### Step 3 — Render service
1. <https://render.com> → sign up (free plan ke liye bhi card maangta hai — charge nahi)
2. **New → Web Service** → repo select
3. Settings: Runtime **Python** · Build `pip install -r requirements.txt` ·
   Start `python bot_server.py` · Plan **Free**
   (`render.yaml` inhe auto-fill bhi karta hai)
4. **Environment** variables:

   | Key | Value |
   |---|---|
   | `BOT_TOKEN` | @BotFather wala token |
   | `ADMIN_IDS` | apna ID (pehle Termux se le chuke ho toh wahi) |
   | `FIREBASE_DB_URL`, `FIREBASE_API_KEY`, `FIREBASE_EMAIL`, `FIREBASE_PASSWORD` | Step 1 wale (email/password wala user) |
   | `API_ID`, `API_HASH` | (optional) my.telegram.org wale — bade PDF (2GB) ke liye; requirements.txt mein telethon already hai |
   | `VPLINK_API_TOKEN` | (optional) aapka vplink.in API token — code mein aapka token already pre-filled hai; nayi account/plan use karna ho toh yahan set karo |
   | `CACHE_LIMIT_MB` | (optional) default 150 theek hai (Render free disk 512MB) |
   | `STORAGE_CHAT_ID` | (optional) merged PDFs kaap channel, warna khali |

5. **Deploy** → ~1 min mein `https://<name>.onrender.com` live

### Step 4 — Ping (free instance ko jaagane ke liye)
Render Free **60 second bina traffic so jaata hai** (bot bhi). Pinger lagao:
1. <https://uptimerobot.com> → free → **Add New Monitor → HTTP(S)**
2. URL: `https://<name>.onrender.com/ping` · Interval: **1 minute**
3. Bas — site 24/7 jaagti rahegi. Occasional cold-start (30–60s) ho sakta
   hai agar ping miss ho — normal hai. Zero cold-start chahiye → **$7/mo**
   plan, pinger hata do.

---

## 9. Limits & cost

| Cheez | Limit | Cost |
|---|---|---|
| Render Free | 750 hr/mo uptime, **100 GB/mo bandwidth**, 512 MB disk (temp), 512 MB RAM | ₹0 |
| Firebase RTDB | 5 GB storage, ~1 GB/mo download (humara data chhota hai) | ₹0 |
| UptimeRobot | 50 monitors, 1-min interval | ₹0 |
| GitHub (tests data) | raw files unlimited; API 60/hr/IP (structure files isse bachati hain) | ₹0 |
| Telegram | PDFs 20 MB tak per file | ₹0 |

100 GB bandwidth ≈ ~12,000 baar 20MB book open karna — chhoti library ke liye
bahut kaafi.

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| Render deploy fail | Logs dekho; build ~2 min leta hai; dobara deploy |
| "Could not connect to Telegram" | `BOT_TOKEN` galat/typo |
| "Firebase problem, using local data only" | `FIREBASE_EMAIL`/`FIREBASE_PASSWORD`/`FIREBASE_API_KEY`/`FIREBASE_DB_URL` mein se koi galat hai (email = jo user banaya, password = uska) |
| Firebase login `INVALID_LOGIN_CREDENTIALS` | Email ya password galat — user delete karke naya banao (step 1) aur env update karke redeploy |
| Books empty | (a) bot se book add hui? (b) book hidden hai? (c) Render par Firebase ON hai? (d) browser refresh (Ctrl+Shift+R) |
| Tests empty / "Could not load tests" | GitHub repo **public** hai? `index.json` root par hai? branch `main`? network? |
| Chapters "Book folder not found" | `index.json` ka `folder_name` repo ke folder se exactly match karo (ya `structure/<book_id>.json` daalo) |
| Site slow (pehla tap) | Cold start (60s) — pinger chal raha hai? Dobara try karo |
| Bot se PDF nahi aaya | Render se Telegram download fail ho sakta hai (network) — 1 min baad retry |
| "MTProto connect failed" | `API_ID`/`API_HASH` mein typo hai, ya internet blocked |
| 20MB+ PDF fail / "file is too big" | `API_ID` + `API_HASH` set ho (dono) aur telethon installed ho — phir restart. Terminal mein `MTProto connected` aana chahiye |
| `big_file` / `DownloadMethods.download_media` error | Telethon bahut purana hai → `pip install -U telethon` phir restart (is ZIP ke code mein naya telethon supported hai) |
| Bade merge slow | Normal hai (download+merge+upload sab aapke net pe) — chhote merge bhejo |
| Popup nahi dikhta | `CONFIG.POPUP_SECONDS` 0 se zyada hai? browser console check karo |
| Logo nahi dikh raha | `LOGO_URL` valid public image link hai? (direct .png/.jpg URL) |
| Book add hui par shortlink nahi bani ("VPLINK key creation failed") | vplink balance/token check karo (`VPLINK_API_TOKEN`) → baad mein /manage → book → 🔑 se retry. Download seedha bot link se bhi chalta hai (direct) |
| Bot par /add /manage nahi chal raha | Message bhejne wala ID `ADMIN_IDS` mein hai? Pehle admin check hota hai — normal user ko kuch nahi milta |
| Shortlink complete par bot nahi khula | Shortlink galat hui ho sakti hai — /manage → book → 🔑 se naya key banao |

---

## 11. Is version mein kya-kya badla (changelog)

**🔑 Key system (SIMPLE kar diya — download-only):**
- Har book tile par sirf **ek button: ⬇ Download** — cover + naam ke saath
- View button, 36-hour unlock, green timer, verify page — **sab hata diya**
- Har book = **1 VPLINK download shortlink** (destination: bot ka `dl_<id>` deeplink)
- Shortlink complete → user bot par → **PDF seedha milega**
- Keygen ON/OFF — `/key` command + Manage mein tap-row; ON par purani books ke links **auto-backfill**
- `SITE_URL` ab zaroori **NAHI** (shortlink ka destination `t.me` hai — Termux par bhi banegi)

**UI (aapki feedback par):**
- **Explore button dono home tiles par** (Books + Tests) — niche wala bada pill hata diya
- Book tiles **choure + chhote** (cover 4:3, naam 1 line mein short) — saare tiles **same size**, ek screen mein acche aate hain
- Pura app-jaisa look, bina side-scroll ke

**Bot (admin safety):**
- **Reply keyboard hata di** — ab sirf **/add /manage /stats /key /backup /cancel** commands
- Pehle **admin ID check** hota hai — normal user ko kuch admin ka nahi dikhta
- Add flow text-based: naam → cover (Skip) → PDFs → **Done** (ya /done)

**Bug fix:**
- **116MB+ PDF "file is too big"** — naye Telethon ka `big_file` argument hata diya;
  ab MTProto bade files theek se download karta hai (2GB tak)

**Purani versions se jo aage bhi hai:**
- Bade PDFs **20MB → 2GB** (MTProto/Telethon) — `API_ID` + `API_HASH` (free, my.telegram.org)
- **Firebase simple** — service account hata; sirf ek **Email/Password user** (4 env vars)
- **Private data**: PDF ka file_id **encrypted** (`enc1:…`) — database read karke direct link nahi nikalta
- Ek hi app: **Home / Books / Tests** + fixed bottom nav, Telegram popup, loader, spinners
- Saari settings **env vars**; `/ping` endpoint; Firebase OFF par loud warning

**Remove hua (aapki request par):** site-par-PDF-reader (view), unlock/timer/verify
system, bot keyboard, request rate-limits (pehle se nahi thi). Search, categories,
Load More, quiz (+4/-1, solutions, tray, results), backup, stats — sab wahi hai.

---

## 12. Aage ke options (jab man kare)

1. ~~Bade PDF (2GB)~~ — **ho chuka hai** (section 4). Aapke API ID/hash lagao.
2. **Books ke liye categories** — abhi tests mein categories hai; books mein
   bhi jod sakte ho.
3. **Dark mode** toggle.
4. **Book detail** (author, description, pages) — bot ke Add flow mein 1 step aur.
