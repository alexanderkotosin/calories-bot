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

# Максимальный разумный колораж на один приём
MEAL_KCAL_CAP = 1500


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
            "Давай настроим твой профиль, чтобы я мог точнее считать калории.\n\n"
            "Активность:\n"
            "• низкая — сидячая работа, мало шагов, нет тренировок;\n"
            "• средняя — 2–3 тренировки в неделю и/или 8–10k шагов в день;\n"
            "• высокая — тяжёлый физический труд или 4+ интенсивных тренировок в неделю.\n"
        ),
        "profile_template": (
            "Скопируй этот шаблон, вставь в чат и заполни своими данными:\n\n"
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
            "Это обычная физика: когда ты ешь больше, чем тратишь, лишняя энергия откладывается в жир. "
            "Когда ешь немного меньше, чем тратишь — тело берёт недостающее из запасов.\n"
        ),
        "profile_kcal_line": (
            "Твоя дневная норма для здорового дефицита: примерно {kcal} ккал в день."
        ),
        "meal_input_help": (
            "Теперь можно вносить еду. Как описывать приём пищи, чтобы я считал точнее:\n\n"
            "• Пиши простым языком, без формальностей.\n"
            "• Указывай ПРОСТО ПРИМЕРНЫЕ количества, не нужны точные граммы.\n\n"
            "Примеры:\n"
            "• \"2 ломтика хлеба из цельного зерна, 2 яйца, немного сыра, чай без сахара\".\n"
            "• \"Куриная грудка примерно 150–200 г, 150 г риса, салат из огурцов и помидоров, "
            "1 столовая ложка оливкового масла\".\n"
            "• \"Бургер из кафе, средняя картошка фри, 2 чайные ложки кетчупа, "
            "капучино 300 мл с молоком 1,5%, без сахара\".\n\n"
            "Важно:\n"
            "• Учитывай соусы (кетчуп, майонез, йогуртовые соусы, масло).\n"
            "• Учитывай калорийные напитки (сладкая газировка, сок, алкоголь, кофе с молоком/сиропом).\n"
            "• Если не знаешь граммы — пиши \"кусок\", \"тарелка\", \"стакан\", \"ложка\" — я оценю по опыту.\n\n"
            "⚠ Одно сообщение = один приём пищи. Не скидывай весь день одним списком, лучше раздели."
        ),
        "ai_disclaimer": (
            "ℹ Я использую бесплатную модель искусственного интеллекта на Hugging Face. "
            "Это приближённый расчёт, а не медицинский инструмент.\n\n"
            "Что должно вызывать подозрение:\n"
            "• полный приём пищи меньше 100 ккал или больше 1500 ккал (если это не ад из пиццы и алкоголя);\n"
            "• очень большие числа у одного продукта (например, \"кусочек сыра\" 800 ккал);\n"
            "• напитки и соусы явно были, но в разборе их нет.\n\n"
            "Если что-то выглядит странно — лучше перепроверь и прикинь здравым смыслом 😊"
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
            "Я не смог нормально разобрать этот приём пищи. "
            "Обычно это случается, если слишком мало деталей или всё в одну строку без структуры.\n\n"
            "Попробуй ещё раз: перечисли продукты и примерные порции — по одному-двум блюдам в строке."
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
            "Не драма, такое бывает 🙂 На завтра рекомендация: немного урезать калории "
            "(–200–300 ккал от нормы) или добавить движения, чтобы вернуть средний дефицит."
        ),
        "meal_cap_note": (
            "\n\n⚠ Сработала защита от завышенных оценок: ИИ насчитал около {raw_kcal} ккал за этот приём, "
            "но я ограничил значение до {cap_kcal} ккал.\n"
            "Если ты вносишь еду за целый день, разбей её на несколько сообщений: "
            "одно сообщение = один приём пищи."
        ),
        "help": (
            "Я помогу вести учёт калорий и видеть картину дня.\n\n"
            "Основные команды:\n"
            "• /start — начало, выбор языка и настройка профиля.\n"
            "• /status — показать твою норму, текущий дневник и остаток по калориям.\n"
            "• /calc — то же самое, плюс краткое напоминание про дефицит.\n"
            "• /reset — сброс калорий за сегодня (начать день заново).\n"
            "• /weight — как обновить вес.\n"
            "• /height — как обновить рост.\n"
            "• /age — как обновить возраст.\n\n"
            "Дальше просто присылай, что ты съел(а), в свободной форме — я разберу, "
            "оценю калории и покажу остаток до дневной нормы."
        ),
        "status_no_profile": "Профиль ещё не настроен. Нажми /start и заполни шаблон профиля.",
        "status": (
            "Твой профиль:\n"
            "• возраст: {age}\n"
            "• рост: {height} см\n"
            "• вес: {weight} кг\n"
            "• цель: {goal} кг\n"
            "• активность-фактор: {activity}\n"
            "• пол: {sex}\n\n"
            "Дневная норма (здоровый дефицит): {target_kcal} ккал.\n"
            "Съедено сегодня: {total_kcal} ккал.\n"
            "Осталось до лимита: {left_kcal} ккал."
        ),
        "reset_done": "Дневной учёт калорий за сегодня обнулён. Можно начинать новый день 😊",
        "cmd_weight_hint": (
            "Чтобы обновить вес, просто пришли сообщение в формате:\n"
            "«Вес 87» или «Вес 90» — я обновлю профиль и пересчитаю норму."
        ),
        "cmd_height_hint": (
            "Чтобы обновить рост, пришли сообщение:\n"
            "«Рост 181» (или другой рост в сантиметрах)."
        ),
        "cmd_age_hint": (
            "Чтобы обновить возраст, пришли сообщение:\n"
            "«Возраст 35» (или другой возраст)."
        ),
        "calc_hint": (
            "Напоминание: дефицит калорий — это когда ты системно ешь немного меньше, чем тратишь.\n"
            "Я уже заложил умеренный дефицит в твою норму. Главное — смотреть на среднюю картину по неделе, "
            "а не зацикливаться на одном дне."
        ),
    },
    # Для краткости: en/sr попроще, но с той же логикой
    "en": {
        "profile_intro": (
            "Let’s set up your profile so I can track calories correctly.\n\n"
            "Activity:\n"
            "• low – desk job, few steps, no workouts;\n"
            "• medium – 2–3 workouts per week and/or ~8–10k steps per day;\n"
            "• high – hard physical work or 4+ intense workouts per week.\n"
        ),
        "profile_template": (
            "Copy, paste and fill in your data:\n\n"
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
            "It’s basic physics: if you eat more than you burn, extra energy is stored as fat; "
            "if you eat a bit less, your body uses stored energy.\n"
        ),
        "profile_kcal_line": (
            "Your daily target for a healthy deficit is about {kcal} kcal."
        ),
        "meal_input_help": (
            "Now you can log meals. How to describe food so I can estimate more accurately:\n\n"
            "• Use simple language.\n"
            "• Rough amounts are enough, no need for exact grams.\n\n"
            "Examples:\n"
            "• \"2 slices of wholegrain bread, 2 eggs, some cheese, tea without sugar\".\n"
            "• \"Chicken breast around 150–200 g, 150 g rice, salad with cucumbers and tomatoes, "
            "1 tbsp olive oil\".\n"
            "• \"Cafe burger, medium fries, 2 tsp ketchup, cappuccino 300 ml with 1.5% milk, no sugar\".\n\n"
            "Important:\n"
            "• Include sauces (ketchup, mayo, yogurt sauces, oil).\n"
            "• Include drinks with calories (soda, juice, alcohol, coffee with milk/syrup).\n"
            "• If you don’t know grams, write \"piece\", \"plate\", \"cup\", \"spoon\" – I’ll estimate.\n\n"
            "⚠ One message = one meal. Don’t send the whole day in one message."
        ),
        "ai_disclaimer": (
            "ℹ I use a free AI model on Hugging Face. This is an approximate estimate, "
            "not a medical tool.\n\n"
            "Be suspicious if:\n"
            "• a full meal is <100 kcal or >1500 kcal (unless it’s a crazy mix of pizza + alcohol);\n"
            "• a single item has huge calories (like \"a piece of cheese\" = 800 kcal);\n"
            "• drinks/sauces were clearly there but missing from the breakdown.\n\n"
            "If something looks off – double-check with common sense 🙂"
        ),
        "need_profile_first": (
            "Looks like your profile isn’t set up yet.\n\n"
            "Send /start, choose language and fill the short profile so I can track calories 👌"
        ),
        "ask_meal_brief": (
            "To calculate calories, describe the meal: what you ate and roughly how much.\n\n"
            "Example: \"2 slices of bread, omelette from 2 eggs, some cheese, tea without sugar\"."
        ),
        "cannot_parse_meal": (
            "I couldn’t clearly understand this meal. Usually it happens when everything "
            "is in one line without structure.\n\n"
            "Please try again and list items with approximate portions."
        ),
        "meal_header": "Meal breakdown:",
        "daily_summary": (
            "\n\nThis meal: {meal_kcal} kcal.\n"
            "Total today: {total_kcal} kcal.\n"
            "Your daily target (healthy deficit): {target_kcal} kcal.\n"
            "Remaining today: {left_kcal} kcal."
        ),
        "daily_overeat": (
            "\n\nYou went over daily target by about {over_kcal} kcal.\n"
            "It’s okay 🙂 Try to slightly reduce calories tomorrow (–200–300 kcal) "
            "or move a bit more to keep a weekly deficit."
        ),
        "meal_cap_note": (
            "\n\n⚠ A safety cap triggered: AI estimated about {raw_kcal} kcal for this meal, "
            "but I limited it to {cap_kcal} kcal.\n"
            "If you log food for the whole day, split it into several messages: "
            "one message = one meal."
        ),
        "help": (
            "I help you track calories and see your day.\n\n"
            "Commands:\n"
            "• /start – language & profile setup.\n"
            "• /status – your profile, daily target and today’s summary.\n"
            "• /calc – same as /status plus a short reminder about deficit.\n"
            "• /reset – reset today’s calories.\n"
            "• /weight – how to update weight.\n"
            "• /height – how to update height.\n"
            "• /age – how to update age.\n"
        ),
        "status_no_profile": "Profile is not set yet. Send /start and fill it first.",
        "status": (
            "Your profile:\n"
            "• age: {age}\n"
            "• height: {height} cm\n"
            "• weight: {weight} kg\n"
            "• goal: {goal} kg\n"
            "• activity factor: {activity}\n"
            "• sex: {sex}\n\n"
            "Daily target (healthy deficit): {target_kcal} kcal.\n"
            "Eaten today: {total_kcal} kcal.\n"
            "Remaining today: {left_kcal} kcal."
        ),
        "reset_done": "Today’s calorie log has been reset. Fresh start 😊",
        "cmd_weight_hint": (
            "To update your weight, just send a message like:\n"
            "\"Weight 87\" – I will update your profile and recalculate the target."
        ),
        "cmd_height_hint": "To update your height, send: \"Height 181\".",
        "cmd_age_hint": "To update your age, send: \"Age 35\".",
        "calc_hint": (
            "Reminder: a calorie deficit means you consistently eat a bit less than you burn. "
            "I already include a moderate deficit in your target. Focus on weekly averages, "
            "not a single day."
        ),
    },
    "sr": {
        "profile_intro": (
            "Hajde da podesimo tvoj profil da bih tačnije računao kalorije.\n\n"
            "Aktivnost:\n"
            "• niska – kancelarijski posao, malo koraka, bez treninga;\n"
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
            "kad malo ne dostižeš normu, telo troši rezerve.\n"
        ),
        "profile_kcal_line": (
            "Tvoja dnevna norma za zdrav deficit je oko {kcal} kcal."
        ),
        "meal_input_help": (
            "Sada možeš da unosiš obroke. Kako da opišeš obrok da bih mogao tačnije da izračunam:\n\n"
            "• Piši jednostavnim jezikom.\n"
            "• Dovoljne su približne količine, ne moraju tačni grami.\n\n"
            "Primeri:\n"
            "• \"2 parčeta hleba od celog zrna, 2 jajeta, malo sira, čaj bez šećera\".\n"
            "• \"Piletina na žaru oko 150–200 g, 150 g pirinča, salata od krastavca i paradajza, "
            "1 kašika maslinovog ulja\".\n"
            "• \"Burger iz kafića, srednji pomfrit, 2 kašičice kečapa, "
            "kapućino 300 ml sa mlekom 1,5%, bez šećera\".\n\n"
            "Važno:\n"
            "• Računaj sosove (kečap, majonez, jogurt-sosovi, ulje).\n"
            "• Računaj pića sa kalorijama (slatke gazirane, sok, alkohol, kafa sa mlekom/sirupom).\n"
            "• Ako ne znaš grame, piši \"parče\", \"tanjir\", \"šolja\", \"kašika\" – proceniću.\n\n"
            "⚠ Jedna poruka = jedan obrok. Nemoj ceo dan u jednoj poruci."
        ),
        "ai_disclaimer": (
            "ℹ Koristim besplatni AI model na Hugging Face-u. Ovo je približna procena, "
            "ne medicinski alat.\n\n"
            "Sumnjivo je ako:\n"
            "• ceo obrok ima <100 kcal ili >1500 kcal (osim ako nije ludilo od pice i alkohola);\n"
            "• jedna stavka ima ogromno mnogo kcal;\n"
            "• pića i sosovi nisu uračunati.\n"
            "Ako nešto deluje čudno – proveri zdravim razumom 🙂"
        ),
        "need_profile_first": (
            "Izgleda da profil još nije podešen.\n\n"
            "Pošalji /start, izaberi jezik i popuni kratak profil da bih mogao da računam kalorije 👌"
        ),
        "ask_meal_brief": (
            "Da izračunam kalorije, opiši obrok: šta si jeo/la i otprilike koliko.\n\n"
            "Primer: \"2 parčeta hleba, omlet od 2 jajeta, malo sira, čaj bez šećera\"."
        ),
        "cannot_parse_meal": (
            "Nisam uspeo jasno da razumem ovaj obrok. Pokušaj opet, sa više detalja i "
            "posebnim nabrajanjem stavki."
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
            "Nije strašno 🙂 Pokušaj sutra malo da smanjiš unos ili da se više krećeš."
        ),
        "meal_cap_note": (
            "\n\n⚠ Uključena je zaštita od previsokih procena: AI je izračunao oko {raw_kcal} kcal, "
            "ali sam ograničio na {cap_kcal} kcal.\n"
            "Ako unosiš ceo dan odjednom, podeli obroke u više poruka."
        ),
        "help": (
            "Pomažem ti da pratiš kalorije i vidiš dnevnu sliku.\n\n"
            "Komande:\n"
            "• /start – jezik i podešavanje profila.\n"
            "• /status – profil + današnji rezime.\n"
            "• /calc – isto, uz kratko objašnjenje deficita.\n"
            "• /reset – reset današnjih kalorija.\n"
            "• /weight, /height, /age – kako da ažuriraš podatke.\n"
        ),
        "status_no_profile": "Profil još nije podešen. Pošalji /start.",
        "status": (
            "Tvoj profil:\n"
            "• godine: {age}\n"
            "• visina: {height} cm\n"
            "• težina: {weight} kg\n"
            "• cilj: {goal} kg\n"
            "• faktor aktivnosti: {activity}\n"
            "• pol: {sex}\n\n"
            "Dnevna norma (zdrav deficit): {target_kcal} kcal.\n"
            "Ukupno danas: {total_kcal} kcal.\n"
            "Preostalo danas: {left_kcal} kcal."
        ),
        "reset_done": "Današnji unos kalorija je poništen. Novi početak 😊",
        "cmd_weight_hint": "Za ažuriranje težine pošalji: \"Težina 88\".",
        "cmd_height_hint": "Za ažuriranje visine pošalji: \"Visina 181\".",
        "cmd_age_hint": "Za ažuriranje godina pošalji: \"Godine 34\".",
        "calc_hint": (
            "Deficit kalorija znači da malo manje jedeš nego što trošiš. "
            "Norma već uključuje blagi deficit. Gledaj proseke po nedelji."
        ),
    },
}


