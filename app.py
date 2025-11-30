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
        "welcome": (
            "Привет! Я бот, который помогает считать калории и наводить порядок в тарелке, а не в жизни — "
            "с этим ты сам справишься 😉\n\n"
            "Сейчас настроим профиль, чтобы я мог считать твою дневную норму и дефицит."
        ),
        "profile_template": (
            "Шаблон профиля — просто скопируй и заполни цифрами вместо подчёркиваний:\n\n"
            "Возраст ___\n"
            "Рост ___\n"
            "Вес ___\n"
            "Цель вес ___\n"
            "Пол м/ж\n"
            "Активность низкая / средняя / высокая"
        ),
        "profile_saved": "Профиль сохранён ✅",
        "need_details": "Мне нужно уточнение — сколько примерно это весит в граммах?",
        "meal_count": "Приём пищи №{}",
        "daily_total": "Съедено за день: {} ккал",
        "daily_left": "Осталось до нормы: {} ккал",
        "need_profile_first": (
            "Чтобы я точнее считал твою личную дневную норму и дефицит, заполни профиль.\n\n"
            "Отправь /start, чтобы ещё раз получить шаблон профиля."
        ),
    },
    "en": {
        "welcome": (
            "Hi! I’m a bot that helps you track calories and keep your plate under control — "
            "your life is your own project 😉\n\n"
            "Let’s set up your profile so I can calculate your daily target and deficit."
        ),
        "profile_template": (
            "Profile template — just copy and fill in the numbers instead of the blanks:\n\n"
            "Age ___\n"
            "Height ___\n"
            "Weight ___\n"
            "Goal weight ___\n"
            "Sex m/f\n"
            "Activity low / medium / high"
        ),
        "profile_saved": "Profile saved ✅",
        "need_details": "I need some clarification — roughly how many grams is that?",
        "meal_count": "Meal #{}",
        "daily_total": "Total eaten today: {} kcal",
        "daily_left": "Remaining to your target: {} kcal",
        "need_profile_first": (
            "To calculate your personal daily target and deficit more accurately, please set up your profile.\n\n"
            "Send /start to get the profile template again."
        ),
    },
    "sr": {
        "welcome": (
            "Ćao! Ja sam bot koji ti pomaže da brojiš kalorije i držiš tanjir pod kontrolom 😉\n\n"
            "Hajde da podesimo profil da bih mogao da izračunam tvoj dnevni limit i deficit."
        ),
        "profile_template": (
            "Šablon profila — samo iskopiraj i popuni brojeve umesto crtica:\n\n"
            "Godine ___\n"
            "Visina ___\n"
            "Težina ___\n"
            "Ciljna težina ___\n"
            "Pol m/ž\n"
            "Aktivnost niska / srednja / visoka"
        ),
        "profile_saved": "Profil sačuvan ✅",
        "need_details": "Treba mi pojašnjenje — koliko otprilike to ima grama?",
        "meal_count": "Obrok #{}",
        "daily_total": "Ukupno danas: {} kcal",
        "daily_left": "Preostalo do norme: {} kcal",
        "need_profile_first": (
            "Da bih preciznije računao tvoj lični dnevni limit i deficit, popuni profil.\n\n"
            "Pošalji /start da ponovo dobiješ šablon."
        ),
    },
}


# ================================
# HUGGINGFACE WRAPPERS (ТОЛЬКО КАЛОРИИ)
# ================================

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
        # исправленный парсинг числа
        nums = re.findall(r"\d+(?:\.\d+)?", content)
        if not nums:
            return None
        return float(nums[0])
    except Exception as e:
        print("AI kcal error:", e)
        return None


