import logging
import os

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# --------------------------------------------------
# ЛОГИ
# --------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# --------------------------------------------------
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# --------------------------------------------------

RAW_TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_TOKEN = "".join(RAW_TELEGRAM_TOKEN.split())

RAW_OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_API_KEY = "".join(RAW_OPENAI_KEY.split())

PORT = int(os.environ.get("PORT", "10000"))

RENDER_EXTERNAL_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "",
).strip().rstrip("/")


# --------------------------------------------------
# OPENAI
# --------------------------------------------------

MODEL = "gpt-5.6-luna"

openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
)


BASE_INSTRUCTIONS = """
Ты — христианский помощник проекта «Библия отвечает».

Твоя задача — помогать людям понимать жизненные ситуации
в свете Священного Писания.

Правила:

1. Отвечай на языке пользователя.
2. Основа ответа — Библия, а не личные откровения,
   пророчества или выдуманные слова от имени Бога.
3. Никогда не говори: «Бог сказал мне о вас»,
   «Бог гарантирует» или подобные утверждения.
4. Не придумывай ссылки на Библию.
5. Указывай только те книги, главы и стихи,
   в которых уверен.
6. Если не уверен в точной формулировке стиха,
   передавай смысл своими словами, а не выдавай
   неточную цитату за дословную.
7. Не осуждай человека и не манипулируй страхом.
8. Ответ должен быть доброжелательным,
   ясным и практически полезным.
9. Обычно используй 2–4 подходящих места Писания.
10. Ответ должен быть достаточно кратким для Telegram.
11. Если речь идёт о здоровье, не обещай исцеление
    и не советуй отказываться от медицинской помощи.
12. Если человек сообщает о непосредственной опасности
    для себя или другого человека, прежде всего
    посоветуй обратиться за экстренной помощью
    и к человеку, которому он доверяет.
"""


MODE_INSTRUCTIONS = {
    "ask": """
Ответь на вопрос пользователя на основании Библии.

Структура:
1. Короткий прямой ответ.
2. 2–4 подходящих места Писания с объяснением,
   как они относятся к ситуации.
3. Один практический шаг, который человек
   может сделать сегодня.
4. Короткое ободрение.

Не составляй молитву, если пользователь
сам её не просил.
""",

    "prayer": """
Пользователь просит молитву по нужде.

Составь:
1. Короткое библейское ободрение.
2. 1–3 подходящих ссылки на Писание.
3. Искреннюю христианскую молитву по описанной нужде.

Не обещай конкретного сверхъестественного результата
и не говори от имени Бога.
""",

    "healing": """
Пользователь просит молитву об исцелении.

Составь:
1. Сочувственный и спокойный ответ.
2. 1–3 подходящих места Писания о молитве,
   надежде, Божьей помощи и поддержке.
3. Короткую молитву об исцелении,
   укреплении и мудрости.

Не утверждай, что человек обязательно будет исцелён.
Не советуй прекращать лечение или игнорировать врача.
""",
}


async def generate_ai_answer(
    user_text: str,
    mode: str,
) -> str:
    instructions = (
        BASE_INSTRUCTIONS
        + "\n"
        + MODE_INSTRUCTIONS.get(
            mode,
            MODE_INSTRUCTIONS["ask"],
        )
    )

    response = await openai_client.responses.create(
        model=MODEL,
        instructions=instructions,
        input=user_text,
        max_output_tokens=700,
    )

    answer = response.output_text.strip()

    if not answer:
        return (
            "Не удалось сформировать ответ. "
            "Пожалуйста, попробуйте ещё раз."
        )

    return answer


