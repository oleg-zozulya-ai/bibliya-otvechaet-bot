import logging
import os
import random
import re

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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


TELEGRAM_TOKEN = "".join(
    os.environ.get("TELEGRAM_BOT_TOKEN", "").split()
)

OPENAI_API_KEY = "".join(
    os.environ.get("OPENAI_API_KEY", "").split()
)

PORT = int(os.environ.get("PORT", "10000"))

RENDER_EXTERNAL_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "",
).strip().rstrip("/")


MODEL = "gpt-5.6-luna"

openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
)


BASE_INSTRUCTIONS = """
Ты — христианский помощник проекта «Библия отвечает».

Твоя задача — не просто дать справочный ответ,
а помочь человеку увидеть свою ситуацию
в свете Священного Писания,
укрепиться в надежде, вере, мудрости и молитве.

Манера ответа:
глубокая, библейско-пастырская, духовно зрелая,
экспозиционная и содержательная.
Не копируй манеру речи конкретного проповедника,
но используй лучшие общие качества сильной библейской проповеди:
ясность, глубину, уважение к тексту Писания,
практическое применение и надежду.

Правила:

1. Отвечай на языке пользователя.

2. Основа ответа — Библия и её смысл в контексте.

3. Не выдавай свои мысли за прямое откровение от Бога.

4. Не говори:
«Бог сказал мне о вас»,
«Бог гарантирует»
или подобных фраз.

5. Не придумывай библейские ссылки.

6. Используй только те книги, главы и стихи,
в которых уверен.

7. Если не уверен в дословной формулировке стиха,
передавай его смысл своими словами,
а не выдавай неточную формулировку за цитату.

8. Не осуждай человека
и не манипулируй страхом.

9. Связывай ответ именно с деталями ситуации пользователя.
Не давай одинаковые универсальные ответы на разные нужды.

10. Объясняй не только «что написано»,
но и почему это важно человеку именно сейчас.

11. Когда это действительно помогает,
кратко показывай контекст места Писания
и духовный принцип, который из него следует.

12. Избегай пустых религиозных клише.
Пиши живо, ясно и с внутренней глубиной.

13. Для обычных вопросов обычно используй
2–4 подходящих места Писания.
Для молитв по нужде и об исцелении обычно используй
3–5 подходящих мест.

14. Не повторяй одни и те же вступления,
одни и те же обороты и одну и ту же последовательность
в каждом ответе. Формулировки должны естественно меняться.

15. Если действительно уверен в значении
греческого или еврейского слова
и это существенно помогает понять стих,
можешь очень кратко упомянуть его.
Если не уверен — не используй язык оригинала.

16. При вопросах о здоровье
не обещай гарантированное исцеление
и не советуй отказываться от медицинской помощи.

17. При непосредственной опасности
для человека или окружающих
сначала советуй обратиться за экстренной помощью
и к человеку, которому пользователь доверяет.

Формат:

18. Пиши обычным текстом без Markdown-разметки.

19. Не используй звёздочки для жирного текста,
решётки для заголовков,
обратные кавычки
и подчёркивания для курсива.

20. Для пунктов списка используй только символ •.

21. Делай удобные для Telegram абзацы.

22. Между смысловыми разделами
оставляй одну пустую строку.

23. Названия смысловых разделов
можно начинать с эмодзи.
"""


