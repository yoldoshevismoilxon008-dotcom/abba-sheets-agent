# KPI qoidalari — 2-qoralama (2026-07-24, Ismoilxon javoblari bilan)

> Holat: `kpi_enabled: false` — pul hisob-kitoblari O'CHIQ, Ismoilxon
> "KPI tasdiqlayman" deguncha. TASDIQLANGAN bo'limlar — Ismoilxon javoblari
> (2026-07-24); qolgan [TEKSHIRILSIN] belgilari ochiq.

## Atamalar (sheet ustunlari)
- **Kpi ideal bali** — loyiha rejadagi maksimal balli (standart 41,2)
- **Proekt bali** — amalda yig'ilgan; **Farq** = ideal − fakt
- **Kechga qolgan kunlar** — kechikish kunlari; **Zarar %** — pastda (tasdiqlangan)
- **Shartnoma muddati**: "Har oy", "Endi qilinadi", "1/2/3 oy", bo'sh

## ✅ TASDIQLANGAN qoidalar

**Ball formulasi** (ERP kodi bilan ham mos):
Loyiha balli = Grafik×1 + Motion×2 + Video×3 + (Hisobot? +5) + (Kontent-plan? +5) + Update-kunlar×0,2
(26 kun → 5,2; standart misol: 4+4+18+5+5+5,2 = 41,2)

**Kechikish / Zarar %:**
- Har kechikish kuni = 3,33% (oyning 1/30 qismi; sheet'dagi "Kun 30 / Foizda 3,33%" shundan)
- 30 kun ichida chiqmagan post = 2 kechikish kuni (6,66%)
- Loyiha kechikish % = (kechikish kunlari + 2 × chiqmagan postlar) × 3,33%
- [TEKSHIRILSIN: portfel (PM darajasidagi) ko'rsatkich loyihalar bo'yicha oddiy o'rtachami?]

**Kechikish jarima balli:** 0,5 ball/kun, chiziqli, LIMIT YO'Q.
Jarima faqat shu ballar orqali — alohida pul jarimasi yo'q.
[TEKSHIRILSIN: sheet'dagi Meeting jarima 200 000 va Yangi mijoz jarima 250 000
kataklari — ishlatiladimi? Qoida bilan ziddiyat.]

**Loyiha reytingi (1-10):** pulga TA'SIR QILMAYDI — informatsion.

**Bajarilgan % chegaralari** (≥90 normal · 80–90 muammoli · 70–80 yomon · <70 kritik):
[TEKSHIRILSIN: gradatsiya aynan shu ko'rinishdami]
MUHIM: rasmiy xulosa OY OXIRIDA (30/31) — oylik yakuniy hisobotda.
Kunlik hisobotdagi % — oraliq, informatsion.

**Fix:** BARCHA PM'larda 5 000 000 (4M varianti bekor).
Oy o'rtasida sheet'da proratsiya: formula =5000000/30*22 — kun soni (22)
QO'LDA yoziladi (avtomatik emas), [TEKSHIRILSIN: kim/qachon yangilaydi].

**1% qiymati** (loyihalar soniga bog'liq):
1% = 100 000 + (n − 6) × 25 000, n = aktiv loyihalar soni
(jadval: 6→100k · 8→150k · 10→200k · 12→250k · 14→300k · 16→350k; toq n — formuladan)
[TEKSHIRILSIN: n<6 va n>16 holatlari]
Jadvaldagi "Ball" ustuni = n × 39 (formula tasdiqlandi: =J31*N31, N31=39).
⚠️ MUHIM (formula tekshiruvi, 2026-07-24): sheet formulalari 1% ni dinamik
hisoblamaydi — to'g'ridan-to'g'ri L36 katagiga (=350 000, ya'ni 16-loyiha
pog'onasi) qotirilgan: =(D40-I40)*L36. [TEKSHIRILSIN: bu ataylabmi (stavka
muzlatilgan) yoki n o'zgarganda qo'lda almashtiriladimi?]
39-norma statistikada ham ishlatiladi (=E22/39 → 18,57).

**Oylik komponentlari** (4 ta) va summa:
1) Jamoaning o'rtacha bali (bajarilish %) — limit 70%: summa = (foiz − 70) × 1%-qiymati, manfiy bo'lsa 0
2) Kechikishni kamaytirish — limit 10%: summa = (10 − kechikish %) × 1%-qiymati, manfiy bo'lsa 0
3) Mijozlar bilan uchrashuv: soni × 100 000
4) Yangi proektlar boshlash: soni × 500 000
**Jami oylik = Σ komponentlar + Fix (5 000 000)**

**Narvon oralig'i:** PROPORTSIONAL (chiziqli) — narvon jadvallari yuqoridagi
formulaning nuqtalari xolos (75→1 750 000 = 5×350k; 0% kechikish→3 500 000 = 10×350k;
34 uchrashuv→3 400 000 = 34×100k — hammasi mos).

**Manager tier tizimi (A=6/B=5/C=4):** hozircha qoidaga KIRMAYDI —
manager sheet'lari qo'shilganda qaytamiz.

## Formula tekshiruvi natijalari (2026-07-24, Zubair Iyul tabi)
- **"Iyul oyligi→ 13 580 000" QO'LDA YOZILGAN SON** (katakda =13580000 — hech
  qanday havola/hisob yo'q). 177,13% esa =D50/G46 — ya'ni qo'lda yozilgan son
  bilan formula-jami (7 666 667) orasidagi NISBAT, ko'paytiruvchi EMAS.
  Bu katak sheet'ning o'z hisobiga zid. Undiruv/bonus ustuni blok atrofida YO'Q.
- Blokdagi "Joriy KPI" qiymatlari ham qo'lda kiritiladi: D40=70 (matn),
  jamoaning haqiqiy 40,31% (=F22/E22) ga BOG'LANMAGAN — ehtimol oy oxirida
  qo'lda to'ldiriladi ("rasmiy xulosa oy oxirida" qoidasiga mos).
- Tasdiqlangan formulalar: komponentlar =(D40-I40)*L36, =(L40-D41)*L36,
  =D42*E33, =D43*E34; Jami =SUM(E40:F45); narvonlar =ABS(...)×stavka —
  proportsionallik formulaning o'zida.

## Ochiq savollar
1. Qo'lda yozilgan 13 580 000 nimani anglatadi (kelishuv? maqsad? eski oy?) —
   sheet egasidan so'rash kerak. [TEKSHIRILSIN]
2. Portfel kechikish % ning aniq agregatsiyasi (1-band).
3. Meeting/Yangi mijoz jarimalari ziddiyati (yuqorida).
4. 1% stavkasi formulada L36 (350 000) ga qotirilgani — ataylabmi (yuqorida).
5. Sheet'lardagi o'ng tomondagi "May oyligi→ Abdullox" bloklari — shablon namunalar,
   hisobga olinmasin (tasdiqlangan kuzatuv).