# --------------------------------------------------
# TELEGRAM — МЕНЮ
# --------------------------------------------------

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "📖 Задать вопрос Библии",
                callback_data="ask",
            )
        ],
        [
            InlineKeyboardButton(
                "🙏 Молитва по нужде",
                callback_data="prayer",
            )
        ],
        [
            InlineKeyboardButton(
                "❤️‍🩹 Молитва об исцелении",
                callback_data="healing",
            )
        ],
        [
            InlineKeyboardButton(
                "📖 Стих из Библии",
                callback_data="verse",
            )
        ],
        [
            InlineKeyboardButton(
                "🤝 Поддержать проект",
                callback_data="donate",
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ О проекте",
                callback_data="about",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# --------------------------------------------------
# ДЛИННЫЕ СООБЩЕНИЯ
# --------------------------------------------------

async def send_long_message(
    update: Update,
    text: str,
):
    message = update.effective_message

    if not message:
        return

    max_length = 3800

    if len(text) <= max_length:
        await message.reply_text(
            text,
            reply_markup=main_menu(),
        )
        return

    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunk = remaining
            remaining = ""
        else:
            split_at = remaining.rfind(
                "\n",
                0,
                max_length,
            )

            if split_at < 1000:
                split_at = max_length

            chunk = remaining[:split_at]
            remaining = remaining[split_at:].lstrip()

        if remaining:
            await message.reply_text(chunk)
        else:
            await message.reply_text(
                chunk,
                reply_markup=main_menu(),
            )


# --------------------------------------------------
# /START
# --------------------------------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    text = (
        "📖 <b>Библия отвечает</b>\n\n"
        "Расскажите, что происходит в вашей жизни, "
        "что вас тревожит или в чём вы нуждаетесь.\n\n"
        "Бот поможет посмотреть на вашу ситуацию "
        "в свете Священного Писания.\n\n"
        "Выберите раздел:"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


# --------------------------------------------------
# КНОПКИ
# --------------------------------------------------

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    action = query.data

    if action == "ask":
        context.user_data["mode"] = "ask"

        text = (
            "📖 <b>Задайте вопрос</b>\n\n"
            "Напишите своими словами, что произошло, "
            "что вас тревожит или в чём вы хотите "
            "получить ответ на основании Библии."
        )

    elif action == "prayer":
        context.user_data["mode"] = "prayer"

        text = (
            "🙏 <b>Молитва по нужде</b>\n\n"
            "Напишите вашу нужду своими словами, "
            "и бот поможет составить молитву "
            "на основании Писания."
        )

    elif action == "healing":
        context.user_data["mode"] = "healing"

        text = (
            "❤️‍🩹 <b>Молитва об исцелении</b>\n\n"
            "Напишите, о ком вы хотите молиться "
            "и в чём состоит нужда."
        )

    elif action == "verse":
        context.user_data.clear()

        text = (
            "📖 «Слово Твоё — светильник ноге моей "
            "и свет стезе моей».\n\n"
            "Псалом 118:105"
        )

    elif action == "donate":
        context.user_data.clear()

        text = (
            "🤝 <b>Поддержать проект</b>\n\n"
            "Здесь позже появится возможность "
            "добровольно поддержать развитие проекта."
        )

    elif action == "about":
        context.user_data.clear()

        text = (
            "ℹ️ <b>О проекте</b>\n\n"
            "«Библия отвечает» — христианский "
            "AI-помощник для поиска библейского "
            "взгляда на жизненные вопросы, молитвенной "
            "поддержки и ободрения."
        )

    else:
        context.user_data.clear()
        text = "Выберите нужный раздел:"

    await query.message.reply_text(
        text,
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


# --------------------------------------------------
# СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ
# --------------------------------------------------

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()

    if not user_text:
        return

    mode = context.user_data.get("mode", "ask")

    wait_message = await update.message.reply_text(
        "⏳ Подбираю ответ на основании Писания..."
    )

    try:
        answer = await generate_ai_answer(
            user_text=user_text,
            mode=mode,
        )

        try:
            await wait_message.delete()
        except Exception:
            pass

        await send_long_message(
            update,
            answer,
        )

        context.user_data.clear()

    except Exception:
        logger.exception(
            "Ошибка при обращении к OpenAI API"
        )

        try:
            await wait_message.edit_text(
                "⚠️ Сейчас не удалось получить "
                "AI-ответ.\n\n"
                "Попробуйте отправить сообщение "
                "ещё раз через несколько секунд."
            )
        except Exception:
            pass


# --------------------------------------------------
# ЗАПУСК
# --------------------------------------------------

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не установлен"
        )

    if ":" not in TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN имеет неверный формат"
        )

    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY не установлен"
        )

    if not RENDER_EXTERNAL_URL:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL не найден"
        )

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    webhook_url = (
        f"{RENDER_EXTERNAL_URL}/telegram"
    )

    logger.info(
        "Запуск webhook: %s",
        webhook_url,
    )

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="telegram",
        webhook_url=webhook_url,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