MODE_INSTRUCTIONS = {
    "ask": """
Ответь глубоко, но понятно, на основании Библии.

Не ограничивайся поверхностным советом.
Покажи духовный принцип Писания
и свяжи его с конкретными словами пользователя.

Не делай ответ механически одинаковым каждый раз.
Можно немного менять названия и порядок разделов.

Обычно ответ должен включать:

📖 Библейский взгляд

Дай содержательный ответ на ситуацию.
Покажи, что Писание говорит о корне вопроса:
страхе, выборе, надежде, прощении, вере,
ответственности, мудрости или другом аспекте.

📚 Слово Божье

Приведи 2–4 действительно подходящих места Писания
и кратко объясни смысл каждого
именно для этой ситуации.

🔥 Духовный акцент

Выдели одну небанальную библейскую мысль:
что человеку важно увидеть о Боге,
о своём сердце или о следующем шаге веры.

✅ Практический шаг

Предложи один конкретный шаг,
который человек может сделать сегодня.

🕊 Надежда

Закончи сильным, но спокойным
библейским ободрением.

Не добавляй молитву,
если пользователь её не просил.
""",

    "prayer": """
Пользователь просит молитву по конкретной нужде.

Ответ не должен быть короткой шаблонной молитвой.
Человек должен почувствовать,
что его конкретная ситуация была услышана и осмыслена.

Используй 3–5 подходящих мест Писания.

Не делай все ответы одинаковыми.
Можно менять названия и порядок смысловых блоков,
если сохраняется ясность.

Ответ должен содержать:

📖 Слово для сердца

В 2–4 коротких абзацах покажи,
как Писание говорит именно в эту ситуацию.
Не просто перечисляй ссылки:
объясни Божий характер, Его верность,
мудрость, присутствие, руководство,
утешение или обеспечение — в зависимости от нужды.

📚 Основание в Писании

Приведи 3–5 мест Писания.
Каждое место кратко свяжи
с конкретной нуждой пользователя.

🔥 Духовный смысл

Выдели одну глубокую библейскую мысль,
которая помогает смотреть на обстоятельства
не только глазами страха или проблемы,
но через истину Божьего Слова.

🙏 Молитва

Составь глубокую персональную молитву
из нескольких абзацев.
Она должна отражать детали нужды пользователя,
а не быть универсальным текстом для всех.

В молитве естественно соединяй:
благодарность Богу,
признание зависимости от Него,
конкретную просьбу,
опору на библейскую истину,
мудрость для правильных решений,
внутренний мир, стойкость и надежду.

Избегай одинаковых фраз
и одинакового порядка предложений
в разных молитвах.

Не обещай конкретного сверхъестественного результата
и не говори от имени Бога.

🕊 Слово надежды

Закончи 1–2 сильными предложениями,
которые возвращают взгляд человека
к Божьей верности и Писанию.
""",

    "healing": """
Пользователь просит молитву об исцелении.

Ответ должен быть глубоко библейским,
сострадательным, исполненным надежды и веры,
но без обещания гарантированного исцеления.

Не делай молитву одинаковой для всех болезней.
Учитывай, что именно рассказал пользователь:
кто болеет, что происходит, чего человек боится,
в чём особенно нуждается.

Используй 3–5 подходящих мест Писания.

Не делай все ответы механически одинаковыми.
Можно менять названия и порядок смысловых блоков.

Ответ должен содержать:

❤️ Поддержка

Начни не с сухого предупреждения,
а с искренней пастырской поддержки.
Покажи, что болезнь часто затрагивает
не только тело, но и сердце, страхи,
семью и способность надеяться.

📖 Основание надежды

Покажи через Писание:
сострадание Христа,
Божью близость в страдании,
право верующего приносить Богу просьбу об исцелении,
силу молитвы, надежду и стойкость.

📚 Места Писания

Приведи 3–5 подходящих мест
и кратко объясни,
что каждое из них открывает
о Божьей помощи и надежде.

🔥 Духовный акцент

Дай одну глубокую мысль,
которая помогает не свести веру
только к результату «исцелился или нет»,
а увидеть Божье присутствие,
верность и действие посреди пути.

🙏 Молитва об исцелении

Составь содержательную молитву
из нескольких абзацев.
Проси об исцелении смело и с надеждой,
но не объявляй результат заранее.

Молитва может включать:
просьбу о восстановлении тела,
облегчении боли и страдания,
мире вместо страха,
мудрости врачам,
правильном лечении,
силе для близких,
стойкости и надежде.

Не советуй прекращать лечение
или игнорировать медицинскую помощь.

🕊 Надежда

Закончи библейским ободрением,
которое направляет взгляд человека
к Богу, а не к отчаянию.
""",
}


