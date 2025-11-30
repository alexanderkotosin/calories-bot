import os
import json
import datetime
import re
import requests
from flask import Flask, request

# =======================================
# CONFIG
# =======================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

# HuggingFace Inference API endpoint for Mixtral
# Example: https://api-inference.huggingface.co/models/mistralai/Mixtral-8x7B-Instruct-v0.1
AI_ENDPOINT = os.environ.get("AI_ENDPOINT")
AI_KEY = os.environ.get("AI_KEY")

app = Flask(__name__)
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# =======================================
# SUPABASE HELPERS
# =======================================

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
    try:
        r = requests.get(url, headers=supabase_headers(), params=params, timeout=10)
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print("supabase_select error:", e)
        return []


def supabase_insert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        r = requests.post(url, headers=supabase_headers(True), data=json.dumps(data), timeout=10)
        return r.json()
    except Exception as e:
        print("supabase_insert error:", e)
        return []


def supabase_upsert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        r = requests.post(
            url,
            headers={**supabase_headers(True), "Prefer": "resolution=merge-duplicates"},
            data=json.dumps(data),
            timeout=10,
        )
        return r.json()
    except Exception as e:
        print("supabase_upsert error:", e)
        return []


# =======================================
# LANGUAGE PACKS
# =======================================

LANG_CHOICES_TEXT = (
    "Выбери язык / Choose language / Izaberi jezik:\n\n"
    "1️⃣ Русский 🇷🇺\n"
    "2️⃣ English 🇬🇧\n"
    "3️⃣ Srpski 🇷🇸\n"
)

