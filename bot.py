import asyncio, base64, io, logging, os
import asyncpg
from aiohttp import web
from groq import AsyncGroq
from openai import AsyncOpenAI
from docx import Document
from pypdf import PdfReader
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(format='%(asctime)s | %(levelname)s | %(name)s | %(message)s', level=os.getenv('LOG_LEVEL','INFO'))
log=logging.getLogger('globalholmes')
BOT_TOKEN=os.environ['TELEGRAM_TOKEN']; GROQ_KEY=os.getenv('GROQ') or os.getenv('GROQ_API_KEY'); DATABASE_URL=os.environ['DATABASE_URL']
TEXT_MODEL='openai/gpt-oss-120b'; VISION_MODEL=os.getenv('GROQ_VISION_MODEL','qwen/qwen3.8-27b')
OPENAI_KEY=os.getenv('OPENAI_API_KEY'); IMAGE_MODEL=os.getenv('OPENAI_IMAGE_MODEL','gpt-image-1')
if not GROQ_KEY: raise RuntimeError('Missing GROQ secret')
groq=AsyncGroq(api_key=GROQ_KEY); openai=AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None
db=None; locks={}
SYSTEM='''أنت مساعد ذكي عام واحترافي. أجب مباشرة دون مقدمة تعريفية متكررة أو تحية آلية أو تكرار اسم الشركة. استخدم لغة المستخدم، وقدّم إجابات واضحة وعملية ومنظمة. ساعد في البرمجة والتقنية وتطوير التطبيقات والمواقع وتحليل المستندات والصور وصناعة المحتوى. لا تدّع تنفيذ إجراءات لم تنفذها ولا تخترع معلومات. اسم الجهة المالكة عند السؤال عن هويتك هو GLOBALHOLMES LTD، وهي شركة تقنية وبرمجية وإعلامية.'''
WELCOME='اكتب رسالة ترحيب عربية قصيرة وطبيعية لمستخدم بدأ محادثة مع مساعد ذكاء اصطناعي تابع لـ GLOBALHOLMES LTD. اذكر بإيجاز إمكانية المساعدة في الأسئلة والبرمجة وتحليل الصور والملفات، وادعُ المستخدم لإرسال طلبه. لا تتجاوز 3 أسطر.'

def keyboard():
 return InlineKeyboardMarkup([[InlineKeyboardButton('✨ محادثة جديدة',callback_data='new'),InlineKeyboardButton('🧠 حول المساعد',callback_data='about')],[InlineKeyboardButton('🖼 إنشاء صورة',callback_data='image_help'),InlineKeyboardButton('📄 تصدير آخر رد',callback_data='export')],[InlineKeyboardButton('📚 المساعدة',callback_data='help'),InlineKeyboardButton('🗑 مسح المحادثة',callback_data='clear')],[InlineKeyboardButton('🌐 GLOBALHOLMES LTD',url='https://krar.top/')]])
def mini(): return InlineKeyboardMarkup([[InlineKeyboardButton('✨ محادثة جديدة',callback_data='new'),InlineKeyboardButton('🖼 إنشاء صورة',callback_data='image_help')]])

