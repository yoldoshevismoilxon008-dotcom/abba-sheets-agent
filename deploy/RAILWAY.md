# Railway'ga ko'chirish — reja, qadamlar, cutover, qabul testi

> Arxitektura: **bitta service** (Dockerfile) — `supervisor.py` ichida bot listener
> (asosiy thread) + APScheduler (09:00 Asia/Tashkent → `run.sh`). Barcha state
> `DATA_DIR=/data` (Railway volume). Kod: private GitHub repo, **push = deploy**.
> Hisobotlar: server har kunlik pipeline'dan keyin ikkinchi private repo'ga
> `hisobotlar/*.md` push qiladi; Mac'dagi soatlik launchd job uni vault'ga tortadi.
> Mac'da faqat yordamchi joblar qoladi — pastdagi «Joriy holat» jadvaliga qarang.
> Plist fayllari o'chirilmaydi, shuning uchun rollback bir buyruq.

## Joriy holat — 07.09.2026 (cutover BAJARILGAN)

Bot va 09:00 kunlik pipeline **Railway'da**; Mac'da faqat vault sinxronizatsiyasi qoldi.

| Job / bosqich | Qayerda | Jadval | Izoh |
|---|---|---|---|
| Kunlik pipeline (`run.sh`) | **Railway** | 09:00 (Asia/Tashkent) | supervisor APScheduler |
| Telegram bot (listener) | **Railway** | doimiy | supervisor asosiy thread |
| PM undiruv push (`pm_push`) | **Railway** | 09:30 | faqat supervisor'da — `run.sh` uni chaqirmaydi, Mac'da bu bosqich umuman mavjud emas |
| Hisobotlar repo'ga push | **Railway** | pipeline'dan keyin | `push_reports.py`; `run.sh` da chaqiruv yo'q, shuning uchun `abba-hisobotlar` dagi har commit — Railway tirikligining isboti |
| `com.abba.reports-pull` | Mac | har 10 daq | hisobotlar repo → vault rsync |
| `com.abba.brain-push` | Mac | har 10 daq | vault → GitHub (`claude-brain`) |
| `com.abba.tg-kunlik` | Mac | 08:30 | **boshqa loyiha** (`~/.abba-tg-audit`), bu repoga aloqasi yo'q |
| `com.abba.sheets-agent` | ❌ disabled | — | 07.09.2026 da o'chirildi |
| `com.abba.sheets-bot` | ❌ disabled | — | 07.09.2026 da o'chirildi |

### Nega o'chirildi (07.09.2026)

Cutover'dan keyin Mac joblari **yoqilgan qolib ketgan** edi — ikki nusxa parallel ishladi:

- **Bot:** bitta Telegram tokenida ikkita poller. `getUpdates` **409 conflict**
  bugungi logda **771 marta**, bot Mac'da shu holatda **7 kun 18 soat** ishlagan —
  buyruqlar ikki instansiya orasida tasodifiy taqsimlangan.
- **Pipeline:** ikkala tomon ham o'z `claude -p` analizini qilib, egaga **ikkita
  har xil hisobot** yuborgan. (07.09 da Mac nusxasi matn rejimida ketdi — o'sha
  kuni PDF render yiqilgan.)

### Tekshiruv — farq darhol ko'rinsin

```bash
launchctl list | grep abba
```
Kutilgan chiqish — aynan **uchta** qator:
```
-	0	com.abba.reports-pull
-	0	com.abba.tg-kunlik
-	0	com.abba.brain-push
```
Agar ro'yxatda `com.abba.sheets-agent` yoki `com.abba.sheets-bot` **paydo bo'lsa**,
ikki nusxa yana ishlayapti — pastdagi buyruq bilan o'chiring.
`disable` holatini alohida tekshirish: `launchctl print-disabled gui/$(id -u) | grep abba`

### O'chirish va rollback

```bash
# O'chirish (07.09.2026 da aynan shunday qilindi):
launchctl bootout gui/$(id -u)/com.abba.sheets-bot
launchctl disable gui/$(id -u)/com.abba.sheets-bot
launchctl bootout gui/$(id -u)/com.abba.sheets-agent
launchctl disable gui/$(id -u)/com.abba.sheets-agent

# Rollback (Railway to'xtasa) — `enable` MAJBURIY:
# disabled holatdagi jobni `bootstrap` yuklamaydi, jimgina e'tiborsiz qoldiradi.
launchctl enable    gui/$(id -u)/com.abba.sheets-bot
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-bot.plist
launchctl enable    gui/$(id -u)/com.abba.sheets-agent
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-agent.plist
```
Rollback'dan oldin Railway tomonni to'xtating (bot tokenini olib tashlab redeploy
yoki deploy'ni o'chirish) — aks holda yana 409 boshlanadi.

