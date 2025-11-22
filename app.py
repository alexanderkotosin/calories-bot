import os
import re
import time
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# === Конфиг из окружения ===
TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_API = f"https://api.telegram.org/bot{TOKEN}"

AI_ENDPOINT = os.getenv("AI_ENDPOINT", "")
AI_KEY = os.getenv("AI_KEY", "")

# === Память в рантайме ===
profiles = {}     # profiles[user_id] = {...}
diary = {}        # diary[user_id] = {...}
user_lang = {}    # user_lang[user_id] = 'ru' | 'en' | 'sr'
user_state = {}   # user_state[user_id] = 'lang_choice' | 'idle'


# ========= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def today_key():
    # можно потом заменить на локальное время
    return time.strftime("%Y%m%d", time.gmtime())


def ensure_diary(user_id):
    """
    Инициализация дневника на сегодня.
    Профиль не трогаем, только дневной учёт.
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


def get_lang(user_id):
    # по умолчанию – английский, пока не выбрали
    return user_lang.get(user_id, "en")


def calc_profile_numbers(profile):
    """Расчёт BMR, калорий на поддержание и дефицит ~20%."""
    age = profile["age"]
    weight = profile["weight"]
    height = profile["height"]
    sex = profile["sex"]
    activity_factor = profile["activity_factor"]

    # Миффлин — Сан Жеор
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
    Парсим профиль RU / EN / SR.
    Формат: возраст/age/godine, рост/height/visina, вес/weight/težina, цель/goal/cilj, активность.
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
    act_factor = 1.35  # средняя
    t = text.lower()

    if re.search(r'низк|сидяч|low|sedentary|nizak', t):
        act_factor = 1.2
    elif re.search(r'высок|очень актив|high|very active|visok', t):
        act_factor = 1.55
    elif re.search(r'умеренн|moderate|medium|srednj', t):
        act_factor = 1.35

    # пока фиксируем пол
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
    Пользователь может просто написать число в конце:
    '... 420' -> считаем 420 ккал.
    Или '420 ккал', '420 kcal', '420 кк', '420 kk'.
    Берём ПОСЛЕДНЕЕ число.
    """
    nums = re.findall(r'(\d+)\s*(?:ккал|kcal|кк|kk)?', text, re.IGNORECASE)
    if not nums:
        return None
    return float(nums[-1])


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


# ========= ТЕКСТЫ ДЛЯ 3 ЯЗЫКОВ ==========

def language_choice_text():
    # показываем всегда на трёх, до выбора языка
    return (
        "Choose your language / Выбери язык / Izaberi jezik:\n\n"
        "1️⃣ English 🇬🇧\n"
        "2️⃣ Русский 🇷🇺\n"
        "3️⃣ Srpski 🇷🇸\n\n"
        "Send 1, 2 or 3.\n"
        "Отправь 1, 2 или 3.\n"
        "Pošalji 1, 2 ili 3."
    )


def profile_template(lang: str):
    if lang == "ru":
        return (
            "Вот шаблон профиля. Скопируй его, подставь свои цифры и пришли одним сообщением:\n\n"
            "Возраст: 34\n"
            "Рост: 181\n"
            "Вес: 86\n"
            "Цель: 84\n"
            "Активность: средняя  (варианты: низкая / средняя / высокая)\n"
        )
    if lang == "sr":
        return (
            "Evo šablona profila. Kopiraj ga, ubaci svoje brojeve i pošalji u jednoj poruci:\n\n"
            "Godine: 34\n"
            "Visina: 181\n"
            "Težina: 86\n"
            "Cilj: 84\n"
            "Aktivnost: srednja  (opcije: niska / srednja / visoka)\n"
        )
    # default en
    return (
        "Here is your profile template. Copy it, insert your numbers and send as one message:\n\n"
        "Age: 34\n"
        "Height: 181\n"
        "Weight: 86\n"
        "Goal: 84\n"
        "Activity: moderate  (options: low / moderate / high)\n"
    )


def after_language_selected_intro(lang: str):
    if lang == "ru":
        return (
            "Я запомнил язык: русский 🇷🇺\n\n"
            "Сейчас вышлю шаблон профиля. Твоя задача:\n"
            "1) Скопировать шаблон.\n"
            "2) Подставить свои цифры.\n"
            "3) Отправить его мне одним сообщением.\n\n"
            "После этого я посчитаю твою норму калорий и дефицит."
        )
    if lang == "sr":
        return (
            "Zapamtio sam jezik: srpski 🇷🇸\n\n"
            "Sada šaljem šablon profila. Tvoj zadatak:\n"
            "1) Kopiraj šablon.\n"
            "2) Ubaci svoje brojeve.\n"
            "3) Pošalji mi ga kao jednu poruku.\n\n"
            "Posle toga ću izračunati tvoju dnevnu normu kalorija i deficit."
        )
    # en
    return (
        "Got it, language set to English 🇬🇧\n\n"
        "Now I’ll send you a profile template. Your steps:\n"
        "1) Copy the template.\n"
        "2) Insert your numbers.\n"
        "3) Send it back as a single message.\n\n"
        "After that I’ll calculate your daily calories and deficit."
    )


