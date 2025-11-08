import os
import re
import time
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# === Конфигурация из переменных окружения ===
TOKEN = os.getenv("TELEGRAM_TOKEN")
BOT_API = f"https://api.telegram.org/bot{TOKEN}"

AI_ENDPOINT = os.getenv("AI_ENDPOINT", "")
AI_KEY = os.getenv("AI_KEY", "")

# === Память в рантайме ===
profiles = {}   # profiles[user_id] = {...}
diary = {}      # diary[user_id] = {...}
user_lang = {}  # user_lang[user_id] = "ru"|"en"|"sr"


# ========= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def today_key():
    return time.strftime("%Y%m%d", time.gmtime())


def ensure_diary(user_id):
    """Инициализируем дневник на сегодня, сбрасываем при смене дня."""
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
    return user_lang.get(user_id, "ru")


def set_lang_from_choice(user_id, text):
    """Пробуем выбрать язык по вводу: 1/2/3, ru/en/sr и т.п."""
    t = text.strip().lower()
    if t in ["1", "ru", "rus", "russian", "рус", "русский"]:
        user_lang[user_id] = "ru"
        return "ru"
    if t in ["2", "en", "eng", "english"]:
        user_lang[user_id] = "en"
        return "en"
    if t in ["3", "sr", "srb", "srpski", "serbian", "српски", "сербский"]:
        user_lang[user_id] = "sr"
        return "sr"
    return None


def language_choice_text():
    return (
        "Choose your language / Выбери язык / Izaberi jezik:\n\n"
        "1️⃣ Русский 🇷🇺\n"
        "2️⃣ English 🇬🇧\n"
        "3️⃣ Srpski 🇷🇸\n\n"
        "Просто отправь цифру 1, 2 или 3."
    )


