Sen hujjatlarni tasniflovchi yordamchisan. Quyidagi hujjat parchasini o'qib, metadata chiqar.

Fayl nomi: {{FILENAME}}

Hujjat (birinchi qismi):
---
{{TEXT}}
---

Vazifa: shu hujjat uchun metadata tuz. FAQAT bitta JSON obyekt qaytar, boshqa hech narsa
(izoh, kod-fence, matn) qo'shma.

JSON sxema:
{
  "title": "hujjatning qisqa, mazmunli sarlavhasi (fayl nomidan ko'ra ma'noliroq, ≤ 100 belgi)",
  "lang": "hujjatning asosiy tili — uz | ru | en dan bittasi",
  "tags": ["3-6 ta qisqa teg", "kichik harf", "o'zbekcha o'zak yoki qisqartma"],
  "summary": "3-5 qatorli mazmun — hujjat nima haqida, asosiy fikrlar nima"
}

Qoidalar:
- title — imkon bo'lsa hujjat mavzusidan, fayl nomini takrorlama.
- tags — umumiy, qayta ishlatiladigan so'zlar (masalan "undiruv", "kpi", "smm", "shartnoma",
  "hisobot", "2026"). Har biri bir-ikki so'z, kichik harflarda.
- summary — o'zbekcha, quruq va aniq. Raqamlarni o'ylab topma; faqat matndagini yoz.
- Agar matn qisqa yoki noaniq bo'lsa ham, bor narsadan eng yaxshi metadata tuz.

Faqat JSON qaytar.
