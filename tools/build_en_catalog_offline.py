from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_DIR / "frontend"
BACKEND_APP_DIR = REPO_DIR / "backend" / "app"
CATALOG_PATH = FRONTEND_DIR / "locales" / "en.json"
TRANSLATABLE_ATTRIBUTES = {"placeholder", "title", "aria-label", "alt"}
SOURCE_OVERRIDES = {
    "2 990 ₽ за 30 дней для одного заведения": "RUB 2,990 for 30 days for one venue",
    "Axelio · Админ · Заведения": "Axelio · Admin · Venues",
    "Axelio · Зарплата": "Axelio · Pay",
    "Axelio · Профили зарплаты": "Axelio · Pay profiles",
    "Axelio · Профиль зарплаты": "Axelio · Pay profile",
    "Axelio · Сводка зарплаты": "Axelio · Pay summary",
    "Админ · Заведения": "Admin · Venues",
    "Базовые справочники для выручки, расходов и KPI.": "Core reference data for revenue, expenses, and KPIs.",
    "Внутренние переводы создают приход и списание на одинаковую сумму: объём движений растёт, а чистый поток заведения не меняется.": "Internal transfers create an inflow and an outflow for the same amount: gross movement increases while the venue's net cash flow stays unchanged.",
    "Безопасный вход": "Secure sign-in",
    "Все заведения": "All venues",
    "Выберите заведение": "Select a venue",
    "Выбрать заведение": "Select venue",
    "Выбранный язык используется в интерфейсе и уведомлениях Axelio в Telegram.": "Your selected language is used for both the interface and Axelio notifications in Telegram.",
    "Войти": "Sign in",
    "Войти по номеру": "Sign in with phone",
    "Вход выполнен": "Signed in",
    "Вход по телефону": "Sign in with phone",
    "Выйти из заведения": "Leave venue",
    "Выручка дня": "Daily revenue",
    "Выручка за вычетом расходов без ФОТ и фонда оплаты труда.": "Revenue less non-payroll expenses and payroll costs.",
    "График → зарплата → смены и индикаторы без боевых действий.": "Schedule → pay → shifts and indicators in read-only mode.",
    "Доля прибыли от выручки за период.": "Profit as a share of revenue for the period.",
    "Для круглосуточных заведений: график и отчёты будут разделяться на день и ночь.": "For 24/7 venues, schedules and reports are split into day and night periods.",
    "Здесь видно, как закрытый день превращается в понятный управленческий срез: выручка, расходы, прибыль и сигналы.": "See how a closed business day becomes a clear management snapshot: revenue, expenses, profit, and alerts.",
    "Здесь собираются выручка, признанные расходы, эффективность смены, план/факт и предупреждения. Экран должен быстро отвечать на вопрос, всё ли в порядке сегодня.": "This view combines revenue, recognized expenses, shift efficiency, targets versus actuals, and alerts so you can quickly see whether today is on track.",
    "Зарегистрироваться": "Create account",
    "Итоговая выручка по выбранному периоду и режиму.": "Total revenue for the selected period and view.",
    "Как смотреть DEMO по движениям": "How to explore cash movements in DEMO",
    "Как смотреть DEMO по экономике дня": "How to explore daily performance in DEMO",
    "Карточка заведения": "Venue overview",
    "Можно переключить публичное демо-заведение, выгрузить или восстановить fixture.": "Switch the public demo venue, export the fixture, or restore it.",
    "Мои заведения": "My venues",
    "Основной способ входа — по номеру телефона и паролю. Звонок нужен только для первой настройки номера и для сброса пароля.": "Sign in with your phone number and password. Phone verification is required only when setting up your number or resetting your password.",
    "Название заведения": "Venue name",
    "Настройка заведения": "Venue setup",
    "Настройки заведения": "Venue settings",
    "Открой нужное заведение или создай новое.": "Open a venue or create a new one.",
    "Открыть выручку": "Open revenue",
    "Перенаправляем на единую страницу зарплаты.": "Redirecting to the unified pay page.",
    "После входа тебя вернёт на": "After signing in, you will return to",
    "Переход к сменам": "Open shifts",
    "По дням выбранного периода, ₽": "By day in the selected period, RUB",
    "Поиск по заведению / invoice / комментарию": "Search by venue, invoice, or comment",
    "Правила заведения": "Venue rules",
    "Разделы DEMO": "DEMO sections",
    "Распределить из плана заведения": "Allocate from the venue target",
    "Сбросить из fixture": "Reset from fixture",
    "Сводка → расходы → начисления → карточка заведения.": "Summary → expenses → accruals → venue overview.",
    "Создать заведение": "Create venue",
    "Скидка, ₽": "Discount, RUB",
    "Сумма возврата, ₽": "Refund amount, RUB",
    "ФОТ / выручка": "Payroll / revenue",
    "ФОТ от выручки": "Payroll as % of revenue",
    "Штрафы / Списания / Премии": "Adjustments / Deductions / Bonuses",
    "Штрафы и премии": "Adjustments and bonuses",
    "Штрафы/Списания": "Adjustments / Deductions",
    "Это заведение": "This venue",
    "выберите заведение": "select a venue",
    "зарплата · штрафы": "pay · adjustments",
    "создание и управление заведениями": "creating and managing venues",
    "вход по телефону": "phone sign-in",
    "штрафы, списания и премии": "adjustments, deductions, and bonuses",
    "упомянуть коллегу · Ctrl/⌘ + Enter — отправить": "mention a colleague · Ctrl/⌘ + Enter — send",
}

