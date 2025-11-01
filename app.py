import os
import re
import time
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_API = f"https://api.telegram.org/bot{TOKEN}"

AI_ENDPOINT = os.getenv("AI_ENDPOINT", "")  # URL сервера ИИ (мы добавим позже)
AI_KEY = os.getenv("AI_KEY", "")            # если нужен ключ (может быть пустым для MVP)

# Память в рантайме
profiles = {}  # profiles[user_id] = {...}
diary = {}     # diary[user_id] = {"day": "yyyymmdd", "meals":[...], "total_kcal": float, "total_p":float, "total_f":float, "total_c":float}

def today_key():
    return time.strftime("%Y%m%d", time.gmtime())

def ensure_diary(user_id):
    dkey = today_key()
    if user_id not in diary or diary[user_id]["day"] != dkey:
        diary[user_id] = {
            "day": dkey,
            "meals": [],
            "total_kcal": 0.0,
            "total_p": 0.0,
            "total_f": 0.0,
            "total_c": 0.0,
        }
    return diary[user_id]

def calc_profile_numbers(profile):
    age = profile["age"]
    weight = profile["weight"]
    height = profile["height"]
    sex = profile["sex"]
    activity_factor = profile["activity_factor"]

    # Миффлин-Сан Жеор
    if sex == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    maintenance = bmr * activity_factor
    deficit = maintenance * 0.80  # -20%

    return {
        "bmr": round(bmr),
        "maintenance": round(maintenance),
        "deficit": round(deficit),
    }

def parse_profile_text(text):
    age_match = re.search(r'возраст\s+(\d+)', text, re.IGNORECASE)
    height_match = re.search(r'рост\s+(\d+)', text, re.IGNORECASE)
    weight_match = re.search(r'вес\s+(\d+)', text, re.IGNORECASE)
    goal_match = re.search(r'цель\s+(\d+)', text, re.IGNORECASE)

    act_factor = 1.35  # по умолчанию "средняя"
    if re.search(r'низк|сидяч', text, re.IGNORECASE):
        act_factor = 1.2
    elif re.search(r'высок|актив', text, re.IGNORECASE):
        act_factor = 1.55

    sex = "male"  # пока фикс

    if not (age_match and height_match and weight_match and goal_match):
        return None

    return {
        "age": int(age_match.group(1)),
        "height": int(height_match.group(1)),
        "weight": float(weight_match.group(1)),
        "goal": float(goal_match.group(1)),
        "sex": sex,
        "activity_factor": act_factor
    }

def ask_ai_for_meal(text_description):
    """
    Отправляем описание еды в ИИ и просим оценить:
    - общие калории
    - белки граммы
    - жиры граммы
    - углеводы граммы

    Возвращаем dict:
    {
      "kcal": float,
      "protein_g": float,
      "fat_g": float,
      "carbs_g": float
    }

    Если что-то пошло не так — вернём None.
    """

    if not AI_ENDPOINT:
        # У нас пока нет AI, fallback на None.
        return None

    prompt = (
        "Ты нутрициолог. Пользователь описывает приём пищи.\n"
        "Твоя задача — очень грубо и практично оценить калории и БЖУ.\n\n"
        "Важно:\n"
        "- Верни ТОЛЬКО JSON без текста вокруг.\n"
        "- Структура строго такая:\n"
        "{"
        "\"kcal\": <число>, "
        "\"protein_g\": <число>, "
        "\"fat_g\": <число>, "
        "\"carbs_g\": <число>"
        "}\n\n"
        f"Описание еды: {text_description}\n"
    )

    headers = {
        "Content-Type": "application/json",
    }
    # Если твой AI сервис требует ключ:
    if AI_KEY:
        headers["Authorization"] = f"Bearer {AI_KEY}"

    payload = {
        "prompt": prompt,
        # В реальном провайдере могут нужны другие поля (model, max_tokens и т.д.).
        # Мы потом адаптируем под конкретный API.
    }

    try:
        resp = requests.post(AI_ENDPOINT, headers=headers, data=json.dumps(payload), timeout=10)
        data = resp.text.strip()

        # Попытаемся разобрать ответ как JSON напрямую
        result = json.loads(data)

        # Ожидаемые ключи
        kcal = float(result.get("kcal", 0))
        p = float(result.get("protein_g", 0))
        f = float(result.get("fat_g", 0))
        c = float(result.get("carbs_g", 0))

        return {
            "kcal": kcal,
            "protein_g": p,
            "fat_g": f,
            "carbs_g": c,
        }

    except Exception as e:
        print("AI PARSE ERROR:", e)
        return None

