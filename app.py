import os
import re
import time
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# === Конфигурация из переменных окружения ===
TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_API = f"https://api.telegram.org/bot{TOKEN}"

AI_ENDPOINT = os.getenv("AI_ENDPOINT", "")
AI_KEY = os.getenv("AI_KEY", "")

# === Память в рантайме ===
# Профиль пользователя живёт, пока не перезапущен сервис.
# Дневник еды сбрасывается раз в сутки по дате.
profiles = {}  # profiles[user_id] = {...}
diary = {}     # diary[user_id] = {"day": "YYYYMMDD", "meals": [...], totals...}


# ========= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def today_key():
    # Можно заменить на локальную зону, но пока хватит UTC
    return time.strftime("%Y%m%d", time.gmtime())


def ensure_diary(user_id):
    """
    Инициализируем дневник на сегодня.
    Если день сменился -> обнуляем, профиль остаётся.
    """
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
    """Расчёт BMR, калорий на поддержание и дефицита ~20%."""
    age = profile["age"]
    weight = profile["weight"]
    height = profile["height"]
    sex = profile["sex"]
    activity_factor = profile["activity_factor"]

    # Формула Миффлина–Сан Жеора
    if sex == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    maintenance = bmr * activity_factor
    deficit = maintenance * 0.80

    return {
        "bmr": round(bmr),
        "maintenance": round(maintenance),
        "deficit": round(deficit),
    }


def parse_profile_text(text):
    """
    Парсим профиль на RU / EN / SR.
    Формат можно набирать как угодно, главное — чтобы были ключевые слова из шаблона:

    RU: возраст, рост, вес, цель, активность
    EN: age, height, weight, goal, activity
    SR: godine/godina, visina, tezina/težina, cilj, aktivnost
    """

    age_match = re.search(
        r'(возраст|age|godine|godina)\s*[:\-]?\s*(\d+)',
        text, re.IGNORECASE
    )
    height_match = re.search(
        r'(рост|height|visina)\s*[:\-]?\s*(\d+)',
        text, re.IGNORECASE
    )
    weight_match = re.search(
        r'(вес|weight|težina|tezina)\s*[:\-]?\s*(\d+)',
        text, re.IGNORECASE
    )
    goal_match = re.search(
        r'(цель|goal|cilj)\s*[:\-]?\s*(\d+)',
        text, re.IGNORECASE
    )

    if not (age_match and height_match and weight_match and goal_match):
        return None

    age = int(age_match.group(2))
    height = int(height_match.group(2))
    weight = float(weight_match.group(2))
    goal = float(goal_match.group(2))

    # Активность: RU / EN / SR
    act_factor = 1.35  # по умолчанию средняя
    t = text.lower()

    if re.search(r'низк|сидяч|low|sedentary|nizak', t):
        act_factor = 1.2
    elif re.search(r'высок|очень актив|high|very active|visok', t):
        act_factor = 1.55
    elif re.search(r'умеренн|moderate|medium|srednj', t):
        act_factor = 1.35

    # Пол пока фикс — можно расширить позже
    sex = "male"

    return {
        "age": age,
        "height": height,
        "weight": weight,
        "goal": goal,
        "sex": sex,
        "activity_factor": act_factor,
    }


