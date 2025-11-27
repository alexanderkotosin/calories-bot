import os
import json
import datetime
import re
import requests
from flask import Flask, request

# ================================
# CONFIG
# ================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

AI_ENDPOINT = os.environ.get("AI_ENDPOINT")  # например: https://router.huggingface.co/v1/chat/completions
AI_KEY = os.environ.get("AI_KEY")            # твой hf_...
AI_MODEL = os.environ.get(
    "AI_MODEL",
    "meta-llama/Meta-Llama-3-8B-Instruct"    # дефолтная модель, можно переопределить в Render
)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = Flask(__name__)


# ================================
# SUPABASE HELPERS
# ================================

def supabase_headers(json_mode=False):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    if json_mode:
        headers["Content-Type"] = "application/json"
    return headers


def supabase_select(table, match):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {"select": "*"}
    params.update(match)
    r = requests.get(url, headers=supabase_headers(), params=params, timeout=15)
    try:
        data = r.json()
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def supabase_upsert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = requests.post(
        url,
        headers={**supabase_headers(json_mode=True), "Prefer": "resolution=merge-duplicates"},
        data=json.dumps(data),
        timeout=15,
    )
    try:
        return r.json()
    except Exception:
        return []


def supabase_insert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = requests.post(
        url,
        headers=supabase_headers(json_mode=True),
        data=json.dumps(data),
        timeout=15,
    )
    try:
        return r.json()
    except Exception:
        return []


# ================================
# LANGUAGE PACKS
# ================================

TEXT = {
    "ru": {
        "ask_profile": (
            "Привет! Я помогу считать калории и дефицит.\n\n"
            "Сначала заполним профиль. Скопируй шаблон ниже, вставь в чат и впиши свои данные цифрами:\n\n"
            "Возраст: ___\n"
            "Рост: ___\n"
            "Вес: ___\n"
            "Цель (вес): ___\n"
            "Пол: м/ж\n"
            "Активность: низкая / средняя / высокая\n\n"
            "Пример:\n"
            "Возраст: 34\n"
            "Рост: 181\n"
            "Вес: 95\n"
            "Цель (вес): 88\n"
            "Пол: м\n"
            "Активность: средняя"
        ),
        "profile_saved": "Профиль сохранён ✅ Теперь просто присылай, что ты съел, а я всё посчитаю.",
        "need_details": "Мне нужно уточнение — сколько примерно это весит в граммах?",
        "meal_count": "Приём пищи №{}",
        "daily_total": "Съедено за день: {} ккал",
        "daily_left": "Осталось до лимита: {} ккал",
        "not_food": "Это не похоже на еду. Но я могу поболтать 😊\n\n{}",
    },
    "en": {
        "ask_profile": (
            "Hi! I’ll help you track calories and deficit.\n\n"
            "First, let’s set up your profile. Copy this template, paste it here and fill in the numbers:\n\n"
            "Age: ___\n"
            "Height: ___\n"
            "Weight: ___\n"
            "Goal weight: ___\n"
            "Sex: m/f\n"
            "Activity: low / medium / high\n\n"
            "Example:\n"
            "Age: 34\n"
            "Height: 181\n"
            "Weight: 95\n"
            "Goal weight: 88\n"
            "Sex: m\n"
            "Activity: medium"
        ),
        "profile_saved": "Profile saved ✅ Now just send what you eat and I’ll track it.",
        "need_details": "I need some clarification — roughly how many grams is that?",
        "meal_count": "Meal #{}",
        "daily_total": "Total eaten today: {} kcal",
        "daily_left": "Remaining today: {} kcal",
        "not_food": "This doesn’t look like food. But we can chat 😄\n\n{}",
    },
    "sr": {
        "ask_profile": (
            "Ćao! Pomoći ću ti da pratiš kalorije i deficit.\n\n"
            "Prvo da podesimo profil. Kopiraj šablon ispod, nalepi u chat i popuni brojevima:\n\n"
            "Godine: ___\n"
            "Visina: ___\n"
            "Težina: ___\n"
            "Ciljna težina: ___\n"
            "Pol: m/ž\n"
            "Aktivnost: niska / srednja / visoka\n\n"
            "Primer:\n"
            "Godine: 34\n"
            "Visina: 181\n"
            "Težina: 95\n"
            "Ciljna težina: 88\n"
            "Pol: m\n"
            "Aktivnost: srednja"
        ),
        "profile_saved": "Profil sačuvan ✅ Sada samo šalji šta jedeš i ja ću sve pratiti.",
        "need_details": "Treba mi pojašnjenje — koliko otprilike to ima grama?",
        "meal_count": "Obrok #{}",
        "daily_total": "Ukupno danas: {} kcal",
        "daily_left": "Preostalo danas: {} kcal",
        "not_food": "Ovo ne liči na hranu. Ali možemo da ćaskamo 😄\n\n{}",
    },
}