def calc_profile_numbers(profile):
    age = profile["age"]
    weight = profile["weight"]
    height = profile["height"]
    sex = profile["sex"]
    activity_factor = profile["activity_factor"]

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
    Парсим профиль на RU / EN / SR.
    Формат:
    Возраст/Age/Godine: 34
    Рост/Height/Visina: 181
    Вес/Weight/Tezina: 86
    Цель/Goal/Cilj: 84
    Активность/Activity/Aktivnost: ...
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

    act_factor = 1.35  # средняя по умолчанию
    t = text.lower()

    if re.search(r'низк|сидяч|low|sedentary|nizak', t):
        act_factor = 1.2
    elif re.search(r'высок|очень актив|high|very active|visok', t):
        act_factor = 1.55
    elif re.search(r'умеренн|moderate|medium|srednj', t):
        act_factor = 1.35

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
    1) Если есть '420 ккал/kcal/кк/kk' — считаем это калориями.
    2) Если ВСЁ сообщение — одно число '420' — это калории.
    3) Иначе (например '2 яйца', '2 бургера') — возвращаем None, и дальше работает ИИ.
    """
    text = text.strip()

    m = re.search(r'(\d+)\s*(ккал|kcal|кк|kk)', text, re.IGNORECASE)
    if m:
        return float(m.group(1))

    if re.fullmatch(r'\d+', text):
        return float(text)

    return None


def _extract_json_block(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE)
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start:end + 1]
    return None


def ask_ai_for_meal(text_description):
    """Запрашиваем у Llama-3.1 калории и БЖУ по описанию еды."""
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


def add_meal_and_get_status(user_id, text):
    d = ensure_diary(user_id)
    lang = get_lang(user_id)

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

    lines = []

    if lang == "en":
        lines.append(f"Meal #{meal_index}")
        lines.append(f"Description: {text}")
        lines.append(f"Calories in this meal: {meal_kcal:.0f} kcal")
        if ai_data:
            lines.append(
                f"Macros this meal: P {meal_p:.1f} g / F {meal_f:.1f} g / C {meal_c:.1f} g"
            )
        lines.append("")
        lines.append(f"Eaten today: {d['total_kcal']:.0f} kcal")
        if d["total_p"] or d["total_f"] or d["total_c"]:
            lines.append(
                f"Daily macros: P {d['total_p']:.1f} g / F {d['total_f']:.1f} g / C {d['total_c']:.1f} g"
            )
        lines.append(f"Daily deficit target: {round(limit)} kcal")
        lines.append(f"Remaining until limit: {remaining} kcal")
        if remaining < 0:
            lines.append("⚠ You exceeded your daily deficit limit.")
        if meal_kcal == 0 and not ai_data and kcal_direct is None:
            lines.append("")
            lines.append("ℹ I couldn't estimate calories automatically. "
                         "You can add a number at the end, like '... 420'.")
    elif lang == "sr":
        lines.append(f"Obrok #{meal_index}")
        lines.append(f"Opis: {text}")
        lines.append(f"Kalorije u ovom obroku: {meal_kcal:.0f} kcal")
        if ai_data:
            lines.append(
                f"Makro za ovaj obrok: P {meal_p:.1f} g / M {meal_f:.1f} g / UH {meal_c:.1f} g"
            )
        lines.append("")
        lines.append(f"Pojedeno danas: {d['total_kcal']:.0f} kcal")
        if d["total_p"] or d["total_f"] or d["total_c"]:
            lines.append(
                f"Makro za dan: P {d['total_p']:.1f} g / M {d['total_f']:.1f} g / UH {d['total_c']:.1f} g"
            )
        lines.append(f"Cilj za dan (deficit): {round(limit)} kcal")
        lines.append(f"Preostalo do limita: {remaining} kcal")
        if remaining < 0:
            lines.append("⚠ Prešao si dnevni deficit.")
        if meal_kcal == 0 and not ai_data and kcal_direct is None:
            lines.append("")
            lines.append("ℹ Nisam uspeo da procenim kalorije automatski. "
                         "Možeš dodati broj na kraj, npr: '... 420'.")
    else:  # ru
        lines.append(f"Приём пищи №{meal_index}")
        lines.append(f"Описание: {text}")
        lines.append(f"Калории этого приёма: {meal_kcal:.0f} ккал")
        if ai_data:
            lines.append(
                f"БЖУ этого приёма: Б {meal_p:.1f} г / Ж {meal_f:.1f} г / У {meal_c:.1f} г"
            )
        lines.append("")
        lines.append(f"Съедено за день: {d['total_kcal']:.0f} ккал")
        if d["total_p"] or d["total_f"] or d["total_c"]:
            lines.append(
                f"БЖУ за день: Б {d['total_p']:.1f} г / Ж {d['total_f']:.1f} г / У {d['total_c']:.1f} г"
            )
        lines.append(f"Цель на день (дефицит): {round(limit)} ккал")
        lines.append(f"Осталось до лимита: {remaining} ккал")
        if remaining < 0:
            lines.append("⚠ Лимит дефицита превышен.")
        if meal_kcal == 0 and not ai_data and kcal_direct is None:
            lines.append("")
            lines.append("ℹ Не удалось оценить калории автоматически. "
                         "Можно дописать в конце сообщения просто число, например: '... 420'.")

    return "\n".join(lines)


def profile_template_text(lang):
    if lang == "en":
        return (
            "PROFILE FORM 🇬🇧 (copy, replace numbers, send):\n"
            "Age: 34\n"
            "Height: 181\n"
            "Weight: 86\n"
            "Goal: 84\n"
            "Activity: high  (options: low / moderate / high)\n"
        )
    if lang == "sr":
        return (
            "FORMULAR PROFILA 🇷🇸 (kopiraj, ubaci svoje brojeve i pošalji):\n"
            "Godine: 34\n"
            "Visina: 181\n"
            "Tezina: 86\n"
            "Cilj: 84\n"
            "Aktivnost: visoka  (nizka / srednja / visoka)\n"
        )
    return (
        "ФОРМА ПРОФИЛЯ 🇷🇺 (скопируй, подставь свои числа и отправь):\n"
        "Возраст: 34\n"
        "Рост: 181\n"
        "Вес: 86\n"
        "Цель: 84\n"
        "Активность: высокая  (варианты: низкая / средняя / высокая)\n"
    )


def help_text(lang):
    if lang == "en":
        return (
            "HOW TO USE THE BOT 🤖\n\n"
            "1️⃣ First, set up your profile using the form (age, height, weight, goal, activity).\n"
            "   Activity:\n"
            "   • low  – you sit most of the day\n"
            "   • moderate – you walk a bit, some light activity\n"
            "   • high – you move a lot, workouts or active job\n\n"
            "2️⃣ Then just send what you eat in free text:\n"
            "   '2 eggs and toast', 'chicken breast 150g, rice 100g, salad'.\n"
            "   I will estimate calories and macros with AI.\n\n"
            "3️⃣ If you already know calories for the meal, just add a number at the end:\n"
            "   'burger and fries – 850' ⇒ I take 850 kcal.\n\n"
            "4️⃣ /status – shows daily summary and how many calories are left.\n\n"
            "Small disclaimer: this is an approximate coach, not a medical device.\n"
            "A bit of inaccuracy is okay – consistency beats perfection 😉"
        )
    if lang == "sr":
        return (
            "KAKO DA KORISTIŠ BOTA 🤖\n\n"
            "1️⃣ Prvo podesi profil pomoću formulara (godine, visina, težina, cilj, aktivnost).\n"
            "   Aktivnost:\n"
            "   • nizka  – uglavnom sediš\n"
            "   • srednja – malo hodaš, malo pokreta\n"
            "   • visoka – dosta se krećeš, trening ili aktivan posao\n\n"
            "2️⃣ Posle toga samo šalji šta si jeo/la:\n"
            "   '2 jaja i hleb', 'piletina 150g, pirinač 100g, salata'.\n"
            "   Ja procenjujem kalorije i makroe uz pomoć AI.\n\n"
            "3️⃣ Ako već znaš kalorije, možeš na kraj poruke staviti broj:\n"
            "   'burger i pomfrit – 850' ⇒ uzimam 850 kcal.\n\n"
            "4️⃣ /status – pokazuje pregled dana i koliko kalorija je ostalo.\n\n"
            "Napomena: bot je približan coach, nije medicinski uređaj.\n"
            "Mala greška je okej – bitna je doslednost 😉"
        )
    return (
        "КАК ПОЛЬЗОВАТЬСЯ БОТОМ 🤖\n\n"
        "1️⃣ Сначала настрой профиль через форму (возраст, рост, вес, цель, активность).\n"
        "   Активность:\n"
        "   • низкая  — сидячая работа, минимум движения\n"
        "   • средняя — ходьба, лёгкая активность в течение дня\n"
        "   • высокая — много движения, тренировки или физический труд\n\n"
        "2️⃣ Дальше просто пиши, что ты ел/ела в свободной форме:\n"
        "   'яичница 2 яйца и хлеб', 'курица 150г, рис 100г, салат'.\n"
        "   Я оценю калории и БЖУ с помощью ИИ.\n\n"
        "3️⃣ Если ты сам знаешь калорийность приёма, в конце сообщения можно указать число:\n"
        "   'шаурма и кола — 850' ⇒ я приму 850 ккал.\n\n"
        "4️⃣ /status — покажет сводку за день и сколько калорий осталось.\n\n"
        "Важно: бот даёт примерную оценку, это не медицинский прибор.\n"
        "Чуть-чуть погрешности — это нормально, главное — регулярность 😉"
    )


def build_status_message(user_id):
    lang = get_lang(user_id)
    profile = profiles.get(user_id)
    d = ensure_diary(user_id)

    if not profile:
        # если профиля нет — просто вернуть форму
        return help_text(lang) + "\n\n" + profile_template_text(lang)

    nums = calc_profile_numbers(profile)
    limit = nums["deficit"]
    remaining = round(limit - d["total_kcal"])

    if lang == "en":
        msg = []
        msg.append("Today status:")
        msg.append(f"- Maintenance: {nums['maintenance']} kcal/day")
        msg.append(f"- Deficit (~20%): {nums['deficit']} kcal/day")
        msg.append(f"- Eaten today: {d['total_kcal']:.0f} kcal")
        msg.append(f"- Remaining until deficit limit: {remaining} kcal")
        if d["total_p"] or d["total_f"] or d["total_c"]:
            msg.append(
                f"- Daily macros: P {d['total_p']:.1f} g / F {d['total_f']:.1f} g / C {d['total_c']:.1f} g"
            )
        if remaining < 0:
            msg.append("⚠ You exceeded today's deficit.")
        return "\n".join(msg)

    if lang == "sr":
        msg = []
        msg.append("Status za danas:")
        msg.append(f"- Održavanje: {nums['maintenance']} kcal/dan")
        msg.append(f"- Deficit (~20%): {nums['deficit']} kcal/dan")
        msg.append(f"- Pojedeno danas: {d['total_kcal']:.0f} kcal")
        msg.append(f"- Preostalo do deficita: {remaining} kcal")
        if d["total_p"] or d["total_f"] or d["total_c"]:
            msg.append(
                f"- Makro za dan: P {d['total_p']:.1f} g / M {d['total_f']:.1f} g / UH {d['total_c']:.1f} g"
            )
        if remaining < 0:
            msg.append("⚠ Prešao si današnji deficit.")
        return "\n".join(msg)

    msg = []
    msg.append("Статус на сегодня:")
    msg.append(f"- Поддержание веса: {nums['maintenance']} ккал/день")
    msg.append(f"- Дефицит (~20%): {nums['deficit']} ккал/день")
    msg.append(f"- Съедено сегодня: {d['total_kcal']:.0f} ккал")
    msg.append(f"- Осталось до лимита дефицита: {remaining} ккал")
    if d["total_p"] or d["total_f"] or d["total_c"]:
        msg.append(
            f"- БЖУ за день: Б {d['total_p']:.1f} г / Ж {d['total_f']:.1f} г / У {d['total_c']:.1f} г"
        )
    if remaining < 0:
        msg.append("⚠ Лимит дефицита на сегодня превышен.")
    return "\n".join(msg)


def is_greeting(text: str) -> bool:
    t = text.strip().lower()
    greetings = [
        "привет", "здарова", "здравствуйте", "добрый день", "добрый вечер",
        "hi", "hello", "hey",
        "zdravo", "cao", "ćao", "hej"
    ]
    return any(t.startswith(g) for g in greetings)


def is_thanks(text: str) -> bool:
    t = text.strip().lower()
    return any(x in t for x in ["спасибо", "спс", "благодар", "thank", "thx", "hvala", "tnx"])


def wants_joke(text: str) -> bool:
    t = text.strip().lower()
    return any(x in t for x in ["шутк", "анекдот", "joke", "funny", "vic", "šala", "salu"])


def greeting_reply(lang) -> str:
    if lang == "en":
        return (
            "Hi! 👋 I'm your calorie bot.\n"
            "I count food, not your sins. Send /help if you want a quick guide 😉"
        )
    if lang == "sr":
        return (
            "Zdravo! 👋 Ja sam tvoj kalorijski bot.\n"
            "Računam obroke, ne grehe. Pošalji /help za kratko uputstvo 😉"
        )
    return (
        "Привет! 👋 Я бот, который считает калории, а не твои грехи.\n"
        "Если хочешь краткую инструкцию — напиши /help 😉"
    )


def thanks_reply(lang) -> str:
    if lang == "en":
        return "You're welcome 😎 Keep going, future shredded legend."
    if lang == "sr":
        return "Nema na čemu 😎 Samo nastavi, budući zver."
    return "Всегда пожалуйста 😎 Продолжаем превращать калории в прогресс."


def joke_reply(lang) -> str:
    if lang == "en":
        return (
            "Joke time 😄\n\n"
            "— Coach, can I eat after 6pm?\n"
            "— Sure. The question is: will you stop after 6am? 😈"
        )
    if lang == "sr":
        return (
            "Vreme je za šalu 😄\n\n"
            "— Treneru, smem li da jedem posle 18h?\n"
            "— Možeš, samo je pitanje: hoćeš li stati pre 6 ujutru? 😈"
        )
    return (
        "Шутка подъехала 😄\n\n"
        "— Тренер, можно есть после шести?\n"
        "— Можно. Вопрос в другом: ты до скольки планируешь не останавливаться? 😈"
    )


def profile_help_text_all_langs():
    return (
        "Я могу работать на русском 🇷🇺, английском 🇬🇧 и сербском 🇷🇸.\n"
        "Сначала выбери язык (1/2/3), потом заполни профиль по форме.\n"
    )


def handle_user_message(user_id, text):
    # 0. Если язык ещё не выбран — сначала выбираем
    lang = user_lang.get(user_id)
    if lang is None:
        chosen = set_lang_from_choice(user_id, text)
        if chosen:
            # Сразу после выбора языка даём инструкцию + форму
            lang = chosen
            intro = help_text(lang)
            template = profile_template_text(lang)
            send_text_message(user_id, intro)
            return template
        else:
            return language_choice_text()

    lang = get_lang(user_id)

    # 1. Приветствия / спасибо / шутки
    if is_greeting(text):
        return greeting_reply(lang)

    if is_thanks(text):
        return thanks_reply(lang)

    if wants_joke(text):
        return joke_reply(lang)

    # 2. Профиль
    if re.search(r'(возраст|age|godine|godina)', text, re.IGNORECASE) and \
       re.search(r'(рост|height|visina)', text, re.IGNORECASE) and \
       re.search(r'(вес|weight|težina|tezina)', text, re.IGNORECASE):

        prof = parse_profile_text(text)
        if prof is None:
            # не смог распарсить
            return help_text(lang) + "\n\n" + profile_template_text(lang)

        profiles[user_id] = prof
        nums = calc_profile_numbers(prof)

        if lang == "en":
            return (
                "Profile updated ✅\n\n"
                f"Age: {prof['age']}, height: {prof['height']} cm, weight: {prof['weight']} kg\n"
                f"Goal: {prof['goal']} kg\n"
                f"Activity factor: {prof['activity_factor']}\n\n"
                f"Maintenance: {nums['maintenance']} kcal/day\n"
                f"Deficit (~20%): {nums['deficit']} kcal/day\n\n"
                "Now just send what you eat, and I'll track meals and remaining calories."
            )
        if lang == "sr":
            return (
                "Profil je ažuriran ✅\n\n"
                f"Godine: {prof['age']}, visina: {prof['height']} cm, težina: {prof['weight']} kg\n"
                f"Cilj: {prof['goal']} kg\n"
                f"Faktor aktivnosti: {prof['activity_factor']}\n\n"
                f"Održavanje: {nums['maintenance']} kcal/dan\n"
                f"Deficit (~20%): {nums['deficit']} kcal/dan\n\n"
                "Sada samo šalji šta jedeš i ja ću pratiti obroke i preostale kalorije."
            )
        return (
            "Профиль обновлён ✅\n\n"
            f"Возраст: {prof['age']}, рост: {prof['height']} см, вес: {prof['weight']} кг\n"
            f"Цель: {prof['goal']} кг\n"
            f"Коэффициент активности: {prof['activity_factor']}\n\n"
            f"Поддержание: {nums['maintenance']} ккал/день\n"
            f"Дефицит (~20%): {nums['deficit']} ккал/день\n\n"
            "Теперь просто присылай, что ты ешь, а я буду считать приёмы пищи и остаток калорий."
        )

    # 3. Статус
    low = text.strip().lower()
    if low in ["/status", "статус", "остаток", "status", "stanje", "koliko je ostalo"]:
        return build_status_message(user_id)

    # 4. Всё остальное считаем приёмом пищи
    return add_meal_and_get_status(user_id, text)


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
    user_text = update["message"].get("text", "")

    text_lower = user_text.strip().lower()

    # /start
    if text_lower.startswith("/start"):
        lang = user_lang.get(chat_id)
        if lang is None:
            reply = language_choice_text()
            send_text_message(chat_id, reply)
            return jsonify({"ok": True})
        else:
            # язык уже выбран — даём help + форму
            send_text_message(chat_id, help_text(lang))
            send_text_message(chat_id, profile_template_text(lang))
            return jsonify({"ok": True})

    # /help
    if text_lower.startswith("/help"):
        lang = get_lang(chat_id)
        send_text_message(chat_id, help_text(lang))
        send_text_message(chat_id, profile_template_text(lang))
        return jsonify({"ok": True})

    # обычное сообщение
    reply = handle_user_message(chat_id, user_text)
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
