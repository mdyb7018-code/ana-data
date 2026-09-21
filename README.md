# ANA DATA — Telegram Search

> أداة بحث متقدمة بتجيب أرقام تليجرام من اليوزر. مجاني للجميع.

## 🚀 نشر سريع (دقيقة واحدة)

### على Railway (مجاني):

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template)

**أو يدوي:**
1. ارفع المشروع على GitHub
2. ادخل https://railway.app/new
3. اختار "Deploy from GitHub repo"
4. حط الـ Environment Variables دي:

```
API_ID=36041141
API_HASH=192dd9c6f9a766c7880bc74a59d53d2d
ADMIN_PHONE=+201143645282
ADMIN_EMAIL=mdyb7018@gmail.com
ADMIN_PASSWORD=admin123456
JWT_SECRET=<أي-كلمة-سر-طويلة>
PORT=8000
```

5. مستني يخلص البناء
6. افتح: `https://<اسم-مشروعك>.up.railway.app/setup`
7. سجّل دخول تليجرام بالكود

### على Render (مجاني برضو):
- ادخل https://render.com
- New → Web Service → Connect GitHub
- Docker environment
- حط نفس الـ Variables فوق

---

## 🔧 تشغيل محلي على جهازك

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
python main.py
```

بعدها افتح http://localhost:8000/setup لإعداد تليجرام.

---

## 👤 الأدمن

- **الإيميل**: `mdyb7018@gmail.com`
- **كلمة المرور**: `admin123456`
- **رابط الأدمن**: `/admin.html`

---

## 📦 بنية المشروع

```
ana-data/
├── backend/                # سيرفر Python
│   ├── main.py             # FastAPI + Pyrogram
│   ├── setup_web.html      # صفحة إعداد تليجرام (ويب)
│   ├── requirements.txt
│   └── .env.example
├── frontend/               # الموقع
│   ├── index.html
│   ├── admin.html
│   ├── css/style.css
│   └── js/
├── Dockerfile              # للـ Docker
├── railway.json            # للـ Railway
├── render.yaml             # للـ Render
└── دليل_بسيط.md            # شرح بالعربي للمبتدئين
```

---

## ⚖️ ملاحظة قانونية

استخدم الخدمة بشكل مسؤول وبما يتوافق مع قوانين بلدك وسياسات تليجرام.
