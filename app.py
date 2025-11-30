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
            "Привет! Я бот, который помогает считать калории и наводить порядок в тарелке, "
            "а не в жизни — с этим ты сам справишься 😉\n\n"
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
        "need_details": (
            "Я не до конца разобрал, что именно и сколько ты съел 😅\n"
            "Попробуй описать ещё раз простыми словами: что было в тарелке и примерно сколько.\n"
            "Например: \"2 ломтика хлеба, курица примерно 150–200 г, немного соуса из греческого йогурта "
            "и кетчупа (1 чайная ложка), кофе с молоком 1,5% и без сахара\"."
        ),
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
            "Let’s set up your profile so I can calculate your daily target and calorie deficit."
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
        "need_details": (
            "I couldn’t fully understand what exactly and how much you ate 😅\n"
            "Please try again in simple words: what was on the plate and roughly how much.\n"
            "For example: \"2 slices of bread, chicken about 150–200 g, a bit of Greek yogurt + ketchup "
            "sauce (1 teaspoon), coffee with 1.5% milk, no sugar\"."
        ),
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
            "Hajde da podesimo profil da bih mogao da izračunam tvoj dnevni unos i kalorijski deficit."
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
        "profile_saved": "Profil je sačuvan ✅",
        "need_details": (
            "Nisam najbolje razumeo šta si tačno i koliko jeo 😅\n"
            "Pokušaj još jednom jednostavnim rečima: šta je bilo na tanjiru i otprilike koliko.\n"
            "Na primer: \"2 parčeta hleba, piletina oko 150–200 g, malo sosa od grčkog jogurta i kečapa "
            "(1 kašičica), kafa sa mlekom 1,5%, bez šećera\"."
        ),
        "meal_count": "Obrok #{}",
        "daily_total": "Ukupno danas: {} kcal",
        "daily_left": "Preostalo do tvoje norme: {} kcal",
        "need_profile_first": (
            "Da bih preciznije računao tvoj lični dnevni limit i deficit, popuni profil.\n\n"
            "Pošalji /start da ponovo dobiješ šablon profila."
        ),
    },
}


def build_logging_instructions(lang):
    if lang == "ru":
        return (
            "Как вести учёт калорий со мной:\n\n"
            "• Пиши простым языком, без математики и точных граммов.\n"
            "• Можно так: \"2 ломтика хлеба, курица примерно 150–200 г, немного соуса из греческого йогурта "
            "и кетчупа (1 чайная ложка), кофе с молоком 1,5%, без сахара\".\n"
            "• Яйца, куски, порции — тоже ок: \"2 яйца\", \"половина пиццы\", \"стандартная порция пасты\".\n"
            "• Важно учитывать всё: соусы, масло, сыр, сладкие напитки, кофе с сиропом/сахаром — "
            "они часто воруют дефицит.\n\n"
            "Твоя задача — описать еду честно и примерно. Моя задача — оценить калории и показать картину дня 💪"
        )
    elif lang == "en":
        return (
            "How to log calories with me:\n\n"
            "• Write in simple language, no need for exact grams.\n"
            "• Example: \"2 slices of bread, chicken about 150–200 g, a bit of Greek yogurt + ketchup sauce "
            "(1 teaspoon), coffee with 1.5% milk, no sugar\".\n"
            "• Eggs, pieces, portions are fine: \"2 eggs\", \"half a pizza\", \"one standard serving of pasta\".\n"
            "• It’s important to include everything: sauces, oil, cheese, sugary drinks, coffee with syrup/sugar — "
            "they often steal your deficit.\n\n"
            "Your job is to describe the food honestly and approximately. My job is to estimate calories "
            "and show you the big picture for the day 💪"
        )
    else:
        return (
            "Kako da vodiš evidenciju kalorija sa mnom:\n\n"
            "• Piši jednostavnim jezikom, bez tačnog brojanja grama.\n"
            "• Primer: \"2 parčeta hleba, piletina oko 150–200 g, malo sosa od grčkog jogurta i kečapa "
            "(1 kašičica), kafa sa mlekom 1,5%, bez šećera\".\n"
            "• Jaja, komadi, porcije su sasvim u redu: \"2 jajeta\", \"pola pice\", \"jedna standardna porcija paste\".\n"
            "• Važno je da računaš sve: soseve, ulje, sir, zaslađene napitke, kafu sa sirupom/šećerom — "
            "često ti ukradu deficit.\n\n"
            "Tvoj zadatak je da pošteno i približno opišeš hranu. Moj zadatak je da procenim kalorije "
            "i pokažem ti sliku celog dana 💪"
        )