PUBLIC_COPY_OVERRIDES = {
    "Актуально на 03.05.2026": "Updated May 3, 2026",
    "Актуально на 29.03.2026": "Updated March 29, 2026",
    "Формат оказания:": "Service format:",
    "Формат предоставления:": "Delivery format:",
    "Стоимость на текущий момент:": "Current price:",
    "Сведения о продавце и каналах связи по Axelio": "Seller details and Axelio support channels",
    "Назначение страницы": "Purpose of this page",
    "Как работает продление доступа, отмена списаний и возвраты": "How access renewal, cancellation, and refunds work",
    "Текущий тариф:": "Current plan:",
    "Тип оплаты:": "Payment type:",
    "разовое продление доступа на 30 дней": "one-time access renewal for 30 days",
    "1. Как работает продление доступа": "1. How access renewal works",
    "2. Что происходит после окончания срока": "2. What happens when access expires",
    "3. Автосписаний сейчас нет": "3. No automatic charges",
    "4. Возврат денежных средств": "4. Refunds",
    "5. Вопросы по оплате и доступу": "5. Payment and access questions",
    "Условия предоставления доступа к сервису Axelio": "Terms for accessing Axelio",
    "3. Стоимость и порядок оплаты": "3. Price and payment procedure",
    "7. Возвраты и отмена подписки": "7. Refunds and subscription cancellation",
    "Доступ к сервису предоставляется в формате «как есть» с учетом текущего функционала продукта. Отдельные модули, интеграции и функции могут добавляться, изменяться или дорабатываться по мере развития сервиса.": "The service is provided as is, based on the functionality currently available. Individual modules, integrations, and features may be added, changed, or improved as the service evolves.",
    "Настоящий документ является предложением самозанятого": "This document is an offer by the self-employed service provider",
    "Таранкова Владимира Алексеевича": "Vladimir Alekseevich Tarankov",
    ", далее — «Продавец», заключить договор на предоставление доступа к сервису Axelio на изложенных ниже условиях.": ", referred to below as the “Seller,” to enter into an agreement for access to Axelio under the terms set out below.",
    "Продавец предоставляет Пользователю неисключительное ограниченное право доступа к функционалу сервиса Axelio в течение оплаченного периода доступа, а Пользователь обязуется оплатить такой доступ.": "The Seller grants the User a limited, non-exclusive right to use Axelio during the paid access period, and the User agrees to pay for that access.",
    "Полным и безоговорочным акцептом настоящей оферты считается успешная оплата продления доступа через доступные на момент оплаты способы, включая платежный сервис Robokassa.": "Successful payment for an access renewal using any payment method available at the time, including Robokassa, constitutes full and unconditional acceptance of this offer.",
    "Стоимость доступа составляет": "Access costs",
    ", если иная цена не указана на момент оформления. Оплата производится в безналичном порядке через подключенные платежные инструменты.": ", unless a different price is shown at checkout. Payment is made electronically through the available payment methods.",
    "Доступ к сервису предоставляется на срок оплаченного периода. На текущем этапе следующий период не продлевается автоматически и оплачивается отдельным платежом.": "Access is provided for the paid period. At this stage, the next period is not renewed automatically and must be purchased separately.",
    "Продавец обязуется предоставить доступ к сервису после подтверждения оплаты.": "The Seller must provide access to the service after payment is confirmed.",
    "Пользователь обязуется указывать достоверные данные и не использовать сервис в нарушение законодательства РФ.": "The User must provide accurate information and must not use the service in violation of Russian law.",
    "Пользователь обязуется не передавать доступ третьим лицам вне предусмотренных сервисом сценариев.": "The User must not transfer access to third parties outside the scenarios supported by the service.",
    "Продавец не несет ответственности за невозможность использования сервиса по причинам, не зависящим от Продавца, включая сбои связи, действия третьих лиц, ограничения со стороны платформ и иные внешние обстоятельства.": "The Seller is not liable when the service cannot be used for reasons beyond the Seller’s control, including connectivity failures, third-party actions, platform restrictions, or other external circumstances.",
    "Порядок продления доступа и возвратов описан на отдельной странице": "Renewals and refunds are described on the separate page",
    "и применяется в совокупности с настоящей офертой.": "It applies together with this offer.",
    "По вопросам оплаты и доступа пользователь может обратиться по указанному телефону поддержки или через Telegram @axelio_support.": "For payment or access questions, contact support by phone or via Telegram at @axelio_support.",
    "По вопросам подключения, оплаты, продления, отмены подписки, доступа к сервису и общим вопросам использования Axelio пользователь может связаться с поддержкой по указанному телефону.": "For help with setup, payment, renewal, cancellation, service access, or general use of Axelio, contact support at the phone number shown above.",
    "Эта страница содержит основные сведения о продавце и контактные данные для пользователей, оформляющих или использующих подписку на сервис Axelio.": "This page provides the seller’s main details and contact information for users who subscribe to or use Axelio.",
    "Оплата предоставляет доступ к сервису Axelio для одного заведения на 30 календарных дней. На текущем этапе используется разовое продление: после окончания оплаченного периода доступ не продлевается автоматически.": "Payment provides access to Axelio for one venue for 30 calendar days. At this stage, renewals are one-time purchases: access is not renewed automatically after the paid period ends.",
    "После окончания оплаченного периода доступ к рабочим функциям ограничивается. Владелец заведения по-прежнему может открыть карточку заведения, увидеть статус оплаты и оформить следующее продление.": "After the paid period ends, access to working features is restricted. The venue owner can still open the venue page, view the payment status, and purchase another renewal.",
    "На старте сервиса Axelio не использует автосписания и автопродление. Каждое следующее продление оформляется отдельной оплатой.": "Axelio does not currently use automatic charges or automatic renewal. Each renewal is purchased separately.",
    "Возврат денежных средств осуществляется в соответствии с законодательством Российской Федерации, применимым к цифровым услугам и доступу по подписочной модели. Каждый запрос рассматривается индивидуально с учетом факта предоставления доступа, периода использования и характера оказанной услуги.": "Refunds are handled in accordance with Russian law applicable to digital services and subscription access. Each request is reviewed individually based on whether access was provided, the period of use, and the nature of the service delivered.",
    "Если у пользователя возникли вопросы по оплате, продлению или статусу доступа, он может обратиться в поддержку по телефону": "For questions about payment, renewal, or access status, contact support by phone at",
    "или через Telegram": "or via Telegram at",
    "Порядок обработки персональных данных пользователей Axelio": "How Axelio processes users’ personal data",
    "Настоящая политика описывает, как самозанятый": "This policy describes how the self-employed service provider",
    "обрабатывает персональные данные пользователей сервиса Axelio.": "processes the personal data of Axelio users.",
    "имя, фамилия, отчество и иные данные профиля, указанные пользователем;": "the user’s first name, last name, patronymic, and other profile data;",
    "номер телефона;": "phone number;",
    "идентификаторы аккаунта и технические данные, необходимые для авторизации и работы сервиса;": "account identifiers and technical data required for authentication and operation of the service;",
    "информация о подписке, оплатах и статусе доступа;": "subscription, payment, and access-status information;",
    "данные, которые пользователь загружает или формирует внутри сервиса в рамках его использования.": "data uploaded or created by the user while using the service.",
    "предоставление доступа к сервису Axelio;": "providing access to Axelio;",
    "идентификация пользователя и поддержание безопасности учетной записи;": "identifying the user and maintaining account security;",
    "обработка платежей, управление подпиской и клиентская поддержка;": "processing payments, managing subscriptions, and providing customer support;",
    "улучшение работы сервиса и разрешение технических обращений.": "improving the service and resolving technical support requests.",
    "Обработка данных осуществляется для исполнения договора с пользователем, соблюдения требований законодательства РФ, а также в иных случаях, допускаемых применимым законодательством.": "Data is processed to perform the agreement with the User, comply with Russian law, and in other cases permitted by applicable law.",
    "Данные могут передаваться только в объеме, необходимом для обработки платежей, технического обслуживания сервиса, исполнения требований закона и обеспечения работы подключенных сервисов, включая платежного партнера Robokassa.": "Data may be shared only to the extent necessary to process payments, maintain the service, comply with legal requirements, and operate connected services, including the payment partner Robokassa.",
    "Внутренняя финансовая информация каждого заведения, включая данные о выручке, расходах, прибыли, зарплатах, отчётах закрытия смен, финансовых сводках и связанных расчётах, относится к данным соответствующего заведения и используется сервисом только для работы функций Axelio.": "Each venue’s internal financial information—including revenue, expenses, profit, payroll, shift-closing reports, financial summaries, and related calculations—belongs to that venue and is used only to operate Axelio features.",
    "Владелец сервиса, администратор сервиса и иные лица со стороны Axelio не осуществляют произвольный доступ к внутренней финансовой составляющей конкретного заведения, за исключением случаев, когда такой доступ необходим для исполнения требований закона, устранения технического инцидента либо обработки прямого обращения владельца заведения или уполномоченного им пользователя.": "The service owner, administrators, and other Axelio personnel do not access a venue’s internal financial information at their discretion. Access is permitted only when required by law, needed to resolve a technical incident, or requested directly by the venue owner or an authorized user.",
    "Такие данные не передаются третьим лицам и не используются в личных целях, рекламных целях или иных целях, не связанных с предоставлением, сопровождением и безопасной работой Axelio, кроме случаев, прямо предусмотренных законодательством или необходимых для работы подключенных сервисов в минимально необходимом объёме.": "This data is not shared with third parties or used for personal, advertising, or unrelated purposes, except where expressly required by law or minimally necessary to operate connected services.",
    "Продавец принимает разумные организационные и технические меры для защиты данных от неправомерного доступа, изменения, раскрытия или уничтожения.": "The Seller takes reasonable organizational and technical measures to protect data against unauthorized access, alteration, disclosure, or destruction.",
    "Пользователь вправе запросить актуализацию, уточнение или удаление персональных данных в пределах, допускаемых законодательством и необходимостью исполнения договора по предоставлению доступа к сервису.": "The User may request that personal data be updated, corrected, or deleted, subject to applicable law and the requirements of the service-access agreement.",
    "По вопросам, связанным с обработкой персональных данных, можно обратиться по телефону поддержки": "For questions about personal data processing, contact support at",
}