# ================================
# HUGGINGFACE CHAT WRAPPER
# ================================

def ask_ai_chat(user_text: str, lang: str, system_prompt: str) -> str | None:
    """
    Общий чат-режим: ответ на свободный вопрос пользователя.
    Работает через /v1/chat/completions.
    """
    if not AI_ENDPOINT or not AI_KEY:
        # Если ИИ не настроен, вернём мягкий фоллбек
        fallback = {
            "ru": "Давай поговорим о питании, целях, тренировках или просто о жизни 🙂",
            "en": "We can talk about nutrition, goals, training or just life 🙂",
            "sr": "Možemo da pričamo o ishrani, ciljevima, treningu ili samo o životu 🙂",
        }.get(lang, "Let's chat 🙂")
        return fallback

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 256,
    }

    try:
        r = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=30)
        data = r.json()
        # Ожидаем OpenAI-совместимый формат
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        print("AI chat error:", e)
        return None


def ask_ai_kcal(prompt: str, lang: str) -> float | None:
    """
    Запрос к ИИ: оценить калории на 100 г.
    Возвращает число или None.
    """
    if not AI_ENDPOINT or not AI_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    system_prompt = {
        "ru": "Ты нутриционист. Отвечай только числом — сколько ккал в 100 граммах указанной еды.",
        "en": "You are a nutritionist. Answer with only a number: kcal per 100g of the given food.",
        "sr": "Ti si nutricionista. Odgovori samo brojem: koliko kcal ima 100g navedene hrane.",
    }.get(lang, "You are a nutritionist. Answer only with a number: kcal per 100g.")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 16,
    }

    try:
        r = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=30)
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        nums = re.findall(r"\d+(\.\d+)?", content)
        if not nums:
            return None
        return float(nums[0])
    except Exception as e:
        print("AI kcal error:", e)
        return None


# ================================
# FOOD / UNITS LOGIC
# ================================

UNIT_WORDS = ["г", "гр", "gram", "g", "kg", "кг", "ml", "мл", "литр", "l"]

FRACTION_PATTERN = r"(\d+/\d+)"


def extract_fraction(text: str):
    match = re.search(FRACTION_PATTERN, text)
    if not match:
        return None
    num, denom = match.group(0).split("/")
    try:
        return float(num) / float(denom)
    except ZeroDivisionError:
        return None


def detect_explicit_weight(text: str):
    """
    Ищем '200 г', '150гр', '250g', '100 ml', '1kg' и т.п.
    Возвращаем число (граммы) или None.
    """
    t = text.lower().replace(",", ".")
    # kg / кг → переведём в граммы
    kg_match = re.findall(r"(\d+(\.\d+)?)\s*(kg|кг)", t)
    if kg_match:
        val = float(kg_match[0][0])
        return val * 1000

    # g / гр / г / gram
    g_match = re.findall(r"(\d+(\.\d+)?)\s*(g|гр|г|gram)", t)
    if g_match:
        val = float(g_match[0][0])
        return val

    # ml / мл – оставляем как есть, ИИ все равно делает оценку по 100 г, это уже упрощение
    ml_match = re.findall(r"(\d+(\.\d+)?)\s*(ml|мл|l|литр)", t)
    if ml_match:
        val = float(ml_match[0][0])
        return val  # будем считать как "условные граммы"

    return None