TEXT = {
    "ru": {
        "welcome": "Привет! Чтобы я мог считать калории — давай настроим профиль 👇",
        "profile_template": (
            "Скопируй, вставь и заполни:\n\n"
            "Возраст ___\n"
            "Рост ___\n"
            "Вес ___\n"
            "Цель вес ___\n"
            "Пол м/ж\n"
            "Активность низкая / средняя / высокая\n\n"
            "📌 Объяснение активности:\n"
            "• НИЗКАЯ — сидячая работа, мало шагов (<7000).\n"
            "• СРЕДНЯЯ — 7–12 тыс шагов в день, 2–3 тренировки/нед.\n"
            "• ВЫСОКАЯ — 12k+ шагов, 4+ тренировок/нед или физическая работа."
        ),
        "profile_saved": "Профиль сохранён ✅",
        "need_profile_first": "Похоже, профиль ещё не настроен. Нажми /start и заполни его 👇",
        "meal_count": "Приём пищи №{}",
        "daily_total": "Итого сегодня: {} ккал",
        "daily_left": "Осталось до нормы: {} ккал",
        "need_details": "Я не смог нормально разобрать приём пищи. Опиши ещё раз, простыми словами: что было и примерно сколько.",
        "logging_help": (
            "Как вносить еду, чтобы я считал точнее:\n\n"
            "• Пиши простым языком, без формальностей.\n"
            "• Указывай примерные количества, не нужны точные цифры.\n\n"
            "Примеры:\n"
            "• \"2 ломтика цельнозернового хлеба, 2 яйца, немного сыра, чай без сахара\".\n"
            "• \"Куриная грудка примерно 150–200 г, 150 г риса, салат из огурцов и помидоров,\n"
            "   1 столовая ложка оливкового масла\".\n"
            "• \"Бургер из кафе, средняя картошка фри, 2 чайные ложки кетчупа,\n"
            "   капучино 300 мл с молоком 1,5%, без сахара\".\n\n"
            "Важно:\n"
            "• Учитывай соусы (кетчуп, майонез, йогурт-соусы, масло).\n"
            "• Учитывай напитки с калориями (сладкая газировка, сок, алкоголь, кофе с молоком/сиропом).\n"
            "• Если не знаешь граммы — пиши \"кусок\", \"тарелка\", \"стакан\", \"ложка\" — я оценю по опыту."
        ),
    },

    "en": {
        "welcome": "Hi! Let's set up your profile so I can calculate your calories 👇",
        "profile_template": (
            "Copy, paste and fill:\n\n"
            "Age ___\n"
            "Height ___\n"
            "Weight ___\n"
            "Goal weight ___\n"
            "Sex m/f\n"
            "Activity low / medium / high\n\n"
            "📌 Activity explanation:\n"
            "• LOW — desk job, <7000 steps/day.\n"
            "• MEDIUM — 7–12k steps, 2–3 workouts/week.\n"
            "• HIGH — 12k+ steps, 4+ workouts/week or physical job."
        ),
        "profile_saved": "Profile saved ✅",
        "need_profile_first": "Your profile is not set yet. Send /start 👇",
        "meal_count": "Meal #{}",
        "daily_total": "Total today: {} kcal",
        "daily_left": "Remaining: {} kcal",
        "need_details": "I couldn't properly understand this meal. Describe again in simple words: what and roughly how much.",
        "logging_help": (
            "How to enter food so I can count more accurately:\n\n"
            "• Use simple language.\n"
            "• Approximate amounts are enough, not exact grams.\n\n"
            "Examples:\n"
            "• \"2 slices of whole-grain bread, 2 eggs, a bit of cheese, tea without sugar\".\n"
            "• \"Chicken breast about 150–200 g, 150 g boiled rice, cucumber-tomato salad,\n"
            "   1 tablespoon of olive oil\".\n"
            "• \"Burger from a café, medium fries, 2 teaspoons of ketchup,\n"
            "   cappuccino 300 ml with 1.5% milk, no sugar\".\n\n"
            "Important:\n"
            "• Include sauces (ketchup, mayo, yogurt sauces, oil).\n"
            "• Include drinks with calories (soda, juice, alcohol, coffee with milk/syrup).\n"
            "• If you don't know grams, write \"a slice\", \"a plate\", \"a glass\", \"a spoon\" — "
            "I'll estimate from experience."
        ),
    },

    "sr": {
        "welcome": "Zdravo! Hajde da podesimo profil da mogu da računam kalorije 👇",
        "profile_template": (
            "Kopiraj, nalepi i popuni:\n\n"
            "Godine ___\n"
            "Visina ___\n"
            "Težina ___\n"
            "Ciljna težina ___\n"
            "Pol m/ž\n"
            "Aktivnost niska / srednja / visoka\n\n"
            "📌 Objašnjenje aktivnosti:\n"
            "• NISKA — kancelarijski posao, malo kretanja (<7000 koraka).\n"
            "• SREDNJA — 7–12k koraka, 2–3 treninga nedeljno.\n"
            "• VISOKA — 12k+ koraka, 4+ treninga ili fizički posao."
        ),
        "profile_saved": "Profil sačuvan ✅",
        "need_profile_first": "Profil još nije podešen. Pošalji /start 👇",
        "meal_count": "Obrok #{}",
        "daily_total": "Ukupno danas: {} kcal",
        "daily_left": "Preostalo: {} kcal",
        "need_details": "Nisam najbolje razumeo obrok. Opiši ponovo jednostavno: šta i približno koliko.",
        "logging_help": (
            "Kako da unosiš hranu da bih preciznije računaо kalorije:\n\n"
            "• Piši jednostavnim jezikom.\n"
            "• Dovoljne su približne količine, ne moraju tačni grami.\n\n"
            "Primeri:\n"
            "• \"2 parčeta integralnog hleba, 2 jaja, malo sira, čaj bez šećera\".\n"
            "• \"Pileća prsa oko 150–200 g, 150 g kuvanog pirinča, salata od krastavca i paradajza,\n"
            "   1 supena kašika maslinovog ulja\".\n"
            "• \"Burger iz lokala, srednja porcija pomfrita, 2 kašičice kečapa,\n"
            "   kapućino 300 ml sa mlekom 1,5%, bez šećera\".\n\n"
            "Važno:\n"
            "• Računaj i soseve (kečap, majonez, jogurt-sosovi, ulje).\n"
            "• Računaj pića sa kalorijama (gazirana pića, sokovi, alkohol, kafa sa mlekom/sirupom).\n"
            "• Ako ne znaš grame — napiši \"parče\", \"tanjir\", \"čaša\", \"kašika\" — proceniću po iskustvu."
        ),
    }
}