## Nima tayyor (kod tomonida)

- `Dockerfile` — python:3.12-slim + chromium (`--no-sandbox --disable-dev-shm-usage`
  konteyner uchun majburiy) + fontlar + node/npm + claude CLI; `.dockerignore`
  sirlar va lokal data'ni image'dan chetlatadi.
- `supervisor.py` — boot'da: `GOOGLE_SA_JSON` (base64) → `/data/credentials/…`,
  brand seed (image → volume, tasdiqlangan dizayn ustun), holat seed
  (`seed/`: ack ro'yxati + bot xotirasi — bir martalik), keyin scheduler + bot.
- `DATA_DIR` env barcha modullarda: snapshots, bot-memory, bot-state, ack,
  qa-pdf, logs, credentials, brand — hammasi volume'da.
- `push_reports.py` — hisobotlarni `REPORTS_REPO`ga push (idempotent).
- `deploy/railway/` — Mac tomoni: `install.sh <repo-url>` soatlik pull + vault INDEX.

## SIZ QILADIGAN QADAMLAR (tartib bilan)

### 1. claude token (Mac terminalda)
```bash
claude setup-token        # brauzer ochiladi → ruxsat → token chiqadi
```
Chiqqan `sk-ant-oat...` tokenni nusxalab oling — 5-qadamda Railway'ga qo'yiladi.
(1 yil yashaydi; hech qayerga fayl qilib saqlamang.)

### 2. GitHub — ikkita PRIVATE repo
[github.com/new](https://github.com/new) da:
- `abba-sheets-agent` — **Private**, bo'sh (README'siz).
- `abba-hisobotlar` — **Private**, bo'sh. (Repo'lar albatta private bo'lsin. Bot suhbat
  xotirasi, ega qarorlari va Sheet ID'lar endi git'da EMAS — Variables orqali beriladi.)

Keyin menga ayting — men push qilaman. (Yoki o'zingiz:
```bash
cd ~/abba-sheets-agent
git remote add origin git@github.com:SIZNING_USER/abba-sheets-agent.git
git push -u origin main
```
)

### 3. Hisobotlar uchun PAT (fine-grained token)
GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate:
- Repository access: **Only select** → `abba-hisobotlar`
- Permissions → Repository → **Contents: Read and write**
- Expiration: 1 yil. Tokenni nusxalang (5-qadamda `GH_TOKEN_REPORTS`).

### 4. Service account base64 (Mac terminalda)
```bash
base64 -i ~/abba-sheets-agent/credentials/service-account.json | pbcopy
```
Buferda — 5-qadamda `GOOGLE_SA_JSON` bo'ladi.