def detect_explicit_kcal(text: str):
    """
    Ищем калории: 300 ккал, 450 kcal, 500кк и т.п.
    Если в сообщении есть единицы веса – считаем, что число относится к весу, а не к калориям.
    """
    t = text.lower()
    if any(u in t for u in UNIT_WORDS):
        # Есть указание веса – будем считать, что числа относятся к весу, а не калориям
        return None

    match = re.findall(r"(\d+)\s*(ккал|kcal|кк|cal|кал)?", t)
    if not match:
        return None

    # Берём последнее число
    val_str, unit = match[-1]
    val = int(val_str)
    # Если явно указана калорийность
    if unit:
        return val
    # Если единиц нет – считаем, что это калории
    return val


def is_food_message(text: str):
    """
    Решаем, похоже ли сообщение на описание еды.
    """
    t = text.lower()
    # ключевые слова
    food_words = [
        "бурек", "burek", "burger", "бургер", "пиц", "pizza", "сыр", "cheese",
        "яичн", "яйцо", "omelette", "греч", "rice", "рис", "chicken", "куриц",
        "пюре", "puree", "kartof", "картоф", "pljeskavica", "ćevap", "ćevapi",
        "salad", "салат", "шницел", "шницель", "gyros", "донер", "донер",
        "kebab", "cevapi", "pasulj", "grašak", "няка", "sarma"
    ]
    if any(w in t for w in food_words):
        return True
    # наличие единиц или дробей
    if detect_explicit_weight(t) is not None:
        return True
    if extract_fraction(t) is not None:
        return True
    return False


# ================================
# PROFILE STORAGE & CALC
# ================================

def get_profile(user_id: str):
    res = supabase_select("profiles", {"user_id": f"eq.{user_id}"})
    return res[0] if res else None


def save_profile(user_id: str, data: dict):
    data["user_id"] = user_id
    data["updated_at"] = datetime.datetime.utcnow().isoformat()
    supabase_upsert("profiles", data)


def get_today_key():
    return datetime.datetime.now().strftime("%Y%m%d")


def get_diary(user_id: str, day: str):
    res = supabase_select("diary_days", {"user_id": f"eq.{user_id}", "day": f"eq.{day}"})
    if res:
        return res[0]
    blank = {"user_id": user_id, "day": day, "total_kcal": 0}
    supabase_insert("diary_days", blank)
    return blank


def update_diary_kcal(user_id: str, day: str, delta_kcal: float):
    d = get_diary(user_id, day)
    new_total = (d.get("total_kcal") or 0) + delta_kcal
    supabase_upsert("diary_days", {
        "user_id": user_id,
        "day": day,
        "total_kcal": new_total
    })
    return new_total


def add_meal_record(user_id: str, day: str, meal_number: int, desc: str, kcal: float):
    supabase_insert("meals", {
        "user_id": user_id,
        "day": day,
        "meal_number": meal_number,
        "description": desc,
        "kcal": kcal,
    })


def parse_profile(text: str):
    t = text.lower()

    def find_int(label_ru: str, label_en: str):
        pattern = rf"{label_ru}:\s*(\d+)|{label_en}:\s*(\d+)"
        m = re.search(pattern, t)
        if not m:
            return None
        return int(m.group(1) or m.group(2))

    age = find_int("возраст", "age")
    height = find_int("рост", "height")
    weight = find_int("вес", "weight")
    goal = find_int("цель", "goal")

    sex = "m"
    if "ж" in t or "f" in t or "female" in t:
        sex = "f"

    if "низк" in t or "low" in t:
        activity = 1.2
    elif "средн" in t or "medium" in t:
        activity = 1.35
    elif "высок" in t or "high" in t:
        activity = 1.6
    else:
        activity = 1.35

    if all([age, height, weight, goal]):
        return {
            "age": age,
            "height": height,
            "weight": float(weight),
            "goal": float(goal),
            "sex": sex,
            "activity_factor": activity,
        }
    return None


def calc_target_kcal(profile: dict | None):
    if not profile:
        return 2000
    if profile["sex"] == "m":
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] + 5
    else:
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] - 161
    tdee = bmr * profile["activity_factor"]
    deficit = tdee * 0.8
    return round(deficit)


# ================================
# TELEGRAM SENDER
# ================================

def send_message(chat_id: str, text: str):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        print("send_message error:", e)


# ================================
# MAIN WEBHOOK
# ================================

