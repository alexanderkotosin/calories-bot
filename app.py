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

AI_ENDPOINT = os.environ.get(
    "AI_ENDPOINT",
    "https://router.huggingface.co/v1/chat/completions",
)
AI_KEY = os.environ.get("AI_KEY")
AI_MODEL = os.environ.get(
    "AI_MODEL",
    "HuggingFaceTB/SmolLM3-3B:hf-inference",
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
    try:
        r = requests.get(url, headers=supabase_headers(), params=params, timeout=15)
        data = r.json()
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print("supabase_select error:", e)
        return []


def supabase_upsert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        r = requests.post(
            url,
            headers={**supabase_headers(json_mode=True), "Prefer": "resolution=merge-duplicates"},
            data=json.dumps(data),
            timeout=15,
        )
        try:
            return r.json()
        except Exception:
            # Supabase часто возвращает пустой body при 204/201
            return []
    except Exception as e:
        print("supabase_upsert error:", e)
        return []


def supabase_insert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
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
    except Exception as e:
        print("supabase_insert error:", e)
        return []


# ================================
# TEXTS / LOCALIZATION
# ================================

LANG_CHOICES_TEXT = (
    "Привет! Я бот, который помогает считать калории и видеть картину дня 💪\n\n"
    "Сначала выбери язык:\n\n"
    "1️⃣ Русский 🇷🇺\n"
    "2️⃣ English 🇬🇧\n"
    "3️⃣ Srpski 🇷🇸\n\n"
    "Просто отправь 1, 2 или 3."
)

TEXT = {
    "ru": {
        "profile_intro": (
            "Давай настроим твой профиль, чтобы я мог точно считать калории.\n\n"
            "Активность:\n"
            "• низкая — сидячая работа, мало шагов, нет тренировок;\n"
            "• средняя — 2–3 тренировки в неделю и/или 8–10k шагов в день;\n"
            "• высокая — тяжёлый физический труд или 4+ интенсивных тренировок в неделю.\n"
        ),
        "profile_template": (
            "Скопируй этот шаблон, вставь в чат и заполни цифрами:\n\n"
            "Возраст 34\n"
            "Рост 181\n"
            "Вес 88\n"
            "Цель вес 84\n"
            "Пол м\n"
            "Активность средняя"
        ),
        "profile_saved": (
            "Готово, профиль сохранён ✅\n\n"
            "Я посчитал твою норму калорий с учётом возраста, роста, веса, пола и активности.\n"
            "• Это не «магическое число», а обычная физика: когда ты ешь больше, чем тратишь, "
            "излишек откладывается в жир; когда немного не добираешь — организм берёт энергию из запасов.\n\n"
            "Я буду вести учёт съеденного за день и показывать, сколько осталось до здорового дефицита."
        ),
        "profile_kcal_line": (
            "Твоя дневная норма для дефицита: примерно {kcal} ккал в день."
        ),
        "meal_input_help": (
            "Как вносить еду, чтобы я считал точнее:\n\n"
            "• Пиши простым языком, без формальностей.\n"
            "• Указывай примерные количества, не нужны точные цифры.\n\n"
            "Примеры:\n"
            "• \"2 ломтика цельнозернового хлеба, 2 яйца, немного сыра, чай без сахара\".\n"
            "• \"Куриная грудка примерно 150–200 г, 150 г риса, салат из огурцов и помидоров, "
            "1 столовая ложка оливкового масла\".\n"
            "• \"Бургер из кафе, средняя картошка фри, 2 чайные ложки кетчупа, "
            "капучино 300 мл с молоком 1,5%, без сахара\".\n\n"
            "Важно:\n"
            "• Учитывай соусы (кетчуп, майонез, йогурт-соусы, масло).\n"
            "• Учитывай напитки с калориями (сладкая газировка, сок, алкоголь, кофе с молоком/сиропом).\n"
            "• Если не знаешь граммы — пиши \"кусок\", \"тарелка\", \"стакан\", \"ложка\" — я оценю по опыту."
        ),
        "need_profile_first": (
            "Похоже, профиль ещё не настроен.\n\n"
            "Нажми /start, выбери язык и заполни короткий профиль — тогда я смогу считать калории 👌"
        ),
        "ask_meal_brief": (
            "Чтобы я посчитал калории, опиши приём пищи простыми словами: что было и примерно сколько.\n\n"
            "Например: \"2 ломтика хлеба, омлет из 2 яиц, немного сыра, чай без сахара\"."
        ),
        "cannot_parse_meal": (
            "Я не смог нормально разобрать приём пищи. Опиши ещё раз, простыми словами: что было в тарелке и примерно сколько.\n\n"
            "Например: \"Куриная грудка примерно 150–200 г, 150 г риса, салат из огурцов и помидоров, "
            "1 столовая ложка оливкового масла\"."
        ),
        "meal_header": "Разбор приёма пищи:",
        "daily_summary": (
            "\n\nИтого за этот приём: {meal_kcal} ккал.\n"
            "Съедено сегодня: {total_kcal} ккал.\n"
            "Твоя дневная норма (здоровый дефицит): {target_kcal} ккал.\n"
            "Осталось до лимита: {left_kcal} ккал."
        ),
        "daily_overeat": (
            "\n\nСегодня ты вышел(а) за лимит примерно на {over_kcal} ккал.\n"
            "Ничего страшного, такое бывает 🙂 Постарайся завтра немного сократить калории "
            "(минус 200–300 ккал от нормы) или добавить активности, чтобы вернуть средний дефицит."
        ),
    },
    # Для экономии места: en/sr можно доработать позже, пока логика одинакова
    "en": {
        "profile_intro": (
            "Let’s set up your profile so I can track calories correctly.\n\n"
            "Activity level:\n"
            "• low – mostly sitting, very few steps, no workouts;\n"
            "• medium – 2–3 workouts per week and/or 8–10k steps per day;\n"
            "• high – hard physical work or 4+ intense workouts per week.\n"
        ),
        "profile_template": (
            "Copy this template, paste it and fill in your data:\n\n"
            "Age 34\n"
            "Height 181\n"
            "Weight 88\n"
            "Goal weight 84\n"
            "Sex m\n"
            "Activity medium"
        ),
        "profile_saved": (
            "Done, profile saved ✅\n\n"
            "I calculated your daily calories based on age, height, weight, sex and activity.\n"
            "It’s just physics: if you eat more than you burn, extra energy is stored as fat; "
            "if you eat a bit less, your body uses fat reserves.\n\n"
            "I’ll track what you eat and show how far you are from a healthy deficit."
        ),
        "profile_kcal_line": (
            "Your daily target for a healthy deficit is about {kcal} kcal."
        ),
        "meal_input_help": (
            "How to describe meals so I can track calories:\n\n"
            "• Use simple language.\n"
            "• Rough amounts are enough, no need for precise grams.\n\n"
            "Examples:\n"
            "• \"2 slices of wholegrain bread, 2 eggs, some cheese, tea without sugar\".\n"
            "• \"Grilled chicken breast around 150–200 g, 150 g rice, salad with cucumbers and tomatoes, "
            "1 tbsp olive oil\".\n"
            "• \"Cafe burger, medium fries, 2 tsp ketchup, cappuccino 300 ml with 1.5% milk, no sugar\".\n\n"
            "Important:\n"
            "• Include sauces (ketchup, mayo, yogurt sauces, oil).\n"
            "• Include drinks with calories (soda, juice, alcohol, coffee with milk/syrup).\n"
            "• If you don’t know grams, write \"piece\", \"plate\", \"cup\", \"spoon\" – I’ll estimate."
        ),
        "need_profile_first": (
            "Looks like your profile isn’t set up yet.\n\n"
            "Send /start, choose language and fill your short profile so I can track calories 👌"
        ),
        "ask_meal_brief": (
            "To calculate calories, describe the meal in simple words: what you ate and roughly how much.\n\n"
            "Example: \"2 slices of bread, omelette from 2 eggs, some cheese, tea without sugar\"."
        ),
        "cannot_parse_meal": (
            "I couldn’t clearly understand this meal. Please describe once more: what was on the plate and roughly how much."
        ),
        "meal_header": "Meal breakdown:",
        "daily_summary": (
            "\n\nThis meal: {meal_kcal} kcal.\n"
            "Total today: {total_kcal} kcal.\n"
            "Your daily target (healthy deficit): {target_kcal} kcal.\n"
            "Remaining today: {left_kcal} kcal."
        ),
        "daily_overeat": (
            "\n\nYou went over your target by about {over_kcal} kcal today.\n"
            "It’s OK, it happens 🙂 Try to slightly reduce calories tomorrow "
            "or move a bit more to keep the weekly deficit."
        ),
    },
    "sr": {
        "profile_intro": (
            "Hajde da podesimo tvoj profil da bih mogao tačno da računam kalorije.\n\n"
            "Aktivnost:\n"
            "• niska – kancelarijski posao, malo koraka, nema treninga;\n"
            "• srednja – 2–3 treninga nedeljno i/ili 8–10k koraka dnevno;\n"
            "• visoka – fizički težak posao ili 4+ intenzivna treninga nedeljno.\n"
        ),
        "profile_template": (
            "Kopiraj ovaj šablon, nalepi u chat i popuni svojim podacima:\n\n"
            "Godine 34\n"
            "Visina 181\n"
            "Težina 88\n"
            "Ciljna težina 84\n"
            "Pol m\n"
            "Aktivnost srednja"
        ),
        "profile_saved": (
            "Profil je sačuvan ✅\n\n"
            "Izračunao sam tvoju dnevnu normu kalorija na osnovu godina, visine, težine, pola i aktivnosti.\n"
            "To je obična fizika: kad jedeš više nego što trošiš, višak ide u masnoću; "
            "kad malo ne dostižeš normu, telo troši rezerve.\n\n"
            "Pratiću šta jedeš i pokazivati koliko ti je ostalo do zdravog deficita."
        ),
        "profile_kcal_line": (
            "Tvoja dnevna norma za zdrav deficit je oko {kcal} kcal."
        ),
        "meal_input_help": (
            "Kako da unosiš obroke da bih tačno računao kalorije:\n\n"
            "• Piši jednostavnim jezikom.\n"
            "• Dovoljne su približne količine, nisu potrebni tačni grami.\n\n"
            "Primeri:\n"
            "• \"2 parčeta hleba od celog zrna, 2 jajeta, malo sira, čaj bez šećera\".\n"
            "• \"Piletina na žaru oko 150–200 g, 150 g pirinča, salata od krastavca i paradajza, "
            "1 kašika maslinovog ulja\".\n"
            "• \"Burger iz kafića, srednji pomfrit, 2 kašičice kečapa, kapućino 300 ml sa mlekom 1,5%, bez šećera\".\n\n"
            "Važno:\n"
            "• Računaj sosove (kečap, majonez, jogurt-sosovi, ulje).\n"
            "• Računaj pića sa kalorijama (slatke gazirane napitke, sok, alkohol, kafu sa mlekom/sirupom).\n"
            "• Ako ne znaš grame, piši \"parče\", \"tanjir\", \"šolja\", \"kašika\" – proceniću po iskustvu."
        ),
        "need_profile_first": (
            "Izgleda da profil još nije podešen.\n\n"
            "Pošalji /start, izaberi jezik i popuni kratak profil da bih mogao da računam kalorije 👌"
        ),
        "ask_meal_brief": (
            "Da bih izračunao kalorije, opiši obrok jednostavnim rečima: šta si jeo i otprilike koliko.\n\n"
            "Primer: \"2 parčeta hleba, omlet od 2 jajeta, malo sira, čaj bez šećera\"."
        ),
        "cannot_parse_meal": (
            "Nisam uspeo jasno da razumem ovaj obrok. Opiši još jednom: šta je bilo na tanjiru i otprilike koliko."
        ),
        "meal_header": "Analiza obroka:",
        "daily_summary": (
            "\n\nOvaj obrok: {meal_kcal} kcal.\n"
            "Ukupno danas: {total_kcal} kcal.\n"
            "Tvoja dnevna norma (zdrav deficit): {target_kcal} kcal.\n"
            "Preostalo danas: {left_kcal} kcal."
        ),
        "daily_overeat": (
            "\n\nDanas si prešao/la dnevni limit za oko {over_kcal} kcal.\n"
            "Nije strašno 🙂 Pokušaj sutra malo da smanjiš unos "
            "ili da se više krećeš da bi vratio/la prosečan deficit."
        ),
    },
}


# ================================
# HF ROUTER CHAT HELPER
# ================================


def call_hf_chat(system_prompt, user_prompt, response_format_json=False):
    """
    Вызов Hugging Face Router в формате /v1/chat/completions.
    Возвращает content из message или None.
    """
    if not AI_ENDPOINT or not AI_KEY or not AI_MODEL:
        print("HF config missing")
        return None

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.25,
        "max_tokens": 512,
    }

    if response_format_json:
        payload["response_format"] = {"type": "json_object"}

    try:
        r = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=40)
        if r.status_code != 200:
            print("HF NON-200 RESPONSE:", r.status_code, r.text[:500])
            return None
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print("HF chat error:", e)
        return None