def extract_kcal_from_text(text):
    """
    Логика:
    1) Если есть '420 ккал', '420 kcal', '420 кк', '420 kk' — считаем это калориями.
    2) Если ВСЁ сообщение — это одно число '420' без букв, считаем это калориями.
    3) Во всех остальных случаях ('2 яйца', '2 бургера', 'rice 100g') возвращаем None,
       чтобы калории оценивал ИИ.
    """
    text = text.strip()

    # явное упоминание калорий
    m = re.search(r'(\d+)\s*(ккал|kcal|кк|kk)', text, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # сообщение — одно число без слов
    if re.fullmatch(r'\d+', text):
        return float(text)

    return None


def _extract_json_block(text: str):
    """Достаём первый {...} из ответа модели."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE)
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start:end + 1]
    return None


def ask_ai_for_meal(text_description):
    """
    Запрос к модели через Hugging Face Router.
    Модель понимает RU / EN / SR.
    Возвращает dict с kcal и БЖУ или None.
    """
    if not AI_ENDPOINT or not AI_KEY:
        print("AI not configured")
        return None

    system_prompt = (
        "You are a nutritionist assistant. "
        "The user describes a meal in Russian, English or Serbian. "
        "Estimate total calories and macros (protein, fat, carbs).\n"
        "Respond ONLY with JSON in this exact format:\n"
        "{"
        "\"kcal\": <number>, "
        "\"protein_g\": <number>, "
        "\"fat_g\": <number>, "
        "\"carbs_g\": <number>"
        "}\n"
        "No extra text before or after JSON."
    )

    user_prompt = f"Meal description: {text_description}"

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "meta-llama/Llama-3.1-8B-Instruct",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 256,
        "temperature": 0.1,
    }

    try:
        resp = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=25)
        print("AI status:", resp.status_code)
        print("AI raw:", resp.text[:400])

        if resp.status_code != 200:
            return None

        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )

        js = _extract_json_block(content)
        if not js:
            return None

        result = json.loads(js)

        return {
            "kcal": float(result.get("kcal", 0) or 0),
            "protein_g": float(result.get("protein_g", 0) or 0),
            "fat_g": float(result.get("fat_g", 0) or 0),
            "carbs_g": float(result.get("carbs_g", 0) or 0),
        }

    except Exception as e:
        print("AI PARSE ERROR:", e)
        return None


def add_meal_and_get_status(user_id, text):
    """
    Логика приёма пищи:
    - пробуем забрать число ккал из текста (только если это реально калории);
    - если его нет — спрашиваем ИИ;
    - обновляем дневник, считаем остаток.
    """
    d = ensure_diary(user_id)

    kcal_direct = extract_kcal_from_text(text)

    meal_kcal = 0.0
    meal_p = 0.0
    meal_f = 0.0
    meal_c = 0.0
    ai_data = None

    if kcal_direct is not None:
        meal_kcal = kcal_direct
    else:
        ai_data = ask_ai_for_meal(text)
        if ai_data:
            meal_kcal = ai_data["kcal"]
            meal_p = ai_data["protein_g"]
            meal_f = ai_data["fat_g"]
            meal_c = ai_data["carbs_g"]

    # записываем приём
    d = ensure_diary(user_id)
    meal_index = len(d["meals"]) + 1
    d["meals"].append({
        "index": meal_index,
        "desc": text,
        "kcal": meal_kcal,
        "protein_g": meal_p,
        "fat_g": meal_f,
        "carbs_g": meal_c,
    })

    d["total_kcal"] += meal_kcal
    d["total_p"] += meal_p
    d["total_f"] += meal_f
    d["total_c"] += meal_c

    profile = profiles.get(user_id)
    if profile:
        nums = calc_profile_numbers(profile)
        limit = nums["deficit"]
    else:
        limit = 2000  # запасная цель, если профиль ещё не задан

    remaining = round(limit - d["total_kcal"])

    lines = []
    lines.append(f"Приём пищи №{meal_index}")
    lines.append(f"Описание: {text}")
    lines.append(f"Калории этого приёма: {meal_kcal:.0f} ккал")

    if ai_data:
        lines.append(
            f"БЖУ этого приёма: Б {meal_p:.1f} г / Ж {meal_f:.1f} г / У {meal_c:.1f} г"
        )

    lines.append("")
    lines.append(f"Съедено за день: {d['total_kcal']:.0f} ккал")

    if d["total_p"] or d["total_f"] or d["total_c"]:
        lines.append(
            f"БЖУ за день: Б {d['total_p']:.1f} г / Ж {d['total_f']:.1f} г / У {d['total_c']:.1f} г"
        )

    lines.append(f"Цель на день (дефицит): {round(limit)} ккал")
    lines.append(f"Осталось до лимита: {remaining} ккал")

    if remaining < 0:
        lines.append("⚠ Лимит дефицита превышен.")

    if meal_kcal == 0 and not ai_data and kcal_direct is None:
        lines.append("")
        lines.append("ℹ Не удалось оценить калории автоматически. "
                     "Можно дописать в конце сообщения просто число, например: '... 420'.")

    return "\n".join(lines)


def profile_help_text():
    """Шаблон профиля (RU/EN/SR), который юзер копирует и заполняет цифрами."""
    return (
        "Заполни профиль, просто вставив цифры в шаблон и отправив его мне.\n\n"
        "РУССКИЙ 🇷🇺 (скопируй, подставь свои числа):\n"
        "Возраст: 34\n"
        "Рост: 181\n"
        "Вес: 86\n"
        "Цель: 84\n"
        "Активность: высокая  (варианты: низкая / средняя / высокая)\n\n"
        "ENGLISH 🇬🇧:\n"
        "Age: 34\n"
        "Height: 181\n"
        "Weight: 86\n"
        "Goal: 84\n"
        "Activity: high  (options: low / moderate / high)\n\n"
        "SRPSKI 🇷🇸:\n"
        "Godine: 34\n"
        "Visina: 181\n"
        "Tezina: 86\n"
        "Cilj: 84\n"
        "Aktivnost: visoka  (nizka / srednja / visoka)\n"
    )


def build_status_message(user_id):
    profile = profiles.get(user_id)
    d = ensure_diary(user_id)

    if not profile:
        return profile_help_text()

    nums = calc_profile_numbers(profile)
    limit = nums["deficit"]
    remaining = round(limit - d["total_kcal"])

    msg = []
    msg.append("Статус на сегодня:")
    msg.append(f"- Поддержание веса: {nums['maintenance']} ккал/день")
    msg.append(f"- Дефицит (~20%): {nums['deficit']} ккал/день")
    msg.append(f"- Съедено сегодня: {d['total_kcal']:.0f} ккал")
    msg.append(f"- Осталось до лимита дефицита: {remaining} ккал")

    if d["total_p"] or d["total_f"] or d["total_c"]:
        msg.append(
            f"- БЖУ за день: Б {d['total_p']:.1f} г / Ж {d['total_f']:.1f} г / У {d['total_c']:.1f} г"
        )

    if remaining < 0:
        msg.append("⚠ Лимит превышен, аккуратнее с вечерними перекусами 😈")

    return "\n".join(msg)


def is_greeting(text: str) -> bool:
    t = text.strip().lower()
    greetings = [
        "привет", "здарова", "здравствуйте", "добрый день",
        "hi", "hello", "hey",
        "здраво", "cao", "ćao", "hej"
    ]
    return any(t.startswith(g) for g in greetings)


def greeting_reply() -> str:
    return (
        "Привет! 👋 Я бот, который считает калории и не осуждает за ночные перекусы.\n\n"
        "Кратко как пользоваться:\n"
        "• Сначала задай профиль (рост, вес и т.д.) — пришлю форму по команде /start.\n"
        "• Потом просто пиши, что ты ел/ела. Можно на русском, английском или сербском.\n"
        "• Если знаешь калории приёма — можешь в конце дописать просто число, например: '... 420'.\n"
        "• Команда /status покажет, сколько уже съел(а) и сколько осталось.\n\n"
        "Окей, давай работать с едой 😉"
    )


def handle_user_message(user_id, text):
    """
    Основная логика:
    - приветствия -> дружелюбный ответ;
    - профиль -> сохраняем профиль;
    - статус -> сводка;
    - всё остальное -> считаем как приём пищи.
    """

    # 0. Приветствия / small-talk
    if is_greeting(text):
        return greeting_reply()

    # 1. Профиль (ищем ключевые слова)
    if re.search(r'(возраст|age|godine|godina)', text, re.IGNORECASE) and \
       re.search(r'(рост|height|visina)', text, re.IGNORECASE) and \
       re.search(r'(вес|weight|težina|tezina)', text, re.IGNORECASE):

        prof = parse_profile_text(text)
        if prof is None:
            return (
                "Не понял профиль 😅\n\n"
                + profile_help_text()
            )

        profiles[user_id] = prof
        nums = calc_profile_numbers(prof)

        return (
            "Профиль обновлён ✅\n\n"
            f"Возраст: {prof['age']}, рост: {prof['height']} см, вес: {prof['weight']} кг\n"
            f"Цель: {prof['goal']} кг\n"
            f"Активность: коэффициент {prof['activity_factor']}\n\n"
            f"Поддержание веса: {nums['maintenance']} ккал/день\n"
            f"Дефицит (~20%): {nums['deficit']} ккал/день\n\n"
            "Теперь просто присылай, что ел/ела (RU / EN / SR), "
            "я буду считать приёмы пищи и остаток калорий."
        )

    # 2. Статус
    low = text.strip().lower()
    if low in ["/status", "статус", "остаток", "status", "stanje", "koliko je ostalo"]:
        return build_status_message(user_id)

    # 3. Всё остальное считаем едой
    return add_meal_and_get_status(user_id, text)


# ============= FLASK / TELEGRAM =============

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
            "Привет 👋 Я AI-бот учёта калорий.\n\n"
            "КАК ПОЛЬЗОВАТЬСЯ:\n"
            "1️⃣ Настрой профиль — просто скопируй форму ниже, вставь свои цифры и отправь:\n\n"
            + profile_help_text() +
            "\n2️⃣ Дальше пиши, что ты ешь. Я разбираю русский, английский и сербский.\n"
            "   Пример: 'яичница 2 яйца и хлеб', '2 burgers and fries', 'piletina 150g i pirinač 100g'.\n"
            "   Небольшая погрешность в описании — не страшно, я всё равно дам адекватную оценку.\n\n"
            "3️⃣ Если ты сам знаешь калории приёма, можно в конце просто написать число:\n"
            "   'шаурма и кола — 850'  → я приму 850 ккал.\n\n"
            "4️⃣ Команда /status покажет, сколько уже съел(а) и сколько осталось на сегодня.\n\n"
            "Ну всё, поехали считать калории, а не овечек 😈"
        )
    else:
        reply = handle_user_message(chat_id, user_text)

    send_text_message(chat_id, reply)
    return jsonify({"ok": True})


def send_text_message(chat_id, text):
    try:
        requests.post(
            f"{BOT_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10
        )
    except Exception as e:
        print("TELEGRAM SEND ERROR:", e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