### 5. Railway project
[railway.app](https://railway.app) → **New Project → Deploy from GitHub repo** →
`abba-sheets-agent` ni ulang. Keyin service'da:
- **Volume**: Add Volume → mount path: `/data` (1 GB yetadi).
- **Settings → Restart policy: Always** (bot doim tiklansin). Serverless/App
  Sleep bo'lsa — O'CHIQ (bot uzluksiz polling qiladi).
- **Variables** (Raw editor'ga birdan qo'yish qulay):
  ```
  TELEGRAM_BOT_TOKEN=...       (Mac .env'dagi bilan bir xil)
  TELEGRAM_CHAT_ID=...
  TELEGRAM_OWNER_IDS=...       (faqat GURUH chat bo'lsa: buyruq beruvchilar user ID'lari, vergul bilan)
  CLAUDE_CODE_OAUTH_TOKEN=...  (1-qadamdan)
  GOOGLE_SA_JSON=...           (4-qadamdan, bitta uzun qator)
  REPORTS_REPO=SIZNING_USER/abba-hisobotlar
  GH_TOKEN_REPORTS=...         (3-qadamdan)
  CONFIG_LOCAL_B64=...         (Sheet ID'lar + dashboard_id — pastga qarang)
  UNDIRUV_QAROR_B64=...        (ega qarorlari — pastga qarang)
  ```
  `CONFIG_LOCAL_B64` va `UNDIRUV_QAROR_B64` — maxfiy biznes ma'lumoti (audit P0-2), public
  repo'da emas. Mac'da bir marta: `python3 scripts/maxfiy_migratsiya.py` — `config.local.yaml`,
  `undiruv_qaror.json` yasaydi va ikkala qatorni chiqaradi. Qaror o'zgarsa: `undiruv_qaror.json`
  ni tahrirlang → `base64 -i undiruv_qaror.json | tr -d '\n'` → Variables'da yangilang
  (Railway redeploy qiladi). `CONFIG_LOCAL_B64` bo'lmasa bot boot'da egaga ⚠️ yuboradi.
  (`DATA_DIR=/data`, `CHROME_*`, `TZ` — Dockerfile'da, qo'yish shart emas.)

**Hali deploy tugashini kutmang / bot ishga tushsa ham xavotir yo'q** — pastdagi
cutover'gacha Mac listener ishlab turgani uchun Telegram'da 409-raqobat bo'lishi
mumkin, bu qisqa va zararsiz, lekin to'g'ri tartib — avval Mac'ni o'chirish:

## CUTOVER (409 conflict'siz almashtirish tartibi)

Ikkita listener bitta botda ishlay olmaydi (getUpdates 409). Tartib:

```bash
# 1. Mac listener + kunlik jobni o'chirish (plist fayllar joyida qoladi):
launchctl bootout gui/$(id -u)/com.abba.sheets-bot
launchctl disable gui/$(id -u)/com.abba.sheets-bot
launchctl bootout gui/$(id -u)/com.abba.sheets-agent
launchctl disable gui/$(id -u)/com.abba.sheets-agent

# 2. Railway'da deploy yashil bo'lishini kutish (Deployments → Active).
#    Log'da ko'rinishi kerak: "[supervisor] scheduler tayyor" va "listener boshlandi".

# 3. Telefondan test (pastdagi QABUL TESTI).

# 4. Hisobot-pull o'rnatish (vault to'ldirilishi uchun):
cd ~/abba-sheets-agent && ./deploy/railway/install.sh git@github.com:SIZNING_USER/abba-hisobotlar.git
```

### ROLLBACK (5 daqiqa)
```bash
# Railway'da: service → Settings → Remove deploy (yoki Variables'da bot tokenni
# vaqtincha o'chirib redeploy — listener to'xtaydi). Keyin Mac'da:
launchctl enable    gui/$(id -u)/com.abba.sheets-bot
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-bot.plist
launchctl enable    gui/$(id -u)/com.abba.sheets-agent
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-agent.plist
```
> `enable` siz `bootstrap` disabled job'ni yuklamaydi (07.09.2026 dan beri
> ikkalasi ham `disable` holatida) — shuning uchun ikkala qator ham kerak.
Server volume'dagi yangi snapshotlar Mac'da bo'lmaydi (hisobotlar repo orqali
matni bor) — qaytgach birinchi kun diff bo'sh tarixdan boshlanishi mumkin, kritik emas.

## QABUL TESTI (Mac YOPIQ holda, telefondan)

| # | Amal | Kutilgan natija |
|---|---|---|
| 1 | `Zubairda Livardi loyihasi bormi?` | Tez matnli javob (fast rejim) |
| 2 | `bu yildagi har bir oylarning natijalarini taqdim et` | Infografik PDF (2-3 daqiqa, deep) |
| 3 | `/hisobot` | Oraliq hisobot (PDF yoki "o'zgarish yo'q") |
| 4 | `/audit` | Strukturali audit PDF |
| 5 | Ertasi 09:00 | Kunlik PDF hisobot avtomatik keladi |
| 6 | 09:00 dan keyin ~1 soat ichida | Vault `hisobotlar/` da yangi kun fayli (Mac yoqilganda) |

1-4 o'tsa — ko'chirish muvaffaqiyatli. 5-6 — ertasi kuni tasdiqlanadi.

## Kundalik ishlatish (ko'chirilgandan keyin)

- **Kod o'zgarishi**: men Mac'da commit qilaman → `git push` → Railway avto-deploy
  (~3-5 daqiqa). Data/volume'ga tegilmaydi.
- **Log ko'rish**: Railway → service → Logs (run.sh chiqishi ham shu yerda, LOG_TEE).
- **Dizayn (/dizayn, logo)**: avvalgidek bot orqali — natija volume'da saqlanadi,
  redeploy'da yo'qolmaydi (brand seed faqat yo'q fayllarni to'ldiradi).