def ask_ai_breakdown(meal_text, lang, total_kcal, weight=None):
    """
    Дружелюбное объяснение: из чего примерно сложились калории этого приёма пищи.
    """
    if not AI_ENDPOINT or not AI_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    if lang == "ru":
        system_prompt = (
            "Ты дружелюбный нутриционист. Объясни клиенту, как примерно получилась указанная "
            "калорийность блюда. Разбей блюдо на 2–5 основных ингредиентов и укажи ориентировочную "
            "калорийность каждого. В конце подтверди общий итог. Пиши коротко, по делу, с поддержкой "
            "и мотивацией, на русском языке."
        )
        user_text = (
            f"Описание блюда: {meal_text}\n"
            f"Я уже оценил этот приём пищи примерно в {total_kcal} ккал"
            + (f" при весе около {weight} г." if weight else ".")
            + " Объясни человеку, как эти калории могли распределиться по ингредиентам."
        )
    elif lang == "en":
        system_prompt = (
            "You are a friendly nutritionist. Explain to the user how the total calories of this meal "
            "could roughly be composed. Split it into 2–5 main ingredients with approximate calories "
            "for each, and then confirm the total. Be short, clear, positive and motivating, in English."
        )
        user_text = (
            f"Meal description: {meal_text}\n"
            f"I have already estimated this meal at about {total_kcal} kcal"
            + (f" with a weight of around {weight} g." if weight else ".")
            + " Explain how these calories could be distributed between the main ingredients."
        )
    else:  # sr
        system_prompt = (
            "Ti si prijateljski nutricionista. Objasni korisniku kako je otprilike nastala ukupna "
            "kalorijska vrednost ovog obroka. Podeli na 2–5 glavnih sastojaka sa približnim kalorijama "
            "za svaki i na kraju potvrdi ukupan zbir. Piši kratko, jasno, podržavajuće i motivišuće, na srpskom."
        )
        user_text = (
            f"Opis obroka: {meal_text}\n"
            f"Već sam procenio ovaj obrok na oko {total_kcal} kcal"
            + (f" sa težinom oko {weight} g." if weight else ".")
            + " Objasni kako se te kalorije mogu raspodeliti po sastojcima."
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 256,
    }

    try:
        r = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=30)
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        print("AI breakdown error:", e)
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
    200 г, 150гр, 250g, 100 ml, 1kg → граммы.
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
    """
    Парсим профиль из свободного текста без двоеточий.
    Ожидаем, что пользователь использовал слова из шаблона:
    "Возраст", "Рост", "Вес", "Цель вес", "Age", "Height", "Weight", "Goal weight" и т.п.
    Форматы допустимы: "Возраст 34", "Возраст - 34", "age 34" и т.д.
    """
    t = text.lower()

    def find_int_by_keywords(keywords):
        for kw in keywords:
            # ищем число в радиусе до 10 нецифровых символов после ключевого слова
            m = re.search(rf"{re.escape(kw)}\D{{0,10}}(\d{{1,3}})", t)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    continue
        return None

    age = find_int_by_keywords(["возраст", "age"])
    height = find_int_by_keywords(["рост", "height"])
    weight = find_int_by_keywords(["вес", "weight"])
    goal = find_int_by_keywords(["цель вес", "цель", "goal weight", "goal"])

    # пол
    sex = "m"
    if " ж" in t or "жен" in t or " f" in t or "female" in t:
        sex = "f"

    # активность
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
            "height": float(height),
            "weight": float(weight),
            "goal": float(goal),
            "sex": sex,
            "activity_factor": activity,
        }

    return None


def calc_bmr_tdee(profile):
    if not profile:
        return None, None
    if profile.get("sex") == "m":
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] + 5
    else:
        bmr = 10 * profile["weight"] + 6.25 * profile["height"] - 5 * profile["age"] - 161
    tdee = bmr * profile["activity_factor"]
    return bmr, tdee


def calc_target_kcal(profile):
    bmr, tdee = calc_bmr_tdee(profile)
    if bmr is None or tdee is None:
        return 2000
    deficit = tdee * 0.8
    return round(deficit)