# ================================
# HF ROUTER CHAT HELPER
# ================================


def call_hf_chat(system_prompt, user_prompt, response_format_json=False):
    """
    Вызов Hugging Face Router в формате /v1/chat/completions.
    Возвращает message.content или None.
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


def reset_diary_today(user_id):
    day = get_today_key()
    supabase_upsert("diary_days", {
        "user_id": user_id,
        "day": day,
        "total_kcal": 0,
    })


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
    Формат: строки с ключевыми словами + число.
    """
    t = text.lower()

    def find_int(labels):
        pattern = r"(" + "|".join([re.escape(l) for l in labels]) + r")\s*[:\-]?\s*(\d+)"
        m = re.search(pattern, t)
        if not m:
            return None
        return int(m.group(2))

    age = find_int(["возраст", "age", "godine"])
    height = find_int(["рост", "height", "visina"])
    weight = find_int(["вес", "weight", "težina", "tezina"])
    goal = find_int(["цель вес", "цель", "goal weight", "goal", "ciljna težina", "ciljna tezina"])

    sex = None
    if re.search(r"\bж\b|female|f|ž\b|z\b", t):
        sex = "f"
    elif re.search(r"\bм\b|male|m", t):
        sex = "m"

    if "низк" in t or "low" in t or "niska" in t:
        activity = 1.2
    elif "средн" in t or "medium" in t or "srednja" in t:
        activity = 1.35
    elif "высок" in t or "high" in t or "visoka" in t:
        activity = 1.6
    else:
        activity = None

    if all([age, height, weight, goal, sex, activity]):
        return {
            "age": age,
            "height": float(height),
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
    "бурек", "burek", "пиц", "pizza", "пицца",
    "burger", "бургер", "хлеб", "bread",
    "rice", "рис", "картоф", "potato", "фри",
    "яйц", "egg", "omlet", "omelet", "омлет",
    "куриц", "chicken", "говядин", "beef", "свинин", "pork",
    "сыр", "cheese", "йогурт", "yogurt",
    "салат", "salad", "овощ", "овощи", "povrće", "povrce",
    "каша", "греч", "oat", "овсян",
    "кофе", "kafa", "капуч", "cappuccino",
    "чай", "tea", "сок", "juice",
    "пиво", "beer", "vino", "вино",
    "бурито", "tortilla", "wrap", "шаурм", "gyros", "донер", "kebab",
]


