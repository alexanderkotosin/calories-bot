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

AI_ENDPOINT = os.environ.get("AI_ENDPOINT")  # https://router.huggingface.co/v1/chat/completions
AI_KEY = os.environ.get("AI_KEY")            # hf_...
AI_MODEL = os.environ.get(
    "AI_MODEL",
    "meta-llama/Meta-Llama-3-8B-Instruct"    # можно переопределить в Render
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

LANG_CHOICES_TEXT = (
    "Choose your language / Выбери язык / Izaberi jezik:\n\n"
    "1️⃣ Русский 🇷🇺\n"
    "2️⃣ English 🇬🇧\n"
    "3️⃣ Srpski 🇷🇸\n\n"
    "Just send 1, 2 or 3 / Просто отправь 1, 2 или 3 / Samo pošalji 1, 2 ili 3."
)

TEXT = {
    "ru": {
        "ask_profile": (
            "Сначала настроим профиль.\n\n"
            "Скопируй этот шаблон, вставь в чат и заполни цифрами:\n\n"
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
        "need_profile_first": "Сначала давай настроим профиль, чтобы я мог считать калории.\n\n" +
                             "Скопируй шаблон и заполни:\n\n" +
                             "Возраст: ___\nРост: ___\nВес: ___\nЦель (вес): ___\nПол: м/ж\n" +
                             "Активность: низкая / средняя / высокая",
    },
    "en": {
        "ask_profile": (
            "Let’s set up your profile first.\n\n"
            "Copy this template, paste it here and fill in the numbers:\n\n"
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
        "need_profile_first": "Let’s set up your profile first so I can track your calories.\n\n"
                             "Copy the template and fill it:\n\n"
                             "Age: ___\nHeight: ___\nWeight: ___\nGoal weight: ___\nSex: m/f\n"
                             "Activity: low / medium / high",
    },
    "sr": {
        "ask_profile": (
            "Hajde prvo da podesimo tvoj profil.\n\n"
            "Kopiraj ovaj šablon, nalepi u chat i popuni brojevima:\n\n"
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
        "need_profile_first": "Prvo da podesimo profil, da bih mogao da pratim kalorije.\n\n"
                             "Kopiraj šablon i popuni:\n\n"
                             "Godine: ___\nVisina: ___\nTežina: ___\nCiljna težina: ___\nPol: m/ž\n"
                             "Aktivnost: niska / srednja / visoka",
    },
}


# ================================
# HUGGINGFACE CHAT WRAPPERS
# ================================

def ask_ai_chat(user_text, lang, system_prompt):
    """
    Общий чат-режим.
    """
    if not AI_ENDPOINT or not AI_KEY:
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
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        print("AI chat error:", e)
        return None


def ask_ai_kcal(prompt, lang):
    """
    Оценка ккал на 100 г.
    """
    if not AI_ENDPOINT or not AI_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    system_prompt = {
        "ru": "Ты нутриционист. Отвечай только числом — сколько ккал в 100 граммах указанной еды.",
        "en": "You are a nutritionist. Answer only with a number: kcal per 100g of the food.",
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


def extract_fraction(text):
    match = re.search(FRACTION_PATTERN, text)
    if not match:
        return None
    num, denom = match.group(0).split("/")
    try:
        return float(num) / float(denom)
    except ZeroDivisionError:
        return None


def detect_explicit_weight(text):
    """
    200 г, 150гр, 250g, 100 ml, 1kg → граммы (условно).
    """
    t = text.lower().replace(",", ".")
    # kg / кг
    kg_match = re.findall(r"(\d+(\.\d+)?)\s*(kg|кг)", t)
    if kg_match:
        val = float(kg_match[0][0])
        return val * 1000

    # g / гр / г / gram
    g_match = re.findall(r"(\d+(\.\d+)?)\s*(g|гр|г|gram)", t)
    if g_match:
        val = float(g_match[0][0])
        return val

    # ml / мl / литр – грубо считаем как граммы
    ml_match = re.findall(r"(\d+(\.\d+)?)\s*(ml|мл|l|литр)", t)
    if ml_match:
        val = float(ml_match[0][0])
        return val

    return None


def detect_explicit_kcal(text):
    """
    Ищем калории. Если есть единицы веса – считаем, что число не калории.
    """
    t = text.lower()
    if any(u in t for u in UNIT_WORDS):
        return None

    match = re.findall(r"(\d+)\s*(ккал|kcal|кк|cal|кал)?", t)
    if not match:
        return None

    val_str, unit = match[-1]
    val = int(val_str)
    if unit:
        return val
    return val


def is_food_message(text):
    t = text.lower()
    food_words = [
        "бурек", "burek", "burger", "бургер", "пиц", "pizza", "сыр", "cheese",
        "яичн", "яйцо", "omelette", "греч", "rice", "рис", "chicken", "куриц",
        "пюре", "puree", "kartof", "картоф", "pljeskavica", "ćevap", "ćevapi",
        "salad", "салат", "шницел", "шницель", "gyros", "донер", "kebab",
        "cevapi", "pasulj", "grašak", "sarma"
    ]
    if any(w in t for w in food_words):
        return True
    if detect_explicit_weight(t) is not None:
        return True
    if extract_fraction(t) is not None:
        return True
    return False


# ================================
# PROFILE STORAGE & CALC
# ================================

def get_profile(user_id):
    res = supabase_select("profiles", {"user_id": f"eq.{user_id}"})
    return res[0] if res else None


def save_profile(user_id, new_data):
    """
    Аккуратно мержим профиль, чтобы не затирать поля.
    """
    existing = get_profile(user_id) or {}
    merged = dict(existing)
    merged.update(new_data)
    merged["user_id"] = user_id
    merged["updated_at"] = datetime.datetime.utcnow().isoformat()
    supabase_upsert("profiles", merged)


def get_today_key():
    return datetime.datetime.now().strftime("%Y%m%d")


def get_diary(user_id, day):
    res = supabase_select("diary_days", {"user_id": f"eq.{user_id}", "day": f"eq.{day}"})
    if res:
        return res[0]
    blank = {"user_id": user_id, "day": day, "total_kcal": 0}
    supabase_insert("diary_days", blank)
    return blank


def update_diary_kcal(user_id, day, delta_kcal):
    d = get_diary(user_id, day)
    new_total = (d.get("total_kcal") or 0) + delta_kcal
    supabase_upsert("diary_days", {
        "user_id": user_id,
        "day": day,
        "total_kcal": new_total
    })
    return new_total


def add_meal_record(user_id, day, meal_number, desc, kcal):
    supabase_insert("meals", {
        "user_id": user_id,
        "day": day,
        "meal_number": meal_number,
        "description": desc,
        "kcal": kcal,
    })


def parse_profile(text):
    t = text.lower()

    def find_int(label_ru, label_en):
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


def calc_target_kcal(profile):
    if not profile:
        return 2000
    if profile.get("sex") == "m":
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] + 5
    else:
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] - 161
    tdee = bmr * profile["activity_factor"]
    deficit = tdee * 0.8
    return round(deficit)


# ================================
# TELEGRAM SENDER
# ================================

def send_message(chat_id, text):
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
    chat = msg.get("chat", {})
    chat_id = str(chat.get("id"))
    text = msg.get("text") or ""
    text_stripped = text.strip()

    # Загружаем профиль (если есть)
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else "ru")
    T = TEXT.get(lang, TEXT["ru"])

    # -------- /start: всегда сначала выбор языка --------
    if text_stripped.lower() == "/start":
        send_message(chat_id, LANG_CHOICES_TEXT)
        return "OK"

    # -------- выбор языка 1/2/3 --------
    if text_stripped in ("1", "2", "3"):
        lang_map = {"1": "ru", "2": "en", "3": "sr"}
        lang = lang_map[text_stripped]
        save_profile(chat_id, {"lang": lang})
        T = TEXT[lang]
        send_message(chat_id, T["ask_profile"])
        return "OK"

    # -------- попытка распарсить профиль --------
    parsed_prof = parse_profile(text_stripped)
    if parsed_prof:
        # сохраняем профиль + язык (если уже был выбран)
        save_profile(chat_id, {"lang": lang, **parsed_prof})
        T = TEXT[lang]
        send_message(chat_id, T["profile_saved"])
        return "OK"

    # после возможного обновления профиля ещё раз загрузим
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else lang)
    T = TEXT.get(lang, TEXT["ru"])

    # проверяем, заполнен ли профиль полностью
    essential_keys = ["age", "height", "weight", "goal", "activity_factor", "sex"]
    has_full_profile = bool(profile and all(profile.get(k) is not None for k in essential_keys))

    # если профиль НЕ заполнен – не болтаем, а просим заполнить
    if not has_full_profile:
        send_message(chat_id, T["need_profile_first"])
        return "OK"

    # -------- дальше можно болтать и считать еду --------

    # если это не еда → режим болталки
    if not is_food_message(text_stripped):
        system_prompt = {
            "ru": "Ты дружелюбный ассистент по питанию и образу жизни. Отвечай кратко, по делу и по-русски.",
            "en": "You are a friendly assistant about nutrition and lifestyle. Answer briefly and clearly in English.",
            "sr": "Ti si prijateljski asistent za ishranu i stil života. Odgovaraj kratko i jasno na srpskom.",
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

    # -------- режим еды --------
    explicit_kcal = detect_explicit_kcal(text_stripped)
    explicit_weight = detect_explicit_weight(text_stripped)
    fraction = extract_fraction(text_stripped)

    if not explicit_kcal and not explicit_weight and not fraction:
        send_message(chat_id, T["need_details"])
        return "OK"

    if explicit_kcal:
        kcal = explicit_kcal
    else:
        cuisine_hint = {
            "ru": "Используй знания о русской и восточноевропейской кухне.",
            "sr": "Koristi znanje o balkanskoj / srpskoj kuhinji.",
            "en": "Use knowledge of international / US / EU cuisine.",
        }.get(lang, "Use knowledge of international cuisine.")

        prompt = f"{cuisine_hint}\nЕда: {text_stripped}\nНужно оценить калорийность на 100 г."

        base_kcal = ask_ai_kcal(prompt, lang)
        if not base_kcal or base_kcal <= 0:
            send_message(chat_id, T["need_details"])
            return "OK"

        if fraction and not explicit_weight:
            weight = fraction * 100.0
        else:
            weight = explicit_weight

        if not weight or weight <= 0:
            send_message(chat_id, T["need_details"])
            return "OK"

        kcal = round(base_kcal * (weight / 100.0))

    # обновляем дневник и записываем приём пищи
    today = get_today_key()
    new_total = update_diary_kcal(chat_id, today, kcal)

    meals_today = supabase_select("meals", {"user_id": f"eq.{chat_id}", "day": f"eq.{today}"})
    meal_number = len(meals_today) + 1

    add_meal_record(chat_id, today, meal_number, text_stripped, kcal)

    target = calc_target_kcal(profile)
    left = target - new_total

    if lang == "ru":
        reply = (
            f"{T['meal_count'].format(meal_number)}\n"
            f"{text_stripped}\n"
            f"{kcal} ккал\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(left)}"
        )
    else:
        reply = (
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
