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
AI_ENDPOINT = os.environ.get("AI_ENDPOINT")               # HuggingFace endpoint
AI_KEY = os.environ.get("AI_KEY")                         # HuggingFace key

# Telegram API
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = Flask(__name__)


# ================================
# SUPABASE REQUEST WRAPPER
# ================================

def supabase_select(table, match):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    response = requests.get(url, headers=headers, params={"select": "*", **match})
    return response.json()


def supabase_upsert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    return response.json()


def supabase_insert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    return response.json()


# ================================
# LANGUAGE PACKS
# ================================

TEXT = {
    "ru": {
        "ask_profile": (
            "Отлично! Вот шаблон профиля.\n"
            "Скопируйте, вставьте и заполните цифрами:\n\n"
            "Возраст: ___\n"
            "Рост: ___\n"
            "Вес: ___\n"
            "Цель (вес): ___\n"
            "Пол: м/ж\n"
            "Активность: низкая / средняя / высокая\n"
        ),
        "profile_saved": "Профиль сохранён! Можете вносить приёмы пищи.",
        "need_details": "Мне нужно уточнение — сколько примерно это весит в граммах?",
        "meal_count": "Приём пищи №{}",
        "daily_total": "Съедено за день: {} ккал",
        "daily_left": "Осталось до лимита: {} ккал",
        "not_food": "Это не похоже на еду. Но я могу поболтать 😊\n\n{}",
    },

    "en": {
        "ask_profile": (
            "Great! Here is your profile template.\n"
            "Copy, paste, and fill in the numbers:\n\n"
            "Age: ___\n"
            "Height: ___\n"
            "Weight: ___\n"
            "Goal weight: ___\n"
            "Sex: m/f\n"
            "Activity: low / medium / high\n"
        ),
        "profile_saved": "Profile saved! You can now enter meals.",
        "need_details": "I need clarification — how many grams approximately?",
        "meal_count": "Meal #{}",
        "daily_total": "Total eaten today: {} kcal",
        "daily_left": "Remaining today: {} kcal",
        "not_food": "This doesn’t look like food. But we can chat 😄\n\n{}",
    },

    "sr": {
        "ask_profile": (
            "Odlično! Evo šablona profila.\n"
            "Kopirajte, nalepite i popunite brojevima:\n\n"
            "Godine: ___\n"
            "Visina: ___\n"
            "Težina: ___\n"
            "Ciljna težina: ___\n"
            "Pol: m/ž\n"
            "Aktivnost: niska / srednja / visoka\n"
        ),
        "profile_saved": "Profil sačuvan! Sada možete unositi obroke.",
        "need_details": "Treba mi pojašnjenje — koliko otprilike to ima grama?",
        "meal_count": "Obrok #{}",
        "daily_total": "Ukupno danas: {} kcal",
        "daily_left": "Preostalo danas: {} kcal",
        "not_food": "Ovo ne liči na hranu. Ali možemo da ćaskamo 😄\n\n{}",
    }
}


# ================================
# AI REQUESTS (HuggingFace)
# ================================

def ask_ai(prompt):
    headers = {"Authorization": f"Bearer {AI_KEY}"}
    payload = {"inputs": prompt, "temperature": 0.4}
    r = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=30)
    try:
        return r.json()[0]["generated_text"]
    except:
        return None


# ================================
# FOOD DETECTION LOGIC
# ================================

UNIT_WORDS = [
    "г", "гр", "грам", "gram", "g", "ml", "мл", "литр", "l", "kg", "кг"
]

FRACTION_PATTERN = r"(\d+/\d+)"


def extract_fraction(text):
    match = re.search(FRACTION_PATTERN, text)
    if not match:
        return None
    num, denom = match.group(0).split("/")
    return float(num) / float(denom)


def detect_explicit_weight(text):
    # finds numbers with units
    matches = re.findall(r"(\d+)\s*(g|гр|г|gram|ml|мл|kg|кг)", text.lower())
    if matches:
        num, unit = matches[0]
        return float(num)
    return None


def detect_explicit_kcal(text):
    # find "300", "300 kcal", "300 ккал"
    kcal_match = re.findall(r"(\d+)\s*(kcal|ккал|кал|к|кк)?", text.lower())
    if kcal_match:
        # choose last number
        val = int(kcal_match[-1][0])
        # if unit missing AND there are units for weight in text → ignore
        if any(u in text.lower() for u in UNIT_WORDS):
            return None
        return val
    return None


def is_food_message(text):
    # has food keywords
    food_words = ["ябл", "бурек", "burger", "пиц", "cheese", "meat", "плов", "сарма",
                  "pljeskavica", "ćevapi", "meso", "kuvano", "греч", "яичн", "chicken"]
    if any(w in text.lower() for w in food_words):
        return True
    # has units or fractions
    if detect_explicit_weight(text) is not None:
        return True
    if extract_fraction(text) is not None:
        return True
    return False


# ================================
# PROFILE STORAGE
# ================================

def get_profile(user_id):
    res = supabase_select("profiles", {"user_id": f"eq.{user_id}"})
    return res[0] if res else None


def save_profile(user_id, data):
    data["user_id"] = user_id
    supabase_upsert("profiles", data)


# ================================
# DIARY STORAGE
# ================================

def get_today():
    return datetime.datetime.now().strftime("%Y%m%d")