# ================================
# PROFILE STORAGE & CALC
# ================================


def get_profile(user_id):
    res = supabase_select("profiles", {"user_id": f"eq.{user_id}"})
    return res[0] if res else None


def save_profile(user_id, new_data):
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
        "total_kcal": new_total,
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
    """
    Парсим профиль из свободного текста без обязательных двоеточий.
    Ожидаем строки вида:
    Возраст 34
    Рост 181
    Вес 88
    Цель вес 84
    Пол м/ж
    Активность низкая/средняя/высокая
    """
    t = text.lower()

    def find_int(labels):
        pattern = r"(" + "|".join([re.escape(l) for l in labels]) + r")\s*[:\-]?\s*(\d+)"
        m = re.search(pattern, t)
        if not m:
            return None
        return int(m.group(2))

    age = find_int(["возраст", "age"])
    height = find_int(["рост", "height"])
    weight = find_int(["вес", "weight"])
    goal = find_int(["цель вес", "цель", "goal weight", "goal"])

    sex = None
    if re.search(r"\bж\b|female|f", t):
        sex = "f"
    elif re.search(r"\bм\b|male|m", t):
        sex = "m"

    if "низк" in t or "low" in t:
        activity = 1.2
    elif "средн" in t or "medium" in t:
        activity = 1.35
    elif "высок" in t or "high" in t:
        activity = 1.6
    else:
        activity = None

    if all([age, height, weight, goal, sex, activity]):
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
# MEAL LOGIC (DETECTION + AI ANALYSIS)
# ================================

