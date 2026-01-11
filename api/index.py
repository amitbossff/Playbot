import os
import json
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler

import requests
from google_play_scraper import reviews, Sort
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
SESSION = requests.Session()

CHAT_STATE = {}  # chat_id -> {"app_id": str}

def send_text(chat_id, text):
    SESSION.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=5
    )

def send_pdf(chat_id, path):
    with open(path, "rb") as f:
        SESSION.post(
            f"{API_URL}/sendDocument",
            data={"chat_id": chat_id},
            files={"document": f},
            timeout=30
        )

def extract_app_id(url):
    if "id=" not in url:
        return None
    return url.split("id=")[1].split("&")[0]

def validate_date(user_date_str):
    try:
        user_date = datetime.strptime(user_date_str, "%Y-%m-%d").date()
    except:
        return False, "❌ Date format galat hai (YYYY-MM-DD)"

    today = datetime.utcnow().date()
    min_date = today - timedelta(days=10)

    if user_date > today:
        return False, "❌ Future date allowed nahi hai"

    if user_date < min_date:
        return False, f"❌ Sirf last 8–10 din allowed ({min_date} se {today})"

    return True, user_date

def fetch_reviews(app_id, start_date):
    all_reviews = []
    token = None

    while True:
        result, token = reviews(
            app_id,
            lang="en",
            country="in",
            sort=Sort.NEWEST,
            count=100,
            continuation_token=token
        )

        if not result:
            break

        for r in result:
            r_date = r.get("at")
            if not r_date:
                continue
            if r_date.date() < start_date:
                return all_reviews

            all_reviews.append({
                "user": r.get("userName", ""),
                "rating": r.get("score", ""),
                "date": r_date.strftime("%Y-%m-%d"),
                "review": r.get("content", "")
            })

        if not token:
            break

    return all_reviews

def generate_pdf(reviews_list, path):
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 40
    c.setFont("Helvetica", 10)

    for i, r in enumerate(reviews_list, 1):
        block = (
            f"{i}. {r['user']} | ⭐ {r['rating']} | {r['date']}\n"
            f"{r['review']}\n"
            + "-" * 90
        )
        for line in block.split("\n"):
            if y < 40:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - 40
            c.drawString(40, y, line[:110])
            y -= 14

    c.save()

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length))
            msg = body.get("message")
            if not msg:
                return self._ok()

            chat_id = msg["chat"]["id"]
            text = msg.get("text", "").strip()

            if text == "/start":
                CHAT_STATE.pop(chat_id, None)
                send_text(chat_id, "Send Google Play App link")
                return self._ok()

            if chat_id not in CHAT_STATE:
                app_id = extract_app_id(text)
                if not app_id:
                    send_text(chat_id, "❌ Invalid Play Store link. Send again.")
                else:
                    CHAT_STATE[chat_id] = {"app_id": app_id}
                    send_text(chat_id, "Now send date (YYYY-MM-DD)\n⚠️ Max 10 days old")
                return self._ok()

            ok, result = validate_date(text)
            if not ok:
                send_text(chat_id, result)
                return self._ok()

            start_date = result
            app_id = CHAT_STATE[chat_id]["app_id"]

            send_text(chat_id, "⏳ Fetching reviews & generating PDF...")
            reviews_list = fetch_reviews(app_id, start_date)

            if not reviews_list:
                send_text(chat_id, "No reviews found.")
                CHAT_STATE.pop(chat_id, None)
                return self._ok()

            pdf_path = f"/tmp/reviews_{chat_id}.pdf"
            generate_pdf(reviews_list, pdf_path)
            send_pdf(chat_id, pdf_path)
            CHAT_STATE.pop(chat_id, None)

        except Exception as e:
            print("ERROR:", e)

        self._ok()

    def do_GET(self):
        self._ok(b"Bot running")

    def _ok(self, msg=b"ok"):
        self.send_response(200)
        self.end_headers()
        try:
            self.wfile.write(msg)
        except:
            pass