# =======================================
# HUGGINGFACE INFERENCE HELPER
# =======================================

def call_hf_inference(prompt: str):
    """
    Универсальный хелпер для Mixtral через Inference API.
    """
    if not AI_ENDPOINT or not AI_KEY:
        print("HF config missing")
        return None

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 512,
            "temperature": 0.4,
            "return_full_text": False,
        },
    }

    try:
        r = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=40)
        data = r.json()

        if isinstance(data, list) and data and "generated_text" in data[0]:
            return data[0]["generated_text"]

        if isinstance(data, dict) and "error" in data:
            print("HF API ERROR:", data["error"])
            return None

        print("HF unexpected response:", data)
        return None

    except Exception as e:
        print("HF REQUEST ERROR:", e)
        return None


# =======================================
# PROFILE STORAGE & PARSING
# =======================================

def get_profile(user_id):
    res = supabase_select("profiles", {"user_id": f"eq.{user_id}"})
    return res[0] if res else None


def save_profile(user_id, new_data):
    existing = get_profile(user_id) or {}
    merged = {**existing, **new_data}
    merged["user_id"] = user_id
    merged["updated_at"] = datetime.datetime.utcnow().isoformat()
    supabase_upsert("profiles", merged)


def parse_profile(text: str):
    t = text.lower()

    def find_value(keywords):
        for word in keywords:
            pattern = rf"{word}\s+(\d+)"
            m = re.search(pattern, t)
            if m:
                return int(m.group(1))
        return None

    age = find_value(["возраст", "age", "godine"])
    height = find_value(["рост", "height", "visina"])
    weight = find_value(["вес", "weight", "težina", "tezina"])
    goal = find_value(["цель", "goal", "cilj", "ciljna"])

    sex = "m"
    if any(x in t for x in [" ж", " f", "female", "ž", " жен", "жен "]):
        sex = "f"

    if "низк" in t or "low" in t or "niska" in t:
        activity = 1.2
    elif "средн" in t or "medium" in t or "srednja" in t:
        activity = 1.35
    elif "высок" in t or "high" in t or "visoka" in t:
        activity = 1.6
    else:
        activity = None

    if all([age, height, weight, goal, activity]):
        return {
            "age": age,
            "height": height,
            "weight": float(weight),
            "goal": float(goal),
            "sex": sex,
            "activity_factor": activity,
        }

    return None


# =======================================
# NORM CALC & DIARY
# =======================================

def calc_target_kcal(profile):
    if not profile:
        return 2000

    if profile["sex"] == "m":
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] + 5
    else:
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] - 161

    tdee = bmr * profile["activity_factor"]
    deficit = tdee * 0.8
    return round(deficit)


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
        "total_kcal": new_total,
    })
    return new_total


def add_meal_record(user_id, day, meal_number, text, kcal):
    supabase_insert("meals", {
        "user_id": user_id,
        "day": day,
        "meal_number": meal_number,
        "description": text,
        "kcal": kcal,
    })


# =======================================
# FOOD DETECTION (решение №1)
# =======================================

def is_food_message(text: str) -> bool:
    if not text:
        return False

    t = text.lower()

    if re.search(r"\d", t):
        return True

    food_words = [
        "есть", "ел", "съел", "поел", "обед", "завтрак", "ужин", "перекус",
        "куриц", "chicken", "meat", "fish", "рыба", "лосось", "tuna",
        "яйц", "egg", "сыр", "cheese", "йогурт", "yogurt",
        "хлеб", "булка", "батон",
        "рис", "rice", "греч", "овсян",
        "паста", "макарон", "spaghetti", "noodles",
        "пицц", "pizza",
        "burger", "бургер",
        "кебаб", "kebab", "шаурма",
        "кофе", "coffee", "латте", "капучино",
        "чай", "tea", "сок", "juice",
        "beer", "пиво", "wine", "вино",
        "соус", "sauce", "кетчуп", "майонез",
        "фрук", "овощ", "салат",
    ]

    if any(w in t for w in food_words):
        return True

    return False