async def init_db():
 global db
 db=await asyncpg.create_pool(DATABASE_URL,min_size=1,max_size=8,command_timeout=45,ssl='require' if os.getenv('DATABASE_SSL','auto').lower()=='require' else None)
 async with db.acquire() as c:
  await c.execute('''CREATE TABLE IF NOT EXISTS chat_messages(id BIGSERIAL PRIMARY KEY,telegram_user_id BIGINT NOT NULL,chat_id BIGINT NOT NULL,role TEXT NOT NULL CHECK(role IN ('user','assistant')),content TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')
  await c.execute('CREATE INDEX IF NOT EXISTS idx_chat_messages_user_chat_id ON chat_messages(telegram_user_id,chat_id,id DESC)')
  await c.execute('''CREATE TABLE IF NOT EXISTS bot_users(telegram_user_id BIGINT PRIMARY KEY,username TEXT,first_name TEXT,last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW())''')
async def save_user(u):
 x=u.effective_user
 if x:
  async with db.acquire() as c: await c.execute('''INSERT INTO bot_users VALUES($1,$2,$3,NOW()) ON CONFLICT(telegram_user_id) DO UPDATE SET username=EXCLUDED.username,first_name=EXCLUDED.first_name,last_seen=NOW()''',x.id,x.username,x.first_name)
async def history(uid,cid):
 async with db.acquire() as c: rows=await c.fetch('''SELECT role,content FROM (SELECT id,role,content FROM chat_messages WHERE telegram_user_id=$1 AND chat_id=$2 ORDER BY id DESC LIMIT 16) q ORDER BY id''',uid,cid)
 return [{'role':r['role'],'content':r['content']} for r in rows]
async def save(uid,cid,role,content):
 async with db.acquire() as c: await c.execute('INSERT INTO chat_messages(telegram_user_id,chat_id,role,content) VALUES($1,$2,$3,$4)',uid,cid,role,content)
async def clear(uid,cid):
 async with db.acquire() as c: await c.execute('DELETE FROM chat_messages WHERE telegram_user_id=$1 AND chat_id=$2',uid,cid)
async def ask(uid,cid,prompt):
 msgs=[{'role':'system','content':SYSTEM}]+await history(uid,cid)+[{'role':'user','content':prompt}]
 r=await groq.chat.completions.create(model=TEXT_MODEL,messages=msgs,temperature=.7,max_completion_tokens=3000)
 answer=r.choices[0].message.content or 'لم أتمكن من إنشاء إجابة.'
 await save(uid,cid,'user',prompt); await save(uid,cid,'assistant',answer); return answer
async def send_long(m,s,markup=None):
 parts=[s[i:i+3900] for i in range(0,len(s),3900)] or ['…']
 for i,p in enumerate(parts): await m.reply_text(p,reply_markup=markup if i==len(parts)-1 else None,disable_web_page_preview=True)
async def start(u,c):
 await save_user(u)
 try:
  r=await groq.chat.completions.create(model=TEXT_MODEL,messages=[{'role':'user','content':WELCOME}],temperature=.8,max_completion_tokens=180); welcome=r.choices[0].message.content or 'مرحباً بك! أرسل طلبك لنبدأ.'
 except Exception: log.exception('welcome failed'); welcome='مرحباً بك! أرسل سؤالك أو صورتك أو ملفك وسأساعدك.'
 await u.effective_message.reply_text(welcome,reply_markup=keyboard())
async def help_cmd(u,c): await u.effective_message.reply_text('أرسل رسالة نصية للسؤال، أو صورة لتحليلها، أو ملف PDF/TXT/MD/CSV/DOCX لقراءته.\n/image وصف الصورة — إنشاء صورة (يتطلب OPENAI_API_KEY)\n/export — تصدير آخر إجابة إلى TXT وDOCX\n/new — محادثة جديدة\n/clear — مسح السجل\n/about — معلومات المساعد',reply_markup=keyboard())
async def about(u,c): await u.effective_message.reply_text(f'GLOBALHOLMES LTD\nمساعد تقني وبرمجي وإعلامي.\nالنموذج النصي: {TEXT_MODEL}\nنموذج تحليل الصور: {VISION_MODEL}',reply_markup=keyboard())
async def new(u,c): await clear(u.effective_user.id,u.effective_chat.id); await u.effective_message.reply_text('بدأنا محادثة جديدة. أرسل طلبك.',reply_markup=keyboard())
async def clear_cmd(u,c): await clear(u.effective_user.id,u.effective_chat.id); await u.effective_message.reply_text('تم مسح سجل محادثتك من قاعدة البيانات.',reply_markup=keyboard())
async def export(u,c):
 async with db.acquire() as x: row=await x.fetchrow("SELECT content FROM chat_messages WHERE telegram_user_id=$1 AND chat_id=$2 AND role='assistant' ORDER BY id DESC LIMIT 1",u.effective_user.id,u.effective_chat.id)
 if not row: return await u.effective_message.reply_text('لا توجد إجابة سابقة لتصديرها.')
 content=row['content']; txt=io.BytesIO(content.encode()); txt.name='GLOBALHOLMES_answer.txt'
 doc=Document(); doc.add_heading('GLOBALHOLMES LTD',0)
 for line in content.splitlines(): doc.add_paragraph(line)
 word=io.BytesIO(); doc.save(word); word.seek(0); word.name='GLOBALHOLMES_answer.docx'
 await u.effective_message.reply_document(txt,caption='نسخة TXT'); await u.effective_message.reply_document(word,caption='نسخة Word DOCX')
async def image_cmd(u,c):
 prompt=' '.join(c.args).strip()
 if not prompt: return await u.effective_message.reply_text('اكتب الوصف هكذا:\n/image شعار تقني حديث لشركة GLOBALHOLMES LTD')
 if not openai: return await u.effective_message.reply_text('إنشاء الصور غير مفعّل. أضف OPENAI_API_KEY إلى Fly.io secrets.')
 st=await u.effective_message.reply_text('🎨 جارٍ إنشاء الصورة...')
 try:
  result=await openai.images.generate(model=IMAGE_MODEL,prompt=prompt,size='1024x1024'); data=base64.b64decode(result.data[0].b64_json); await st.delete(); await u.effective_message.reply_photo(io.BytesIO(data),caption='تم إنشاء الصورة بواسطة GLOBALHOLMES AI ✨')
 except Exception: log.exception('image generation failed'); await st.edit_text('تعذر إنشاء الصورة. تحقق من مفتاح OpenAI وصلاحية نموذج الصور.')
async def analyze_image(u,c):
 m=u.effective_message; media=m.photo[-1] if m.photo else m.document; st=await m.reply_text('🔎 جارٍ تحليل الصورة...')
 try:
  f=await c.bot.get_file(media.file_id); raw=bytes(await f.download_as_bytearray())
  if len(raw)>18*1024*1024: return await st.edit_text('حجم الصورة أكبر من 18 ميغابايت.')
  mime=m.document.mime_type if m.document else 'image/jpeg'
  if mime not in ('image/jpeg','image/png','image/webp','image/gif'): mime='image/jpeg'
  url='data:'+mime+';base64,'+base64.b64encode(raw).decode()
  r=await groq.chat.completions.create(model=VISION_MODEL,messages=[{'role':'user','content':[{'type':'text','text':m.caption or 'حلّل هذه الصورة واشرح محتواها.'},{'type':'image_url','image_url':{'url':url}}]}],temperature=.4,max_completion_tokens=1800)
  answer=r.choices[0].message.content or 'لم أتمكن من تحليل الصورة.'; await st.delete(); await send_long(m,answer,mini()); await save(u.effective_user.id,u.effective_chat.id,'user','[صورة] '+(m.caption or 'حلل الصورة')); await save(u.effective_user.id,u.effective_chat.id,'assistant',answer)
 except Exception: log.exception('vision failed'); await st.edit_text('تعذر تحليل الصورة. تحقق من تفعيل نموذج الرؤية في حساب Groq.')
async def analyze_doc(u,c):
 m=u.effective_message; d=m.document; name=(d.file_name or '').lower()
 if d.file_size and d.file_size>15*1024*1024: return await m.reply_text('الحد الأقصى لحجم الملف 15 ميغابايت.')
 st=await m.reply_text('📄 جارٍ قراءة الملف...')
 try:
  f=await c.bot.get_file(d.file_id); raw=bytes(await f.download_as_bytearray())
  if name.endswith(('.txt','.md','.csv')): text=raw.decode('utf-8-sig',errors='replace')
  elif name.endswith('.pdf'): text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages)
  elif name.endswith('.docx'):
   doc=Document(io.BytesIO(raw)); text='\n'.join(p.text for p in doc.paragraphs)
   for table in doc.tables:
    for row in table.rows: text+='\n'+' | '.join(cell.text for cell in row.cells)
  else: return await st.edit_text('صيغة غير مدعومة. المدعوم: PDF وTXT وMD وCSV وDOCX.')
  if not text.strip(): return await st.edit_text('لم أستطع استخراج نص. ربما PDF ممسوح ضوئياً ويحتاج OCR.')
  prompt=f'اسم الملف: {d.file_name}\nطلب المستخدم: {m.caption or "لخّص الملف وحلّله واستخرج أهم النقاط."}\n\nمحتوى الملف:\n{text[:50000]}'
  answer=await ask(u.effective_user.id,u.effective_chat.id,prompt); await st.delete(); await send_long(m,answer,mini())
 except Exception: log.exception('document read failed'); await st.edit_text('حدث خطأ أثناء قراءة الملف أو تحليله.')
async def text_msg(u,c):
 if not u.message or not u.message.text: return
 await save_user(u); uid=u.effective_user.id; cid=u.effective_chat.id; lock=locks.setdefault(cid,asyncio.Lock())
 async with lock:
  st=await u.message.reply_text('⏳'); await c.bot.send_chat_action(chat_id=cid,action=ChatAction.TYPING)
  try: answer=await ask(uid,cid,u.message.text.strip()); await st.delete(); await send_long(u.message,answer,mini())
  except Exception: log.exception('text failed'); await st.edit_text('حدث خطأ مؤقت أثناء معالجة طلبك. حاول مرة أخرى.')
async def buttons(u,c):
 q=u.callback_query; await q.answer(); uid=q.from_user.id; cid=q.message.chat_id
 if q.data in ('new','clear'): await clear(uid,cid); await q.edit_message_text('تم بدء محادثة جديدة. أرسل رسالتك.')
 elif q.data=='about': await q.edit_message_text(f'GLOBALHOLMES LTD\n{TEXT_MODEL}\nتحليل الصور: {VISION_MODEL}',reply_markup=keyboard())
 elif q.data=='help': await q.edit_message_text('أرسل نصاً أو صورة أو ملف PDF/TXT/MD/CSV/DOCX. استخدم /image للوصف وتوليد صورة، و/export لتصدير آخر إجابة.',reply_markup=keyboard())
 elif q.data=='image_help': await q.edit_message_text('لإنشاء صورة أرسل:\n/image وصف الصورة المطلوبة',reply_markup=keyboard())
 elif q.data=='export': await q.message.reply_text('استخدم /export لتصدير آخر إجابة بصيغتي TXT وDOCX.')
async def health(r): return web.json_response({'status':'ok','service':'GLOBALHOLMES AI'})
async def health_server():
 a=web.Application(); a.router.add_get('/',health); a.router.add_get('/health',health); runner=web.AppRunner(a); await runner.setup(); await web.TCPSite(runner,'0.0.0.0',int(os.getenv('PORT','8080'))).start(); return runner
async def post_init(app): await init_db(); app.bot_data['health_runner']=await health_server()
async def post_shutdown(app):
 if app.bot_data.get('health_runner'): await app.bot_data['health_runner'].cleanup()
 if db: await db.close()
 await groq.close()
 if openai: await openai.close()
def main():
 app=Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
 for cmd,fn in [('start',start),('help',help_cmd),('about',about),('new',new),('clear',clear_cmd),('image',image_cmd),('export',export)]: app.add_handler(CommandHandler(cmd,fn))
 app.add_handler(CallbackQueryHandler(buttons)); app.add_handler(MessageHandler(filters.PHOTO,analyze_image)); app.add_handler(MessageHandler(filters.Document.IMAGE,analyze_image)); app.add_handler(MessageHandler(filters.Document.ALL,analyze_doc)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_msg))
 app.run_polling(drop_pending_updates=True)
if __name__=='__main__': main()
