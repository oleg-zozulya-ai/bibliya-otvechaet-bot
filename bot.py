import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Логи
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Секретный токен будет храниться в Render, а не в GitHub
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Render передаёт эти значения автоматически для Web Service
PORT = int(os.environ.get("PORT", "10000"))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")


def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "📖 Задать вопрос Библии",
                callback_data="ask"
            )
        ],
        [
            InlineKeyboardButton(
                "🙏 Молитва по нужде",
                callback_data="prayer"
            )
        ],
        [
            InlineKeyboardButton(
                "❤️‍🩹 Молитва об исцелении",
                callback_data="healing"
            )
        ],
        [
            InlineKeyboardButton(
                "📖 Стих из Библии",
                callback_data="verse"
            )
        ],
        [
            InlineKeyboardButton(
                "🤝 Поддержать проект",
                callback_data="donate"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ О проекте",
                callback_data="about"
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    text = (
        "📖 <b>Библия отвечает</b>\n\n"
        "Расскажите, что происходит в вашей жизни, "
        "что вас тревожит или в чём вы нуждаетесь.\n\n"
        "Бот поможет найти подходящие места из "
        "Священного Писания и молитву по вашей нужде.\n\n"
        "Выберите раздел:"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
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
            "Напишите вашу нужду своими словами."
        )

    elif action == "healing":
        context.user_data["mode"] = "healing"

        text = (
            "❤️‍🩹 <b>Молитва об исцелении и укреплении</b>\n\n"
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

    else:
        context.user_data.clear()

        text = (
            "ℹ️ <b>О проекте</b>\n\n"
            "«Библия отвечает» — помощник для поиска "
            "мест Священного Писания, молитвенной "
            "поддержки и ободрения."
        )

    await query.message.reply_text(
        text,
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    mode = context.user_data.get("mode")

    if mode in ("ask", "prayer", "healing"):
        await update.message.reply_text(
            "🙏 Спасибо. Ваше обращение принято.\n\n"
            "Сейчас мы запускаем основу проекта. "
            "Следующим этапом подключим точный подбор "
            "мест из Библии и формирование ответа "
            "по вашей ситуации.",
            reply_markup=main_menu(),
        )

        context.user_data.clear()

    else:
        await update.message.reply_text(
            "Выберите нужный раздел:",
            reply_markup=main_menu(),
        )


def main():
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не установлен"
        )

    if not RENDER_EXTERNAL_URL:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL не найден"
        )

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
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