# =======================================
# AI MEAL ANALYSIS (TOTAL_KCAL: XXX)
# =======================================

def ai_meal_analysis(meal_text: str, lang: str) -> str:
    if lang == "en":
        system_prompt = (
            "You are a friendly nutritionist. You receive a natural language description of a meal.\n"
            "Your tasks:\n"
            "1) Break the meal into 2–7 main components (food items).\n"
            "2) For each component, give an approximate kcal value.\n"
            "3) At the VERY END, on a separate line, write the TOTAL calories in the exact format:\n"
            "TOTAL_KCAL: XXX\n"
            "where XXX is an integer.\n\n"
            "Use realistic values. A typical single-person meal is often 200–1200 kcal, "
            "but if the user clearly describes a big amount of food or the whole day, higher totals are acceptable.\n"
            "Do not add any text after the TOTAL_KCAL line."
        )
    elif lang == "sr":
        system_prompt = (
            "Ti si prijateljski nutricionista. Dobijaš opis obroka na prirodnom jeziku.\n"
            "Tvoj zadatak:\n"
            "1) Podeli obrok na 2–7 glavnih stavki.\n"
            "2) Za svaku stavku daj približnu kalorijsku vrednost (kcal).\n"
            "3) NA SAMOM KRAJU, u posebnoj liniji, napiši ukupan broj kalorija u tačnom formatu:\n"
            "TOTAL_KCAL: XXX\n"
            "gde je XXX ceo broj.\n\n"
            "Koristi realne vrednosti. Običan obrok je 200–1200 kcal, ali ako korisnik opiše veliku količinu "
            "ili ceo dan, dozvoljeno je više.\n"
            "Nemoj pisati nikakav tekst posle linije TOTAL_KCAL."
        )
    else:
        system_prompt = (
            "Ты — дружелюбный нутриционист. Тебе дают описание приёма пищи обычным языком.\n"
            "Твоя задача:\n"
            "1) Разбить приём пищи на 2–7 основных продуктов/блюд.\n"
            "2) Для каждого указать примерную калорийность (ккал).\n"
            "3) В САМОМ КОНЦЕ отдельной строкой написать общий итог строго в формате:\n"
            "TOTAL_KCAL: XXX\n"
            "где XXX — целое число.\n\n"
            "Используй реалистичные значения. Обычный приём пищи одного человека — около 200–1200 ккал, "
            "но если явно описано много еды или целый день, допустимо больше.\n"
            "После строки TOTAL_KCAL НИЧЕГО больше не пиши."
        )

    prompt = f"{system_prompt}\n\nТекст пользователя:\n{meal_text}"
    response = call_hf_inference(prompt)
    return response or ""


def extract_total_kcal(ai_text: str) -> int:
    if not ai_text:
        return None

    m = re.search(r"TOTAL_KCAL:\s*(\d+(?:\.\d+)?)", ai_text, flags=re.IGNORECASE)
    if not m:
        print("NO TOTAL_KCAL IN AI OUTPUT:", ai_text)
        return None

    try:
        return int(float(m.group(1)))
    except Exception as e:
        print("TOTAL_KCAL PARSE ERROR:", e, ai_text)
        return None


def build_meal_reply(lang: str, meal_number: int, ai_text: str, new_total: int, left: int) -> str:
    T = TEXT[lang]
    # убираем строку TOTAL_KCAL из текста для красоты
    lines = ai_text.strip().splitlines()
    cleaned_lines = [ln for ln in lines if not ln.strip().upper().startswith("TOTAL_KCAL:")]
    explanation = "\n".join(cleaned_lines).strip()

    reply = (
        f"{T['meal_count'].format(meal_number)}\n\n"
        f"{explanation}\n\n"
        f"{T['daily_total'].format(new_total)}\n"
        f"{T['daily_left'].format(left)}"
    )
    return reply


# =======================================
# PROFILE EXPLANATION
# =======================================

