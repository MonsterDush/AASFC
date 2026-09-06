# Промпты генерации

Режим: встроенный image_gen. Концепты с демонстрационными данными, не снимки работающего нового интерфейса.

## План по дням

Use case: ui-mockup
Create a single high-fidelity product UI screenshot concept for the Russian restaurant management web app Axelio, showing the redesigned "Планы департаментов" page in "План по дням" mode. This is a polished realistic application screen, not a marketing poster or presentation. All text is Russian, crisp and readable. Large 1536x1536 or 2048x1536 landscape canvas with generous margins. Centered content layout, no sidebar, matching Axelio's existing deep navy theme: background #090F1D, cards #0E1730, subtle borders #1C2C55, off-white text #E8ECF5, secondary text #B3BDD6, primary buttons muted azure #3C78C8, emerald successes. System sans serif, 16 px rounded cards, calm professional financial interface, subtle shadows. A small angular A logo and Axelio wordmark in the top left. Bottom navigation like existing app: "Заведение", "Сводка", "Расходы", gear icon. No device frame, no perspective, no neon, no photo.
Header: small breadcrumb "Финансы / Планы". Main title "Планы департаментов", subtitle "Настройте выручку, от которой зависит процент сотрудников". A small unobtrusive "Концепт · пример данных" chip.
Top filter row: labelled select "Департамент" showing "Бар", and labelled month selector "Сентябрь 2026" with left/right chevrons. Beneath it large segmented control "План на месяц" and selected "План по дням".
Section 1 white text heading "Недельная схема". Helper "Задайте обычную неделю и примените к нужным датам". Seven equal input cards in one horizontal row with weekday labels and ruble values: "Пн" "50 000 ₽", "Вт" "50 000 ₽", "Ср" "60 000 ₽", "Чт" "60 000 ₽", "Пт" "100 000 ₽", "Сб" "130 000 ₽", "Вс" "80 000 ₽". Weekend cards subtle blue tinted background, all inputs readable.
Below three buttons: "Применить к этой неделе", primary "Применить ко всему месяцу", "Выбрать диапазон".
Below buttons an unchecked checkbox labelled exactly "Перезаписать уже настроенные даты".
Quiet explanatory line: "Будут заполнены 23 даты. 7 настроенных дат сохранятся."
Section 2 below weekly scheme, full width: heading "Планы на конкретные даты", right small "Сентябрь · 30 дней". Hint "Любую дату можно изменить отдельно". Clean editable financial table with columns "Дата", "День", "План, ₽", "Факт, ₽", "Выполнение". Render exactly these rows:
01.09 | Вт | 50 000 | 47 500 | 95%
02.09 | Ср | 60 000 | 64 200 | 107%
03.09 | Чт | 60 000 | — | —
04.09 | Пт | 100 000 | 116 000 | 116%
05.09 | Сб | 130 000 | — | —
11.09 | Пт | 150 000 [small tag "Вручную"] | — | —
For 11.09 show pencil icon next to editable plan, separate little tag. Table is a shortened preview: show below "Показать все 30 дней". Fact percentages >=100 in restrained emerald, 95% neutral muted. Blank facts must be em-dash never zero. Plans look editable inputs, facts are plain text.
Footer inside content small information icon: "Факт учитывает только закрытые отчёты. Если план не задан, повышение за день не применяется."
Bottom small quiet line "Источник в профиле зарплаты: план департамента по дням" with link "Открыть профили".
Keep design internally consistent and restrained. This page edits revenue plans only, do not add any percent tier editor, charts, monthly total comparison, or fabricated extra navigation. Ensure every control fits without clipped text.

## План на месяц

Use case: ui-mockup
Generate a polished high-fidelity desktop UI screenshot of Axelio restaurant management app, redesigned "Планы департаментов" page in monthly mode. This is a product concept with example data, not a marketing poster. Russian labels exactly, high readability. Wide landscape 1536x1024 canvas. Centered content area about 1100 px, no sidebar. Deep navy background #090F1D, dark navy cards #0E1730, fine blue borders #1C2C55, text #E8ECF5, secondary #B3BDD6, muted blue primary buttons #3C78C8 and restrained emerald accents. System sans serif, rounded 16px cards, subtle shadows, understated existing Axelio app style. Small angular A logo and wordmark Axelio, no device mockup or perspective.
Top breadcrumb "Финансы / Планы"; title "Планы департаментов"; subtitle "Настройте выручку, от которой зависит процент сотрудников"; small badge "Концепт · пример данных".
Selectors "Департамент" with "Бар"; month "Сентябрь 2026" with arrows. Segmented mode control with selected "План на месяц" and unselected "План по дням".
Large main card heading "Месячный план · Бар".
A clear editable field under label "План на сентябрь" containing "1 500 000 ₽", with nearby primary button "Сохранить план".
Three clean stat columns underneath: "Фактическая выручка" value "1 260 000 ₽"; "Выполнение" value "84%"; "Осталось до плана" value "240 000 ₽".
A horizontal progress bar filled exactly 84%, labelled left "1 260 000 ₽" and right "1 500 000 ₽".
Below a muted note with information icon: "Факт учитывает только закрытые отчёты".
Second smaller card heading "Как используется этот план". Body exactly "В профиле зарплаты выберите «План департамента за месяц»." Another short line "Дневные планы настраиваются отдельно и не заменяют месячный план." Link-like button "Открыть профили зарплаты".
No daily table, no tier editor, no money amounts other than the specified example. Bottom existing Axelio navigation "Заведение", "Сводка", "Расходы", gear icon. Refined spacing, legible Cyrillic typography, airy uncluttered layout, sharp realistic screenshot quality.