def profile_parse_error_text(lang: str):
    if lang == "ru":
        return (
            "Не смог разобрать профиль 😅\n\n"
            "Сделай так:\n"
            "1) Возьми шаблон.\n"
            "2) Просто подставь свои цифры вместо примеров.\n"
            "3) Отправь одним сообщением.\n\n"
            + profile_template("ru")
        )
    if lang == "sr":
        return (
            "Nisam uspeo da pročitam profil 😅\n\n"
            "Uradi ovako:\n"
            "1) Uzmi šablon.\n"
            "2) Ubaci svoje brojeve umesto primera.\n"
            "3) Pošalji kao jednu poruku.\n\n"
            + profile_template("sr")
        )
    # en
    return (
        "I couldn’t read your profile 😅\n\n"
        "Do this:\n"
        "1) Take the template.\n"
        "2) Replace the numbers with your own.\n"
        "3) Send it as one message.\n\n"
        + profile_template("en")
    )


def off_topic_text(lang: str):
    if lang == "ru":
        return (
            "Кажется, это не очень похоже на приём пищи 😅\n\n"
            "Я бот по учёту калорий. Напиши, пожалуйста, что ты ел/ела "
            "(пример: 'куриная грудка 150г, рис 100г, салат'), "
            "или вызови /status, чтобы увидеть сводку дня."
        )
    if lang == "sr":
        return (
            "Izgleda da ova poruka nije baš obrok 😅\n\n"
            "Ja sam bot za kalorije. Napiši šta si jeo/la "
            "(primer: 'pileća prsa 150g, pirinač 100g, salata'), "
            "ili pošalji /status za današnji rezime."
        )
    # en
    return (
        "This doesn’t really look like a meal 😅\n\n"
        "I’m a calorie-tracking bot. Please write what you ate "
        "(e.g. 'chicken breast 150g, rice 100g, salad'), "
        "or send /status to see today’s summary."
    )


def help_text(lang: str):
    if lang == "ru":
        return (
            "📝 Как со мной работать:\n\n"
            "1️⃣ Сначала заполни профиль по шаблону.\n"
            "2️⃣ Потом просто присылай, что ты ешь.\n"
            "3️⃣ Я считаю калории, БЖУ и остаток на день.\n\n"
            "Команды:\n"
            "/status — сводка за сегодня\n"
            "/lang — сменить язык\n"
            "/start — начать заново (но профиль не стираю, если сам не перепишешь)\n"
        )
    if lang == "sr":
        return (
            "📝 Kako da koristiš bota:\n\n"
            "1️⃣ Prvo popuni profil po šablonu.\n"
            "2️⃣ Zatim šalji šta jedeš tokom dana.\n"
            "3️⃣ Ja računam kalorije, makroe i ostatak za dan.\n\n"
            "Komande:\n"
            "/status — današnji rezime\n"
            "/lang — promeni jezik\n"
            "/start — novi početak (profil ostaje, osim ako ga ne promeniš)\n"
        )
    # en
    return (
        "📝 How to use this bot:\n\n"
        "1️⃣ First, fill in your profile using the template.\n"
        "2️⃣ Then just send what you eat during the day.\n"
        "3️⃣ I’ll track calories, macros and your daily balance.\n\n"
        "Commands:\n"
        "/status — today’s summary\n"
        "/lang — change language\n"
        "/start — restart (I keep your profile unless you overwrite it)\n"
    )


# ========= ОСНОВНАЯ ЛОГИКА ПРИЁМА ПИЩИ/СТАТУСА ==========