def build_profile_explanation(profile, lang: str) -> str:
    age = int(profile["age"])
    height = int(profile["height"])
    weight = int(profile["weight"])
    goal = int(profile["goal"])

    if profile["sex"] == "m":
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] + 5
    else:
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] - 161

    tdee = bmr * profile["activity_factor"]
    target = calc_target_kcal(profile)

    if lang == "en":
        text = (
            f"{TEXT['en']['profile_saved']}\n\n"
            f"Here is what I calculated from your data:\n"
            f"Age: {age}, height: {height} cm, weight: {weight} kg, goal: {goal} kg.\n\n"
            f"1️⃣ BMR (basal metabolism) ≈ {round(bmr)} kcal — what your body burns at rest.\n"
            f"2️⃣ With your activity, your daily expenditure (TDEE) ≈ {round(tdee)} kcal.\n"
            f"3️⃣ For healthy fat loss, I use ~20% calorie deficit.\n"
            f"➡️ Your working daily target ≈ {target} kcal.\n\n"
            "Physics is simple:\n"
            "- If you regularly eat ABOVE your target, the extra energy is stored as fat.\n"
            "- If you eat a bit BELOW your target, your body takes the difference from fat stores.\n\n"
            "From now on, I’ll compare your daily total with this target and show whether you’re in deficit,\n"
            "around maintenance, or in surplus. No magic, just numbers and a bit of support 🙂"
        )
    elif lang == "sr":
        text = (
            f"{TEXT['sr']['profile_saved']}\n\n"
            f"Evo šta sam izračunao na osnovu tvojih podataka:\n"
            f"Godine: {age}, visina: {height} cm, težina: {weight} kg, cilj: {goal} kg.\n\n"
            f"1️⃣ Bazalni metabolizam (BMR) ≈ {round(bmr)} kcal — koliko trošiš u mirovanju.\n"
            f"2️⃣ Sa tvojom aktivnošću, dnevna potrošnja (TDEE) ≈ {round(tdee)} kcal.\n"
            f"3️⃣ Za zdravo mršavljenje koristim ~20% kalorijskog deficita.\n"
            f"➡️ Tvoja radna dnevna norma ≈ {target} kcal.\n\n"
            "Logika je jednostavna:\n"
            "- Ako stalno jedeš IZNAD norme, višak energije se skladišti kao mast.\n"
            "- Ako jedeš malo ISPOD norme, telo uzima razliku iz rezervi.\n\n"
            "Od sada ću upoređivati tvoj dnevni zbir sa ovom normom i javljati da li si u deficitu,\n"
            "oko održavanja ili u višku. Nema magije, samo brojevi i malo podrške 🙂"
        )
    else:
        text = (
            f"{TEXT['ru']['profile_saved']}\n\n"
            f"Смотри, что я посчитал по твоим данным:\n"
            f"Возраст: {age} лет, рост: {height} см, вес: {weight} кг, цель: {goal} кг.\n\n"
            f"1️⃣ Базовый обмен (BMR) ≈ {round(bmr)} ккал — столько ты тратишь в покое.\n"
            f"2️⃣ С учётом активности твой расход (TDEE) ≈ {round(tdee)} ккал в день.\n"
            f"3️⃣ Для комфортного снижения веса я заложил ~20% дефицит.\n"
            f"➡️ Твоя рабочая дневная норма ≈ {target} ккал.\n\n"
            "Физика простая:\n"
            "- если стабильно есть ВЫШЕ этой нормы — профицит энергии уходит в жир;\n"
            "- если стабильно есть ЧУТЬ НИЖЕ нормы — организм добирает из запасов, и вес падает.\n\n"
            "Дальше я буду сравнивать твой дневной итог с этой нормой и подсказывать, что происходит —\n"
            "держишь дефицит, вышел в ноль или слегка перебрал. Никакой магии, только цифры и немного юмора 🙂"
        )

    return text


# =======================================
# TELEGRAM SENDER
# =======================================

def send_message(chat_id, text):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        print("send_message error:", e)