@app.route("/", methods=["POST"])
def telegram_webhook():
    data = request.json
    if not data or "message" not in data:
        return "OK"

    msg = data["message"]
    chat_id = str(msg["chat"]["id"])
    text = msg.get("text") or ""

    # Загружаем профиль и язык
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else "ru")
    T = TEXT.get(lang, TEXT["ru"])

    text_stripped = text.strip()

    # -------- /start --------
    if text_stripped.lower() == "/start":
        if not profile:
            # создаём базовый профиль с языком
            save_profile(chat_id, {"lang": lang})
            send_message(chat_id, T["ask_profile"])
        else:
            send_message(chat_id, T["profile_saved"])
        return "OK"

    # -------- Парсинг профиля --------
    parsed_prof = parse_profile(text_stripped)
    if parsed_prof:
        save_profile(chat_id, {"lang": lang, **parsed_prof})
        send_message(chat_id, T["profile_saved"])
        return "OK"

    # -------- Не еда → болталка --------
    if not is_food_message(text_stripped):
        system_prompt = {
            "ru": "Ты дружелюбный ассистент, отвечаешь на русском, кратко и по делу.",
            "en": "You are a friendly assistant, answer in English, clearly and concisely.",
            "sr": "Ti si prijateljski asistent, odgovaraš na srpskom, jasno i sažeto.",
        }.get(lang, "You are a friendly assistant.")
        reply = ask_ai_chat(text_stripped, lang, system_prompt)
        if not reply:
            reply = {
                "ru": "Давай поговорим о питании, тренировках, целях или просто о жизни 😉",
                "en": "Let's talk about nutrition, training, goals or just life 😉",
                "sr": "Hajde da pričamo o ishrani, treningu, ciljevima ili samo o životu 😉",
            }.get(lang, "Let's chat 😉")
        send_message(chat_id, T["not_food"].format(reply))
        return "OK"

    # -------- Режим еды --------
    explicit_kcal = detect_explicit_kcal(text_stripped)
    explicit_weight = detect_explicit_weight(text_stripped)
    fraction = extract_fraction(text_stripped)

    if not explicit_kcal and not explicit_weight and not fraction:
        send_message(chat_id, T["need_details"])
        return "OK"

    # Если пользователь явно указал калории – просто добавляем
    if explicit_kcal:
        kcal = explicit_kcal
    else:
        # Определяем кухню
        cuisine_hint = {
            "ru": "Используй знания о русской и восточноевропейской кухне.",
            "sr": "Koristi znanje o balkanskoj/ srpskoj kuhinji.",
            "en": "Use knowledge of international / US / EU cuisine.",
        }.get(lang, "Use knowledge of international cuisine.")

        prompt = f"{cuisine_hint}\nЕда: {text_stripped}\nНужно оценить калорийность на 100 г."

        base_kcal = ask_ai_kcal(prompt, lang)
        if not base_kcal or base_kcal <= 0:
            send_message(chat_id, T["need_details"])
            return "OK"

        # вес
        if fraction and not explicit_weight:
            # дробь от условной порции 100 г
            weight = fraction * 100.0
        else:
            weight = explicit_weight

        if not weight or weight <= 0:
            send_message(chat_id, T["need_details"])
            return "OK"

        kcal = round(base_kcal * (weight / 100.0))

    # Обновляем дневник
    today = get_today_key()
    new_total = update_diary_kcal(chat_id, today, kcal)

    # Узнаём номер приёма пищи
    meals_today = supabase_select("meals", {"user_id": f"eq.{chat_id}", "day": f"eq.{today}"})
    meal_number = len(meals_today) + 1

    add_meal_record(chat_id, today, meal_number, text_stripped, kcal)

    target = calc_target_kcal(profile)
    left = target - new_total

    reply = (
        f"{T['meal_count'].format(meal_number)}\n"
        f"{text_stripped}\n"
        f"{kcal} ккал\n\n"
        f"{T['daily_total'].format(new_total)}\n"
        f"{T['daily_left'].format(left)}"
    ) if lang == "ru" else (
        f"{T['meal_count'].format(meal_number)}\n"
        f"{text_stripped}\n"
        f"{kcal} kcal\n\n"
        f"{T['daily_total'].format(new_total)}\n"
        f"{T['daily_left'].format(left)}"
    )

    send_message(chat_id, reply)
    return "OK"


@app.route("/", methods=["GET"])
def home():
    return "AI Calories Bot with Supabase is running!"
