import logging
import os
import random
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone

import httpx
from openai import AsyncOpenAI
from telegram import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import NetworkError, RetryAfter, TimedOut
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
SUPABASE_TIMEOUT_SECONDS = 10.0
OPENAI_TIMEOUT_SECONDS = 120.0

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
                    "📖 Стих из Библии",
                    callback_data="verse",
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

    source_names = [
        ("Instagram", "instagram"),
        ("Instagram Stories", "instagram_story"),
        ("Bless United", "blessunited"),
        ("Facebook", "facebook"),
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
        f"• Активные за 7 дней: {active_7d}\n\n"
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
        "Расскажите, что происходит в вашей жизни, "
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
            "Напишите своими словами, "
            "что произошло, "
            "что вас тревожит "
            "или какой библейский ответ "
            "вы хотите найти."
        )

    elif action == "prayer":
        context.user_data["mode"] = "prayer"
        text = (
            "🙏 <b>Молитва по нужде</b>\n\n"
            "Опишите вашу нужду конкретно: "
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
            "Напишите, за кого молимся "
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
            "Опишите вашу ситуацию: "
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
            "Напишите, кого или что "
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
            "не к технологии, а ко Христу."
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
