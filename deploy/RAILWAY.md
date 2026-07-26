# Railway'ga ko'chirish — reja, qadamlar, cutover, qabul testi

> Arxitektura: **bitta service** (Dockerfile) — `supervisor.py` ichida bot listener
> (asosiy thread) + APScheduler (09:00 Asia/Tashkent → `run.sh`). Barcha state
> `DATA_DIR=/data` (Railway volume). Kod: private GitHub repo, **push = deploy**.
> Hisobotlar: server har kunlik pipeline'dan keyin ikkinchi private repo'ga
> `hisobotlar/*.md` push qiladi; Mac'dagi soatlik launchd job uni vault'ga tortadi.
> Mac launchd plist'lar joyida qoladi (o'chirilgan holda) — 5 daqiqalik rollback.

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
- `abba-hisobotlar` — **Private**, bo'sh. (Diqqat: kod repo'sida `seed/` ichida
  bot suhbat xotirasi bor — repo'lar albatta private bo'lsin.)

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
  CLAUDE_CODE_OAUTH_TOKEN=...  (1-qadamdan)
  GOOGLE_SA_JSON=...           (4-qadamdan, bitta uzun qator)
  REPORTS_REPO=SIZNING_USER/abba-hisobotlar
  GH_TOKEN_REPORTS=...         (3-qadamdan)
  ```
  (`DATA_DIR=/data`, `CHROME_*`, `TZ` — Dockerfile'da, qo'yish shart emas.)

**Hali deploy tugashini kutmang / bot ishga tushsa ham xavotir yo'q** — pastdagi
cutover'gacha Mac listener ishlab turgani uchun Telegram'da 409-raqobat bo'lishi
mumkin, bu qisqa va zararsiz, lekin to'g'ri tartib — avval Mac'ni o'chirish:

## CUTOVER (409 conflict'siz almashtirish tartibi)

Ikkita listener bitta botda ishlay olmaydi (getUpdates 409). Tartib:

```bash
# 1. Mac listener + kunlik jobni o'chirish (plist fayllar joyida qoladi):
launchctl bootout gui/$(id -u)/com.abba.sheets-bot
launchctl bootout gui/$(id -u)/com.abba.sheets-agent

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
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-bot.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.abba.sheets-agent.plist
```
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

## Eslatmalar / ma'lum cheklovlar

- Konteynerda `/dizayn` git-commit qilmaydi (theme'lar volume'da, git yo'q) —
  dizayn tarixи kerak bo'lsa Mac'dan `--code` bilan tortib olinadi (keyin hal qilamiz).
- Snapshot json tarixi (30 kun) Railway'da noldan yig'iladi — birinchi kun baseline,
  trend grafigi 7 kunda to'ladi. Dashboard'dagi Trend tabi (Google Sheets) to'liq qoladi.
- VPS varianti (deploy/deploy.sh, systemd) muqobil sifatida repo'da qoladi.
