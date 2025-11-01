import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# забираем токен из переменных окружения Render
TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_API = f"https://api.telegram.org/bot{TOKEN}"

# 1. healthcheck, чтобы Render показывал "AI Calories Bot is running!"
@app.route("/", methods=["GET"])
def home():
    return "AI Calories Bot is running!"

# 2. основной webhook-эндпоинт
#    ВАЖНО: путь ДОЛЖЕН совпадать с тем, что мы поставили через setWebhook
@app.route(f"/{os.getenv('TELEGRAM_TOKEN')}", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True)

    # лог в stdout -> ты будешь видеть апдейты в Render → Logs
    print("=== incoming update ===")
    print(update)
    print("=======================")

    # если апдейт странный или пустой — просто отвечаем ОК, чтобы Telegram нас не считал мёртвым
    if not update or "message" not in update:
        return jsonify({"ok": True})

    chat_id = update["message"]["chat"]["id"]
    user_text = update["message"].get("text", "")

    # простая логика ответа
    if user_text.strip() == "/start":
        reply = (
            "Привет 👋 Я бот учёта калорий.\n\n"
            "Что я могу делать:\n"
            "• Рассчитать твою дневную норму калорий и дефицит\n"
            "• Вести дневник приёмов пищи\n"
            "• Говорить сколько калорий осталось на сегодня\n\n"
            "Напиши свои данные так:\n"
            "Возраст 34, рост 181, вес 95, цель 90, активность средняя.\n"
        )
    else:
        reply = f"Ты написал: {user_text}"

    send_text_message(chat_id, reply)

    # Telegram ждёт JSON с {"ok":true}, чтобы считать, что запрос обработан
    return jsonify({"ok": True})


def send_text_message(chat_id, text):
    """Отправка текста пользователю в Telegram."""
    requests.post(
        f"{BOT_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
        }
    )


# ВАЖНО:
# никакого set_webhook() тут не вызываем.
# Мы уже вручную привязали вебхук к URL:
# https://calories-bot-ltzv.onrender.com/7903...ОСТАЛЬНОЕ_ТОКЕНА
# Значит, сервер просто слушает и отвечает.


if __name__ == "__main__":
    # локально (на своём компе) Flask слушал бы порт.
    # на Render у нас Start Command = "python app.py", поэтому тут тоже run().
    app.run(host="0.0.0.0", port=10000)
