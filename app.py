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

# HuggingFace Inference API endpoint
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
    except:
        return []


def supabase_insert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        r = requests.post(url, headers=supabase_headers(True), data=json.dumps(data), timeout=10)
        return r.json()
    except:
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
    except:
        return []


# =======================================
# LANGUAGE PACKS (с исправленной локализацией)
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
        "profile_saved": "Профиль сохранён ✅ Отлично, теперь просто отправляй, что ты съел!",
        "need_profile_first": "Похоже, профиль ещё не настроен. Нажми /start и заполни его 👇",
        "meal_count": "Приём пищи №{}",
        "daily_total": "Итого сегодня: {} ккал",
        "daily_left": "Осталось до нормы: {} ккал",
        "need_details": "Опиши, пожалуйста, что было на тарелке и примерно сколько.",
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
        "profile_saved": "Profile saved ✅ Now just send what you ate!",
        "need_profile_first": "Your profile is not set yet. Send /start 👇",
        "meal_count": "Meal #{}",
        "daily_total": "Total today: {} kcal",
        "daily_left": "Remaining: {} kcal",
        "need_details": "Please describe what was on the plate and roughly how much.",
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
        "profile_saved": "Profil sačuvan ✅ Pošalji šta si jeo!",
        "need_profile_first": "Profil još nije podešen. Pošalji /start 👇",
        "meal_count": "Obrok #{}",
        "daily_total": "Ukupno danas: {} kcal",
        "daily_left": "Preostalo: {} kcal",
        "need_details": "Opiši jednostavno šta si jeo i približnu količinu.",
    }
}

# =======================================
# UNIVERSAL HUGGINGFACE INFERENCE CALL
# =======================================

def call_hf_inference(prompt: str):
    """
    Универсальный хелпер для Mixtral через Inference API.
    """
    if not AI_ENDPOINT or not AI_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    payload = {"inputs": prompt}

    try:
        r = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=40)
        data = r.json()

        if isinstance(data, list) and "generated_text" in data[0]:
            return data[0]["generated_text"]

        if isinstance(data, dict) and "error" in data:
            print("HF API ERROR:", data["error"])
            return None

        return str(data)

    except Exception as e:
        print("HF REQUEST ERROR:", e)
        return None
# =======================================
# PROFILE STORAGE
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


# =======================================
# PROFILE PARSER
# =======================================

def parse_profile(text: str):
    """
    Мы убрали двоеточия — бот просто ищет числа в строке,
    ориентируясь на ключевые слова.
    """

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

    # SEX
    sex = "m"
    if any(x in t for x in ["ж", "f", "female", "ž"]):
        sex = "f"

    # ACTIVITY
    if "низк" in t or "low" in t or "niska" in t:
        activity = 1.2
    elif "средн" in t or "medium" in t or "srednja" in t:
        activity = 1.35
    elif "высок" in t or "high" in t or "visoka" in t:
        activity = 1.6
    else:
        activity = None  # чтобы бот снова попросил заполнить

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
# TDEE / TARGET NORM CALCULATION
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


# =======================================
# DIARY STORAGE
# =======================================

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


def add_meal_record(user_id, day, meal_number, text, kcal):
    supabase_insert("meals", {
        "user_id": user_id,
        "day": day,
        "meal_number": meal_number,
        "description": text,
        "kcal": kcal,
    })


# =======================================
# FOOD DETECTION 2.0 (решение №1)
# =======================================