# =======================================
# MAIN WEBHOOK
# =======================================

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

    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else "ru")
    if lang not in TEXT:
        lang = "ru"
    T = TEXT[lang]

    # /start -> choose language
    if text_stripped.lower().startswith("/start"):
        send_message(chat_id, LANG_CHOICES_TEXT)
        return "OK"

    # language selection
    if text_stripped in ("1", "2", "3"):
        lang_map = {"1": "ru", "2": "en", "3": "sr"}
        lang = lang_map[text_stripped]
        save_profile(chat_id, {"lang": lang})
        T = TEXT[lang]
        send_message(chat_id, T["welcome"])
        send_message(chat_id, T["profile_template"])
        return "OK"

    # profile parsing
    parsed = parse_profile(text_stripped)
    if parsed:
        parsed["lang"] = lang
        save_profile(chat_id, parsed)
        profile = get_profile(chat_id)
        lang = profile.get("lang", "ru")
        if lang not in TEXT:
            lang = "ru"
        explanation = build_profile_explanation(profile, lang)
        send_message(chat_id, explanation)
        send_message(chat_id, TEXT[lang]["logging_help"])
        return "OK"

    # reload profile
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else "ru")
    if lang not in TEXT:
        lang = "ru"
    T = TEXT[lang]

    # check profile completeness
    essential = ["age", "height", "weight", "goal", "activity_factor", "sex"]
    has_full_profile = bool(profile and all(profile.get(k) is not None for k in essential))

    if not has_full_profile:
        send_message(chat_id, T["need_profile_first"])
        send_message(chat_id, T["profile_template"])
        return "OK"

    # if message not recognized as food -> show instructions
    if not is_food_message(text_stripped):
        send_message(chat_id, TEXT[lang]["logging_help"])
        return "OK"

    # FOOD MODE: call AI
    ai_text = ai_meal_analysis(text_stripped, lang)
    total_kcal = extract_total_kcal(ai_text)

    if not ai_text or not total_kcal or total_kcal <= 0:
        send_message(chat_id, T["need_details"])
        send_message(chat_id, TEXT[lang]["logging_help"])
        return "OK"

    kcal = int(total_kcal)

    today = get_today_key()
    new_total = update_diary_kcal(chat_id, today, kcal)
    meals_today = supabase_select("meals", {"user_id": f"eq.{chat_id}", "day": f"eq.{today}"})
    meal_number = len(meals_today) + 1
    add_meal_record(chat_id, today, meal_number, text_stripped, kcal)

    target = calc_target_kcal(profile)
    left = target - new_total

    reply = build_meal_reply(lang, meal_number, ai_text, new_total, left)

    if new_total > target:
        over = new_total - target
        if lang == "en":
            extra = (
                f"\n\nToday you went about {over} kcal over your daily target.\n"
                "Not a disaster, but if it happens often, weight will slowly creep up.\n"
                "Tip: tomorrow you can make a soft minus (100–200 kcal below target) "
                "by cutting sweets/snacks and moving a bit more — no starvation needed 🙂"
            )
        elif lang == "sr":
            extra = (
                f"\n\nDanas si otišao oko {over} kcal iznad svoje dnevne norme.\n"
                "Nije smak sveta, ali ako se često ponavlja, kilaža polako raste.\n"
                "Savet: sutra napravi mali minus (100–200 kcal ispod norme), "
                "smanji slatkiše/grickalice i ubaci malo više kretanja — bez izgladnjivanja 🙂"
            )
        else:
            extra = (
                f"\n\nСегодня ты вышел примерно на {over} ккал выше своей дневной нормы.\n"
                "Не катастрофа, но если так делать регулярно, вес начнёт ползти вверх.\n"
                "Совет: завтра можно сделать мягкий минус (на 100–200 ккал ниже нормы) "
                "за счёт сладкого и перекусов и добавить чуть больше движения — без жёсткого голода 🙂"
            )
        reply += extra

    send_message(chat_id, reply)
    return "OK"


# =======================================
# HEALTHCHECK
# =======================================

@app.route("/", methods=["GET"])
def home():
    return "AI Calories Bot with Mixtral is running!"