VERSES = [
    {
        "reference": "Псалом 118:105",
        "text": "«Слово Твоё — светильник ноге моей и свет стезе моей».",
        "thought": (
            "Божье Слово помогает увидеть следующий шаг, "
            "даже когда весь путь ещё не ясен."
        ),
    },
    {
        "reference": "Псалом 33:19",
        "text": (
            "«Близок Господь к сокрушенным сердцем "
            "и смиренных духом спасет»."
        ),
        "thought": (
            "В тяжёлое время Бог не далёк от человека, "
            "который искренне обращается к Нему."
        ),
    },
    {
        "reference": "Псалом 45:2",
        "text": (
            "«Бог нам прибежище и сила, "
            "скорый помощник в бедах»."
        ),
        "thought": (
            "В трудностях можно искать у Бога "
            "опору, помощь и внутреннюю стойкость."
        ),
    },
    {
        "reference": "Притчи 3:5",
        "text": (
            "«Надейся на Господа всем сердцем твоим, "
            "и не полагайся на разум твой»."
        ),
        "thought": (
            "Не всё можно просчитать заранее; "
            "мудро соединять размышление с доверием Богу."
        ),
    },
    {
        "reference": "Исаия 41:10",
        "text": (
            "«Не бойся, ибо Я с тобою; "
            "не смущайся, ибо Я Бог твой; "
            "Я укреплю тебя, и помогу тебе»."
        ),
        "thought": (
            "Этот стих напоминает о Божьей поддержке "
            "посреди страха и неопределённости."
        ),
    },
    {
        "reference": "Матфея 11:28",
        "text": (
            "«Придите ко Мне все труждающиеся "
            "и обремененные, и Я успокою вас»."
        ),
        "thought": (
            "Христос приглашает приносить Ему "
            "усталость, тяжесть и внутреннее напряжение."
        ),
    },
    {
        "reference": "Иоанна 14:27",
        "text": (
            "«Мир оставляю вам, "
            "мир Мой даю вам»."
        ),
        "thought": (
            "Библейский мир не зависит полностью "
            "от внешних обстоятельств."
        ),
    },
    {
        "reference": "Римлянам 12:12",
        "text": (
            "«Утешайтесь надеждою; "
            "в скорби будьте терпеливы, "
            "в молитве постоянны»."
        ),
        "thought": (
            "Надежда, терпение и молитва помогают "
            "проходить трудные периоды шаг за шагом."
        ),
    },
    {
        "reference": "Филиппийцам 4:6",
        "text": (
            "«Не заботьтесь ни о чем, "
            "но всегда в молитве и прошении "
            "с благодарением открывайте "
            "свои желания пред Богом»."
        ),
        "thought": (
            "Тревогу можно превращать "
            "в конкретную молитву "
            "и доверять Богу свои нужды."
        ),
    },
    {
        "reference": "1 Петра 5:7",
        "text": (
            "«Все заботы ваши возложите на Него, "
            "ибо Он печется о вас»."
        ),
        "thought": (
            "Не обязательно нести все переживания одному — "
            "Писание призывает отдавать их Богу."
        ),
    },
]


def clean_ai_text(text: str) -> str:
    text = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )

    text = re.sub(
        r"```(?:[a-zA-Z0-9_-]+)?\n?",
        "",
        text,
    )

    text = text.replace("```", "")
    text = text.replace("`", "")

    text = re.sub(
        r"\*\*(.*?)\*\*",
        r"\1",
        text,
        flags=re.DOTALL,
    )

    text = re.sub(
        r"__(.*?)__",
        r"\1",
        text,
        flags=re.DOTALL,
    )

    text = re.sub(
        r"(?<!\*)\*([^*\n]+)\*(?!\*)",
        r"\1",
        text,
    )

    text = re.sub(
        r"(?<!_)_([^_\n]+)_(?!_)",
        r"\1",
        text,
    )

    text = re.sub(
        r"(?m)^\s{0,3}#{1,6}\s*",
        "",
        text,
    )

    text = re.sub(
        r"(?m)^\s*[-+*]\s+",
        "• ",
        text,
    )

    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r"\1 (\2)",
        text,
    )

    text = re.sub(
        r"(?m)^\s*[-_*]{3,}\s*$",
        "",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


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
        max_output_tokens=1200,
    )

    answer = clean_ai_text(
        response.output_text or ""
    )

    if not answer:
        return (
            "Не удалось сформировать ответ. "
            "Пожалуйста, попробуйте ещё раз."
        )

    return answer


def main_menu() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
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
    )