def get_diary(user_id, day):
    res = supabase_select("diary_days", {"user_id": f"eq.{user_id}", "day": f"eq.{day}"})
    if res:
        return res[0]
    # create if missing
    blank = {"user_id": user_id, "day": day, "total_kcal": 0}
    supabase_insert("diary_days", blank)
    return blank


def update_diary(user_id, day, kcal):
    d = get_diary(user_id, day)
    new_total = d["total_kcal"] + kcal
    supabase_upsert("diary_days", {
        "user_id": user_id,
        "day": day,
        "total_kcal": new_total
    })
    return new_total


def add_meal_record(user_id, day, number, desc, kcal):
    supabase_insert("meals", {
        "user_id": user_id,
        "day": day,
        "meal_number": number,
        "description": desc,
        "kcal": kcal
    })


# ================================
# PROFILE PARSING
# ================================

def parse_profile(text):
    lines = text.lower()

    def find(pattern):
        m = re.search(pattern, lines)
        if m:
            return m.group(1)
        return None

    age = find(r"возраст:\s*(\d+)|age:\s*(\d+)")
    height = find(r"рост:\s*(\d+)|height:\s*(\d+)")
    weight = find(r"вес:\s*(\d+)|weight:\s*(\d+)")
    goal = find(r"цель.*:\s*(\d+)|goal.*:\s*(\d+)")

    sex = "m" if "м" in lines or "male" in lines else "f"

    if "низ" in lines or "low" in lines:
        activity = 1.2
    elif "сред" in lines or "medium" in lines:
        activity = 1.35
    else:
        activity = 1.6

    if all([age, height, weight, goal]):
        return {
            "age": int(age),
            "height": int(height),
            "weight": float(weight),
            "goal": float(goal),
            "sex": sex,
            "activity_factor": activity
        }
    return None


def calc_target_kcal(profile):
    # Mifflin-St Jeor
    if profile["sex"] == "m":
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] + 5
    else:
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] - 161

    tdee = bmr * profile["activity_factor"]
    deficit = tdee * 0.8  # 20% дефицит
    return round(deficit)


# ================================
# TELEGRAM RESPONSE
# ================================

def send_message(chat_id, text):
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })


# ================================
# MAIN LOGIC
# ================================

@app.route("/", methods=["POST"])
def webhook():
    data = request.json

    if "message" not in data:
        return "OK"

    msg = data["message"]
    chat_id = str(msg["chat"].get("id"))
    text = msg.get("text", "")

    # 1. Load profile
    profile = get_profile(chat_id)
    lang = profile["lang"] if profile and profile.get("lang") else "ru"
    T = TEXT[lang]

    # 2. If message looks like profile template
    parsed = parse_profile(text)
    if parsed:
        save_profile(chat_id, {"lang": lang, **parsed})
        send_message(chat_id, T["profile_saved"])
        return "OK"

    # 3. If message is not food → chat mode
    if not is_food_message(text):
        # ask HF for general chat
        response = ask_ai(f"Reply in {lang}. User said: {text}")
        send_message(chat_id, T["not_food"].format(response))
        return "OK"

    # 4. Food mode
    explicit_kcal = detect_explicit_kcal(text)
    explicit_weight = detect_explicit_weight(text)
    fraction = extract_fraction(text)

    # If ambiguous → request clarification
    if not explicit_kcal and not explicit_weight and not fraction:
        send_message(chat_id, T["need_details"])
        return "OK"

    # Compute kcal
    if explicit_kcal:
        kcal = explicit_kcal
    else:
        # Ask AI for base kcal per 100g
        cuisine_hint = {
            "ru": "Use Russian/Eastern European cuisine database.",
            "sr": "Use Balkan/Serbian cuisine database.",
            "en": "Use international/US/EU cuisine database."
        }[lang]

        prompt = (
            f"{cuisine_hint}\n"
            f"Estimate calories per 100g for food: {text}.\n"
            f"Answer ONLY with a number."
        )

        base_kcal_str = ask_ai(prompt)
        try:
            base_kcal = float(re.findall(r"\d+", base_kcal_str)[0])
        except:
            send_message(chat_id, T["need_details"])
            return "OK"

        if fraction:
            weight = fraction * 100  # условно, ИИ оценивает базу на 100g
        else:
            weight = explicit_weight

        if not weight:
            send_message(chat_id, T["need_details"])
            return "OK"

        kcal = round(base_kcal * (weight / 100))

    # Update diary
    today = get_today()
    diary_total = update_diary(chat_id, today, kcal)

    # Count meals
    meals_today = supabase_select("meals", {
        "user_id": f"eq.{chat_id}",
        "day": f"eq.{today}"
    })
    meal_number = len(meals_today) + 1

    add_meal_record(chat_id, today, meal_number, text, kcal)

    # Calc target kcal
    target = calc_target_kcal(profile) if profile else 2000
    left = target - diary_total

    reply = (
        f"{T['meal_count'].format(meal_number)}\n"
        f"{text}\n"
        f"{kcal} kcal\n\n"
        f"{T['daily_total'].format(diary_total)}\n"
        f"{T['daily_left'].format(left)}"
    )

    send_message(chat_id, reply)
    return "OK"


@app.route("/", methods=["GET"])
def home():
    return "AI Calories Bot with Supabase is running!"

