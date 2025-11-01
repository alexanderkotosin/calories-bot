from flask import Flask, request
import requests
import os

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
URL = f"https://api.telegram.org/bot{TOKEN}/"

# Главная страница для проверки
@app.route('/')
def index():
    return "AI Calories Bot is running!"

# Этот маршрут Telegram будет дергать при новых сообщениях
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    data = request.get_json()
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        send_message(chat_id, f"Ты написал: {text}")
    return {"ok": True}

def send_message(chat_id, text):
    requests.post(URL + "sendMessage", json={"chat_id": chat_id, "text": text})

# Устанавливаем webhook
def set_webhook():
    webhook_url = "https://calories-bot-ltzv.onrender.com" + TOKEN
    requests.get(URL + f"setWebhook?url={webhook_url}")

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=10000)