def extract_kcal_from_text(text):
    """
    Если юзер сам указал калории '420 ккал', просто возьми их.
    Это экономит запрос к ИИ.
    """
    kcal_numbers = re.findall(r'(\d+)\s*ккал', text, re.IGNORECASE)
    if kcal_numbers:
        return float(kcal_numbers[0])
    return None

def add_meal_and_get_status(user_id, text):
    """
    1. Пытаемся понять калории из текста напрямую ('420 ккал').
    2. Если не нашли — спрашиваем ИИ.
    3. Обновляем дневник.
    4. Формируем ответ пользователю.
    """
    d = ensure_diary(user_id)

    # шаг 1: прямое число в тексте
    kcal_direct = extract_kcal_from_text(text)

    ai_data = None
    meal_kcal = 0.0
    meal_p = 0.0
    meal_f = 0.0
    meal_c = 0.0

    if kcal_direct is not None:
        meal_kcal = kcal_direct
    else:
        # шаг 2: спросим ИИ
        ai_data = ask_ai_for_meal(text)
        if ai_data:
            meal_kcal = ai_data["kcal"]
            meal_p = ai_data["protein_g"]
            meal_f = ai_data["fat_g"]
            meal_c = ai_data["carbs_g"]
        else:
            # если ИИ недоступен, считаем 0 (но сообщим)
            meal_kcal = 0.0

    # сохранить приём
    meal_index = len(d["meals"]) + 1
    d["meals"].append({
        "index": meal_index,
        "desc": text,
        "kcal": meal_kcal,
        "protein_g": meal_p,
        "fat_g": meal_f,
        "carbs_g": meal_c,
    })

    # обновить дневные суммы
    d["total_kcal"] += meal_kcal
    d["total_p"] += meal_p
    d["total_f"] += meal_f
    d["total_c"] += meal_c

    # расчёт остатка калорий относительно дефицита
    profile = profiles.get(user_id)
    if profile:
        nums = calc_profile_numbers(profile)
        limit = nums["deficit"]
    else:
        limit = 2000  # fallback если нет профиля

    remaining = round(limit - d["total_kcal"])

    lines = []
    lines.append(f"Приём пищи №{meal_index}")
    lines.append(f"Описание: {text}")
    lines.append(f"Калории этого приёма: {meal_kcal:.0f} ккал")

    # показываем БЖУ если они есть
    if ai_data:
        lines.append(f"Белки: {meal_p:.1f} г, Жиры: {meal_f:.1f} г, Углеводы: {meal_c:.1f} г")

    lines.append("")
    lines.append(f"Съедено за день: {d['total_kcal']:.0f} ккал")
    if ai_data:
        lines.append(
            f"БЖУ за день: Б {d['total_p']:.1f} г / Ж {d['total_f']:.1f} г / У {d['total_c']:.1f} г"
        )

    lines.append(f"Цель на день (дефицит): {round(limit)} ккал")
    lines.append(f"Осталось до лимита: {remaining} ккал")

    if remaining < 0:
        lines.append("⚠ Превышение лимита дефицита.")

    if meal_kcal == 0.0 and not ai_data and kcal_direct is None:
        lines.append("")
        lines.append("ℹ Не получилось оценить калории автоматически. "
                     "Можно написать примерно так: '... всего 450 ккал'.")

    return "\n".join(lines)