- **claude limitlari**: Max akkaunt limiti Mac + Railway umumiy (MIGRATION.md
  2-bo'limga qarang); token 1 yildan keyin yangilanadi (setup-token → Railway var).
- **Xarajat**: hobby plan ~$5/oy atrofida (bitta doimiy service + 1GB volume;
  claude API xarajati yo'q — Max plan token).

## Undiruv: oy oxiri ko'chirish ro'yxati (AUDIT P0-3)

Oy oxirida (oxirgi 6 kun) 💰 blok «🔁 <oy> tabiga ko'chirilgan» deb ko'rsatgan qarzlar
keyingi oyda ham eslab qolinadi (`undiruv_carry.py`): o'tgan oy qatori ochiq qolsa, PM'dan
IKKINCHI marta so'ralmaydi, egaga har kuni «⚠️ Ikki tabda dublikat» chiqadi; ko'chirilgan
qatordan pul izsiz yo'qolsa — «$N izohsiz».

- **Holat fayli:** `/data/undiruv_carry/<YYYY-MM>.json` (YYYY-MM — ro'yxat tuzilgan oy, masalan
  `2026-09.json` oktabr uchun). Bu **volume holati — git'ga HECH QACHON qo'shilmaydi**: repo
  public, faylda mijoz nomlari va summalar bor (`data/*` .gitignore'da).
- **Qachon yoziladi:** keyingi oyning birinchi undiruv o'qishida (09:00 run, 09:30 push,
  /hisobot yoki dashboard — qaysi biri birinchi bo'lsa) **bir marta** muzlatiladi, manbasi —
  o'tgan oy oxirgi faol kunining `snapshots/<kun>/report.json`i. Keyin o'zgarmaydi.
  Kelajak sanali simulyatsiya (`pm_push.py --dry-run --date 2026-11-01` 28.10 da) faylni
  **muzlatmaydi** — real sana oy oxiridan o'tmaguncha ro'yxat faqat xotirada quriladi.
- **Qayta qurish:** faylni o'chiring — keyingi o'qishda `snapshots/<oy oxiri>/report.json`dan
  qayta tuziladi. Bu faqat o'sha papka turgan paytda ishlaydi: retention 30 kun (30.09 papkasi
  **31.10 09:00 run oxirida** o'chadi).
- **Buzilgan fayl:** bot o'zi tuzatmaydi — 💰 blokda «⚠️ undiruv_carry/… buzilgan» chiqadi va
  qarzlar odatdagidek so'raladi. Faylni o'chiring (yuqoridagi qayta qurish).
- **Kill switch:** Railway Variables'da `UNDIRUV_CARRY_OFF=1` → redeploy. P0-3 qo'shimchalarining
  hammasi o'chadi (dublikat/izohsiz, 1–10 kunlik o'tgan tab kuzatuvi, 💰dagi «⚖️ Summa farqli»),
  xulq 69a8de7 bilan bir xil. Fayl o'chirilmaydi — kalit olinsa yana ishlatiladi.
- **Muzlatishdan oldin `analyze.py --date <oy oxiri>` ni ishga tushirmang:** `summary` jonli
  ma'lumotdan o'qiydi va o'sha kunning report.json ro'yxatini BUGUNGI holat bilan qayta yozadi.

**Birinchi deploy (sentabr → oktabr):** 31.10 09:00 dan OLDIN (aks holda 30.09 snapshot'i
o'chib, oktabr eski xulqda qoladi). Avval zaxira:
```bash
mkdir -p /data/keep && cp -r /data/snapshots/2026-09-30 /data/snapshots/2026-10-01 /data/snapshots/2026-10-02 /data/keep/
python3 -c "import json;d=json.load(open('/data/snapshots/2026-09-30/report.json'));print([(i['loyiha'],i['summa'],i['yangi_muddat']) for i in d['undiruv']['keyingi']['kochgan']])"
```
Ro'yxatda `('Bosimov shcool', 2500, '18.10')` bo'lishi kerak. Deploy'dan keyin (bu buyruq faylni
o'zi muzlatadi ham):
```bash
cd /app && venv/bin/python -c "import undiruv_carry as c; from datetime import date; print(c.royxat(date(2026,10,13)))"
ls -l /data/undiruv_carry/2026-09.json
```
Chiqishda `Bosimov shcool` 2500 → `Bosimov School` 18.10 bo'lishi, `baza` — `snapshot:2026-09-30`.

## Eslatmalar / ma'lum cheklovlar

- Konteynerda `/dizayn` git-commit qilmaydi (theme'lar volume'da, git yo'q) —
  dizayn tarixи kerak bo'lsa Mac'dan `--code` bilan tortib olinadi (keyin hal qilamiz).
- Snapshot json tarixi (30 kun) Railway'da noldan yig'iladi — birinchi kun baseline,
  trend grafigi 7 kunda to'ladi. Dashboard'dagi Trend tabi (Google Sheets) to'liq qoladi.
- VPS varianti (deploy/deploy.sh, systemd) muqobil sifatida repo'da qoladi.
