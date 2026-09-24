import asyncio
import io
import logging
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import wave
from array import array
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import quote

import httpx
from openai import AsyncOpenAI
from telegram import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut
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

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "",
).strip().rstrip("/")

SUPABASE_SECRET_KEY = "".join(
    os.environ.get("SUPABASE_SECRET_KEY", "").split()
)

SUPABASE_TABLE = "bible_bot_user_state"
ANALYTICS_USERS_TABLE = "bible_bot_users"
ANALYTICS_EVENTS_TABLE = "bible_bot_events"
DAILY_MESSAGES_TABLE = "bible_bot_daily_messages"
SUPABASE_TIMEOUT_SECONDS = 10.0
OPENAI_TIMEOUT_SECONDS = 120.0
VOICE_TRANSCRIPTION_MODEL = os.environ.get(
    "VOICE_TRANSCRIPTION_MODEL",
    "gpt-4o-transcribe",
).strip() or "gpt-4o-transcribe"

# Аудиоответ на входящее голосовое сообщение.
# По умолчанию используется глубокий мужской голос Onyx и оригинальная
# тихая инструментальная молитвенная подложка, генерируемая локально.
VOICE_TTS_MODEL = os.environ.get(
    "VOICE_TTS_MODEL",
    "gpt-4o-mini-tts",
).strip() or "gpt-4o-mini-tts"
VOICE_TTS_VOICE = os.environ.get(
    "VOICE_TTS_VOICE",
    "onyx",
).strip() or "onyx"
VOICE_TTS_SPEED = 1.0
VOICE_TTS_MAX_CHARS = 1800
VOICE_TTS_TIMEOUT_SECONDS = 180.0
VOICE_REPLY_FILENAME = "bibliya_otvechaet.ogg"
PRAYER_MUSIC_PATH = os.path.join(
    tempfile.gettempdir(),
    "bibliya_otvechaet_prayer_pad_v3.wav",
)

MAX_VOICE_DURATION_SECONDS = 600
MAX_VOICE_FILE_BYTES = 20 * 1024 * 1024

# Ежедневное «Слово на сегодня».
# Отправка идёт в 07:10 по времени Германии.
DAILY_TIMEZONE = ZoneInfo("Europe/Berlin")
DAILY_SEND_HOUR = 7
DAILY_SEND_MINUTE = 10
DAILY_TOPIC_PROMPT_LIMIT = 365
DAILY_GENERATION_MAX_ATTEMPTS = 8
DAILY_WORD_HARD_MAX_WORDS = 450
DAILY_SYSTEM_USER_ID = 0
DAILY_SCHEDULER_INTERVAL_SECONDS = 60
DAILY_WORD_CACHE: dict[str, tuple[str, str]] = {}
DAILY_GENERATION_LOCK = asyncio.Lock()

TELEGRAM_ADMIN_ID_RAW = "".join(
    os.environ.get("TELEGRAM_ADMIN_ID", "").split()
)

try:
    TELEGRAM_ADMIN_ID = (
        int(TELEGRAM_ADMIN_ID_RAW)
        if TELEGRAM_ADMIN_ID_RAW
        else None
    )
except ValueError:
    TELEGRAM_ADMIN_ID = None
    logger.warning(
        "TELEGRAM_ADMIN_ID имеет неверный формат"
    )

PORT = int(os.environ.get("PORT", "10000"))

RENDER_EXTERNAL_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "",
).strip().rstrip("/")

# Публичные реквизиты поддержки.
# Банковские реквизиты сверены с официальной страницей фонда:
# https://blessunited.com/rekviziti
DONATION_OFFICIAL_URL = "https://blessunited.com/rekviziti"

DONATION_RECIPIENT = "БО БФ ОБʼЄДНАНІ У БЛАГОДАТІ УКРАЇНІ"
DONATION_RECIPIENT_CODE = "45171665"

DONATION_UAH_IBAN = "UA813052990000026005050581845"
DONATION_UAH_BANK = 'АТ КБ "ПРИВАТБАНК"'
DONATION_UAH_PURPOSE = "Благодійна допомога"

DONATION_EUR_IBAN = "UA073052990000026005050579006"
DONATION_USD_IBAN = "UA173052990000026002050584845"
DONATION_SWIFT = "PBANUA2X"
DONATION_FOREIGN_BANK = (
    'JSC CB "PRIVATBANK", '
    "1D HRUSHEVSKOHO STR., KYIV, 01001, UKRAINE"
)
DONATION_RECIPIENT_ADDRESS = (
    "21050, УКРАЇНА, ОБЛ. ВІННИЦЬКА, М. ВІННИЦЯ, "
    "ВУЛ. ТЕАТРАЛЬНА, Б. 20, КВ. 410"
)

# Адрес предоставлен владельцем проекта.
DONATION_USDT_TRC20 = "TH8a2B77sFFw4CyFppKnE6sNyX4QsMprAp"

DONATION_MINIMUMS = {
    "UAH": Decimal("50"),
    "EUR": Decimal("1"),
    "USD": Decimal("1"),
    "USDT": Decimal("1"),
}

DONATION_QUICK_AMOUNTS = {
    "UAH": [50, 100, 300, 500, 1000],
    "EUR": [5, 10, 25, 50, 100],
    "USD": [5, 10, 25, 50, 100],
    "USDT": [5, 10, 25, 50, 100],
}

MODEL = "gpt-5.6-luna"

openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    timeout=OPENAI_TIMEOUT_SECONDS,
    max_retries=2,
)

BASE_INSTRUCTIONS = """
Ты — христианский помощник проекта «Библия отвечает».

Твоя цель — помогать человеку обращаться к Богу через молитву,
возвращаться к Священному Писанию,
укрепляться в вере, надежде, мудрости,
покаянии, любви и практическом послушании Христу.

Ты не заменяешь Библию, личную молитву,
живую церковь, пастырскую помощь,
врача, психолога или экстренные службы.

ДУХОВНАЯ ПОДАЧА

1. Отвечай на языке пользователя.
2. Пиши глубоко, библейски, пастырски,
с теплотой, убеждённостью и надеждой.
3. Не копируй манеру конкретного проповедника.
Используй общие качества сильной библейской проповеди:
уважение к тексту Писания,
ясное объяснение духовного принципа,
связь с жизнью,
практическое применение
и надежду во Христе.
4. Ответ должен быть персональным.
Используй детали, которые дал человек.
Не выдавай одинаковые заготовки
для разных людей и ситуаций.
5. Не ограничивайся перечислением стихов.
Показывай, почему конкретное место Писания
важно именно сейчас.
6. Избегай пустых религиозных клише,
канцелярского тона
и искусственной торжественности.

ТОЧНОСТЬ ПИСАНИЯ

7. Не придумывай книги, главы, стихи и цитаты.
8. Используй только те ссылки,
в которых уверен.
9. Если не уверен в дословной формулировке,
передавай смысл своими словами
и не ставь неточный текст в кавычки.
10. Различай:
что прямо говорит Писание,
что является богословским выводом,
а что — практическим применением.

10А. Если рядом с утверждением стоит одна ссылка на Писание,
эта ссылка должна прямо подтверждать именно это утверждение.
Не объединяй в одном предложении несколько разных утверждений,
если приведённый стих подтверждает только одно из них.

10Б. Когда применяешь общий библейский принцип
к конкретной ситуации пользователя
— например, к ребёнку, врачу, операции, работе или финансам —
явно показывай, что это применение или молитвенная просьба.
Пиши:
«мы просим Бога дать врачам мудрость на основании Иакова 1:5»
или
«этот стих побуждает нас просить о мудрости»,
а не:
«Иакова 1:5 говорит, что Бог даст мудрость врачам»,
если стих прямо этого не говорит.

10В. В разделе «🗣 Провозглашение Слова»
используй один из двух точных форматов:
• точная цитата Писания + ссылка;
или
• краткое исповедание веры + формулировка
«на основании...» и ссылка.
Не выдавай богословское применение
за дословный текст стиха.

11. При необходимости кратко объясняй контекст стиха.
12. Греческие или еврейские слова используй
только когда точно уверен в значении
и это реально помогает пониманию.

ВЕРА И ПРОВОЗГЛАШЕНИЕ СЛОВА

13. Поощряй человека читать,
размышлять и произносить вслух Божье Слово,
особенно когда страх, боль или обстоятельства
давят на разум и сердце.
14. Объясняй:
библейское исповедание — не магическая формула
и не способ заставить Бога исполнить желание.
Это согласие сердца и уст
с истиной Божьего Слова,
стойкость в вере
и возвращение к надежде.
15. Когда уместно, добавляй раздел:
🗣 Провозглашение Слова
В нём давай 2–5 коротких
библейски точных утверждений от первого лица
с указанием мест Писания.
16. Не обвиняй человека
в недостатке веры,
если ответ на молитву ещё не виден.
17. Не учи,
что всякое желаемое обязательно произойдёт,
если человек достаточно сильно верит.

ХРИСТОС, КРЕСТ, КРОВЬ И ДУХОВНАЯ БРАНЬ

18. Центр надежды — Иисус Христос:
Его крест, воскресение,
примирение с Богом,
прощение,
победа над грехом
и силами тьмы.
19. Можно говорить о драгоценной крови Христа
как об основании искупления,
прощения,
принадлежности Христу
и победы, совершённой на кресте.
20. При духовной брани
можно молиться во имя Иисуса Христа,
противостоять страху,
духовному угнетению,
искушению
и действию тьмы.
21. Не называй конкретную физическую болезнь
или медицинский диагноз «демоном»
как установленный факт.
22. Не утверждай,
что рак, инфекция, диабет,
сердечная болезнь
или другой диагноз
обязательно вызван нечистым духом.
23. Если тема духовного угнетения уместна,
можно молиться:
«Во имя Иисуса Христа
мы противостоим всякому действию тьмы
и всякому духовному угнетению.
Пусть всё, что не от Бога,
отступит перед властью Христа».

ИСЦЕЛЕНИЕ И МЕДИЦИНА

24. За исцеление молись смело,
конкретно и с верой.
25. Можно прямо просить Бога:
исцелить,
восстановить повреждённое,
укрепить ослабленное,
остановить разрушительные процессы,
уменьшить боль,
дать телу силы,
дать врачам мудрость,
а лечению — принести пользу.
26. Не объявляй заранее,
что физическое исцеление
гарантированно произошло.
27. Не советуй отменять лекарства,
операции, обследования,
терапию
или медицинское наблюдение.
28. Вера и обращение к врачу
не противопоставляются.
29. Никогда не внушай,
что человек остался болен
только потому,
что «плохо верил».
30. В теме исцеления особенно полезны,
когда соответствуют ситуации:
Исаия 53:4–5,
Матфея 4:23–24,
Матфея 8:16–17,
Матфея 9:35,
Матфея 10:1,
Иакова 5:14–16,
Псалом 102:2–5,
Псалом 106:20,
Римлянам 8:11,
Евреям 10:23,
1 Петра 2:24.
Используй их с учётом контекста.

МОЛИТВА И ВОЛЯ БОЖИЯ

31. Учи дерзновенно приходить к Богу
через Иисуса Христа.
32. Показывай одновременно
дерзновение в молитве
и доверие Божьей воле.
33. Полезные основания:
Евреям 4:16,
1 Иоанна 5:14,
Иоанна 15:7,
Иоанна 14:13–14,
1 Иоанна 3:22.
34. Не превращай слова
«да будет воля Твоя»
в пассивность и неверие.
Христианин может смело просить,
стоять в вере
и одновременно доверять Богу результат.

ФИНАНСЫ, РАБОТА И ОБЕСПЕЧЕНИЕ

35. Не проповедуй автоматическое богатство.
36. Не утверждай,
что финансовый успех —
обязательное доказательство
Божьего благоволения.
37. В финансовых нуждах соединяй:
доверие Богу,
мудрый труд,
ответственность,
честность,
дисциплину,
управление ресурсами,
разумное отношение к долгам,
поиск возможностей,
щедрость
и молитву об обеспечении.
38. Можно молиться:
о работе,
клиентах,
идеях,
правильных людях,
открытых дверях,
новых источниках дохода,
мудрых решениях,
защите от мошенничества,
способности создавать ценность
и благословлять других.
39. Полезные места:
Матфея 6:31–33,
Филиппийцам 4:6–7,
Филиппийцам 4:19,
Иакова 1:5,
Притчи 3:5–6,
Притчи 21:5,
Второзаконие 8:18
с учётом его заветного контекста,
2 Коринфянам 9:6–11,
Псалом 22.

СВЯТОСТЬ, ПОКАЯНИЕ И ЛЮБОВЬ

40. Если вопрос касается греха,
говори ясно,
но без унижения.
41. Показывай:
грех разрушает,
покаяние возвращает к свету,
Бог прощает кающегося,
а благодать не отменяет послушания.
42. Не выдавай человеческий комментарий
за прямую речь Иисуса.
43. Тексты в форме
«Иисус лично сказал тебе...»
переформулируй как:
«Писание показывает...»,
«из истории Иосифа мы видим...»,
«верующий может находить надежду в том, что...».

БЕЗОПАСНОСТЬ

44. Если человек сообщает
о непосредственной опасности,
намерении причинить вред себе
или другому человеку,
тяжёлом неотложном медицинском состоянии,
сначала советуй немедленно обратиться
за экстренной помощью
и к находящемуся рядом человеку,
которому можно доверять.

ФОРМАТ TELEGRAM

45. Пиши обычным текстом,
без Markdown-разметки.
46. Не используй:
**
__
###
обратные кавычки
и другие технические символы.
47. Для списков используй символ •.
48. Делай короткие абзацы.
49. Между смысловыми разделами
оставляй одну пустую строку.
50. Заголовки можно начинать с эмодзи.
51. Не растягивай ответ пустыми словами.
Глубина важнее длины.

52. Всегда доводи ответ до логического завершения.
Не заканчивай посреди слова, предложения,
молитвы, списка или предупреждения.

53. Даже для глубокого ответа
старайся укладываться примерно в 900–1400 слов,
чтобы ответ оставался содержательным,
но полностью завершался.
"""