def is_food_message(text: str) -> bool:
    """
    ЛОГИКА: почти всё считаем едой, кроме команд и профиля.
    Если есть хоть одно число или хоть одно слово о еде → это еда.
    """

    if not text:
        return False

    t = text.lower()

    # Есть хотя бы одно число → считаем едой
    if re.search(r"\d", t):
        return True

    # Слова-индикаторы еды
    food_words = [
        "есть", "ел", "съел", "поел", "обед", "завтрак", "ужин", "перекус",
        "куриц", "chicken", "meat", "fish", "рыба", "лосось", "tuna",
        "яйц", "egg", "сыр", "cheese", "йогурт", "yogurt",
        "хлеб", "булка", "батон",
        "рис", "rice", "греч", "овсян",
        "паста", "макарон", "spaghetti",
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
# AI — MEAL ANALYSIS VIA MIXTRAL
# =======================================

def ai_meal_analysis(meal_text: str, lang: str) -> str:
    """
    Запрос к Mixtral, который разбирает еду по-продуктово,
    считает примерные калории и формирует структурированный ответ,
    похожий на ChatGPT-стиль.
    """

    system_ru = (
        "Ты — нутриционист. Разбери приём пищи, который прислал пользователь. "
        "Определи продукты и приблизительные порции, даже если они указаны не точно. "
        "Укажи примерные калории для каждого продукта и общий итог.\n"
        "Всегда используй реалистичные значения. "
        "Для обычного блюда одного человека итог обычно 200–1200 ккал, "
        "но если пользователь явно описывает большой объём (много еды или весь день за раз), "
        "разрешено больше — НЕ придумывай лишнее.\n"
        "Структура ответа:\n"
        "1) Список продуктов: продукт — оценка калорий.\n"
        "2) ИТОГО: X ккал.\n"
        "Пиши дружелюбно, но чётко."
    )

    system_en = (
        "You are a nutritionist. Break down the user's meal into individual components. "
        "Estimate calories per item and total calories. "
        "Use realistic values. A normal single-person meal is usually 200–1200 kcal, "
        "but if the user clearly describes a large amount of food or an entire day, higher values are allowed. "
        "Do NOT hallucinate.\n\n"
        "Response structure:\n"
        "1) List of items: item — kcal estimate.\n"
        "2) TOTAL.\n"
        "Friendly but concise."
    )

    system_sr = (
        "Ti si nutricionista. Analiziraj obrok koji je korisnik poslao. "
        "Razdvoji ga na stavke, proceni kalorije za svaku i ukupno. "
        "Koristi realne vrednosti. Običan obrok je 200–1200 kcal, "
        "ali ako korisnik opiše veliku količinu hrane ili ceo dan, može i više. "
        "Ne izmišljaj.\n\n"
        "Struktura:\n"
        "1) Stavke i kalorije.\n"
        "2) UKUPNO.\n"
        "Piši jasno i prijateljski."
    )

    system_prompt = {
        "ru": system_ru,
        "en": system_en,
        "sr": system_sr,
    }.get(lang, system_ru)

    full_prompt = f"{system_prompt}\n\nТекст пользователя:\n{meal_text}"

    response = call_hf_inference(full_prompt)
    return response or ""


# =======================================
# EXTRACT Kcal FROM MIXTRAL OUTPUT
# =======================================

def extract_total_kcal(ai_text: str) -> int:
    """
    Извлекает итог калорий из текста ИИ.
    Ищем такие варианты:
    - 'ИТОГО: 530 ккал'
    - 'TOTAL: 850 kcal'
    - 'Total ~1200 kcal'
    """

    if not ai_text:
        return None

    patterns = [
        r"итого[:,\s]*~?\s*(\d+)",
        r"итого[:,\s]*(\d+)",
        r"total[:,\s]*~?\s*(\d+)",
        r"total[:,\s]*(\d+)",
        r"ukupno[:,\s]*(\d+)",
    ]

    for p in patterns:
        m = re.search(p, ai_text.lower())
        if m:
            try:
                return int(m.group(1))
            except:
                pass

    return None


# =======================================
# FINAL MEAL TEXT BUILDER
# =======================================

def build_meal_reply(lang: str, meal_number: int, ai_text: str, total_kcal: int, new_total: int, left: int):
    T = TEXT[lang]

    if lang == "ru":
        txt = (
            f"{T['meal_count'].format(meal_number)}\n\n"
            f"{ai_text}\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(left)}"
        )
    elif lang == "en":
        txt = (
            f"{T['meal_count'].format(meal_number)}\n\n"
            f"{ai_text}\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(left)}"
        )
    else:  # srpski
        txt = (
            f"{T['meal_count'].format(meal_number)}\n\n"
            f"{ai_text}\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(left)}"
        )

    return txt

# =======================================
# PROFILE EXPLANATION TEXT
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

    # текущий профиль (может быть None)
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else "ru")
    if lang not in TEXT:
        lang = "ru"
    T = TEXT[lang]

    # /start — выбор языка
    if text_stripped.lower().startswith("/start"):
        send_message(chat_id, LANG_CHOICES_TEXT)
        return "OK"

    # выбор языка
    if text_stripped in ("1", "2", "3"):
        lang_map = {"1": "ru", "2": "en", "3": "sr"}
        lang = lang_map[text_stripped]
        save_profile(chat_id, {"lang": lang})
        T = TEXT[lang]
        send_message(chat_id, T["welcome"])
        send_message(chat_id, T["profile_template"])
        return "OK"

    # попытка распарсить профиль
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
        return "OK"

    # обновим профиль ещё раз
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else "ru")
    if lang not in TEXT:
        lang = "ru"
    T = TEXT[lang]

    # проверка, что профиль полный
    essential = ["age", "height", "weight", "goal", "activity_factor", "sex"]
    has_full_profile = bool(profile and all(profile.get(k) is not None for k in essential))

    if not has_full_profile:
        send_message(chat_id, T["need_profile_first"])
        send_message(chat_id, T["profile_template"])
        return "OK"

    # профиль есть → считаем, что все нормальные сообщения — это еда
    if not is_food_message(text_stripped):
        # даже если это не похоже на еду, мягко направляем пользователя
        if lang == "en":
            send_message(
                chat_id,
                "I track food. Just describe what you ate today in simple words, with approximate amounts.\n"
                "Example: \"2 slices of bread, 150–200 g chicken, a bit of yogurt + ketchup sauce, "
                "coffee with 1.5% milk, no sugar.\""
            )
        elif lang == "sr":
            send_message(
                chat_id,
                "Ja pratim hranu. Opiši jednostavno šta si jeo danas i približne količine.\n"
                "Primer: \"2 parčeta hleba, 150–200 g piletine, malo sosa od grčkog jogurta i kečapa, "
                "kafa sa mlekom 1,5%, bez šećera.\""
            )
        else:
            send_message(
                chat_id,
                "Я считаю калории по еде. Опиши простыми словами, что ты съел и примерно сколько.\n"
                "Например: \"2 ломтика хлеба, 150–200 г курицы, немного соуса из йогурта и кетчупа, "
                "кофе с молоком 1,5%, без сахара.\""
            )
        return "OK"

    # ==== РЕЖИМ ЕДЫ: Анализ через Mixtral ====
    ai_text = ai_meal_analysis(text_stripped, lang)
    total_kcal = extract_total_kcal(ai_text)

    if not ai_text or not total_kcal or total_kcal <= 0:
        send_message(chat_id, T["need_details"])
        return "OK"

    kcal = int(total_kcal)

    today = get_today_key()
    new_total = update_diary_kcal(chat_id, today, kcal)
    meals_today = supabase_select("meals", {"user_id": f"eq.{chat_id}", "day": f"eq.{today}"})
    meal_number = len(meals_today) + 1
    add_meal_record(chat_id, today, meal_number, text_stripped, kcal)

    target = calc_target_kcal(profile)
    left = target - new_total

    reply = build_meal_reply(lang, meal_number, ai_text, kcal, new_total, left)

    # если перебор по калориям — добавим комментарий
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
                "Savet: sutra napravi mali minus (100–200 kcal ispod norme) "
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