def build_status_message(user_id):
    profile = profiles.get(user_id)
    d = ensure_diary(user_id)

    if not profile:
        return "Профиль не задан. Отправь свои данные (возраст, рост, вес, цель...)."

    nums = calc_profile_numbers(profile)
    limit = nums["deficit"]
    remaining = round(limit - d["total_kcal"])

    msg = []
    msg.append("Твой статус на сегодня:")
    msg.append(f"- Поддержание веса: {nums['maintenance']} ккал/день")
    msg.append(f"- Дефицит (~20%): {nums['deficit']} ккал/день")
    msg.append(f"- Съедено сегодня: {d['total_kcal']:.0f} ккал")
    msg.append(f"- Осталось до лимита дефицита: {remaining} ккал")

    # Если мы уже накопили БЖУ за день — покажем
    if d["total_p"] > 0 or d["total_f"] > 0 or d["total_c"] > 0:
        msg.append(
            f"- БЖУ за день: Б {d['total_p']:.1f} г / Ж {d['total_f']:.1f} г / У {d['total_c']:.1f} г"
        )

    if remaining < 0:
        msg.append("⚠ Ты превысил лимит дефицита сегодня.")

    return "\n".join(msg)

def handle_user_message(user_id, text):
    # Обновление профиля пользователя
    if re.search(r'возраст', text, re.IGNORECASE) and \
       re.search(r'рост', text, re.IGNORECASE) and \
       re.search(r'вес', text, re.IGNORECASE):

        prof = parse_profile_text(text)
        if prof is None:
            return (
                "Не понял данные. Пришли в формате:\n"
                "Возраст 34, рост 181, вес 95, цель 90, активность средняя."
            )

        profiles[user_id] = prof
        nums = calc_profile_numbers(prof)

        return (
            "Профиль обновлён ✅\n\n"
            f"Возраст: {prof['age']}, рост: {prof['height']} см, вес: {prof['weight']} кг\n"
            f"Цель: {prof['goal']} кг\n"
            f"Активность: коэффициент {prof['activity_factor']}\n\n"
            f"Поддержание веса: {nums['maintenance']} ккал/день\n"
            f"Дефицит (~20%): {nums['deficit']} ккал/день\n"
            "Теперь просто присылай еду, а я буду считать приёмы пищи."
        )

    # Запрос статуса
    if text.strip().lower() in ["/status", "статус", "остаток", "сколько осталось"]:
        return build_status_message(user_id)

    # Любой другой текст считаем едой
    meal_report = add_meal_and_get_status(user_id, text)
    return meal_report

# ====== TELEGRAM HANDLERS ======

@app.route("/", methods=["GET"])
def health():
    return "AI Calories Bot is running!"

@app.route(f"/{TOKEN}", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True)

    print("=== incoming update ===")
    print(update)
    print("=======================")

    if not update or "message" not in update:
        return jsonify({"ok": True})

    chat_id = update["message"]["chat"]["id"]
    user_text = update["message"].get("text", "")

    if user_text.strip() == "/start":
        reply = (
            "Привет 👋 Я бот учёта калорий.\n\n"
            "1) Пришли свои данные (возраст, рост, вес, цель, активность)\n"
            "   Пример:\n"
            "   Возраст 34, рост 181, вес 95, цель 90, активность средняя.\n\n"
            "2) Потом просто пиши что ты ел в свободной форме — "
            "я сам оценю калории и БЖУ.\n\n"
            "3) Напиши /status чтобы увидеть остаток калорий на день."
        )
    else:
        reply = handle_user_message(chat_id, user_text)

    send_text_message(chat_id, reply)
    return jsonify({"ok": True})

def send_text_message(chat_id, text):
    requests.post(
        f"{BOT_API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