def add_meal_and_get_status(user_id, text, lang: str):
    """
    - пробуем вытащить калории из числа (последнее число в сообщении),
    - если нет числа -> спрашиваем ИИ,
    - если ИИ тоже не дал, отвечаем off-topic / не смог оценить.
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

    # если вообще ноль и ничего не поняли — считаем, что сообщение не по теме
    if meal_kcal == 0 and ai_data is None and kcal_direct is None:
        return off_topic_text(lang)

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
        limit = 2000

    remaining = round(limit - d["total_kcal"])

    if lang == "ru":
        lines = [
            f"Приём пищи №{meal_index}",
            f"Описание: {text}",
            f"Калории этого приёма: {meal_kcal:.0f} ккал",
        ]
        if ai_data:
            lines.append(
                f"БЖУ этого приёма: Б {meal_p:.1f} г / Ж {meal_f:.1f} г / У {meal_c:.1f} г"
            )
        lines += [
            "",
            f"Съедено за день: {d['total_kcal']:.0f} ккал",
        ]
        if d["total_p"] or d["total_f"] or d["total_c"]:
            lines.append(
                f"БЖУ за день: Б {d['total_p']:.1f} г / Ж {d['total_f']:.1f} г / У {d['total_c']:.1f} г"
            )
        lines += [
            f"Цель на день (дефицит): {round(limit)} ккал",
            f"Осталось до лимита: {remaining} ккал",
        ]
        if remaining < 0:
            lines.append("⚠ Лимит дефицита превышен.")
        return "\n".join(lines)

    if lang == "sr":
        lines = [
            f"Obrok #{meal_index}",
            f"Opis: {text}",
            f"Kalorije ovog obroka: {meal_kcal:.0f} kcal",
        ]
        if ai_data:
            lines.append(
                f"Makroi ovog obroka: P {meal_p:.1f} g / M {meal_f:.1f} g / UH {meal_c:.1f} g"
            )
        lines += [
            "",
            f"Pojedeno danas: {d['total_kcal']:.0f} kcal",
        ]
        if d["total_p"] or d["total_f"] or d["total_c"]:
            lines.append(
                f"Makroi danas: P {d['total_p']:.1f} g / M {d['total_f']:.1f} g / UH {d['total_c']:.1f} g"
            )
        lines += [
            f"Cilj za dan (deficit): {round(limit)} kcal",
            f"Preostalo do limita: {remaining} kcal",
        ]
        if remaining < 0:
            lines.append("⚠ Premašio/la si dnevni deficit.")
        return "\n".join(lines)

    # en
    lines = [
        f"Meal #{meal_index}",
        f"Description: {text}",
        f"Calories in this meal: {meal_kcal:.0f} kcal",
    ]
    if ai_data:
        lines.append(
            f"Macros for this meal: P {meal_p:.1f} g / F {meal_f:.1f} g / C {meal_c:.1f} g"
        )
    lines += [
        "",
        f"Total eaten today: {d['total_kcal']:.0f} kcal",
    ]
    if d["total_p"] or d["total_f"] or d["total_c"]:
        lines.append(
            f"Macros today: P {d['total_p']:.1f} g / F {d['total_f']:.1f} g / C {d['total_c']:.1f} g"
        )
    lines += [
        f"Daily target (deficit): {round(limit)} kcal",
        f"Remaining for today: {remaining} kcal",
    ]
    if remaining < 0:
        lines.append("⚠ You’ve exceeded your daily deficit.")
    return "\n".join(lines)


def build_status_message(user_id, lang: str):
    profile = profiles.get(user_id)
    d = ensure_diary(user_id)

    if not profile:
        return profile_parse_error_text(lang)

    nums = calc_profile_numbers(profile)
    limit = nums["deficit"]
    remaining = round(limit - d["total_kcal"])

    if lang == "ru":
        msg = [
            "Статус на сегодня:",
            f"- Поддержание веса: {nums['maintenance']} ккал/день",
            f"- Дефицит (~20%): {nums['deficit']} ккал/день",
            f"- Съедено сегодня: {d['total_kcal']:.0f} ккал",
            f"- Осталось до лимита дефицита: {remaining} ккал",
        ]
        if d["total_p"] or d["total_f"] or d["total_c"]:
            msg.append(
                f"- БЖУ за день: Б {d['total_p']:.1f} г / Ж {d['total_f']:.1f} г / У {d['total_c']:.1f} г"
            )
        if remaining < 0:
            msg.append("⚠ Лимит превышен, аккуратнее с перекусами 😈")
        return "\n".join(msg)

    if lang == "sr":
        msg = [
            "Status za danas:",
            f"- Održavanje težine: {nums['maintenance']} kcal/dan",
            f"- Deficit (~20%): {nums['deficit']} kcal/dan",
            f"- Pojedeno danas: {d['total_kcal']:.0f} kcal",
            f"- Preostalo do dnevnog deficita: {remaining} kcal",
        ]
        if d["total_p"] or d["total_f"] or d["total_c"]:
            msg.append(
                f"- Makroi danas: P {d['total_p']:.1f} g / M {d['total_f']:.1f} g / UH {d['total_c']:.1f} g"
            )
        if remaining < 0:
            msg.append("⚠ Prešao/la si dnevni limit, oprez sa grickalicama 😈")
        return "\n".join(msg)

    # en
    msg = [
        "Status for today:",
        f"- Maintenance calories: {nums['maintenance']} kcal/day",
        f"- Deficit (~20%): {nums['deficit']} kcal/day",
        f"- Eaten today: {d['total_kcal']:.0f} kcal",
        f"- Remaining to daily deficit: {remaining} kcal",
    ]
    if d["total_p"] or d["total_f"] or d["total_c"]:
        msg.append(
            f"- Macros today: P {d['total_p']:.1f} g / F {d['total_f']:.1f} g / C {d['total_c']:.1f} g"
        )
    if remaining < 0:
        msg.append("⚠ Daily limit exceeded, go easy on late snacks 😈")
    return "\n".join(msg)


def handle_user_message(user_id, text, lang: str):
    """
    Основная логика:
    - если похоже на профиль -> пытаемся распарсить; если ок – обновляем, если нет – не трогаем старый профиль;
    - /status, /help, /menu обрабатываем;
    - всё остальное считаем приёмом пищи.
    """

    low = text.strip().lower()

    # команды
    if low in ["/status"]:
        return build_status_message(user_id, lang)

    if low in ["/help", "/menu"]:
        return help_text(lang)

    # профиль (по ключевым словам)
    if re.search(r'(возраст|age|godine|godina)', text, re.IGNORECASE) and \
       re.search(r'(рост|height|visina)', text, re.IGNORECASE) and \
       re.search(r'(вес|weight|težina|tezina)', text, re.IGNORECASE):

        prof = parse_profile_text(text)
        if prof is None:
            # ВАЖНО: профиль НЕ перезаписываем, если не смогли распарсить
            return profile_parse_error_text(lang)

        profiles[user_id] = prof
        nums = calc_profile_numbers(prof)

        if lang == "ru":
            return (
                "Профиль обновлён ✅\n\n"
                f"Возраст: {prof['age']}, рост: {prof['height']} см, вес: {prof['weight']} кг\n"
                f"Цель: {prof['goal']} кг\n"
                f"Активность: коэффициент {prof['activity_factor']}\n\n"
                f"Поддержание веса: {nums['maintenance']} ккал/день\n"
                f"Дефицит (~20%): {nums['deficit']} ккал/день\n\n"
                "Теперь просто присылай, что ты ешь, а я буду считать приёмы и остаток."
            )
        if lang == "sr":
            return (
                "Profil je ažuriran ✅\n\n"
                f"Godine: {prof['age']}, visina: {prof['height']} cm, težina: {prof['weight']} kg\n"
                f"Cilj: {prof['goal']} kg\n"
                f"Aktivnost: koeficijent {prof['activity_factor']}\n\n"
                f"Održavanje težine: {nums['maintenance']} kcal/dan\n"
                f"Deficit (~20%): {nums['deficit']} kcal/dan\n\n"
                "Sada samo šalji šta jedeš, a ja ću brojati obroke i ostatak."
            )
        # en
        return (
            "Profile updated ✅\n\n"
            f"Age: {prof['age']}, height: {prof['height']} cm, weight: {prof['weight']} kg\n"
            f"Goal: {prof['goal']} kg\n"
            f"Activity factor: {prof['activity_factor']}\n\n"
            f"Maintenance: {nums['maintenance']} kcal/day\n"
            f"Deficit (~20%): {nums['deficit']} kcal/day\n\n"
            "Now just send what you eat, and I’ll track your meals and remaining calories."
        )

    # всё остальное -> считаем приёмом пищи
    return add_meal_and_get_status(user_id, text, lang)


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
    user_text = update["message"].get("text", "").strip()

    # /start -> выбор языка
    if user_text == "/start":
        user_state[chat_id] = "lang_choice"
        send_text_message(chat_id, language_choice_text())
        return jsonify({"ok": True})

    # смена языка в любой момент
    if user_text in ["/lang", "/language"]:
        user_state[chat_id] = "lang_choice"
        send_text_message(chat_id, language_choice_text())
        return jsonify({"ok": True})

    # обрабатываем выбор языка, если ждём его
    if user_state.get(chat_id) == "lang_choice":
        if user_text in ["1", "2", "3"]:
            if user_text == "1":
                lang = "en"
            elif user_text == "2":
                lang = "ru"
            else:
                lang = "sr"
            user_lang[chat_id] = lang
            user_state[chat_id] = "idle"

            # интро + шаблон отдельными сообщениями
            send_text_message(chat_id, after_language_selected_intro(lang))
            send_text_message(chat_id, profile_template(lang))
            send_text_message(chat_id, help_text(lang))
            return jsonify({"ok": True})
        else:
            # повторяем просьбу выбрать 1/2/3
            send_text_message(chat_id, language_choice_text())
            return jsonify({"ok": True})

    # обычный режим
    lang = get_lang(chat_id)
    reply = handle_user_message(chat_id, user_text, lang)
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