SOURCE_OVERRIDES.update(PUBLIC_COPY_OVERRIDES)
SOURCE_OVERRIDES.update(
    {
        "Активно": "Active",
        "Аренда": "Rent",
        "Вперёд": "Next",
        "Выплата ФОТ": "Payroll payment",
        "Выплаты ФОТ": "Payroll payments",
        "Главный экран оставляет только ключевые метрики. Детальные разделы ниже открываются отдельно.": "The overview shows only the key metrics. Open the sections below for details.",
        "Готово": "Done",
        "Динамика выручки, затрат и прибыли": "Revenue, costs, and profit over time",
        "Для просмотра ФОТ нужны права на начисления.": "Payroll permission is required to view this data.",
        "Для части месяца ФОТ распределяется по дням, а проводка создаётся на месяц": "For a partial month, payroll is allocated by day while the ledger entry covers the whole month",
        "За полный месяц сверяются начисления и проводки ФОТ.": "For a full month, payroll accruals are reconciled with ledger entries.",
        "Затраты от выручки": "Total costs as % of revenue",
        "Заведение в архиве": "Archived venue",
        "Заведение сейчас в архиве. Доступно только владельцу.": "This venue is archived and available only to its owner.",
        "Закрытые отчёты, подтверждённые расходы и ФОТ": "Closed reports, confirmed expenses, and payroll",
        "Легенда графика": "Chart legend",
        "Маржинальность": "Profit margin",
        "Маржинальность, %": "Profit margin, %",
        "На сайт": "Website",
        "Начать пользоваться": "Get started",
        "Оставить заявку": "Contact us",
        "Открыть экономику дня": "Open daily performance",
        "Основная сумма по закрытым отчётам за выбранный период.": "Revenue from closed reports in the selected period.",
        "Перейти к деталям": "View details",
        "Порядковый день": "Day number",
        "Прибыль": "Profit",
        "Прибыль дня": "Daily profit",
        "Прибыль месяца": "Monthly profit",
        "Подтверждённые расходы и распределённый ФОТ": "Confirmed expenses and allocated payroll",
        "Расходы / выручка": "Expenses / revenue",
        "Расходы без ФОТ": "Expenses excluding payroll",
        "Расходы от выручки": "Expenses as % of revenue",
        "Сравниваемый период": "Comparison period",
        "Текущий период": "Current period",
        "к прошлому месяцу": "vs previous month",
        "п.п.": "pp",
        "подтверждённые расходы и распределённый ФОТ": "Confirmed expenses and allocated payroll",
    }
)