def looks_like_meal(text):
    t = text.lower().strip()
    if not t:
        return False
    if t.startswith("/"):
        return False
    if t in ("1", "2", "3"):
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
            "Ты нутриционист. По описанию приёма пищи оцени калории.\n"
            "1) Разбей текст на конкретные элементы (блюда/продукты).\n"
            "2) Для каждого элемента оцени калории (kcal) для указанной порции.\n"
            "3) Посчитай итоговую сумму калорий для этого приёма пищи.\n"
            "4) Используй реалистичные значения: обычный приём пищи взрослого человека "
            "обычно в диапазоне 100–1500 ккал. Если явно описан целый день или очень много еды/алкоголя, "
            "сумма может быть выше, но старайся не завышать без причины.\n"
            "5) Если информации мало или всё очень примерное — сделай лучшую оценку, "
            "НЕ задавай уточняющих вопросов.\n\n"
            "Ответ верни строго в формате JSON:\n"
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
            "1) Split it into specific items.\n"
            "2) For each item, estimate kcal for the given portion.\n"
            "3) Compute total kcal for this meal.\n"
            "4) Use realistic values: a typical adult meal is ~100–1500 kcal. "
            "If clearly described as a full day or huge binge, it can be higher, "
            "but avoid unreasonable overestimates.\n"
            "5) If information is approximate, still give your best estimate, "
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
            "3) Izračunaj ukupne kalorije za ovaj obrok.\n"
            "4) Koristi realne vrednosti: tipičan obrok odrasle osobe je oko 100–1500 kcal. "
            "Ako je jasno da je opisan ceo dan ili ekstremno mnogo hrane/alkohola, "
            "ukupno može biti više, ali izbegavaj preterivanje.\n"
            "5) Ako je opis približan, ipak daj najbolju procenu, BEZ dodatnih pitanja.\n\n"
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

    user_prompt = f"Opis obroka / meal description:\n{user_text}\n\nVrati только JSON."

    raw = call_hf_chat(system_prompt, user_prompt, response_format_json=True)
    if raw is None:
        return None

    data = None
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except Exception:
            try:
                start = raw.find("{")
                end = raw.rfind("}")
                if start != -1 and end != -1 and end > start:
                    data = json.loads(raw[start: end + 1])
            except Exception:
                data = None

    if not isinstance(data, dict):
        print("AI JSON parse failed, raw:", raw)
        return None

    items = data.get("items") or []
    total = data.get("total_kcal")

    try:
        if total is None or float(total) <= 0:
            total = sum(float(i.get("kcal") or 0) for i in items)
        total = float(total)
    except Exception:
        return None

    if total <= 0 or total > 20000:
        return None

    comment = data.get("comment") or ""
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

    # /start — выбор языка
    if text.lower() == "/start":
        send_message(chat_id, LANG_CHOICES_TEXT)
        return "OK"

    # команды помощи и статуса, не зависят от языка
    if text.lower() == "/help":
        send_message(chat_id, T["help"])
        send_message(chat_id, T["ai_disclaimer"])
        return "OK"

    # выбор языка 1/2/3
    if text in ("1", "2", "3"):
        lang_map = {"1": "ru", "2": "en", "3": "sr"}
        lang = lang_map[text]
        save_profile(chat_id, {"lang": lang})
        T = TEXT[lang]
        send_message(chat_id, T["profile_intro"])
        send_message(chat_id, T["profile_template"])
        return "OK"

    # попытка распарсить профиль
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
        send_message(chat_id, T["ai_disclaimer"])
        return "OK"

    # обновим профиль ещё раз (вдруг уже есть)
    profile = get_profile(chat_id)
    lang = (profile.get("lang") if profile and profile.get("lang") else lang)
    T = TEXT.get(lang, TEXT["ru"])

    essential_keys = ["age", "height", "weight", "goal", "activity_factor", "sex"]
    has_full_profile = bool(profile and all(profile.get(k) is not None for k in essential_keys))

    # команды, зависящие от профиля
    if text.lower() == "/status" or text.lower() == "/calc":
        if not has_full_profile:
            send_message(chat_id, T["status_no_profile"])
            return "OK"
        target = calc_target_kcal(profile)
        today = get_today_key()
        diary = get_diary(chat_id, today)
        total = diary.get("total_kcal") or 0
        left = target - total
        sex = profile.get("sex") or "m"
        sex_label = {"m": "м", "f": "ж"}.get(sex, sex)
        status_text = T["status"].format(
            age=int(profile["age"]),
            height=int(profile["height"]),
            weight=float(profile["weight"]),
            goal=float(profile["goal"]),
            activity=float(profile["activity_factor"]),
            sex=sex_label,
            target_kcal=target,
            total_kcal=total,
            left_kcal=left,
        )
        send_message(chat_id, status_text)
        if text.lower() == "/calc":
            send_message(chat_id, T["calc_hint"])
        return "OK"

    if text.lower() == "/reset":
        if not has_full_profile:
            send_message(chat_id, T["status_no_profile"])
            return "OK"
        reset_diary_today(chat_id)
        send_message(chat_id, T["reset_done"])
        return "OK"

    if text.lower() == "/weight":
        send_message(chat_id, T["cmd_weight_hint"])
        return "OK"

    if text.lower() == "/height":
        send_message(chat_id, T["cmd_height_hint"])
        return "OK"

    if text.lower() == "/age":
        send_message(chat_id, T["cmd_age_hint"])
        return "OK"

    # если профиль не заполнен — отказываемся считать
    if not has_full_profile:
        send_message(chat_id, T["need_profile_first"])
        return "OK"

    # дальше — логика еды
    if not looks_like_meal(text):
        # если это не похоже на еду — мягко возвращаем к формату
        send_message(chat_id, T["ask_meal_brief"])
        return "OK"

    analysis = ai_meal_analysis(text, lang)
    if not analysis:
        send_message(chat_id, T["cannot_parse_meal"])
        send_message(chat_id, T["meal_input_help"])
        return "OK"

    meal_kcal_raw = analysis["total_kcal"]
    items = analysis["items"]
    comment = analysis.get("comment") or ""

    # лимит 1500 ккал на один приём
    meal_kcal = meal_kcal_raw
    cap_triggered = False
    if meal_kcal > MEAL_KCAL_CAP:
        cap_triggered = True
        meal_kcal = MEAL_KCAL_CAP

    today = get_today_key()
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

    if cap_triggered:
        reply += T["meal_cap_note"].format(
            raw_kcal=meal_kcal_raw,
            cap_kcal=MEAL_KCAL_CAP,
        )

    if left < 0:
        over = abs(left)
        reply += T["daily_overeat"].format(over_kcal=over)

    send_message(chat_id, reply)
    return "OK"


@app.route("/", methods=["GET"])
def home():
    return "AI Calories Bot with HF Router is running!"