FOOD_HINT_WORDS = [
    "бурек", "burek", "пиц", "pizza", "burger", "бургер",
    "хлеб", "bread", "rice", "рис", "картоф", "potato", "фри",
    "яйц", "egg", "omelet", "омлет",
    "куриц", "chicken", "говядин", "beef", "свинин", "pork",
    "сыр", "cheese", "йогурт", "yogurt",
    "салат", "salad", "овощ", "овощи",
    "каша", "греч", "oat", "овсян",
    "кофе", "kafa", "капа", "капуч", "чай", "сок", "пиво", "beer",
    "бурито", "tortilla", "wrap", "шаурм", "gyros", "донер", "kebab",
]


def looks_like_meal(text):
    t = text.lower().strip()
    if not t:
        return False
    if t in ("/start", "1", "2", "3"):
        return False
    if parse_profile(t):
        return False
    if any(w in t for w in FOOD_HINT_WORDS):
        return True
    if re.search(r"\d", t):
        return True
    return False


def ai_meal_analysis(user_text, lang):
    """
    Отправляет описание еды в ИИ и возвращает структуру:
    {
        "items": [{"name": str, "kcal": float}, ...],
        "total_kcal": float,
        "comment": str
    }
    либо None при ошибке.
    """
    if lang not in TEXT:
        lang = "ru"

    if lang == "ru":
        system_prompt = (
            "Ты нутриционист. Твоя задача — по описанию приёма пищи оценить калории.\n"
            "1) Разбей описание на конкретные элементы (блюда/продукты).\n"
            "2) Для каждого элемента оцени калории (kcal) в всей указанной порции.\n"
            "3) Посчитай итоговую сумму калорий для приёма пищи.\n"
            "4) Используй реалистичные значения: обычный приём пищи взрослого человека "
            "обычно в диапазоне 100–1800 ккал. Если описан весь день или очень много еды/алкоголя, "
            "сумма может быть выше — это допускается.\n"
            "5) Если информации мало или она приблизительная, сделай лучшую возможную оценку, "
            "НЕ задавай уточняющих вопросов.\n\n"
            "Ответ ВЕРНИ строго в формате JSON:\n"
            "{\n"
            "  \"items\": [\n"
            "    {\"name\": \"описание элемента\", \"kcal\": число},\n"
            "    ...\n"
            "  ],\n"
            "  \"total_kcal\": число,\n"
            "  \"comment\": \"краткое пояснение на русском\"\n"
            "}\n"
            "Без лишнего текста вне JSON."
        )
    elif lang == "en":
        system_prompt = (
            "You are a nutritionist. Given a meal description, estimate calories.\n"
            "1) Split the description into concrete items.\n"
            "2) Estimate kcal for each item for the whole portion.\n"
            "3) Compute total kcal for the meal.\n"
            "4) Use realistic values: typical single meal for an adult is ~100–1800 kcal, "
            "but the total can be higher if it's a full day of eating or lots of alcohol.\n"
            "5) If the description is approximate, still give your best estimate, "
            "do NOT ask follow-up questions.\n\n"
            "Return STRICT JSON only:\n"
            "{\n"
            "  \"items\": [\n"
            "    {\"name\": \"item description\", \"kcal\": number},\n"
            "    ...\n"
            "  ],\n"
            "  \"total_kcal\": number,\n"
            "  \"comment\": \"short explanation in English\"\n"
            "}"
        )
    else:  # sr
        system_prompt = (
            "Ti si nutricionista. Na osnovu opisa obroka proceni kalorije.\n"
            "1) Podeli opis na konkretne stavke.\n"
            "2) Za svaku stavku proceni kalorije (kcal) za celu porciju.\n"
            "3) Izračunaj ukupne kalorije za obrok.\n"
            "4) Koristi realne vrednosti: tipičan obrok odrasle osobe je oko 100–1800 kcal, "
            "ali ukupno može biti više ako je opisan ceo dan ili mnogo alkohola.\n"
            "5) Ako je opis približan, ipak daj najbolju moguću procenu, "
            "BEZ dodatnih pitanja.\n\n"
            "Vrati STROGO JSON:\n"
            "{\n"
            "  \"items\": [\n"
            "    {\"name\": \"opis stavke\", \"kcal\": broj},\n"
            "    ...\n"
            "  ],\n"
            "  \"total_kcal\": broj,\n"
            "  \"comment\": \"kratko objašnjenje na srpskom\"\n"
            "}"
        )

    user_prompt = f"Opis obroka / meal description:\n{user_text}\n\nVrati samo JSON."

    raw = call_hf_chat(system_prompt, user_prompt, response_format_json=True)
    if raw is None:
        return None

    # message.content может быть строкой JSON или уже dict
    data = None
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except Exception:
            # Попробуем вытащить первую {...}
            try:
                start = raw.find("{")
                end = raw.rfind("}")
                if start != -1 and end != -1 and end > start:
                    data = json.loads(raw[start : end + 1])
            except Exception:
                data = None

    if not isinstance(data, dict):
        return None

    items = data.get("items") or []
    total = data.get("total_kcal")

    # если total_kcal нет или мусор — считаем по сумме
    try:
        if total is None or float(total) <= 0:
            total = sum(float(i.get("kcal") or 0) for i in items)
        total = float(total)
    except Exception:
        return None

    if total <= 0 or total > 20000:
        return None

    comment = data.get("comment") or ""
    # нормализуем items
    norm_items = []
    for it in items:
        try:
            name = str(it.get("name") or "").strip()
            kcal = float(it.get("kcal") or 0)
            if name and kcal > 0:
                norm_items.append({"name": name, "kcal": round(kcal)})
        except Exception:
            continue

    if not norm_items:
        # хотя бы один элемент с общим total
        norm_items = [{"name": "Общий приём пищи", "kcal": round(total)}]

    return {
        "items": norm_items,
        "total_kcal": round(total),
        "comment": comment,
    }


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
    text_raw = msg.get("text") or ""
    text = text_raw.strip()

    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else "ru")
    T = TEXT.get(lang, TEXT["ru"])

    # /start — всегда выбор языка
    if text.lower() == "/start":
        send_message(chat_id, LANG_CHOICES_TEXT)
        return "OK"

    # выбор языка 1/2/3
    if text in ("1", "2", "3"):
        lang_map = {"1": "ru", "2": "en", "3": "sr"}
        lang = lang_map[text]
        save_profile(chat_id, {"lang": lang})
        T = TEXT[lang]
        # два сообщения: интро и шаблон
        send_message(chat_id, T["profile_intro"])
        send_message(chat_id, T["profile_template"])
        return "OK"

    # пытаемся распарсить профиль
    parsed_prof = parse_profile(text)
    if parsed_prof:
        save_profile(chat_id, {"lang": lang, **parsed_prof})
        profile = get_profile(chat_id)
        lang = profile.get("lang", lang)
        T = TEXT.get(lang, TEXT["ru"])
        target = calc_target_kcal(profile)

        send_message(chat_id, T["profile_saved"])
        send_message(chat_id, T["profile_kcal_line"].format(kcal=target))
        send_message(chat_id, T["meal_input_help"])
        return "OK"

    # профиль после возможного обновления
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else lang)
    T = TEXT.get(lang, TEXT["ru"])

    essential_keys = ["age", "height", "weight", "goal", "activity_factor", "sex"]
    has_full_profile = bool(profile and all(profile.get(k) is not None for k in essential_keys))

    if not has_full_profile:
        send_message(chat_id, T["need_profile_first"])
        return "OK"

    # дальше — только лог еды
    if not looks_like_meal(text):
        send_message(chat_id, T["ask_meal_brief"])
        return "OK"

    analysis = ai_meal_analysis(text, lang)
    if not analysis:
        send_message(chat_id, T["cannot_parse_meal"])
        send_message(chat_id, T["meal_input_help"])
        return "OK"

    meal_kcal = analysis["total_kcal"]
    items = analysis["items"]
    comment = analysis.get("comment") or ""

    today = get_today_key()
    # сколько приёмов уже есть
    meals_today = supabase_select("meals", {"user_id": f"eq.{chat_id}", "day": f"eq.{today}"})
    meal_number = len(meals_today) + 1

    new_total = update_diary_kcal(chat_id, today, meal_kcal)
    add_meal_record(chat_id, today, meal_number, text, meal_kcal)

    target = calc_target_kcal(profile)
    left = target - new_total

    # формируем ответ
    if lang == "ru":
        lines = [f"{T['meal_header']}"]
        for it in items:
            lines.append(f"• {it['name']}: {it['kcal']} ккал")
        if comment:
            lines.append(f"\nКомментарий: {comment}")
    elif lang == "sr":
        lines = [f"{T['meal_header']}"]
        for it in items:
            lines.append(f"• {it['name']}: {it['kcal']} kcal")
        if comment:
            lines.append(f"\nKomentar: {comment}")
    else:
        lines = [f"{T['meal_header']}"]
        for it in items:
            lines.append(f"• {it['name']}: {it['kcal']} kcal")
        if comment:
            lines.append(f"\nComment: {comment}")

    reply = "\n".join(lines)
    reply += T["daily_summary"].format(
        meal_kcal=meal_kcal,
        total_kcal=new_total,
        target_kcal=target,
        left_kcal=left,
    )

    if left < 0:
        over = abs(left)
        reply += T["daily_overeat"].format(over_kcal=over)

    send_message(chat_id, reply)
    return "OK"


@app.route("/", methods=["GET"])
def home():
    return "AI Calories Bot with HF Router is running!"