GLOSSARY_REPLACEMENTS = (
    ("Establishments", "Venues"),
    ("establishments", "venues"),
    ("Establishment", "Venue"),
    ("establishment", "venue"),
    ("Institutions", "Venues"),
    ("institutions", "venues"),
    ("Institution", "Venue"),
    ("institution", "venue"),
    ("Salary profiles", "Pay profiles"),
    ("salary profiles", "pay profiles"),
    ("Salary profile", "Pay profile"),
    ("salary profile", "pay profile"),
    ("Expenditures", "Expenses"),
    ("expenditures", "expenses"),
    ("Expenditure", "Expense"),
    ("expenditure", "expense"),
    ("Coming", "Income"),
    ("coming", "income"),
    ("Clean stream", "Net cash flow"),
    ("clean stream", "net cash flow"),
    ("Regime", "Mode"),
    ("regime", "mode"),
    ("Meanings", "Values"),
    ("meanings", "values"),
    ("Meaning", "Value"),
    ("meaning", "value"),
    ("Minus guarantee", "Minimum guarantee"),
    ("minus guarantee", "minimum guarantee"),
    ("Purpose of KPI", "KPI target"),
    ("purpose of KPI", "KPI target"),
    ("Fact KPI", "KPI actual"),
    ("fact KPI", "KPI actual"),
    ("Totally", "Total"),
    ("totally", "total"),
    ("FOOT", "Payroll"),
    ("FOT", "Payroll"),
    ("PHOTO", "Payroll"),
    ("PayrollA", "Payroll"),
    ("PHOT", "Payroll"),
    ("Payrolls", "Payroll"),
    ("Marginality", "Profit margin"),
    ("Profits", "Profit"),
    ("Itogo", "Total"),
)


