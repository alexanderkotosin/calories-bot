import os
import re
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_API = f"https://api.telegram.org/bot{TOKEN}"

# Память в рантайме (пока без базы)
profiles = {}  # profiles[user_id] = {...данные пользователя...}
diary = {}     # diary[user_id] = {"day": <yyyymmdd>, "meals": [...], "total_kcal": float}

def today_key():
    # будем различать дни по дате, чтобы сбрасывать дневник каждый новый день
    return time.strftime("%Y%m%d", time.gmtime())

def calc_profile_numbers(profile):
    """
    Считает:
    - BMR по Mifflin-St Jeor
    - maintenance калорий (учитывая активность)
    - дефицит ~20%
    Возвращает dict.
    """
    age = profile["age"]
    weight = profile["weight"]
    height = profile["height"]
    sex = profile["sex"]  # 'male' / 'female'
    activity_factor = profile["activity_factor"]  # например 1.35

    # Формула Миффлина-Сан Жеора
    if sex == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    maintenance = bmr * activity_factor
    deficit = maintenance * 0.80  # минус 20%

    return {
        "bmr": round(bmr),
        "maintenance": round(maintenance),
        "deficit": round(deficit),
    }

def ensure_diary(user_id):
    """
    Инициализируем дневник на сегодня.
    Если день сменился - сбрасываем.
    """
    dkey = today_key()
    if user_id not in diary or diary[user_id]["day"] != dkey:
        diary[user_id] = {
            "day": dkey,
            "meals": [],         # список приёмов пищи
            "total_kcal": 0.0    # суммарные ккал за день
        }
    return diary[user_id]

def parse_profile_text(text):
    """
    Парсим сообщение вида:
    'Возраст 34, рост 181, вес 95, цель 90, активность средняя.'
    Возвращаем dict с age, height, weight, goal, activity_factor, sex='male'
    Для MVP: считаем юзера мужчиной, активность 'средняя' = 1.35
    """
    # простейший регекс на числа
    age_match = re.search(r'возраст\s+(\d+)', text, re.IGNORECASE)
    height_match = re.search(r'рост\s+(\d+)', text, re.IGNORECASE)
    weight_match = re.search(r'вес\s+(\d+)', text, re.IGNORECASE)
    goal_match = re.search(r'цель\s+(\d+)', text, re.IGNORECASE)

    # активность
    # если есть слово "низ", "сидяч" => 1.2
    # "сред" => 1.35
    # "выс" => 1.55
    act_factor = 1.35
    if re.search(r'низк|сидяч', text, re.IGNORECASE):
        act_factor = 1.2
    elif re.search(r'высок|актив', text, re.IGNORECASE):
        act_factor = 1.55

    # пол пока жёстко male, можем потом расширить
    sex = "male"

    # защита от пустых значений
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

def add_meal_and_get_status(user_id, text):
    """
    Ожидаем текст типа:
    'овсянка 100г - 350 ккал; яйцо 2шт - 160 ккал'
    Мы сделаем очень простой разбор: найдём все числа перед словом 'ккал'
    и сложим их.
    """
    d = ensure_diary(user_id)

    # найдём все калории вида '350 ккал'
    kcal_numbers = re.findall(r'(\d+)\s*ккал', text, re.IGNORECASE)
    meal_kcal = sum([float(x) for x in kcal_numbers]) if kcal_numbers else 0.0

    # добавить приём пищи
    meal_index = len(d["meals"]) + 1
    d["meals"].append({
        "index": meal_index,
        "desc": text,
        "kcal": meal_kcal
    })
    d["total_kcal"] += meal_kcal

    # расчёт суточной нормы с дефицитом
    profile = profiles.get(user_id)
    if profile:
        nums = calc_profile_numbers(profile)
        limit = nums["deficit"]  # целевая калорийность с дефицитом
    else:
        limit = 2000  # запасной дефолт если профиль не задан

    remaining = round(limit - d["total_kcal"])

    # собираем ответ
    lines = []
    lines.append(f"Приём пищи №{meal_index}")
    lines.append(f"Описание: {text}")
    lines.append(f"Калории этого приёма: {meal_kcal:.0f} ккал")
    lines.append("")
    lines.append(f"Съедено за день: {d['total_kcal']:.0f} ккал")
    lines.append(f"Цель на день (дефицит): {round(limit)} ккал")
    lines.append(f"Осталось до лимита: {remaining} ккал")

    # если превышение
    if remaining < 0:
        lines.append("Внимание: лимит на день превышен ⚠")

    return "\n".join(lines)

def build_status_message(user_id):
    """
    Отчёт о текущей ситуации: нормы + прогресс за день.
    """
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

    if remaining < 0:
        msg.append("⚠ Ты превысил лимит дефицита сегодня.")

    return "\n".join(msg)

def handle_user_message(user_id, text):
    """
    Здесь решаем, что бот отвечает на входящее сообщение.
    """

    # 1. пользователь хочет задать/обновить профиль
    # триггеры: содержит 'возраст' и 'рост' и 'вес'
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

    # 2. пользователь просит статус
    if text.strip().lower() in ["/status", "статус", "остаток", "сколько осталось"]:
        return build_status_message(user_id)

    # 3. иначе считаем, что это приём пищи
    meal_report = add_meal_and_get_status(user_id, text)
    return meal_report


# --------- ТЕПЕРЬ МЫ СВЯЗЫВАЕМ ЭТО С ТЕЛЕГРАМ ---------

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
            "Привет 👋 Я бот контроля калорий.\n\n"
            "1) Пришли свои данные (возраст, рост, вес, цель, активность)\n"
            "   Пример:\n"
            "   Возраст 34, рост 181, вес 95, цель 90, активность средняя.\n\n"
            "2) Потом просто присылай что ты ел. Я буду считать:\n"
            "- Приём пищи №1, №2, ...\n"
            "- Сколько ккал в каждом\n"
            "- Сколько уже за день\n"
            "- Сколько осталось до лимита\n\n"
            "3) Напиши /status чтобы увидеть сводку дня."
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