# ================================
# HUGGINGFACE: АНАЛИЗ ПРИЁМА ПИЩИ
# ================================

def ask_ai_meal_analysis(meal_text, lang):
    """
    Отправляем ИИ описание еды, он:
    - разбирает по продуктам,
    - даёт приблизительные калории по каждому,
    - в конце отдельной строкой пишет: 'TOTAL_KCAL: XXX'
    Возвращаем (explanation_text, total_kcal) или (None, None).
    """
    if not AI_ENDPOINT or not AI_KEY:
        return None, None

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    if lang == "ru":
        system_prompt = (
            "Ты дружелюбный нутриционист. Тебе дают описание приёма пищи обычным человеческим языком.\n"
            "Твоя задача:\n"
            "1) Разбить приём пищи на основные компоненты (2–7 пунктов) — хлеб, мясо, гарнир, соусы, кофе и т.п.\n"
            "2) Для каждого компонента указать примерную калорийность.\n"
            "3) В конце посчитать суммарную калорийность этого приёма пищи.\n\n"
            "Пиши коротко, по делу, с лёгкой поддержкой и мотивацией.\n\n"
            "Формат ответа:\n"
            "- Сначала текст с разбором (список продуктов и калорий).\n"
            "- В САМОМ КОНЦЕ отдельная строка строго в формате:\n"
            "TOTAL_KCAL: XXX\n"
            "где XXX — общее количество ккал (целое число). Не пиши ничего после этой строки."
        )
    elif lang == "en":
        system_prompt = (
            "You are a friendly nutritionist. You receive a description of a meal in natural language.\n"
            "Your tasks:\n"
            "1) Break the meal into main components (2–7 items) — bread, meat, side dish, sauces, coffee, etc.\n"
            "2) Give an approximate calorie value for each component.\n"
            "3) At the end, calculate the total kcal for the entire meal.\n\n"
            "Write briefly, clearly and with light support/motivation.\n\n"
            "Response format:\n"
            "- First, a short explanation with the breakdown (list of foods and their kcal).\n"
            "- At the VERY END, a separate line in this exact format:\n"
            "TOTAL_KCAL: XXX\n"
            "where XXX is the total kcal (integer). Do not write anything after this line."
        )
    else:
        system_prompt = (
            "Ti si prijateljski nutricionista. Dobijaš opis obroka na prirodnom jeziku.\n"
            "Tvoj zadatak:\n"
            "1) Podeli obrok na glavne komponente (2–7 stavki) — hleb, meso, prilog, sosevi, kafa itd.\n"
            "2) Za svaku komponentu daj približnu kalorijsku vrednost.\n"
            "3) Na kraju izračunaj ukupan broj kalorija za ceo obrok.\n\n"
            "Piši kratko, jasno, uz blagu podršku i motivaciju.\n\n"
            "Format odgovora:\n"
            "- Prvo kratko objašnjenje sa spiskom namirnica i njihovim kcal.\n"
            "- NA SAMOM KRAJU posebna linija u formatu:\n"
            "TOTAL_KCAL: XXX\n"
            "gde je XXX ukupan broj kcal (ceo broj). Ne piši ništa posle ove linije."
        )

    user_text = meal_text

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.4,
        "max_tokens": 512,
    }

    try:
        r = requests.post(AI_ENDPOINT, headers=headers, json=payload, timeout=60)
        data = r.json()
        content = data["choices"][0]["message"]["content"]

        m = re.search(r"TOTAL_KCAL:\s*(\d+(?:\.\d+)?)", content)
        if not m:
            return None, None
        total_kcal = float(m.group(1))

        lines = content.strip().splitlines()
        cleaned_lines = [ln for ln in lines if not ln.strip().upper().startswith("TOTAL_KCAL:")]
        explanation = "\n".join(cleaned_lines).strip()

        return explanation, total_kcal
    except Exception as e:
        print("AI meal analysis error:", e)
        return None, None