def normalize_source(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def has_cyrillic(value: str) -> bool:
    return any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in value)


class StaticTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: set[str] = set()
        self.ignored_depth = 0

    def add(self, value: str | None) -> None:
        source = normalize_source(value or "")
        if source and has_cyrillic(source):
            self.sources.add(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        for name, value in attrs:
            if name in TRANSLATABLE_ATTRIBUTES:
                self.add(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.add(data)


class ScriptContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._script_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        self._script_depth += 1
        if self._script_depth == 1:
            self._chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._script_depth:
            return
        self._script_depth -= 1
        if self._script_depth == 0:
            self.scripts.append("".join(self._chunks))
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._script_depth:
            self._chunks.append(data)


def collect_code_sources(code: str) -> set[str]:
    sources: set[str] = set()
    for chunk in re.split(r"""["'`<>{}\n\r;]""", code):
        match = re.search(r"[А-Яа-яЁё]", chunk)
        if match is None:
            continue
        value = chunk[match.start() :]
        value = re.sub(r"\\[nrt]", " ", value)
        value = re.sub(r"\$\s*$", "", value)
        value = re.sub(r"[\s),\]]+$", "", value)
        source = normalize_source(value)
        if source and has_cyrillic(source):
            sources.add(source)
    return sources


def collect_sources() -> list[str]:
    sources: set[str] = set()
    for file in sorted(FRONTEND_DIR.glob("*.html")):
        raw = file.read_text(encoding="utf-8")
        parser = StaticTextParser()
        parser.feed(raw)
        sources.update(parser.sources)
        script_parser = ScriptContentParser()
        script_parser.feed(raw)
        for script in script_parser.scripts:
            sources.update(collect_code_sources(script))
    for file in sorted(FRONTEND_DIR.rglob("*.js")):
        if file.name in {"i18n.js", "i18n-bootstrap.js"}:
            continue
        sources.update(collect_code_sources(file.read_text(encoding="utf-8")))
    for file in sorted(BACKEND_APP_DIR.rglob("*.py")):
        raw = file.read_text(encoding="utf-8")
        for match in re.finditer(r"""(?:^|[^\w])(?:[rubf]{0,3})(["'])([^\n]*?)\1""", raw, re.IGNORECASE | re.MULTILINE):
            sources.update(collect_code_sources(match.group(2)))
    return sorted(sources)


def translate_missing_sources(sources: list[str]) -> dict[str, str]:
    import os
    import ssl

    os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")
    os.environ.setdefault("ARGOS_STANZA_AVAILABLE", "0")
    os.environ.setdefault("ARGOS_CHUNK_TYPE", "ARGOSTRANSLATE")

    import argostranslate.package
    import argostranslate.translate
    import certifi

    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
    installed = argostranslate.translate.get_installed_languages()
    if not (
        any(language.code == "ru" for language in installed) and any(language.code == "en" for language in installed)
    ):
        argostranslate.package.update_package_index()
        packages = argostranslate.package.get_available_packages()
        package = next((item for item in packages if item.from_code == "ru" and item.to_code == "en"), None)
        if package is None:
            raise RuntimeError("Argos Russian to English language package is unavailable")
        package_path = package.download()
        argostranslate.package.install_from_path(package_path)

    translated: dict[str, str] = {}
    for index, source in enumerate(sources, start=1):
        translated[source] = argostranslate.translate.translate(source, "ru", "en").strip()
        if index % 25 == 0 or index == len(sources):
            print(f"translated {index}/{len(sources)} strings", flush=True)
    return translated


def refine_translation(source: str, translation: str) -> str:
    if source in SOURCE_OVERRIDES:
        return SOURCE_OVERRIDES[source]
    refined = str(translation or "").strip()
    for old, new in GLOSSARY_REPLACEMENTS:
        refined = refined.replace(old, new)
    if re.search(r"завед", source, re.IGNORECASE):
        venue_terms = re.compile(
            r"\b(place|places|facility|facilities|building|buildings|location|locations)\b",
            re.IGNORECASE,
        )

        def replace_venue_term(match: re.Match[str]) -> str:
            plural = match.group(0).lower().endswith(("s", "ies"))
            replacement = "venues" if plural else "venue"
            return replacement.capitalize() if match.group(0)[0].isupper() else replacement

        refined = venue_terms.sub(replace_venue_term, refined)
    if "₽" in source:
        refined = re.sub(r"[А-Яа-яЁё]+", "", refined)
        refined = re.sub(r"\s+", " ", refined).strip()
        if "RUB" not in refined and "₽" not in refined:
            if source.rstrip().endswith("₽"):
                refined = refined.rstrip(" ,") + (", RUB" if ", ₽" in source else " RUB")
            else:
                refined = refined.rstrip(" ,/") + " (RUB)"
    if has_cyrillic(refined):
        refined = re.sub(r"[А-Яа-яЁё]+", "", refined)
        refined = re.sub(r"\s+", " ", refined).strip()
    if not source.endswith((".", "!", "?", ":", ";")) and refined.endswith("."):
        refined = refined[:-1].rstrip()
    return refined


def main() -> None:
    sources = collect_sources()
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    missing = [source for source in sources if not str(catalog.get(source) or "").strip()]
    if missing:
        catalog.update(translate_missing_sources(missing))
    catalog = {source: refine_translation(source, translation) for source, translation in catalog.items()}
    ordered = dict(sorted(catalog.items(), key=lambda item: item[0]))
    CATALOG_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"English catalog: {len(ordered)} entries ({len(missing)} added)")


if __name__ == "__main__":
    main()