MODE_INSTRUCTIONS = {
    "ask": """
Ответь глубоко, ясно
и строго на основании Писания.

Обычно включай:

📖 Библейский взгляд
Объясни духовную суть ситуации.

📚 Слово Божье
Дай 2–4 подходящих места Писания
и объясни их связь с вопросом.

🔥 Глубже
Покажи один важный духовный принцип,
который легко пропустить
при поверхностном взгляде.

✅ Что делать сегодня
Дай 1–3 конкретных шага.

🗣 Провозглашение Слова
Если это уместно,
дай 2–4 коротких исповедания
со ссылками на Писание.

🕊 Надежда
Закончи Христоцентричным ободрением.

Не составляй молитву,
если пользователь её не просил.
""",

    "prayer": """
Пользователь просит молитву
по конкретной жизненной нужде.

Ответ должен быть персональным,
духовно зрелым
и библейски насыщенным.

Обычно включай:

📖 Слово для сердца
Покажи, как Писание говорит
именно в эту ситуацию.

📚 Основание в Писании
Используй 3–5 подходящих мест
и объясни их значение.

🔥 Позиция веры
Покажи, на чём человек может стоять:
верность Бога,
доступ к Отцу через Христа,
Его мудрость,
провидение,
защита,
мир,
обеспечение
или другое уместное основание.

🙏 Молитва
Составь содержательную,
персональную молитву
из нескольких абзацев.

Естественно соединяй:
благодарность,
поклонение,
конкретную просьбу,
опору на Слово,
противостояние страху,
мудрость,
послушание,
мир,
стойкость
и надежду.

Если ситуация касается
духовного давления,
можно во имя Иисуса Христа
противостоять всякому действию тьмы
и духовному угнетению.

🗣 Провозглашение Слова
Дай 3–5 коротких утверждений
от первого лица,
каждое со ссылкой на Писание.

Одной фразой поясни:
это не магическая формула,
а способ согласить сердце и уста
с Божьей истиной.

🕊 Надежда
Закончи сильным,
но не манипулятивным ободрением.
""",

    "healing": """
Пользователь просит молитву
об исцелении.

Молись смело,
с верой,
состраданием
и сильным основанием в Писании.

Не делай ответ стерильным
или чрезмерно осторожным,
но не обещай гарантированный результат.

Учитывай конкретные детали:
кто болеет,
какой диагноз или симптомы названы,
что происходит сейчас,
чего человек боится,
есть ли операция,
реанимация,
лечение,
ребёнок,
семья,
длительная боль
или другая конкретика.

Обычно включай:

❤️ Пастырская поддержка
Покажи сострадание Христа
и близость Бога к страдающему.

✝️ Основание во Христе
Раскрой:
крест,
воскресение,
искупление,
победу Христа,
Его сострадание к больным,
право верующего приходить к Отцу
во имя Иисуса Христа.

Используй Исаию 53:4–5
в связи с Матфея 8:16–17,
если это уместно.

📚 Слово об исцелении
Используй 3–5 подходящих мест Писания.

🔥 Стойте на Слове
Призывай:
читать Слово,
размышлять над ним,
молиться им
и провозглашать его вслух с верой.

Объясняй:
мы не отрицаем симптомы,
но не позволяем страху
быть последним словом.

🛡 Духовная брань
Если уместно,
во имя Иисуса Христа
противостой всякому действию тьмы,
духовному угнетению,
страху
и отчаянию.

Не называй конкретный диагноз
«демоном болезни»
как установленный факт.

🩺 Вера и медицина
Не противопоставляй веру врачам.
Молись:
о мудрости врачам,
точной диагностике,
правильном лечении,
успешной операции,
восстановлении организма,
уменьшении боли,
силе для пациента
и семьи.

🙏 Молитва об исцелении
Молитва должна быть
содержательной и конкретной.

Смело проси:
об исцелении,
восстановлении,
укреплении,
остановке разрушительных процессов,
нормальной работе органов,
облегчении боли,
силе телу,
мире сердцу,
мудрости врачам.

Можно молиться:
«Господь Иисус,
мы приходим к Тебе
на основании Твоего Слова
и просим об исцелении...»

Можно говорить
о драгоценной крови Христа
как об основании искупления
и победы на кресте.

Не используй кровь Христа
как магическую или суеверную формулу.

🗣 Провозглашение Слова
Дай 3–5 коротких утверждений
со ссылками на Писание.

В конце напомни:
провозглашение Слова
не является магической формулой,
а отсутствие мгновенного результата
не означает,
что человек «плохо верит».

🕊 Надежда
Закончи сильным взглядом на Христа,
а не на болезнь.
""",

    "finances": """
Пользователь просит помощи
в вопросах работы,
денег,
финансового роста,
обеспечения
или бизнеса.

Не обещай автоматического богатства
и не делай богатство мерой духовности.

Обычно включай:

📖 Бог — источник
Покажи Божью заботу
и освободи человека
от рабства страху перед будущим.

📚 Основание в Писании
Используй 3–5 подходящих мест:
Матфея 6:31–33,
Филиппийцам 4:19,
Иакова 1:5,
Притчи 3:5–6,
Притчи 21:5,
2 Коринфянам 9:6–11
или другие уместные места.

💼 Мудрость и труд
Говори о:
честном труде,
дисциплине,
планировании,
разумном риске,
избегании мошенничества,
создании ценности,
обучении,
ответственности
и правильном управлении деньгами.

🙏 Молитва
Проси:
о работе,
клиентах,
идеях,
возможностях,
правильных людях,
новых источниках дохода,
мудрости,
защите от плохих решений,
достатке для нужд
и способности благословлять других.

🗣 Провозглашение Слова
Дай 3–5 библейских утверждений
со ссылками.

🕊 Следующий шаг
Дай 1–3 практических действия
на ближайшее время.
""",

    "blessing": """
Пользователь просит благословение
для себя,
семьи,
детей,
дома,
труда,
пути
или будущего.

Не пророчествуй
и не обещай конкретных событий.

Опирайся на Писание.

Можно включать:
Божий мир,
мудрость,
защиту,
святость,
любовь,
единство семьи,
руководство,
плод Духа,
верность,
труд,
служение,
здоровье
и способность быть благословением
для других.

Обычно структура:

📖 Слово благословения

📚 2–4 места Писания

🙏 Молитва благословения

🗣 Провозглашение Слова

🕊 Ободрение

Молитва должна направлять
к Богу и Христу,
а не к суеверному ожиданию удачи.
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
            "Доверие Богу не отменяет мудрости; "
            "оно не позволяет нашему ограниченному пониманию "
            "занять место Бога."
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
            "Страх не должен диктовать человеку будущее: "
            "Писание возвращает взгляд к присутствию Бога."
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
            "не только грех, но и тяжесть, усталость и боль."
        ),
    },
    {
        "reference": "Иоанна 14:27",
        "text": (
            "«Мир оставляю вам, "
            "мир Мой даю вам»."
        ),
        "thought": (
            "Мир Христа глубже обстоятельств "
            "и может хранить сердце среди неопределённости."
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
            "Надежда, стойкость и молитва "
            "помогают проходить трудный путь день за днём."
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
            "в конкретную молитву и благодарение."
        ),
    },
    {
        "reference": "1 Петра 5:7",
        "text": (
            "«Все заботы ваши возложите на Него, "
            "ибо Он печется о вас»."
        ),
        "thought": (
            "Бог не призывает человека "
            "нести каждую тяжесть в одиночку."
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
    mode_instruction = MODE_INSTRUCTIONS.get(
        mode,
        MODE_INSTRUCTIONS["ask"],
    )

    if mode == "ask":
        mode_instruction += """

ВАЖНО О ДЛИНЕ И СТРУКТУРЕ ОТВЕТА:

Обычный ответ на библейский вопрос должен быть глубоким,
но компактным и удобным для чтения в Telegram.

Ориентируйся примерно на 450–650 слов.

Не повторяй одну и ту же мысль разными словами.
Не растягивай вступление.
Не создавай лишние разделы только ради объёма.

Выбери самые сильные и непосредственно относящиеся
к вопросу места Писания.

Обычно достаточно:
• ясного библейского объяснения;
• 2–4 ключевых мест Писания;
• одного действительно глубокого духовного принципа;
• 1–3 практических шагов;
• короткого провозглашения, если оно уместно;
• завершённого Христоцентричного ободрения.

Каждый раздел должен добавлять новую мысль,
а не повторять предыдущий.

ОБЯЗАТЕЛЬНО доводи ответ до логического завершения.
Никогда не заканчивай ответ на незаконченной фразе,
незавершённом списке или посреди раздела.
"""

    instructions = (
        BASE_INSTRUCTIONS
        + "\n"
        + mode_instruction
    )

    response = await openai_client.responses.create(
        model=MODEL,
        instructions=instructions,
        input=user_text,
        max_output_tokens=3000,
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



def donation_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🇺🇦 UAH / гривна",
                    callback_data="donate_uah",
                )
            ],
            [
                InlineKeyboardButton(
                    "🇪🇺 EUR / банковский перевод",
                    callback_data="donate_eur",
                )
            ],
            [
                InlineKeyboardButton(
                    "💵 USD / банковский перевод",
                    callback_data="donate_usd",
                )
            ],
            [
                InlineKeyboardButton(
                    "₮ USDT / TRC20",
                    callback_data="donate_usdt",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Главное меню",
                    callback_data="menu",
                )
            ],
        ]
    )


def currency_label(currency: str) -> str:
    labels = {
        "UAH": "🇺🇦 Гривна / UAH",
        "EUR": "🇪🇺 Евро / EUR",
        "USD": "💵 Доллары / USD",
        "USDT": "₮ USDT / TRC20",
    }
    return labels.get(currency, currency)


def format_donation_amount(
    amount: Decimal,
    currency: str,
) -> str:
    if amount == amount.to_integral_value():
        number = f"{int(amount):,}".replace(",", " ")
    else:
        number = (
            f"{amount.quantize(Decimal('0.01')):,.2f}"
            .replace(",", " ")
        )

    suffixes = {
        "UAH": "₴",
        "EUR": "€",
        "USD": "$",
        "USDT": "USDT",
    }
    suffix = suffixes.get(currency, currency)

    if currency in {"EUR", "USD"}:
        return f"{suffix}{number}"

    return f"{number} {suffix}"


def donation_amount_menu(
    currency: str,
) -> InlineKeyboardMarkup:
    rows = []
    amounts = DONATION_QUICK_AMOUNTS[currency]

    current_row = []

    for value in amounts:
        amount = Decimal(str(value))
        current_row.append(
            InlineKeyboardButton(
                format_donation_amount(
                    amount,
                    currency,
                ),
                callback_data=(
                    f"don_amt_{currency.lower()}_{value}"
                ),
            )
        )

        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "✏️ Другая сумма",
                    callback_data=(
                        f"don_custom_{currency.lower()}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 Реквизиты без суммы",
                    callback_data=(
                        f"don_details_{currency.lower()}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Способы поддержки",
                    callback_data="donate",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Главное меню",
                    callback_data="menu",
                )
            ],
        ]
    )

    return InlineKeyboardMarkup(rows)


def donation_details_menu(
    currency: str,
    amount: Decimal | None = None,
) -> InlineKeyboardMarkup:
    rows = []

    if amount is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    "📋 Скопировать сумму",
                    copy_text=CopyTextButton(
                        text=str(
                            amount.normalize()
                        ),
                    ),
                )
            ]
        )

    if currency == "UAH":
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "📋 Скопировать IBAN",
                        copy_text=CopyTextButton(
                            text=DONATION_UAH_IBAN,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📋 Скопировать код получателя",
                        copy_text=CopyTextButton(
                            text=DONATION_RECIPIENT_CODE,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📋 Скопировать назначение",
                        copy_text=CopyTextButton(
                            text=DONATION_UAH_PURPOSE,
                        ),
                    )
                ],
            ]
        )

    elif currency in {"EUR", "USD"}:
        iban = (
            DONATION_EUR_IBAN
            if currency == "EUR"
            else DONATION_USD_IBAN
        )

        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "📋 Скопировать IBAN",
                        copy_text=CopyTextButton(
                            text=iban,
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📋 Скопировать SWIFT",
                        copy_text=CopyTextButton(
                            text=DONATION_SWIFT,
                        ),
                    )
                ],
            ]
        )

    elif currency == "USDT":
        rows.append(
            [
                InlineKeyboardButton(
                    "📋 Скопировать USDT-адрес",
                    copy_text=CopyTextButton(
                        text=DONATION_USDT_TRC20,
                    ),
                )
            ]
        )

    if currency in {"UAH", "EUR", "USD"}:
        rows.append(
            [
                InlineKeyboardButton(
                    "🌐 Официальные реквизиты фонда",
                    url=DONATION_OFFICIAL_URL,
                )
            ]
        )

    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Изменить сумму",
                    callback_data=(
                        f"donate_{currency.lower()}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "🤝 Другой способ",
                    callback_data="donate",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Главное меню",
                    callback_data="menu",
                )
            ],
        ]
    )

    return InlineKeyboardMarkup(rows)


def donation_details_text(
    currency: str,
    amount: Decimal | None = None,
) -> str:
    amount_block = ""

    if amount is not None:
        amount_block = (
            f"\n<b>Вы выбрали:</b> "
            f"{format_donation_amount(amount, currency)}\n"
        )

    if currency == "UAH":
        return (
            "🇺🇦 <b>Поддержка в гривне</b>\n"
            f"{amount_block}\n"
            "Перевод выполняется в вашем банковском приложении.\n\n"
            f"<b>Получатель:</b> {DONATION_RECIPIENT}\n"
            f"<b>Код:</b> <code>{DONATION_RECIPIENT_CODE}</code>\n"
            f"<b>IBAN:</b> <code>{DONATION_UAH_IBAN}</code>\n"
            f"<b>Банк:</b> {DONATION_UAH_BANK}\n"
            f"<b>Назначение:</b> {DONATION_UAH_PURPOSE}\n\n"
            "Перед подтверждением перевода проверьте "
            "получателя и IBAN."
        )

    if currency == "EUR":
        return (
            "🇪🇺 <b>Поддержка в евро</b>\n"
            f"{amount_block}\n"
            "Это банковский валютный перевод на официальный "
            "EUR-счёт фонда.\n\n"
            f"<b>Получатель:</b> {DONATION_RECIPIENT}\n"
            f"<b>IBAN:</b> <code>{DONATION_EUR_IBAN}</code>\n"
            f"<b>SWIFT:</b> <code>{DONATION_SWIFT}</code>\n"
            f"<b>Банк:</b> {DONATION_FOREIGN_BANK}\n"
            f"<b>Адрес получателя:</b> {DONATION_RECIPIENT_ADDRESS}\n\n"
            "Если ваш банк запросит банк-корреспондент, "
            "используйте кнопку «Официальные реквизиты фонда»."
        )

    if currency == "USD":
        return (
            "💵 <b>Поддержка в долларах</b>\n"
            f"{amount_block}\n"
            "Это банковский валютный перевод на официальный "
            "USD-счёт фонда.\n\n"
            f"<b>Получатель:</b> {DONATION_RECIPIENT}\n"
            f"<b>IBAN:</b> <code>{DONATION_USD_IBAN}</code>\n"
            f"<b>SWIFT:</b> <code>{DONATION_SWIFT}</code>\n"
            f"<b>Банк:</b> {DONATION_FOREIGN_BANK}\n"
            f"<b>Адрес получателя:</b> {DONATION_RECIPIENT_ADDRESS}\n\n"
            "Если ваш банк запросит банк-корреспондент, "
            "используйте кнопку «Официальные реквизиты фонда»."
        )

    if currency == "USDT":
        return (
            "₮ <b>Поддержка USDT</b>\n"
            f"{amount_block}\n"
            "<b>Сеть:</b> TRON / TRC20\n"
            f"<b>Адрес:</b>\n<code>{DONATION_USDT_TRC20}</code>\n\n"
            "⚠️ Отправляйте только USDT по сети TRON / TRC20. "
            "Криптовалютные переводы обычно необратимы, "
            "поэтому перед отправкой ещё раз сверьте адрес и сеть. "
            "Для крупной суммы разумно сначала сделать небольшой "
            "тестовый перевод."
        )

    return "Выберите способ поддержки."


def parse_donation_amount(
    text: str,
    currency: str,
) -> tuple[Decimal | None, str | None]:
    cleaned = text.strip().upper()

    for token in (
        "UAH",
        "EUR",
        "USD",
        "USDT",
        "₴",
        "€",
        "$",
    ):
        cleaned = cleaned.replace(
            token,
            "",
        )

    cleaned = (
        cleaned
        .replace(" ", "")
        .replace(",", ".")
    )

    if not re.fullmatch(
        r"\d+(?:\.\d{1,2})?",
        cleaned,
    ):
        return (
            None,
            "Введите только сумму, например: 500",
        )

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return (
            None,
            "Не удалось распознать сумму.",
        )

    minimum = DONATION_MINIMUMS[currency]

    if amount < minimum:
        return (
            None,
            (
                "Минимальная сумма для этого раздела — "
                f"{format_donation_amount(minimum, currency)}."
            ),
        )

    return amount, None



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
                    "💼 Работа и финансы",
                    callback_data="finances",
                )
            ],
            [
                InlineKeyboardButton(
                    "✨ Благословение",
                    callback_data="blessing",
                )
            ],
            [
                InlineKeyboardButton(
                    "🌅 Слово на каждый день",
                    callback_data="daily",
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
                    "📤 Поделиться ботом",
                    callback_data="share",
                )
            ],
            [
                InlineKeyboardButton(
                    "🤝 Поддержать служение",
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


def supabase_is_configured() -> bool:
    return bool(
        SUPABASE_URL
        and SUPABASE_URL.startswith("https://")
        and SUPABASE_SECRET_KEY
    )


def supabase_headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }



def normalize_start_source(
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    if not context.args:
        return "direct"

    raw_source = context.args[0].strip().lower()

    if not re.fullmatch(
        r"[a-z0-9_-]{1,64}",
        raw_source,
    ):
        return "other"

    return raw_source


def analytics_event_for_action(
    action: str,
) -> str:
    if action.startswith("don_amt_"):
        parts = action.split("_")

        if len(parts) >= 3:
            return (
                "donation_amount_"
                + parts[2].lower()
            )

    if action.startswith("don_custom_"):
        return (
            "donation_custom_"
            + action.replace(
                "don_custom_",
                "",
            ).lower()
        )

    if action.startswith("don_details_"):
        return (
            "donation_details_"
            + action.replace(
                "don_details_",
                "",
            ).lower()
        )

    aliases = {
        "donate": "donation_open",
        "donate_uah": "donation_currency_uah",
        "donate_eur": "donation_currency_eur",
        "donate_usd": "donation_currency_usd",
        "donate_usdt": "donation_currency_usdt",
        "ask": "menu_ask",
        "prayer": "menu_prayer",
        "healing": "menu_healing",
        "finances": "menu_finances",
        "blessing": "menu_blessing",
        "verse": "menu_verse",
        "daily": "menu_daily",
        "daily_subscribe": "daily_subscribe_click",
        "daily_unsubscribe": "daily_unsubscribe_click",
        "daily_today": "daily_today_click",
        "share": "share_open",
        "about": "menu_about",
        "menu": "menu_home",
    }

    return aliases.get(
        action,
        "button_other",
    )


async def analytics_get_user(
    telegram_user_id: int,
) -> dict | None:
    if not supabase_is_configured():
        return None

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{ANALYTICS_USERS_TABLE}"
    )

    params = {
        "telegram_user_id": (
            f"eq.{telegram_user_id}"
        ),
        "select": (
            "telegram_user_id,first_seen_at,"
            "last_seen_at,source,start_count"
        ),
        "limit": "1",
    }

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(
                url,
                headers=supabase_headers(),
                params=params,
            )
            response.raise_for_status()

        rows = response.json()

        if not rows:
            return None

        return rows[0]

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
        ValueError,
    ):
        logger.exception(
            "Не удалось прочитать пользователя аналитики"
        )
        return None


async def analytics_track_start(
    telegram_user_id: int,
    source: str,
) -> None:
    if not supabase_is_configured():
        return

    now = datetime.now(
        timezone.utc
    ).isoformat()

    existing = await analytics_get_user(
        telegram_user_id
    )

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{ANALYTICS_USERS_TABLE}"
    )

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            if existing is None:
                payload = {
                    "telegram_user_id": telegram_user_id,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "source": source,
                    "start_count": 1,
                }

                response = await client.post(
                    url,
                    headers=supabase_headers(),
                    json=payload,
                )
            else:
                current_count = existing.get(
                    "start_count",
                    0,
                )

                if not isinstance(
                    current_count,
                    int,
                ):
                    current_count = 0

                params = {
                    "telegram_user_id": (
                        f"eq.{telegram_user_id}"
                    ),
                }

                payload = {
                    "last_seen_at": now,
                    "start_count": (
                        current_count + 1
                    ),
                }

                response = await client.patch(
                    url,
                    headers=supabase_headers(),
                    params=params,
                    json=payload,
                )

            response.raise_for_status()

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
    ):
        logger.exception(
            "Не удалось сохранить старт пользователя "
            "в аналитике"
        )


async def analytics_touch_user(
    telegram_user_id: int,
) -> None:
    if not supabase_is_configured():
        return

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{ANALYTICS_USERS_TABLE}"
    )

    params = {
        "telegram_user_id": (
            f"eq.{telegram_user_id}"
        ),
    }

    payload = {
        "last_seen_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.patch(
                url,
                headers=supabase_headers(),
                params=params,
                json=payload,
            )
            response.raise_for_status()

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
    ):
        logger.exception(
            "Не удалось обновить активность пользователя"
        )


async def analytics_log_event(
    telegram_user_id: int,
    event_name: str,
) -> None:
    if not supabase_is_configured():
        return

    safe_event = re.sub(
        r"[^a-z0-9_-]",
        "_",
        event_name.lower(),
    )[:80]

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{ANALYTICS_EVENTS_TABLE}"
    )

    payload = {
        "telegram_user_id": telegram_user_id,
        "event_name": safe_event,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.post(
                url,
                headers=supabase_headers(),
                json=payload,
            )
            response.raise_for_status()

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
    ):
        logger.exception(
            "Не удалось записать событие аналитики"
        )


async def analytics_activity(
    telegram_user_id: int,
    event_name: str,
) -> None:
    await analytics_touch_user(
        telegram_user_id
    )
    await analytics_log_event(
        telegram_user_id,
        event_name,
    )




async def analytics_has_event(
    telegram_user_id: int,
    event_name: str,
) -> bool:
    """Проверяет наличие точного события без изменения схемы БД."""
    if not supabase_is_configured():
        return False

    safe_event = re.sub(
        r"[^a-z0-9_-]",
        "_",
        event_name.lower(),
    )[:80]

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{ANALYTICS_EVENTS_TABLE}"
    )
    params = {
        "telegram_user_id": f"eq.{telegram_user_id}",
        "event_name": f"eq.{safe_event}",
        "select": "id",
        "limit": "1",
    }

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(
                url,
                headers=supabase_headers(),
                params=params,
            )
            response.raise_for_status()
        rows = response.json()
        return bool(rows)
    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
        ValueError,
    ):
        logger.exception(
            "Не удалось проверить событие аналитики"
        )
        return False


async def analytics_fetch_events(
    filters_map: dict[str, str],
    *,
    select: str = "telegram_user_id,event_name,created_at",
    order: str = "created_at.asc",
    max_rows: int = 10000,
) -> list[dict]:
    """Постранично читает события из Supabase."""
    if not supabase_is_configured():
        return []

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{ANALYTICS_EVENTS_TABLE}"
    )
    result: list[dict] = []
    page_size = 1000
    offset = 0

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            while len(result) < max_rows:
                params = {
                    "select": select,
                    "order": order,
                    "limit": str(
                        min(page_size, max_rows - len(result))
                    ),
                    "offset": str(offset),
                    **filters_map,
                }
                response = await client.get(
                    url,
                    headers=supabase_headers(),
                    params=params,
                )
                response.raise_for_status()
                rows = response.json()

                if not isinstance(rows, list):
                    break

                result.extend(rows)
                if len(rows) < page_size:
                    break
                offset += len(rows)

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
        ValueError,
    ):
        logger.exception(
            "Не удалось получить список событий аналитики"
        )

    return result


def daily_date_key(
    value: datetime | None = None,
) -> str:
    now = value or datetime.now(DAILY_TIMEZONE)
    return now.astimezone(DAILY_TIMEZONE).strftime("%Y_%m_%d")


def daily_sent_event(date_key: str) -> str:
    return f"daily_sent_{date_key}"


def daily_topic_prefix(date_key: str) -> str:
    return f"daily_topic_{date_key}_"


async def daily_get_active_subscriber_ids() -> set[int]:
    rows = await analytics_fetch_events(
        {
            "event_name": (
                "in.(daily_subscribe,daily_unsubscribe)"
            )
        },
        max_rows=10000,
    )

    status: dict[int, bool] = {}
    for row in rows:
        user_id = row.get("telegram_user_id")
        event_name = row.get("event_name")
        if not isinstance(user_id, int):
            continue
        if event_name == "daily_subscribe":
            status[user_id] = True
        elif event_name == "daily_unsubscribe":
            status[user_id] = False

    return {
        user_id
        for user_id, subscribed in status.items()
        if subscribed and user_id > 0
    }


async def daily_is_subscribed(
    telegram_user_id: int,
) -> bool:
    rows = await analytics_fetch_events(
        {
            "telegram_user_id": f"eq.{telegram_user_id}",
            "event_name": (
                "in.(daily_subscribe,daily_unsubscribe)"
            ),
        },
        order="created_at.desc",
        max_rows=1,
    )
    if not rows:
        return False
    return rows[0].get("event_name") == "daily_subscribe"


async def daily_get_sent_user_ids(
    date_key: str,
) -> set[int]:
    rows = await analytics_fetch_events(
        {
            "event_name": f"eq.{daily_sent_event(date_key)}",
        },
        max_rows=10000,
    )
    result: set[int] = set()
    for row in rows:
        user_id = row.get("telegram_user_id")
        if isinstance(user_id, int) and user_id > 0:
            result.add(user_id)
    return result


async def daily_get_used_topic_keys() -> list[str]:
    """
    Возвращает полную историю использованных основных отрывков.

    Новые ежедневные тексты хранятся в bible_bot_daily_messages.
    Старые темы, созданные до этого обновления, дополнительно читаются
    из bible_bot_events. При ошибке проверки история считается
    недоступной и новое Слово не публикуется: лучше пропустить отправку,
    чем случайно повторить уже использованный отрывок.
    """
    if not supabase_is_configured():
        raise RuntimeError(
            "Supabase недоступен: нельзя проверить историю ежедневных отрывков"
        )

    keys: list[str] = []
    seen: set[str] = set()

    async def add_key(value) -> None:
        if not isinstance(value, str):
            return
        key = value.strip().lower().strip("_")
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    # Постоянная история новых публикаций.
    messages_url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{DAILY_MESSAGES_TABLE}"
    )

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            offset = 0
            page_size = 1000
            while True:
                response = await client.get(
                    messages_url,
                    headers=supabase_headers(),
                    params={
                        "select": "verse_reference",
                        "order": "created_at.desc",
                        "limit": str(page_size),
                        "offset": str(offset),
                    },
                )
                response.raise_for_status()
                rows = response.json()
                if not isinstance(rows, list):
                    raise ValueError("Некорректный ответ daily_messages")

                for row in rows:
                    await add_key(row.get("verse_reference"))

                if len(rows) < page_size:
                    break
                offset += len(rows)

            # Наследуем темы, которые уже были опубликованы старой версией.
            events_url = (
                f"{SUPABASE_URL}/rest/v1/"
                f"{ANALYTICS_EVENTS_TABLE}"
            )
            offset = 0
            while True:
                response = await client.get(
                    events_url,
                    headers=supabase_headers(),
                    params={
                        "telegram_user_id": f"eq.{DAILY_SYSTEM_USER_ID}",
                        "event_name": "like.daily_topic_*",
                        "select": "event_name",
                        "order": "created_at.desc",
                        "limit": str(page_size),
                        "offset": str(offset),
                    },
                )
                response.raise_for_status()
                rows = response.json()
                if not isinstance(rows, list):
                    raise ValueError("Некорректный ответ analytics events")

                for row in rows:
                    event_name = row.get("event_name")
                    if not isinstance(event_name, str):
                        continue
                    match = re.match(
                        r"daily_topic_\d{4}_\d{2}_\d{2}_(.+)$",
                        event_name,
                    )
                    if match:
                        await add_key(match.group(1))

                if len(rows) < page_size:
                    break
                offset += len(rows)

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
        ValueError,
    ) as exc:
        logger.exception(
            "Не удалось проверить постоянную историю ежедневных отрывков"
        )
        raise RuntimeError(
            "Не удалось проверить историю ежедневных отрывков"
        ) from exc

    return keys


def daily_reference_scope(reference_key: str) -> str:
    """
    Нормализует основной отрывок до книги и главы.

    Это дополнительная защита: после использования места из Луки 24
    бот не сможет позже обойти проверку, назвав тот же сюжет
    luke_24_32 вместо luke_24_13_35 (или наоборот).
    """
    parts = [p for p in reference_key.lower().split("_") if p]
    if len(parts) < 2:
        return reference_key.lower()

    search_from = 1 if parts[0] in {"1", "2", "3"} else 0
    chapter_index = None
    for index in range(search_from, len(parts)):
        if parts[index].isdigit():
            chapter_index = index
            break

    if chapter_index is None or chapter_index == 0:
        return reference_key.lower()

    book = "_".join(parts[:chapter_index])
    chapter = parts[chapter_index]
    return f"{book}_{chapter}"


async def daily_get_today_topic_key(
    date_key: str,
) -> str | None:
    rows = await analytics_fetch_events(
        {
            "telegram_user_id": f"eq.{DAILY_SYSTEM_USER_ID}",
            "event_name": f"like.{daily_topic_prefix(date_key)}*",
        },
        order="created_at.asc",
        max_rows=1,
    )
    if not rows:
        return None

    event_name = rows[0].get("event_name")
    if not isinstance(event_name, str):
        return None

    prefix = daily_topic_prefix(date_key)
    if not event_name.startswith(prefix):
        return None

    key = event_name[len(prefix):].strip("_")
    return key or None



def daily_publish_date(date_key: str) -> str:
    return date_key.replace("_", "-")


def daily_extract_title(body: str, fallback: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("🔥"):
            title = line.lstrip("🔥").strip()
            if title:
                return title[:300]
    return fallback[:300]


async def daily_load_stored_word(
    date_key: str,
) -> tuple[str, str] | None:
    """Загружает уже утверждённое Слово на конкретную дату."""
    if not supabase_is_configured():
        raise RuntimeError(
            "Supabase недоступен: нельзя безопасно загрузить ежедневное Слово"
        )

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{DAILY_MESSAGES_TABLE}"
    )
    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(
                url,
                headers=supabase_headers(),
                params={
                    "publish_date": f"eq.{daily_publish_date(date_key)}",
                    "select": "verse_reference,body",
                    "limit": "1",
                },
            )
            response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Некорректный ответ daily_messages")
        if not rows:
            return None

        key = str(rows[0].get("verse_reference") or "").strip().lower()
        body = str(rows[0].get("body") or "").strip()
        if key and body:
            return key, body
        return None

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
        ValueError,
    ) as exc:
        logger.exception(
            "Не удалось загрузить сохранённое ежедневное Слово"
        )
        raise RuntimeError(
            "Не удалось загрузить сохранённое ежедневное Слово"
        ) from exc


async def daily_store_word(
    date_key: str,
    reference_key: str,
    body: str,
) -> bool:
    """
    Сохраняет Слово до отправки.

    UNIQUE-индексы Supabase по verse_reference и title — последний
    уровень защиты от повторов. False означает конфликт уникальности.
    """
    if not supabase_is_configured():
        raise RuntimeError(
            "Supabase недоступен: нельзя безопасно сохранить ежедневное Слово"
        )

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{DAILY_MESSAGES_TABLE}"
    )
    payload = {
        "publish_date": daily_publish_date(date_key),
        "verse_reference": reference_key.lower(),
        "title": daily_extract_title(body, reference_key),
        "body": body,
    }

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.post(
                url,
                headers=supabase_headers(),
                json=payload,
            )

        if response.status_code == 409:
            return False

        response.raise_for_status()
        return True

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            return False
        logger.exception("Не удалось сохранить ежедневное Слово")
        raise RuntimeError("Не удалось сохранить ежедневное Слово") from exc
    except (
        httpx.TimeoutException,
        httpx.NetworkError,
    ) as exc:
        logger.exception("Не удалось сохранить ежедневное Слово")
        raise RuntimeError("Не удалось сохранить ежедневное Слово") from exc


def daily_word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


async def daily_compress_if_needed(text: str) -> str:
    """Жёстко удерживает ежедневный текст в мобильном формате."""
    result = clean_ai_text(text)
    if daily_word_count(result) <= DAILY_WORD_HARD_MAX_WORDS:
        return result

    instructions = """
Ты — строгий редактор ежедневного библейского текста для Telegram.

Сожми текст до 320–410 слов. Абсолютный максимум — 450 слов.
Сохрани:
• главное место Писания;
• сильный заголовок;
• одну центральную духовную мысль;
• короткое «🌿 Свидетельство Божьей славы», прямо связанное с темой;
• ровно 3 коротких шага «✅ На сегодня»;
• молитву из 2–3 предложений.

Удали повторы, длинные вводные и второстепенные объяснения.
Не добавляй новых библейских фактов и не меняй смысл.
Обычный текст без Markdown. Верни только готовый текст.
"""

    for _ in range(2):
        response = await openai_client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=result,
            max_output_tokens=1700,
        )
        candidate = clean_ai_text(response.output_text or "")
        if candidate:
            result = candidate
        if daily_word_count(result) <= DAILY_WORD_HARD_MAX_WORDS:
            return result

    # Fail closed: длинный материал лучше не отправить, чем нарушить формат.
    raise RuntimeError(
        "Ежедневное Слово не удалось сократить до установленной длины"
    )


def parse_daily_generation(
    raw_text: str,
) -> tuple[str | None, str]:
    raw_text = (raw_text or "").strip()
    match = re.search(
        r"(?im)^REFERENCE_KEY:\s*([a-z0-9_]{3,70})\s*$",
        raw_text,
    )
    key = match.group(1).lower() if match else None

    body_match = re.search(
        r"(?is)^.*?^BODY:\s*\n?(.*)$",
        raw_text,
    )
    body = body_match.group(1).strip() if body_match else raw_text
    return key, clean_ai_text(body)


async def generate_daily_word(
    *,
    forced_reference_key: str | None = None,
    recent_topic_keys: list[str] | None = None,
) -> tuple[str, str]:
    recent_topic_keys = recent_topic_keys or []

    recent_for_prompt = ", ".join(
        recent_topic_keys[:DAILY_TOPIC_PROMPT_LIMIT]
    ) or "пока нет"

    if forced_reference_key:
        topic_instruction = (
            "Сегодняшний отрывок уже выбран. "
            "Используй именно этот ключ библейского места: "
            f"{forced_reference_key}. "
            "Не меняй его на другой."
        )
    else:
        topic_instruction = (
            "Выбери сильный библейский отрывок или эпизод, "
            "которого нет в списке недавних тем. "
            "Не повторяй ни тот же стих, ни тот же основной сюжет."
        )

    generation_instructions = """
Ты создаёшь ежедневное христианское размышление для Telegram-проекта
«Библия отвечает».

Цель: чтобы человеку хотелось читать его каждый день, глубже понимать
Писание, приближаться ко Христу, молиться и применять Слово в жизни.

Требования к качеству:
• строго опирайся на Библию;
• не выдумывай книги, главы, стихи, детали библейских историй;
• не приписывай Богу обещаний, которых текст не даёт;
• не превращай веру в магическую формулу или гарантию желаемого исхода;
• если приводишь дословную цитату, она должна быть точной; если есть
  сомнение в дословности, передай смысл без кавычек и укажи ссылку;
• не выдумывай современные «свидетельства». Раздел свидетельства должен
  опираться на реальное событие из Писания;
• не копируй стиль конкретного современного автора или проповедника;
• пиши живо, глубоко, пастырски, без канцелярита и пустых клише;
• центр надежды — Иисус Христос, Божья верность и послушание Слову;
• русский язык, обычный текст без Markdown-символов **, ### и обратных кавычек.

Длина всего BODY: 320–410 слов. Абсолютный максимум — 450 слов.
Текст должен читаться примерно за 2–3 минуты на телефоне.
Не повторяй одну мысль разными словами. Один день — одна центральная мысль.

Структура BODY:
📖 Слово на сегодня

Короткая точная цитата или аккуратный пересказ выбранного места Писания
с указанием ссылки.

🔥 Сильный уникальный заголовок

Основное размышление: 3–4 плотных абзаца. Объясни контекст, главный
духовный принцип и связь с реальной жизнью. Не повторяй вывод разными
формулировками и не превращай один день во вторую длинную проповедь.

🌿 Свидетельство Божьей славы
70–100 слов. Покажи один реальный библейский эпизод, который прямо
усиливает центральную тему дня. Это не отдельная вторая тема. Не выдавай
человеческое предположение за факт Писания.

✅ На сегодня
Дай ровно 3 коротких практических шага, пронумерованных (1), (2), (3).
Каждый шаг — максимум одно короткое предложение.

🙏 Молитва
2–3 предложения, Христоцентрично и строго по теме дня.

Верни ответ строго в формате:
REFERENCE_KEY: english_book_chapter_verse
BODY:
<готовое размышление>

REFERENCE_KEY должен быть только латиницей, цифрами и подчёркиваниями.
Он обязан обозначать весь ОСНОВНОЙ отрывок/сюжет, а не случайный один
стих внутри него. Например, для дороги в Эммаус используй
luke_24_13_35, даже если в начале цитируется только Луки 24:32.
Для одного самостоятельного стиха допустим ключ вроде joshua_6_1.
Один и тот же основной отрывок всегда должен получать один и тот же ключ.
"""

    base_input = (
        f"{topic_instruction}\n\n"
        "Недавние темы, которые нельзя повторять:\n"
        f"{recent_for_prompt}\n\n"
        "Создай сегодняшнее Слово."
    )

    last_key: str | None = None
    last_body = ""

    used_keys = set(recent_topic_keys)
    used_scopes = {daily_reference_scope(item) for item in recent_topic_keys}

    for _ in range(DAILY_GENERATION_MAX_ATTEMPTS):
        response = await openai_client.responses.create(
            model=MODEL,
            instructions=generation_instructions,
            input=base_input,
            max_output_tokens=2400,
        )
        key, body = parse_daily_generation(
            response.output_text or ""
        )
        last_key = key
        last_body = body

        if forced_reference_key:
            key = forced_reference_key

        if (
            key
            and body
            and (
                forced_reference_key
                or (
                    key not in used_keys
                    and daily_reference_scope(key) not in used_scopes
                )
            )
        ):
            last_key = key
            break

        if key and not forced_reference_key:
            used_keys.add(key)
            used_scopes.add(daily_reference_scope(key))

        base_input += (
            "\n\nПредыдущая попытка повторила уже использованный основной "
            "отрывок/главу либо нарушила формат. Выбери другое место "
            "Писания и верни точный формат."
        )

    if not last_key or not last_body:
        raise RuntimeError(
            "Не удалось сформировать ежедневное Слово"
        )

    audit_instructions = """
Ты — редактор библейского ежедневного размышления.
Проверь текст перед публикацией.

Исправь только то, что необходимо для точности и качества:
• ссылки и факты Писания должны быть корректны;
• сомнительную дословную цитату замени точным кратким пересказом без
  кавычек, сохранив ссылку;
• не допускай выдуманных современных свидетельств;
• свидетельство должно быть из Писания;
• не обещай человеку гарантированного материального успеха, исцеления или
  определённого исхода там, где Писание этого не обещает;
• сохрани сильный, живой, пастырский тон и призыв к вере и послушанию;
• сохрани структуру, 3 практических шага и короткую молитву;
• итог 320–410 слов, абсолютный максимум 450;
• «Свидетельство Божьей славы» короткое и прямо поддерживает центральную тему;
• обычный текст без Markdown-разметки.

Верни только готовый текст для Telegram, без комментариев редактора.
"""

    audit_response = await openai_client.responses.create(
        model=MODEL,
        instructions=audit_instructions,
        input=(
            f"Выбранный ключ отрывка: {last_key}\n\n"
            f"Текст:\n{last_body}"
        ),
        max_output_tokens=2400,
    )

    audited = clean_ai_text(
        audit_response.output_text or ""
    )
    if audited:
        last_body = audited

    last_body = await daily_compress_if_needed(last_body)

    return last_key, last_body


async def get_or_generate_daily_word(
    date_key: str,
) -> tuple[str, str]:
    cached = DAILY_WORD_CACHE.get(date_key)
    if cached:
        return cached

    async with DAILY_GENERATION_LOCK:
        cached = DAILY_WORD_CACHE.get(date_key)
        if cached:
            return cached

        # Один день — один утверждённый текст для всех пользователей.
        stored = await daily_load_stored_word(date_key)
        if stored:
            DAILY_WORD_CACHE[date_key] = stored
            return stored

        used = await daily_get_used_topic_keys()
        today_key = await daily_get_today_topic_key(date_key)

        # Если сегодняшняя тема уже была создана предыдущей версией кода,
        # сохраняем именно её, но уже в новом компактном формате.
        if today_key:
            key, body = await generate_daily_word(
                forced_reference_key=today_key,
                recent_topic_keys=used,
            )
            saved = await daily_store_word(date_key, key, body)
            if saved:
                result = (key, body)
                DAILY_WORD_CACHE[date_key] = result
                return result

            stored = await daily_load_stored_word(date_key)
            if stored:
                DAILY_WORD_CACHE[date_key] = stored
                return stored

            raise RuntimeError(
                "Не удалось безопасно сохранить сегодняшнее Слово"
            )

        working_used = list(used)

        for _ in range(DAILY_GENERATION_MAX_ATTEMPTS):
            key, body = await generate_daily_word(
                recent_topic_keys=working_used,
            )

            saved = await daily_store_word(date_key, key, body)
            if saved:
                await analytics_log_event(
                    DAILY_SYSTEM_USER_ID,
                    f"{daily_topic_prefix(date_key)}{key}",
                )
                result = (key, body)
                DAILY_WORD_CACHE[date_key] = result

                if len(DAILY_WORD_CACHE) > 3:
                    for old_key in sorted(DAILY_WORD_CACHE)[:-3]:
                        DAILY_WORD_CACHE.pop(old_key, None)

                return result

            # Если конфликт был по дате — другой процесс уже успел сохранить
            # сегодняшний текст. Берём его, не создавая второй вариант.
            stored = await daily_load_stored_word(date_key)
            if stored:
                DAILY_WORD_CACHE[date_key] = stored
                return stored

            # Иначе конфликт был по отрывку/заголовку — пробуем новую тему.
            if key not in working_used:
                working_used.append(key)

        raise RuntimeError(
            "Не удалось подобрать новый, ранее не использованный отрывок"
        )


def daily_post_menu(
    subscribed: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                "📖 Задать вопрос Библии",
                callback_data="ask",
            )
        ],
        [
            InlineKeyboardButton(
                "🙏 Нужна молитва",
                callback_data="prayer",
            )
        ],
        [
            InlineKeyboardButton(
                "📤 Поделиться ботом",
                callback_data="share",
            )
        ],
        [
            InlineKeyboardButton(
                "🤝 Поддержать проект",
                callback_data="donate",
            )
        ],
    ]

    if subscribed:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔕 Отключить ежедневное Слово",
                    callback_data="daily_unsubscribe",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔔 Получать Слово каждый день",
                    callback_data="daily_subscribe",
                )
            ]
        )

    return InlineKeyboardMarkup(rows)


def daily_settings_menu(
    subscribed: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                "📖 Слово на сегодня",
                callback_data="daily_today",
            )
        ],
    ]
    if subscribed:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔕 Отключить ежедневное Слово",
                    callback_data="daily_unsubscribe",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔔 Получать каждый день в 07:10",
                    callback_data="daily_subscribe",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "🏠 Главное меню",
                callback_data="menu",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


async def send_daily_word_to_chat(
    bot,
    chat_id: int,
    text: str,
    *,
    subscribed: bool,
) -> None:
    chunks = split_telegram_text(text)
    for index, chunk in enumerate(chunks):
        kwargs = {}
        if index == len(chunks) - 1:
            kwargs["reply_markup"] = daily_post_menu(subscribed)
        await bot.send_message(
            chat_id=chat_id,
            text=chunk,
            **kwargs,
        )


async def ensure_support_pin_for_chat(
    bot,
    telegram_user_id: int,
) -> None:
    if await analytics_has_event(
        telegram_user_id,
        "support_message_created",
    ):
        return

    text = (
        "🤝 Поддержать проект «Библия отвечает»\n\n"
        "Если это служение помогает вам обращаться к Божьему Слову, "
        "молиться и укрепляться в вере, вы можете добровольно поддержать "
        "его развитие.\n\n"
        "Пожертвование помогает оплачивать техническую инфраструктуру "
        "и развивать служение. Доступ к библейским ответам и молитве "
        "не зависит от пожертвования."
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🤝 Поддержать проект",
                    callback_data="donate",
                )
            ]
        ]
    )

    try:
        message = await bot.send_message(
            chat_id=telegram_user_id,
            text=text,
            reply_markup=markup,
        )
        await analytics_log_event(
            telegram_user_id,
            "support_message_created",
        )

        try:
            await bot.pin_chat_message(
                chat_id=telegram_user_id,
                message_id=message.message_id,
                disable_notification=True,
            )
            await analytics_log_event(
                telegram_user_id,
                "support_pin_success",
            )
        except (BadRequest, Forbidden):
            logger.info(
                "Не удалось закрепить сообщение поддержки для %s",
                telegram_user_id,
            )
            await analytics_log_event(
                telegram_user_id,
                "support_pin_failed",
            )

    except (BadRequest, Forbidden):
        logger.info(
            "Не удалось отправить сообщение поддержки пользователю %s",
            telegram_user_id,
        )


async def send_today_daily_to_user(
    application: Application,
    telegram_user_id: int,
    *,
    manual: bool = False,
) -> bool:
    date_key = daily_date_key()
    sent_event = daily_sent_event(date_key)

    if not manual and await analytics_has_event(
        telegram_user_id,
        sent_event,
    ):
        return False

    subscribed = await daily_is_subscribed(
        telegram_user_id
    )

    _, word = await get_or_generate_daily_word(
        date_key
    )

    await send_daily_word_to_chat(
        application.bot,
        telegram_user_id,
        word,
        subscribed=subscribed,
    )

    if not await analytics_has_event(
        telegram_user_id,
        sent_event,
    ):
        await analytics_log_event(
            telegram_user_id,
            sent_event,
        )

    await analytics_log_event(
        telegram_user_id,
        "daily_manual" if manual else "daily_auto",
    )
    return True


async def daily_broadcast(
    application: Application,
    date_key: str,
) -> None:
    subscribers = await daily_get_active_subscriber_ids()
    if not subscribers:
        return

    sent = await daily_get_sent_user_ids(date_key)
    targets = sorted(subscribers - sent)
    if not targets:
        return

    _, word = await get_or_generate_daily_word(date_key)

    logger.info(
        "Ежедневное Слово: отправка %s пользователям",
        len(targets),
    )

    for user_id in targets:
        try:
            await send_daily_word_to_chat(
                application.bot,
                user_id,
                word,
                subscribed=True,
            )
            await analytics_log_event(
                user_id,
                daily_sent_event(date_key),
            )
            await analytics_log_event(
                user_id,
                "daily_auto",
            )
            await asyncio.sleep(0.08)
        except Forbidden:
            logger.info(
                "Пользователь %s заблокировал бота",
                user_id,
            )
            await analytics_log_event(
                user_id,
                "daily_delivery_forbidden",
            )
        except (BadRequest, NetworkError, TimedOut):
            logger.exception(
                "Не удалось отправить ежедневное Слово пользователю %s",
                user_id,
            )


async def daily_scheduler_loop(
    application: Application,
) -> None:
    processed_date: str | None = None

    await asyncio.sleep(3)
    while True:
        try:
            now = datetime.now(DAILY_TIMEZONE)
            date_key = daily_date_key(now)
            due = (
                now.hour > DAILY_SEND_HOUR
                or (
                    now.hour == DAILY_SEND_HOUR
                    and now.minute >= DAILY_SEND_MINUTE
                )
            )

            if due and processed_date != date_key:
                await daily_broadcast(
                    application,
                    date_key,
                )
                processed_date = date_key

            if not due and processed_date == date_key:
                processed_date = None

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Ошибка фоновой ежедневной рассылки"
            )

        await asyncio.sleep(
            DAILY_SCHEDULER_INTERVAL_SECONDS
        )


async def daily_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    subscribed = await daily_is_subscribed(user.id)
    status = (
        "включена"
        if subscribed
        else "выключена"
    )
    await message.reply_text(
        "🌅 Слово на каждый день\n\n"
        f"Ежедневная рассылка сейчас {status}.\n"
        "При включении новое размышление приходит каждый день "
        "примерно в 07:10 по времени Германии.\n\n"
        "Каждый день выбирается новый основной отрывок Писания; уже "
        "использованные отрывки повторно не используются.",
        reply_markup=daily_settings_menu(subscribed),
    )


async def handle_daily_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.message or not user:
        return

    if action == "daily":
        subscribed = await daily_is_subscribed(user.id)
        status = "включена" if subscribed else "выключена"
        await query.message.reply_text(
            "🌅 Слово на каждый день\n\n"
            f"Ежедневная рассылка сейчас {status}.\n\n"
            "В 07:10 по времени Германии бот присылает новое глубокое "
            "размышление: место Писания, объяснение, библейское "
            "свидетельство Божьей славы, 3 шага на день и короткую молитву.\n\n"
            "Использованные основные отрывки сохраняются в постоянной истории "
            "и больше не используются повторно.",
            reply_markup=daily_settings_menu(subscribed),
        )
        return

    if action == "daily_subscribe":
        if not await daily_is_subscribed(user.id):
            await analytics_log_event(
                user.id,
                "daily_subscribe",
            )
        await query.message.reply_text(
            "🔔 Ежедневное Слово включено.\n\n"
            "Теперь каждый день примерно в 07:10 по времени Германии "
            "вы будете получать новое библейское размышление. "
            "Отключить рассылку можно в любой момент одной кнопкой."
        )
        await ensure_support_pin_for_chat(
            context.bot,
            user.id,
        )
        try:
            await send_today_daily_to_user(
                context.application,
                user.id,
                manual=True,
            )
        except Exception:
            logger.exception(
                "Не удалось отправить Слово сразу после подписки"
            )
        return

    if action == "daily_unsubscribe":
        if await daily_is_subscribed(user.id):
            await analytics_log_event(
                user.id,
                "daily_unsubscribe",
            )
        await query.message.reply_text(
            "🔕 Ежедневная рассылка отключена.\n\n"
            "Вы по-прежнему можете в любой момент открыть «Слово на "
            "каждый день» в меню и прочитать Слово на сегодня.",
            reply_markup=daily_settings_menu(False),
        )
        return

    if action == "daily_today":
        wait = await query.message.reply_text(
            "📖 Готовлю Слово на сегодня..."
        )
        try:
            await send_today_daily_to_user(
                context.application,
                user.id,
                manual=True,
            )
            try:
                await wait.delete()
            except Exception:
                pass
        except Exception:
            logger.exception(
                "Не удалось сформировать Слово на сегодня"
            )
            try:
                await wait.edit_text(
                    "⚠️ Сейчас не удалось подготовить Слово на сегодня. "
                    "Попробуйте ещё раз через несколько секунд."
                )
            except Exception:
                pass
        return

async def analytics_exact_count(
    table: str,
    filters_map: dict[str, str] | None = None,
) -> int:
    if not supabase_is_configured():
        return 0

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{table}"
    )

    params = {
        "select": "*",
        "limit": "1",
    }

    if filters_map:
        params.update(
            filters_map
        )

    headers = supabase_headers()
    headers["Prefer"] = "count=exact"
    headers["Range"] = "0-0"

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(
                url,
                headers=headers,
                params=params,
            )
            response.raise_for_status()

        content_range = response.headers.get(
            "content-range",
            "",
        )

        if "/" not in content_range:
            return 0

        total = content_range.rsplit(
            "/",
            1,
        )[1]

        if total == "*":
            return 0

        return int(total)

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
        ValueError,
    ):
        logger.exception(
            "Не удалось получить count аналитики"
        )
        return 0


async def verify_analytics_connection() -> bool:
    if not supabase_is_configured():
        return False

    try:
        await analytics_exact_count(
            ANALYTICS_USERS_TABLE
        )
        await analytics_exact_count(
            ANALYTICS_EVENTS_TABLE
        )

        logger.info(
            "Analytics подключена: %s, %s",
            ANALYTICS_USERS_TABLE,
            ANALYTICS_EVENTS_TABLE,
        )
        return True

    except Exception:
        logger.exception(
            "Analytics таблицы пока недоступны"
        )
        return False


def admin_is_configured() -> bool:
    return TELEGRAM_ADMIN_ID is not None


def user_is_admin(
    update: Update,
) -> bool:
    user = update.effective_user

    return bool(
        user
        and TELEGRAM_ADMIN_ID is not None
        and user.id == TELEGRAM_ADMIN_ID
    )


async def require_admin(
    update: Update,
) -> bool:
    if user_is_admin(update):
        return True

    message = update.effective_message

    if not message:
        return False

    if not admin_is_configured():
        user = update.effective_user
        user_id = (
            user.id
            if user
            else "не определён"
        )

        await message.reply_text(
            "🔐 Статистика ещё не привязана "
            "к владельцу бота.\n\n"
            f"Ваш Telegram ID: {user_id}\n\n"
            "Добавьте этот ID в Render "
            "как переменную TELEGRAM_ADMIN_ID."
        )
        return False

    await message.reply_text(
        "🔐 Эта команда доступна "
        "только владельцу бота."
    )
    return False


async def myid_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    await message.reply_text(
        "🆔 Ваш Telegram ID:\n"
        f"{user.id}"
    )


async def links_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await require_admin(update):
        return

    message = update.effective_message

    if not message:
        return

    me = await context.bot.get_me()

    if not me.username:
        await message.reply_text(
            "Не удалось определить username бота."
        )
        return

    base = f"https://t.me/{me.username}"

    text = (
        "🔗 Ссылки для продвижения\n\n"
        f"Instagram профиль:\n"
        f"{base}?start=instagram\n\n"
        f"Instagram Stories:\n"
        f"{base}?start=instagram_story\n\n"
        f"Сайт Bless United:\n"
        f"{base}?start=blessunited\n\n"
        f"Facebook:\n"
        f"{base}?start=facebook\n\n"
        f"TikTok:\n"
        f"{base}?start=tiktok\n\n"
        f"YouTube Shorts:\n"
        f"{base}?start=youtube_shorts\n\n"
        f"Церкви и христианские группы:\n"
        f"{base}?start=church\n\n"
        f"QR / печатные материалы:\n"
        f"{base}?start=qr_print\n\n"
        f"Рекомендация из Telegram:\n"
        f"{base}?start=shared\n\n"
        f"Реклама №1:\n"
        f"{base}?start=ad_campaign_1\n\n"
        "Каждая ссылка ведёт в того же бота, "
        "но источник сохраняется отдельно "
        "для статистики."
    )

    await message.reply_text(
        text
    )


async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await require_admin(update):
        return

    message = update.effective_message

    if not message:
        return

    now = datetime.now(
        timezone.utc
    )
    last_24h = (
        now - timedelta(hours=24)
    ).isoformat()
    last_7d = (
        now - timedelta(days=7)
    ).isoformat()
    last_30d = (
        now - timedelta(days=30)
    ).isoformat()

    total_users = await analytics_exact_count(
        ANALYTICS_USERS_TABLE
    )
    new_24h = await analytics_exact_count(
        ANALYTICS_USERS_TABLE,
        {
            "first_seen_at": (
                f"gte.{last_24h}"
            )
        },
    )
    new_7d = await analytics_exact_count(
        ANALYTICS_USERS_TABLE,
        {
            "first_seen_at": (
                f"gte.{last_7d}"
            )
        },
    )
    new_30d = await analytics_exact_count(
        ANALYTICS_USERS_TABLE,
        {
            "first_seen_at": (
                f"gte.{last_30d}"
            )
        },
    )
    active_7d = await analytics_exact_count(
        ANALYTICS_USERS_TABLE,
        {
            "last_seen_at": (
                f"gte.{last_7d}"
            )
        },
    )

    daily_subscribers = len(
        await daily_get_active_subscriber_ids()
    )
    daily_sent_today = len(
        await daily_get_sent_user_ids(
            daily_date_key()
        )
    )

    source_names = [
        ("Instagram", "instagram"),
        ("Instagram Stories", "instagram_story"),
        ("Bless United", "blessunited"),
        ("Facebook", "facebook"),
        ("TikTok", "tiktok"),
        ("YouTube Shorts", "youtube_shorts"),
        ("Церкви / группы", "church"),
        ("QR / печать", "qr_print"),
        ("Рекомендации", "shared"),
        ("Реклама №1", "ad_campaign_1"),
        ("Прямой запуск", "direct"),
    ]

    source_lines = []

    for label, source in source_names:
        count = await analytics_exact_count(
            ANALYTICS_USERS_TABLE,
            {
                "source": f"eq.{source}"
            },
        )

        source_lines.append(
            f"• {label}: {count}"
        )

    event_names = [
        ("Библейские вопросы", "ai_ask"),
        ("Молитва по нужде", "ai_prayer"),
        ("Исцеление", "ai_healing"),
        ("Работа и финансы", "ai_finances"),
        ("Благословение", "ai_blessing"),
        ("Стих из Библии", "menu_verse"),
        ("Аудиоответы на голосовые", "voice_reply_audio"),
        ("Открыли «Поделиться ботом»", "share_open"),
    ]

    usage_lines = []

    for label, event_name in event_names:
        count = await analytics_exact_count(
            ANALYTICS_EVENTS_TABLE,
            {
                "event_name": (
                    f"eq.{event_name}"
                ),
                "created_at": (
                    f"gte.{last_7d}"
                ),
            },
        )

        usage_lines.append(
            f"• {label}: {count}"
        )

    donation_lines = []

    for label, event_name in [
        ("UAH", "donation_currency_uah"),
        ("EUR", "donation_currency_eur"),
        ("USD", "donation_currency_usd"),
        ("USDT", "donation_currency_usdt"),
    ]:
        count = await analytics_exact_count(
            ANALYTICS_EVENTS_TABLE,
            {
                "event_name": (
                    f"eq.{event_name}"
                ),
                "created_at": (
                    f"gte.{last_7d}"
                ),
            },
        )

        donation_lines.append(
            f"• {label}: {count}"
        )

    text = (
        "📊 Статистика «Библия отвечает»\n\n"
        "👥 Пользователи\n"
        f"• Всего: {total_users}\n"
        f"• Новые за 24 часа: {new_24h}\n"
        f"• Новые за 7 дней: {new_7d}\n"
        f"• Новые за 30 дней: {new_30d}\n"
        f"• Активные за 7 дней: {active_7d}\n"
        f"• Подписаны на ежедневное Слово: {daily_subscribers}\n"
        f"• Получили Слово сегодня: {daily_sent_today}\n\n"
        "📍 Источники\n"
        + "\n".join(source_lines)
        + "\n\n"
        "📖 Использование за 7 дней\n"
        + "\n".join(usage_lines)
        + "\n\n"
        "🤝 Интерес к поддержке за 7 дней\n"
        + "\n".join(donation_lines)
        + "\n\n"
        "Примечание: раздел поддержки показывает "
        "нажатия на способы пожертвования, "
        "а не подтверждённые банковские платежи."
    )

    await message.reply_text(
        text
    )


def normalize_verse_state(
    raw_queue,
    raw_last_index,
) -> tuple[list[int], int | None]:
    queue: list[int] = []
    seen: set[int] = set()

    if isinstance(raw_queue, list):
        for value in raw_queue:
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value < len(VERSES)
                and value not in seen
            ):
                queue.append(value)
                seen.add(value)

    last_index = (
        raw_last_index
        if (
            isinstance(raw_last_index, int)
            and not isinstance(raw_last_index, bool)
            and 0 <= raw_last_index < len(VERSES)
        )
        else None
    )

    return queue, last_index


async def load_verse_state(
    telegram_user_id: int,
) -> tuple[list[int], int | None] | None:
    if not supabase_is_configured():
        return None

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{SUPABASE_TABLE}"
    )

    params = {
        "telegram_user_id": (
            f"eq.{telegram_user_id}"
        ),
        "select": (
            "verse_queue,last_verse_index"
        ),
        "limit": "1",
    }

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(
                url,
                headers=supabase_headers(),
                params=params,
            )
            response.raise_for_status()

        rows = response.json()

        if not rows:
            return [], None

        row = rows[0]

        return normalize_verse_state(
            row.get("verse_queue"),
            row.get("last_verse_index"),
        )

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
        ValueError,
    ):
        logger.exception(
            "Не удалось прочитать состояние "
            "стихов из Supabase"
        )
        return None


async def save_verse_state(
    telegram_user_id: int,
    queue: list[int],
    last_index: int | None,
) -> bool:
    if not supabase_is_configured():
        return False

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{SUPABASE_TABLE}"
    )

    params = {
        "on_conflict": "telegram_user_id",
    }

    headers = supabase_headers()
    headers["Prefer"] = (
        "resolution=merge-duplicates,"
        "return=minimal"
    )

    payload = {
        "telegram_user_id": telegram_user_id,
        "verse_queue": queue,
        "last_verse_index": last_index,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.post(
                url,
                headers=headers,
                params=params,
                json=payload,
            )
            response.raise_for_status()

        return True

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
    ):
        logger.exception(
            "Не удалось сохранить состояние "
            "стихов в Supabase"
        )
        return False


async def verify_supabase_connection() -> bool:
    if not supabase_is_configured():
        logger.warning(
            "Supabase не настроен полностью. "
            "Бот продолжит работу "
            "с памятью процесса."
        )
        return False

    url = (
        f"{SUPABASE_URL}/rest/v1/"
        f"{SUPABASE_TABLE}"
    )

    params = {
        "select": "telegram_user_id",
        "limit": "1",
    }

    try:
        async with httpx.AsyncClient(
            timeout=SUPABASE_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(
                url,
                headers=supabase_headers(),
                params=params,
            )
            response.raise_for_status()

        logger.info(
            "Supabase подключён: таблица %s доступна",
            SUPABASE_TABLE,
        )
        return True

    except (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
    ):
        logger.exception(
            "Supabase временно недоступен. "
            "Бот продолжит работу "
            "с резервной памятью процесса."
        )
        return False


def choose_next_verse(
    queue: list[int],
    last_index: int | None,
) -> tuple[dict, list[int], int]:
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

    verse_index = queue.pop()

    return (
        VERSES[verse_index],
        queue,
        verse_index,
    )


async def random_verse(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> dict:
    user = update.effective_user

    if user is None:
        queue, last_index = normalize_verse_state(
            context.user_data.get(
                "verse_queue",
                [],
            ),
            context.user_data.get(
                "last_verse_index"
            ),
        )

        verse, queue, last_index = (
            choose_next_verse(
                queue,
                last_index,
            )
        )

        context.user_data[
            "verse_queue"
        ] = queue
        context.user_data[
            "last_verse_index"
        ] = last_index

        return verse

    telegram_user_id = user.id

    if not context.user_data.get(
        "verse_state_loaded",
        False,
    ):
        stored_state = await load_verse_state(
            telegram_user_id
        )

        if stored_state is not None:
            queue, last_index = stored_state
            context.user_data[
                "verse_queue"
            ] = queue
            context.user_data[
                "last_verse_index"
            ] = last_index
            context.user_data[
                "verse_state_loaded"
            ] = True

    queue, last_index = normalize_verse_state(
        context.user_data.get(
            "verse_queue",
            [],
        ),
        context.user_data.get(
            "last_verse_index"
        ),
    )

    verse, queue, last_index = (
        choose_next_verse(
            queue,
            last_index,
        )
    )

    context.user_data[
        "verse_queue"
    ] = queue
    context.user_data[
        "last_verse_index"
    ] = last_index

    saved = await save_verse_state(
        telegram_user_id,
        queue,
        last_index,
    )

    if saved:
        context.user_data[
            "verse_state_loaded"
        ] = True

    return verse


def split_telegram_text(
    text: str,
) -> list[str]:
    hard_limit = 4096
    preferred_limit = 3900
    min_tail = 450
    search_from = 1800

    remaining = text.strip()
    chunks: list[str] = []

    while remaining:
        if len(remaining) <= hard_limit:
            chunks.append(remaining)
            break

        max_split = min(
            preferred_limit,
            len(remaining) - min_tail,
        )

        split_at = -1

        separators = (
            "\n\n",
            "\n",
            ". ",
            "! ",
            "? ",
            "; ",
            ": ",
            ", ",
            " ",
        )

        for separator in separators:
            position = remaining.rfind(
                separator,
                search_from,
                max_split,
            )

            if position == -1:
                continue

            if separator in (
                ". ",
                "! ",
                "? ",
                "; ",
                ": ",
                ", ",
            ):
                split_at = position + 1
            else:
                split_at = position

            break

        if split_at < search_from:
            split_at = max_split

            while (
                split_at > search_from
                and not remaining[
                    split_at - 1
                ].isspace()
            ):
                split_at -= 1

            if split_at <= search_from:
                split_at = max_split

        chunk = remaining[
            :split_at
        ].strip()

        remaining = remaining[
            split_at:
        ].lstrip()

        if chunk:
            chunks.append(chunk)

    return chunks


async def send_long_message(
    update: Update,
    text: str,
) -> None:
    message = update.effective_message

    if not message:
        return

    chunks = split_telegram_text(
        text
    )

    for index, chunk in enumerate(
        chunks
    ):
        is_last = (
            index == len(chunks) - 1
        )

        if is_last:
            await message.reply_text(
                chunk,
                reply_markup=main_menu(),
            )
        else:
            await message.reply_text(
                chunk
            )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    context.user_data.pop(
        "mode",
        None,
    )
    context.user_data.pop(
        "awaiting_donation_amount",
        None,
    )

    user = update.effective_user

    if user:
        source = normalize_start_source(
            context
        )

        context.application.create_task(
            analytics_track_start(
                user.id,
                source,
            )
        )
        context.application.create_task(
            analytics_log_event(
                user.id,
                "start",
            )
        )

    text = (
        "📖 <b>Библия отвечает</b>\n\n"
        "Расскажите текстом или голосовым сообщением, "
        "что происходит в вашей жизни, "
        "что вас тревожит или в чём вы нуждаетесь.\n\n"
        "Здесь можно обратиться к Божьему Слову, "
        "получить библейское ободрение "
        "и помощь в молитве.\n\n"
        "Этот бот не заменяет Библию, личную молитву "
        "и живое общение с церковью — "
        "его задача помочь направить сердце ко Христу.\n\n"
        "Выберите раздел:"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu(),
        parse_mode="HTML",
    )

    if user:
        await ensure_support_pin_for_chat(
            context.bot,
            user.id,
        )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    if not query:
        return

    await query.answer()

    action = query.data

    if not action:
        return

    user = update.effective_user

    if user:
        context.application.create_task(
            analytics_activity(
                user.id,
                analytics_event_for_action(
                    action
                ),
            )
        )

    if action in {
        "daily",
        "daily_subscribe",
        "daily_unsubscribe",
        "daily_today",
    }:
        await handle_daily_action(
            update,
            context,
            action,
        )
        return

    if not action.startswith("don_custom_"):
        context.user_data.pop(
            "awaiting_donation_amount",
            None,
        )

    reply_markup = main_menu()

    if action == "ask":
        context.user_data["mode"] = "ask"
        text = (
            "📖 <b>Задайте вопрос</b>\n\n"
            "Напишите или отправьте голосовое сообщение: "
            "что произошло, "
            "что вас тревожит "
            "или какой библейский ответ "
            "вы хотите найти."
        )

    elif action == "prayer":
        context.user_data["mode"] = "prayer"
        text = (
            "🙏 <b>Молитва по нужде</b>\n\n"
            "Опишите вашу нужду текстом или голосом: "
            "что происходит, "
            "за кого молимся, "
            "чего вы особенно просите у Бога.\n\n"
            "Бот подберёт места Писания, "
            "поможет увидеть основание веры "
            "и составит персональную молитву."
        )

    elif action == "healing":
        context.user_data["mode"] = "healing"
        text = (
            "❤️‍🩹 <b>Молитва об исцелении</b>\n\n"
            "Напишите или расскажите голосом, за кого молимся "
            "и что известно о состоянии человека.\n\n"
            "Можно указать диагноз, симптомы, "
            "операцию, лечение, страхи семьи "
            "или другую важную информацию.\n\n"
            "Ответ будет основан на Писании, "
            "молитве веры и надежде во Христе."
        )

    elif action == "finances":
        context.user_data["mode"] = "finances"
        text = (
            "💼 <b>Работа и финансы</b>\n\n"
            "Опишите ситуацию текстом или голосом: "
            "работа, бизнес, долги, "
            "поиск клиентов, доход, "
            "важное решение или финансовая нужда.\n\n"
            "Бот соединит молитву "
            "с библейскими принципами "
            "мудрости, труда, обеспечения "
            "и ответственности."
        )

    elif action == "blessing":
        context.user_data["mode"] = "blessing"
        text = (
            "✨ <b>Молитва благословения</b>\n\n"
            "Напишите или расскажите голосом, кого или что "
            "вы хотите благословить в молитве: "
            "себя, детей, семью, дом, работу, "
            "служение, дорогу или важное начинание."
        )

    elif action == "verse":
        context.user_data.pop(
            "mode",
            None,
        )

        verse = await random_verse(
            update,
            context,
        )

        text = (
            "📖 <b>Стих из Библии</b>\n\n"
            f"{verse['text']}\n\n"
            f"<b>{verse['reference']}</b>\n\n"
            "💬 <b>Коротко о смысле</b>\n"
            f"{verse['thought']}"
        )

    elif action == "share":
        context.user_data.pop(
            "mode",
            None,
        )

        me = await context.bot.get_me()

        if not me.username:
            text = (
                "⚠️ Сейчас не удалось подготовить ссылку для отправки. "
                "Попробуйте ещё раз позже."
            )
            reply_markup = main_menu()
        else:
            bot_link = (
                f"https://t.me/{me.username}?start=shared"
            )
            share_text = (
                "Я пользуюсь бесплатным Telegram-проектом "
                "«Библия отвечает»: здесь можно задать вопрос по Писанию, "
                "получить помощь в молитве и читать ежедневное Слово. "
                "Возможно, он будет полезен и тебе."
            )
            telegram_share_url = (
                "https://t.me/share/url?url="
                + quote(bot_link, safe="")
                + "&text="
                + quote(share_text, safe="")
            )

            text = (
                "📤 <b>Поделиться «Библия отвечает»</b>\n\n"
                "Если бот оказался полезен, вы можете отправить его "
                "человеку, которому сейчас нужна молитва, поддержка "
                "или помощь в поиске библейского ответа.\n\n"
                "Проект остаётся бесплатным. Поделиться ссылкой можно "
                "без регистрации и без каких-либо обязательств."
            )

            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📤 Отправить в Telegram",
                            url=telegram_share_url,
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "📋 Скопировать ссылку",
                            copy_text=CopyTextButton(
                                text=bot_link,
                            ),
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
                            "🏠 Главное меню",
                            callback_data="menu",
                        )
                    ],
                ]
            )

    elif action == "donate":
        context.user_data.pop(
            "mode",
            None,
        )

        text = (
            "🤝 <b>Поддержать служение «Библия отвечает»</b>\n\n"
            "Если вы свободно желаете участвовать "
            "в распространении Божьего Слова "
            "и развитии этого служения, "
            "выберите удобный способ поддержки.\n\n"
            "Поддержка полностью добровольна. "
            "Молитва, библейский ответ и доступ к боту "
            "не зависят от пожертвования.\n\n"
            "Выберите валюту или криптовалюту:"
        )
        reply_markup = donation_main_menu()

    elif action in {
        "donate_uah",
        "donate_eur",
        "donate_usd",
        "donate_usdt",
    }:
        context.user_data.pop(
            "mode",
            None,
        )

        currency = action.replace(
            "donate_",
            "",
        ).upper()

        minimum = DONATION_MINIMUMS[currency]

        text = (
            f"{currency_label(currency)}\n\n"
            "Выберите удобную сумму "
            "или нажмите «Другая сумма».\n\n"
            f"Минимум: "
            f"{format_donation_amount(minimum, currency)}.\n"
            "Верхний предел бот не устанавливает; "
            "фактические банковские лимиты могут зависеть "
            "от вашего банка или платёжного сервиса."
        )
        reply_markup = donation_amount_menu(
            currency
        )

    elif action.startswith("don_amt_"):
        context.user_data.pop(
            "mode",
            None,
        )

        parts = action.split("_")

        if len(parts) != 4:
            text = "Не удалось определить сумму."
        else:
            currency = parts[2].upper()
            amount = Decimal(parts[3])

            text = donation_details_text(
                currency,
                amount,
            )
            reply_markup = donation_details_menu(
                currency,
                amount,
            )

    elif action.startswith("don_details_"):
        context.user_data.pop(
            "mode",
            None,
        )

        currency = action.replace(
            "don_details_",
            "",
        ).upper()

        text = donation_details_text(
            currency
        )
        reply_markup = donation_details_menu(
            currency
        )

    elif action.startswith("don_custom_"):
        context.user_data.pop(
            "mode",
            None,
        )

        currency = action.replace(
            "don_custom_",
            "",
        ).upper()

        context.user_data[
            "awaiting_donation_amount"
        ] = currency

        minimum = DONATION_MINIMUMS[currency]

        text = (
            f"✏️ <b>Другая сумма — "
            f"{currency_label(currency)}</b>\n\n"
            "Напишите сумму одним сообщением.\n\n"
            "Например: <code>750</code> "
            "или <code>2500</code>.\n\n"
            f"Минимум: "
            f"{format_donation_amount(minimum, currency)}."
        )

        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data=(
                            f"donate_{currency.lower()}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 Главное меню",
                        callback_data="menu",
                    )
                ],
            ]
        )

    elif action == "about":
        context.user_data.pop(
            "mode",
            None,
        )

        text = (
            "ℹ️ <b>О проекте</b>\n\n"
            "«Библия отвечает» — "
            "христианский AI-помощник, "
            "созданный для того, чтобы помогать людям "
            "обращаться к Священному Писанию, "
            "молиться, находить надежду во Христе "
            "и применять Божье Слово в жизни.\n\n"
            "Проект не заменяет Библию, "
            "личные отношения с Богом, "
            "поместную церковь, пастырское служение "
            "или профессиональную медицинскую помощь.\n\n"
            "Цель проекта — направлять человека "
            "не к технологии, а ко Христу.\n\n"
            "Аудиоответы могут использовать "
            "автоматическую синтезированную озвучку."
        )

    elif action == "menu":
        context.user_data.pop(
            "mode",
            None,
        )

        text = (
            "📖 <b>Библия отвечает</b>\n\n"
            "Выберите нужный раздел:"
        )

    else:
        context.user_data.pop(
            "mode",
            None,
        )
        text = "Выберите нужный раздел:"

    if query.message:
        await query.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )


async def transcribe_voice_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    message = update.effective_message

    if not message or not message.voice:
        return ""

    voice = message.voice

    if (
        voice.duration
        and voice.duration > MAX_VOICE_DURATION_SECONDS
    ):
        raise ValueError(
            "Голосовое сообщение слишком длинное. "
            "Пожалуйста, отправьте его частями "
            "до 10 минут каждая."
        )

    if (
        voice.file_size
        and voice.file_size > MAX_VOICE_FILE_BYTES
    ):
        raise ValueError(
            "Голосовой файл слишком большой. "
            "Пожалуйста, отправьте сообщение короче."
        )

    telegram_file = await context.bot.get_file(
        voice.file_id
    )
    audio = await telegram_file.download_as_bytearray()

    if not audio:
        raise ValueError(
            "Не удалось получить голосовое сообщение."
        )

    transcription = await openai_client.audio.transcriptions.create(
        model=VOICE_TRANSCRIPTION_MODEL,
        file=(
            "telegram_voice.ogg",
            bytes(audio),
            "audio/ogg",
        ),
        prompt=(
            "Точно расшифруй голосовое сообщение. "
            "Сохраняй имена людей, названия мест, "
            "библейские имена, книги Библии, "
            "медицинские термины и денежные суммы. "
            "Не добавляй ничего от себя. "
            "Сообщение может быть на русском, "
            "украинском, немецком или другом языке."
        ),
    )

    text = getattr(
        transcription,
        "text",
        "",
    )

    if not isinstance(text, str):
        return ""

    return text.strip()


def prepare_tts_text(text: str) -> str:
    """Готовит письменный ответ к естественной озвучке."""
    cleaned = clean_ai_text(text)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(
        r"[📖📚🔥✅🙏🕊🗣❤️❤‍🩹✝️🛡🩺💼✨🌿🤝🌅📍👥📊🎙🎧•]",
        "",
        cleaned,
    )
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def split_tts_text(
    text: str,
    max_chars: int = VOICE_TTS_MAX_CHARS,
) -> list[str]:
    """Делит длинный ответ на безопасные части для TTS API."""
    remaining = prepare_tts_text(text)
    chunks: list[str] = []

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        search_start = max(0, int(max_chars * 0.55))
        candidate = remaining[:max_chars]
        split_at = -1

        for delimiter in ("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "):
            pos = candidate.rfind(delimiter, search_start)
            if pos > split_at:
                split_at = pos + len(delimiter)

        if split_at <= 0:
            split_at = max_chars

        chunk = remaining[:split_at].strip()
        remaining = remaining[split_at:].strip()

        if chunk:
            chunks.append(chunk)

    return chunks


async def create_tts_wav(text: str) -> bytes:
    """Создаёт WAV-озвучку одной части ответа через OpenAI TTS."""
    payload = {
        "model": VOICE_TTS_MODEL,
        "voice": VOICE_TTS_VOICE,
        "input": text,
        "instructions": (
            "Говори на языке текста глубоким естественным мужским баритоном. "
            "Голос взрослый, зрелый, спокойный, мудрый и очень приятный, "
            "с близкой, тёплой подачей, будто человек говорит рядом, а не "
            "читает дикторский текст. Держи низкий устойчивый регистр без "
            "искусственного утяжеления голоса. Дикция должна быть образцово "
            "чёткой: согласные, окончания, имена, числа, названия книг Библии, "
            "главы и стихи произноси разборчиво и естественно. Не говори "
            "роботизированно, монотонно, певуче или театрально. Не делай "
            "одинаковые паузы после каждой фразы и не растягивай гласные. "
            "Интонация живая, сдержанная и пастырская: спокойная уверенность, "
            "сочувствие и внутренняя глубина без пафоса. Темп умеренный, "
            "примерно как у хорошего взрослого рассказчика; важные духовные "
            "фразы можно слегка замедлять, но общая речь должна оставаться "
            "естественной. Если текст русский — используй нейтральное чистое "
            "русское произношение без заметного акцента. Если текст на другом "
            "языке — произноси его естественно для этого языка. Молитву и "
            "Писание читай особенно спокойно, благоговейно и ясно."
        ),
        "response_format": "wav",
        "speed": VOICE_TTS_SPEED,
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=VOICE_TTS_TIMEOUT_SECONDS,
    ) as client:
        response = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.content


def concatenate_tts_wavs(chunks: list[bytes]) -> bytes:
    """Склеивает WAV-части, вставляя короткую естественную паузу."""
    if not chunks:
        raise ValueError("Пустой список аудиофрагментов")

    output = io.BytesIO()
    expected: tuple[int, int, int, str] | None = None

    with wave.open(output, "wb") as writer:
        for index, chunk in enumerate(chunks):
            with wave.open(io.BytesIO(chunk), "rb") as reader:
                params = (
                    reader.getnchannels(),
                    reader.getsampwidth(),
                    reader.getframerate(),
                    reader.getcomptype(),
                )

                if expected is None:
                    expected = params
                    writer.setnchannels(params[0])
                    writer.setsampwidth(params[1])
                    writer.setframerate(params[2])
                    writer.setcomptype(params[3], "not compressed")
                elif params != expected:
                    raise ValueError(
                        "Формат TTS-фрагментов различается"
                    )

                writer.writeframes(reader.readframes(reader.getnframes()))

                if index < len(chunks) - 1:
                    pause_frames = int(params[2] * 0.18)
                    writer.writeframes(
                        b"\x00"
                        * pause_frames
                        * params[0]
                        * params[1]
                    )

    return output.getvalue()


def ensure_original_prayer_music() -> str:
    """Создаёт мягкую оригинальную молитвенную подложку: pad + редкое piano."""
    if (
        os.path.exists(PRAYER_MUSIC_PATH)
        and os.path.getsize(PRAYER_MUSIC_PATH) > 1000
    ):
        return PRAYER_MUSIC_PATH

    sample_rate = 16000
    chord_seconds = 12.0

    # Тёплая спокойная гармония без яркого ритма.
    chords = [
        (65.41, 130.81, 164.81, 196.00, 246.94, 293.66),
        (55.00, 110.00, 130.81, 164.81, 196.00, 246.94),
        (43.65, 87.31, 130.81, 164.81, 220.00, 261.63),
        (49.00, 98.00, 146.83, 196.00, 220.00, 293.66),
    ]

    piano_sets = [
        (261.63, 329.63, 392.00, 493.88),
        (220.00, 261.63, 329.63, 493.88),
        (261.63, 329.63, 440.00, 523.25),
        (293.66, 392.00, 440.00, 587.33),
    ]
    piano_offsets = (1.4, 4.3, 7.4, 10.1)

    total_seconds = chord_seconds * len(chords)
    total_samples = int(sample_rate * total_seconds)
    mix = [0.0] * total_samples

    # Мягкий sustained-pad с лёгкой детонацией, чтобы звук не был синтетически плоским.
    for chord_index, chord in enumerate(chords):
        start_sample = int(chord_index * chord_seconds * sample_rate)
        end_sample = int((chord_index + 1) * chord_seconds * sample_rate)

        for sample_index in range(start_sample, end_sample):
            t = sample_index / sample_rate
            local_t = t - chord_index * chord_seconds
            fade = min(
                1.0,
                local_t / 2.2,
                (chord_seconds - local_t) / 2.2,
            )
            fade = max(0.0, fade)
            breathe = 0.93 + 0.07 * math.sin(
                2.0 * math.pi * 0.032 * t
                + chord_index * 0.7
            )

            pad = 0.0
            for note_index, frequency in enumerate(chord):
                phase = note_index * 0.58
                pad += 0.26 * math.sin(
                    2.0 * math.pi * frequency * t + phase
                )
                pad += 0.10 * math.sin(
                    2.0 * math.pi * (frequency * 1.0032) * t
                    + phase
                    + 0.3
                )
                if frequency >= 100.0:
                    pad += 0.055 * math.sin(
                        2.0 * math.pi * (frequency * 2.0) * t
                        + phase
                        + 0.15
                    )
                    pad += 0.018 * math.sin(
                        2.0 * math.pi * (frequency * 3.0) * t
                        + phase
                        + 0.35
                    )

            pad /= len(chord)

            # Едва заметный воздушный слой: добавляет глубину без "колокольчиков".
            air = (
                0.018 * math.sin(2.0 * math.pi * 659.25 * t + 0.4)
                + 0.012 * math.sin(2.0 * math.pi * 783.99 * t + 1.1)
            )

            mix[sample_index] += (
                0.62 * pad * fade * breathe
                + air * fade * breathe
            )

    # Редкие мягкие фортепианные ноты с коротким естественным "пространством".
    for chord_index, notes in enumerate(piano_sets):
        chord_start = chord_index * chord_seconds

        for offset, frequency in zip(piano_offsets, notes):
            onset = chord_start + offset
            start_sample = int(onset * sample_rate)
            note_samples = min(
                int(5.0 * sample_rate),
                total_samples - start_sample,
            )

            if note_samples <= 0:
                continue

            note = [0.0] * note_samples

            for i in range(note_samples):
                dt = i / sample_rate
                envelope = (
                    math.exp(-0.82 * dt)
                    * (1.0 - math.exp(-20.0 * dt))
                )

                value = (
                    1.00 * math.sin(2.0 * math.pi * frequency * dt)
                    + 0.50 * math.sin(
                        2.0 * math.pi * frequency * 2.0 * dt + 0.18
                    )
                    + 0.25 * math.sin(
                        2.0 * math.pi * frequency * 3.0 * dt + 0.31
                    )
                    + 0.13 * math.sin(
                        2.0 * math.pi * frequency * 4.0 * dt + 0.47
                    )
                    + 0.07 * math.sin(
                        2.0 * math.pi * frequency * 5.0 * dt + 0.66
                    )
                    + 0.10 * math.sin(
                        2.0 * math.pi * frequency * 0.997 * dt + 0.10
                    )
                )
                note[i] = 0.20 * envelope * value

            for i, value in enumerate(note):
                mix[start_sample + i] += value

            # Несколько тихих отражений создают мягкий реверберационный хвост.
            for delay, decay in (
                (0.10, 0.28),
                (0.22, 0.17),
                (0.39, 0.10),
                (0.67, 0.05),
            ):
                delayed_start = int((onset + delay) * sample_rate)
                available = total_samples - delayed_start
                count = min(note_samples, max(0, available))

                for i in range(count):
                    mix[delayed_start + i] += decay * note[i]

    samples = array("h")

    for i, value in enumerate(mix):
        t = i / sample_rate
        fade_in = min(1.0, t / 2.0)
        fade_out = min(
            1.0,
            (total_seconds - t) / 2.0,
        )
        value *= max(0.0, fade_in * fade_out)

        # Уровень подобран так, чтобы музыка была слышима,
        # но оставалась ниже голоса после финального микширования.
        value *= 0.68
        value = math.tanh(value * 1.03) / 1.03
        pcm = int(32767 * value)
        samples.append(max(-32768, min(32767, pcm)))

    temp_path = (
        PRAYER_MUSIC_PATH
        + f".{os.getpid()}.{random.randint(1000, 9999)}.tmp"
    )

    try:
        with wave.open(temp_path, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(samples.tobytes())
        os.replace(temp_path, PRAYER_MUSIC_PATH)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    return PRAYER_MUSIC_PATH

def get_ffmpeg_executable() -> str:
    """Берёт FFmpeg из imageio-ffmpeg, с системным FFmpeg как fallback."""
    try:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()
        if executable:
            return executable
    except Exception:
        logger.exception("Не удалось получить FFmpeg из imageio-ffmpeg")

    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("FFmpeg недоступен")
    return executable


async def build_voice_reply_ogg(answer: str) -> bytes:
    """Создаёт голосовой ответ с оригинальной тихой музыкальной подложкой."""
    parts = split_tts_text(answer)
    if not parts:
        raise ValueError("Нет текста для озвучивания")

    wav_parts: list[bytes] = []
    for part in parts:
        wav_parts.append(
            await create_tts_wav(part)
        )

    voice_wav = concatenate_tts_wavs(wav_parts)
    music_path = await asyncio.to_thread(
        ensure_original_prayer_music
    )
    ffmpeg = get_ffmpeg_executable()

    with tempfile.TemporaryDirectory(
        prefix="bibliya_audio_",
    ) as temp_dir:
        voice_path = os.path.join(temp_dir, "voice.wav")
        output_path = os.path.join(temp_dir, VOICE_REPLY_FILENAME)

        with open(voice_path, "wb") as file:
            file.write(voice_wav)

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            voice_path,
            "-stream_loop",
            "-1",
            "-i",
            music_path,
            "-filter_complex",
            (
                "[1:a]volume=0.45,highpass=f=55,lowpass=f=3600[music];"
                "[0:a][music]amix=inputs=2:duration=first:"
                "dropout_transition=2:normalize=0,alimiter=limit=0.95[mix]"
            ),
            "-map",
            "[mix]",
            "-c:a",
            "libopus",
            "-b:a",
            "64k",
            "-vbr",
            "on",
            "-application",
            "audio",
            "-ac",
            "1",
            "-ar",
            "48000",
            output_path,
        ]

        result = await asyncio.to_thread(
            subprocess.run,
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        if result.returncode != 0:
            error_text = result.stderr.decode(
                "utf-8",
                errors="replace",
            )[-2000:]
            raise RuntimeError(
                "FFmpeg не смог собрать аудиоответ: "
                + error_text
            )

        with open(output_path, "rb") as file:
            return file.read()


async def send_voice_answer_audio(
    message,
    answer: str,
    telegram_user_id: int | None = None,
) -> bool:
    """Отправляет аудиоверсию, не затрагивая уже отправленный текст."""
    progress = await message.reply_text(
        "🎧 Готовлю аудиоверсию ответа "
        "с тихой молитвенной музыкой..."
    )

    disclosure_needed = True

    if telegram_user_id:
        try:
            disclosure_needed = not await analytics_has_event(
                telegram_user_id,
                "voice_ai_disclosure_shown",
            )
        except Exception:
            disclosure_needed = True

    try:
        audio = await build_voice_reply_ogg(answer)
        voice_file = io.BytesIO(audio)
        voice_file.name = VOICE_REPLY_FILENAME

        try:
            await progress.delete()
        except Exception:
            pass

        caption = "🎧 Аудиоверсия ответа"

        if disclosure_needed:
            caption += (
                "\n\nℹ️ Аудиоозвучка создана автоматически."
            )

        await message.reply_voice(
            voice=voice_file,
            caption=caption,
        )

        if disclosure_needed and telegram_user_id:
            await analytics_log_event(
                telegram_user_id,
                "voice_ai_disclosure_shown",
            )

        return True

    except Exception:
        logger.exception("Не удалось создать аудиоверсию ответа")
        try:
            await progress.edit_text(
                "⚠️ Письменный ответ готов, но аудиоверсию "
                "сейчас создать не удалось. Попробуйте следующее "
                "голосовое сообщение немного позже."
            )
        except Exception:
            pass
        return False


async def voice_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message

    if not message or not message.voice:
        return

    if context.user_data.get(
        "awaiting_donation_amount"
    ):
        await message.reply_text(
            "Для суммы пожертвования отправьте, "
            "пожалуйста, только число текстом, "
            "например: 500."
        )
        return

    wait_message = await message.reply_text(
        "🎙 Распознаю голосовое сообщение..."
    )

    user = update.effective_user

    if user:
        context.application.create_task(
            analytics_activity(
                user.id,
                "voice_message",
            )
        )

    try:
        user_text = await transcribe_voice_message(
            update,
            context,
        )

        if not user_text:
            raise ValueError(
                "Не удалось распознать речь. "
                "Попробуйте записать голосовое ещё раз, "
                "говоря немного ближе к микрофону."
            )

        mode = context.user_data.get(
            "mode",
            "ask",
        )

        safe_mode = (
            mode
            if mode in {
                "ask",
                "prayer",
                "healing",
                "finances",
                "blessing",
            }
            else "ask"
        )

        if user:
            context.application.create_task(
                analytics_log_event(
                    user.id,
                    "voice_transcribed",
                )
            )
            context.application.create_task(
                analytics_activity(
                    user.id,
                    f"ai_{safe_mode}",
                )
            )

        try:
            await wait_message.edit_text(
                "📖 Голосовое распознано. "
                "Подбираю ответ на основании Писания..."
            )
        except Exception:
            pass

        answer = await generate_ai_answer(
            user_text=user_text,
            mode=mode,
        )

        try:
            await wait_message.delete()
        except Exception:
            pass

        audio_sent = await send_voice_answer_audio(
            message,
            answer,
            user.id if user else None,
        )

        if user and audio_sent:
            context.application.create_task(
                analytics_log_event(
                    user.id,
                    "voice_reply_audio",
                )
            )

        await send_long_message(
            update,
            answer,
        )

        context.user_data.pop(
            "mode",
            None,
        )

    except ValueError as exc:
        logger.info(
            "Голосовое сообщение отклонено: %s",
            exc,
        )

        try:
            await wait_message.edit_text(
                f"⚠️ {exc}"
            )
        except Exception:
            pass

    except Exception:
        logger.exception(
            "Ошибка обработки голосового сообщения"
        )

        try:
            await wait_message.edit_text(
                "⚠️ Сейчас не удалось обработать "
                "голосовое сообщение.\n\n"
                "Попробуйте отправить его ещё раз "
                "через несколько секунд или напишите текстом."
            )
        except Exception:
            pass


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

    donation_currency = context.user_data.get(
        "awaiting_donation_amount"
    )

    if donation_currency:
        amount, error = parse_donation_amount(
            user_text,
            donation_currency,
        )

        if error:
            await update.message.reply_text(
                "⚠️ " + error,
                reply_markup=donation_amount_menu(
                    donation_currency
                ),
            )
            return

        context.user_data.pop(
            "awaiting_donation_amount",
            None,
        )
        context.user_data.pop(
            "mode",
            None,
        )

        user = update.effective_user

        if user:
            context.application.create_task(
                analytics_activity(
                    user.id,
                    (
                        "donation_custom_amount_"
                        + donation_currency.lower()
                    ),
                )
            )

        await update.message.reply_text(
            donation_details_text(
                donation_currency,
                amount,
            ),
            reply_markup=donation_details_menu(
                donation_currency,
                amount,
            ),
            parse_mode="HTML",
        )
        return

    mode = context.user_data.get(
        "mode",
        "ask",
    )

    user = update.effective_user

    if user:
        safe_mode = (
            mode
            if mode in {
                "ask",
                "prayer",
                "healing",
                "finances",
                "blessing",
            }
            else "ask"
        )

        context.application.create_task(
            analytics_activity(
                user.id,
                f"ai_{safe_mode}",
            )
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



async def post_init(
    application: Application,
) -> None:
    await verify_supabase_connection()
    await verify_analytics_connection()
    asyncio.create_task(
        daily_scheduler_loop(application),
        name="daily_word_scheduler",
    )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    error = context.error

    if isinstance(error, RetryAfter):
        logger.warning(
            "Telegram временно ограничил частоту запросов: %s",
            error,
        )
        return

    if isinstance(
        error,
        (TimedOut, NetworkError),
    ):
        logger.warning(
            "Временная сетевая ошибка Telegram: %s",
            error,
        )
        return

    if isinstance(error, BaseException):
        logger.error(
            "Необработанная ошибка Telegram update",
            exc_info=(
                type(error),
                error,
                error.__traceback__,
            ),
        )
    else:
        logger.error(
            "Необработанная ошибка Telegram update: %r",
            error,
        )

    try:
        if isinstance(update, Update):
            message = update.effective_message

            if message is not None:
                await message.reply_text(
                    "⚠️ Произошла временная ошибка. "
                    "Попробуйте действие ещё раз.",
                    reply_markup=main_menu(),
                )
    except Exception:
        logger.exception(
            "Не удалось отправить пользователю "
            "сообщение об ошибке"
        )

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
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "myid",
            myid_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "links",
            links_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "daily",
            daily_command,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.VOICE,
            voice_handler,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_handler,
        )
    )

    application.add_error_handler(
        error_handler
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