def build_profile_explanation(profile, lang):
    """
    Одноразовое объяснение принципа дефицита и формулы после создания профиля.
    """
    bmr, tdee = calc_bmr_tdee(profile)
    target = calc_target_kcal(profile)

    age = int(profile["age"])
    height = int(profile["height"])
    weight = int(profile["weight"])
    goal = int(profile["goal"])

    if lang == "ru":
        text = (
            f"{TEXT['ru']['profile_saved']}\n\n"
            f"Смотри, что я посчитал по твоим данным:\n"
            f"Возраст: {age} лет, рост: {height} см, вес: {weight} кг, цель: {goal} кг.\n\n"
            f"1️⃣ Базовый обмен (BMR) ≈ {round(bmr)} ккал — столько ты тратишь в покое.\n"
            f"2️⃣ С учётом активности твой расход (TDEE) ≈ {round(tdee)} ккал в день.\n"
            f"3️⃣ Для комфортного снижения веса я заложил ~20% дефицит.\n"
            f"➡️ Твоя рабочая дневная норма ≈ {target} ккал.\n\n"
            "Логика простая, почти как таблица в Excel:\n"
            "- если стабильно ешь ВЫШЕ своей нормы — профицит энергии откладывается в жир;\n"
            "- если стабильно ешь ЧУТЬ НИЖЕ нормы — организм добирает из запасов, и вес падает.\n\n"
            "Дальше я буду сравнивать твой дневной итог с этой нормой и подсказывать, что происходит — "
            "держишь дефицит, вышел в ноль или слегка перебрал. Никакой магии, только физика и немного здорового юмора 😎"
        )
    elif lang == "en":
        text = (
            f"{TEXT['en']['profile_saved']}\n\n"
            f"Here is what I calculated from your data:\n"
            f"Age: {age}, height: {height} cm, weight: {weight} kg, goal: {goal} kg.\n\n"
            f"1️⃣ Basal Metabolic Rate (BMR) ≈ {round(bmr)} kcal — what you burn at rest.\n"
            f"2️⃣ With your activity, your daily expenditure (TDEE) ≈ {round(tdee)} kcal.\n"
            f"3️⃣ For healthy fat loss I used about a 20% deficit.\n"
            f"➡️ Your working daily target ≈ {target} kcal.\n\n"
            "The idea is simple:\n"
            "- if you regularly eat ABOVE your target — energy surplus gets stored as fat;\n"
            "- if you eat a bit BELOW your target — your body takes the rest from fat stores.\n\n"
            "From now on I’ll compare your daily total with this target and show what’s going on — "
            "deficit, maintenance or a little surplus. No magic, just physics and a pinch of humor 😎"
        )
    else:
        text = (
            f"{TEXT['sr']['profile_saved']}\n\n"
            f"Evo šta sam izračunao iz tvojih podataka:\n"
            f"Godine: {age}, visina: {height} cm, težina: {weight} kg, cilj: {goal} kg.\n\n"
            f"1️⃣ Bazalni metabolizam (BMR) ≈ {round(bmr)} kcal — toliko trošiš u mirovanju.\n"
            f"2️⃣ Sa aktivnošću tvoja potrošnja (TDEE) ≈ {round(tdee)} kcal dnevno.\n"
            f"3️⃣ Za zdravo mršavljenje koristim oko 20% deficita.\n"
            f"➡️ Tvoja radna dnevna norma ≈ {target} kcal.\n\n"
            "Ideja je jednostavna:\n"
            "- ako stalno jedeš IZNAD norme — višak energije ide u masne rezerve;\n"
            "- ako jedeš malo ISPOD norme — telo uzima razliku iz tih rezervi.\n\n"
            "Od sada ću upoređivati tvoj dnevni zbir sa ovom normom i javljati da li si u deficitu, "
            "na nuli ili u plusu. Nema magije, samo fizika i malo humora 😎"
        )
    return text


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

    # -------- /start: выбор языка и онбординг --------
    if text_stripped.lower().startswith("/start"):
        send_message(chat_id, LANG_CHOICES_TEXT)
        return "OK"

    # -------- выбор языка 1/2/3 --------
    if text_stripped in ("1", "2", "3"):
        lang_map = {"1": "ru", "2": "en", "3": "sr"}
        lang = lang_map[text_stripped]
        save_profile(chat_id, {"lang": lang})
        T = TEXT[lang]
        # приветствие и объяснение + отдельным сообщением шаблон
        send_message(chat_id, T["welcome"])
        send_message(chat_id, T["profile_template"])
        return "OK"

    # -------- попытка распарсить профиль --------
    parsed_prof = parse_profile(text_stripped)
    if parsed_prof:
        save_profile(chat_id, {"lang": lang, **parsed_prof})
        # берём актуальный профиль для расчётов
        profile = get_profile(chat_id)
        explanation = build_profile_explanation(profile, lang)
        send_message(chat_id, explanation)
        return "OK"

    # после возможного обновления профиля ещё раз загрузим
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else lang)
    T = TEXT.get(lang, TEXT["ru"])

    essential_keys = ["age", "height", "weight", "goal", "activity_factor", "sex"]
    has_full_profile = bool(profile and all(profile.get(k) is not None for k in essential_keys))

    # -------- если сообщение не похоже на еду --------
    if not is_food_message(text_stripped):
        # если профиля нет — мягко отправляем к /start
        if not has_full_profile:
            send_message(chat_id, T["need_profile_first"])
            return "OK"

        # если профайл есть — напоминаем формат еды
        if lang == "ru":
            msg_text = (
                "Я заточен под подсчёт калорий 😊\n\n"
                "Опиши, пожалуйста, что ты съел и примерный вес в граммах.\n"
                "Например: «2 яйца, 50 г сыра, 200 г картофельного пюре»."
            )
        elif lang == "en":
            msg_text = (
                "I'm here to track calories 😊\n\n"
                "Please describe what you ate and the approximate weight in grams.\n"
                "For example: “2 eggs, 50 g of cheese, 200 g of mashed potatoes”."
            )
        else:
            msg_text = (
                "Tu sam da brojim kalorije 😊\n\n"
                "Opiši šta si jeo i približnu težinu u gramima.\n"
                "Na primer: „2 jajeta, 50 g sira, 200 g pire krompira“."
            )
        send_message(chat_id, msg_text)
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
        weight_for_expl = explicit_weight
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
        weight_for_expl = weight

    # дружелюбное объяснение из чего сложились калории
    breakdown_text = ask_ai_breakdown(text_stripped, lang, kcal, weight_for_expl)

    # обновляем дневник и записываем приём пищи
    today = get_today_key()
    new_total = update_diary_kcal(chat_id, today, kcal)

    meals_today = supabase_select("meals", {"user_id": f"eq.{chat_id}", "day": f"eq.{today}"})
    meal_number = len(meals_today) + 1

    add_meal_record(chat_id, today, meal_number, text_stripped, kcal)

    target = calc_target_kcal(profile)
    left = target - new_total

    # базовый ответ
    if lang == "ru":
        base_reply = (
            f"{T['meal_count'].format(meal_number)}\n"
            f"{text_stripped}\n"
            f"{kcal} ккал\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(max(left, 0))}"
        )
    elif lang == "en":
        base_reply = (
            f"{T['meal_count'].format(meal_number)}\n"
            f"{text_stripped}\n"
            f"{kcal} kcal\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(max(left, 0))}"
        )
    else:
        base_reply = (
            f"{T['meal_count'].format(meal_number)}\n"
            f"{text_stripped}\n"
            f"{kcal} kcal\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(max(left, 0))}"
        )

    # если профиля нет — мягкий намёк (но калории уже посчитаны)
    if not has_full_profile:
        if lang == "ru":
            base_reply += (
                "\n\n⚠️ Чтобы я точнее считал твою дневную норму и дефицит, "
                "заполни профиль по шаблону (/start покажет его ещё раз)."
            )
        elif lang == "en":
            base_reply += (
                "\n\n⚠️ To get a more accurate daily target and deficit, "
                "please fill in your profile template (send /start to see it again)."
            )
        else:
            base_reply += (
                "\n\n⚠️ Da bih preciznije računao tvoj dnevni limit i deficit, "
                "popuni profil (/start prikazuje šablon ponovo)."
            )

    # анализ переедания: только если ушёл ВЫШЕ нормы
    if new_total > target:
        over = new_total - target
        if lang == "ru":
            over_text = (
                f"\n\nСегодня ты вышел выше своей нормы примерно на {over} ккал.\n"
                "Не катастрофа, но если так делать регулярно — вес начнёт ползти вверх.\n\n"
                "Совет: завтра можно сделать небольшой мягкий минус (на 100–200 ккал меньше нормы) "
                "за счёт сладкого и лишних перекусов и добавить чуть больше движения. "
                "Главное — не устраивать жесткий голод, а спокойно выровнять баланс 👍"
            )
        elif lang == "en":
            over_text = (
                f"\n\nToday you went above your target by about {over} kcal.\n"
                "Not a disaster, but if this happens often, the scale will slowly creep up.\n\n"
                "Tip: tomorrow you can create a small extra deficit (about 100–200 kcal below your target) "
                "by cutting sweets/snacks and adding a bit more movement. "
                "No starving — just gently balancing things 👍"
            )
        else:
            over_text = (
                f"\n\nDanas si otišao iznad svoje norme za oko {over} kcal.\n"
                "Nije smak sveta, ali ako se ovo često ponavlja, kilaža će lagano rasti.\n\n"
                "Savjet: sutra možeš napraviti mali dodatni deficit (100–200 kcal ispod norme) "
                "tako što ćeš smanjiti slatkiše/grickalice i ubaciti malo više kretanja. "
                "Bez izgladnjivanja — samo lagano poravnanje balansa 👍"
            )
        base_reply += over_text

    # собираем финальный ответ
    if breakdown_text:
        reply = f"{breakdown_text}\n\n{base_reply}"
    else:
        # запасной вариант, если объяснение не удалось получить
        if lang == "ru":
            intro = f"Окей, я оценил этот приём пищи примерно в {kcal} ккал. Двигаемся дальше 💪"
        elif lang == "en":
            intro = f"Okay, I’ve estimated this meal at about {kcal} kcal. Let’s keep going 💪"
        else:
            intro = f"OK, ovaj obrok sam procenio na oko {kcal} kcal. Idemo dalje 💪"
        reply = f"{intro}\n\n{base_reply}"

    send_message(chat_id, reply)
    return "OK"


@app.route("/", methods=["GET"])
def home():
    return "AI Calories Bot with Supabase is running!"
