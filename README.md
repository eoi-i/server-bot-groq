# GLOBALHOLMES AI — Advanced Telegram Bot

## الميزات
- محادثة Groq عبر `openai/gpt-oss-120b` دون مقدمة تعريفية متكررة.
- ترحيب مولّد بالذكاء الاصطناعي عند `/start`.
- تحليل الصور عبر `qwen/qwen3.8-27b` على Groq.
- قراءة PDF وTXT وMD وCSV وDOCX وتحليلها.
- توليد الصور اختيارياً عبر OpenAI Images API.
- تصدير آخر إجابة إلى TXT وDOCX عبر `/export`.
- PostgreSQL لحفظ المستخدمين وسجل المحادثات.
- Fly.io + Docker + health endpoint.

## المتغيرات
مطلوب: `TELEGRAM_TOKEN`, `GROQ` (أو `GROQ_API_KEY`), `DATABASE_URL`.

اختياري لتوليد الصور: `OPENAI_API_KEY`, `OPENAI_IMAGE_MODEL` (افتراضياً `gpt-image-1`).
اختياري: `GROQ_VISION_MODEL` (افتراضياً `qwen/qwen3.8-27b`), `DATABASE_SSL=require` عند الحاجة.

## النشر
1. فك الضغط وافتح الطرفية داخل المجلد.
2. `fly auth login`
3. `fly launch --no-deploy` ثم تأكد أن اسم `app` في `fly.toml` مطابق لتطبيقك.
4. `fly secrets set TELEGRAM_TOKEN="..." GROQ="..." DATABASE_URL="..."`
5. لتفعيل إنشاء الصور: `fly secrets set OPENAI_API_KEY="..."`
6. `fly deploy` ثم `fly logs`.

## الأوامر
`/start`, `/help`, `/about`, `/new`, `/clear`, `/image وصف الصورة`, `/export`.
أرسل صورة مباشرة للتحليل أو ملف PDF/TXT/MD/CSV/DOCX.

## ملاحظات تقنية
- GPT-OSS 120B نصي ولا يحلل الصور بنفسه؛ لذلك استُخدم نموذج Groq بصري منفصل.
- Groq لا يولّد الصور؛ توليدها هنا عبر OpenAI Images API ويتطلب مفتاحاً منفصلاً وقد تكون له تكلفة.
- PDF الممسوح ضوئياً كصورة يحتاج OCR، وغير مضاف في هذه النسخة.
- Telegram لا يتيح تخصيص شفافية أو ألوان أزرار Inline Keyboard من خلال Bot API.
- لا تضع المفاتيح داخل الكود أو GitHub؛ استخدم Fly secrets.