# ================================
# FOOD / UNITS LOGIC (для определения, что это еда)
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
    t = text.lower().replace(",", ".")
    kg_match = re.findall(r"(\d+(\.\d+)?)\s*(kg|кг)", t)
    if kg_match:
        val = float(kg_match[0][0])
        return val * 1000
    g_match = re.findall(r"(\d+(\.\d+)?)\s*(g|гр|г|gram)", t)
    if g_match:
        val = float(g_match[0][0])
        return val
    ml_match = re.findall(r"(\d+(\.\d+)?)\s*(ml|мл|l|литр)", t)
    if ml_match:
        val = float(ml_match[0][0])
        return val
    return None


def is_food_message(text):
    t = text.lower()
    food_words = [
        "бурек", "burek", "burger", "бургер", "пиц", "pizza", "сыр", "cheese",
        "яичн", "яйцо", "jaje", "egg", "omelette", "греч", "rice", "рис", "chicken", "куриц", "piletina",
        "пюре", "puree", "pire", "kartof", "картоф", "krompir",
        "pljeskavica", "ćevap", "ćevapi", "cevapi",
        "salad", "салат", "salata",
        "шницел", "шницель", "šnicl", "gyros", "донер", "kebab",
        "pasulj", "grašak", "sarma",
        "coffee", "kafa", "кофе", "чай", "tea"
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

    def find_int_by_keywords(keywords):
        for kw in keywords:
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

    sex = "m"
    if " ж" in t or "жен" in t or " f" in t or "female" in t:
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
            "Логика простая:\n"
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

    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else "ru")
    T = TEXT.get(lang, TEXT["ru"])

    # /start
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
        send_message(chat_id, build_logging_instructions(lang))
        return "OK"

    # попытка распарсить профиль
    parsed_prof = parse_profile(text_stripped)
    if parsed_prof:
        save_profile(chat_id, {"lang": lang, **parsed_prof})
        profile = get_profile(chat_id)
        explanation = build_profile_explanation(profile, lang)
        send_message(chat_id, explanation)
        send_message(chat_id, build_logging_instructions(lang))
        return "OK"

    # обновим профиль/язык ещё раз
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else lang)
    T = TEXT.get(lang, TEXT["ru"])

    essential_keys = ["age", "height", "weight", "goal", "activity_factor", "sex"]
    has_full_profile = bool(profile and all(profile.get(k) is not None for k in essential_keys))

    # не похоже на еду
    if not is_food_message(text_stripped):
        if not has_full_profile:
            send_message(chat_id, T["need_profile_first"])
        else:
            send_message(chat_id, build_logging_instructions(lang))
        return "OK"

    # ===== РЕЖИМ ЕДЫ: полный анализ через ИИ =====
    breakdown_text, total_kcal = ask_ai_meal_analysis(text_stripped, lang)

    if not breakdown_text or not total_kcal or total_kcal <= 0:
        send_message(chat_id, T["need_details"])
        return "OK"

    kcal = round(total_kcal)

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
            f"Оценка: ~{kcal} ккал\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(max(left, 0))}"
        )
    elif lang == "en":
        base_reply = (
            f"{T['meal_count'].format(meal_number)}\n"
            f"{text_stripped}\n"
            f"Estimate: ~{kcal} kcal\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(max(left, 0))}"
        )
    else:
        base_reply = (
            f"{T['meal_count'].format(meal_number)}\n"
            f"{text_stripped}\n"
            f"Procena: ~{kcal} kcal\n\n"
            f"{T['daily_total'].format(new_total)}\n"
            f"{T['daily_left'].format(max(left, 0))}"
        )

    # если профиля нет — подсказка
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

    # анализ переедания
    if has_full_profile and new_total > target:
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
                "Nije smak sveta, ali ako se ovo često ponavlja, kilaža će polako rasti.\n\n"
                "Savet: sutra možeš da napraviš mali dodatni deficit (oko 100–200 kcal ispod norme) "
                "tako što ćeš smanjiti slatkiše i grickalice i ubaciti malo više kretanja. "
                "Bez izgladnjivanja — samo lagano poravnanje balansa 👍"
            )
        base_reply += over_text

    # финальный ответ: сначала разбор от ИИ, потом сводка по дню
    reply = f"{breakdown_text}\n\n{base_reply}"

    send_message(chat_id, reply)
    return "OK"


@app.route("/", methods=["GET"])
def home():
    return "AI Calories Bot with Supabase is running!"