def random_verse(
    context: ContextTypes.DEFAULT_TYPE,
) -> dict:

    queue = context.user_data.get(
        "verse_queue"
    )

    last_index = context.user_data.get(
        "last_verse_index"
    )

    if not queue:
        queue = list(
            range(len(VERSES))
        )

        random.shuffle(queue)

        if (
            last_index is not None
            and len(queue) > 1
            and queue[-1] == last_index
        ):
            for position in range(
                len(queue) - 1
            ):
                if queue[position] != last_index:
                    queue[position], queue[-1] = (
                        queue[-1],
                        queue[position],
                    )
                    break

        context.user_data[
            "verse_queue"
        ] = queue

    verse_index = context.user_data[
        "verse_queue"
    ].pop()

    context.user_data[
        "last_verse_index"
    ] = verse_index

    return VERSES[verse_index]


async def send_long_message(
    update: Update,
    text: str,
) -> None:

    message = update.effective_message

    if not message:
        return

    max_length = 3800
    remaining = text.strip()

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

            chunk = remaining[:split_at].strip()

            remaining = (
                remaining[split_at:]
                .lstrip()
            )

        if remaining:

            await message.reply_text(
                chunk
            )

        else:

            await message.reply_text(
                chunk,
                reply_markup=main_menu(),
            )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    context.user_data.pop(
        "mode",
        None,
    )

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


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    query = update.callback_query

    await query.answer()

    action = query.data

    if action == "ask":

        context.user_data["mode"] = "ask"

        text = (
            "📖 <b>Задайте вопрос</b>\n\n"
            "Напишите своими словами, "
            "что произошло, "
            "что вас тревожит "
            "или в чём вы хотите "
            "получить ответ "
            "на основании Библии."
        )

    elif action == "prayer":

        context.user_data["mode"] = "prayer"

        text = (
            "🙏 <b>Молитва по нужде</b>\n\n"
            "Напишите вашу нужду "
            "своими словами, "
            "и бот поможет составить молитву "
            "на основании Писания."
        )

    elif action == "healing":

        context.user_data["mode"] = "healing"

        text = (
            "❤️‍🩹 <b>Молитва об исцелении</b>\n\n"
            "Напишите, "
            "о ком вы хотите молиться "
            "и в чём состоит нужда."
        )

    elif action == "verse":

        verse = random_verse(
            context
        )

        text = (
            "📖 <b>Стих из Библии</b>\n\n"
            f"{verse['text']}\n\n"
            f"<b>{verse['reference']}</b>\n\n"
            "💬 <b>Коротко о смысле</b>\n"
            f"{verse['thought']}"
        )

    elif action == "donate":

        context.user_data.pop(
            "mode",
            None,
        )

        text = (
            "🤝 <b>Поддержать проект</b>\n\n"
            "Здесь позже появится возможность "
            "добровольно поддержать "
            "развитие проекта."
        )

    elif action == "about":

        context.user_data.pop(
            "mode",
            None,
        )

        text = (
            "ℹ️ <b>О проекте</b>\n\n"
            "«Библия отвечает» — "
            "христианский AI-помощник "
            "для поиска библейского взгляда "
            "на жизненные вопросы, "
            "молитвенной поддержки "
            "и ободрения."
        )

    else:

        context.user_data.pop(
            "mode",
            None,
        )

        text = "Выберите нужный раздел:"

    await query.message.reply_text(
        text,
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:

    if (
        not update.message
        or not update.message.text
    ):
        return

    user_text = (
        update.message.text.strip()
    )

    if not user_text:
        return

    mode = context.user_data.get(
        "mode",
        "ask",
    )

    wait_message = (
        await update.message.reply_text(
            "⏳ Подбираю ответ "
            "на основании Писания..."
        )
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

        context.user_data.pop(
            "mode",
            None,
        )

    except Exception:

        logger.exception(
            "Ошибка при обращении "
            "к OpenAI API"
        )

        try:

            await wait_message.edit_text(
                "⚠️ Сейчас не удалось "
                "получить AI-ответ.\n\n"
                "Попробуйте отправить сообщение "
                "ещё раз через несколько секунд."
            )

        except Exception:
            pass


def main() -> None:

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не установлен"
        )

    if ":" not in TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN "
            "имеет неверный формат"
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
            filters.TEXT
            & ~filters.COMMAND,
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


main()
