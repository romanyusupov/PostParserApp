# Калькулятор лёгкой практики

## Что это

Самостоятельный статический PWA-калькулятор воды и ходьбы/бега. Он не зависит от PostParser, Flask, Gunicorn или базы данных и может быть перенесён на другой HTTPS static hosting целиком вместе с папкой `easypracticecalc/`.

Production URL: `/easypracticecalc/`.

## Основные файлы

- `index.html` — интерфейс, неизменяемые таблицы расчётов воды и движения, регистрация service worker.
- `timer_logic.js` — модель таймера и persistence-слой без привязки к DOM.
- `timer.js` — отображение последовательных отрезков, history, cumulative time и действия Start, Pause, Resume, Next и Reset.
- `timer_logic.test.js` — автономные Node.js-тесты модели времени.
- `workout_session.test.js` — тесты Workout Session, запрета Next и migration старого состояния.
- `manifest.webmanifest` и `icon-*.png` — PWA manifest и иконки.
- `sw.js` — собственный offline cache, ограниченный scope `/easypracticecalc/`.

## Архитектура Workout Session

Источником времени служит абсолютный timestamp `endAt`. `setInterval()` используется только для перерисовки; после background/suspend фактический остаток снова вычисляется через `Date.now()`.

Текущее состояние хранится под ключом `easypracticecalc.workoutSession.v2`. Session содержит `completedSegments`, неизменяемый после Start `currentSegment`, черновик следующего отрезка и один из статусов:

- `running` — текущий отрезок выполняется;
- `paused` — остаток текущего отрезка зафиксирован;
- `segment_completed` — таймер достиг `00:00`, отрезок завершён, но ещё не перенесён в history;
- `configuring_next_segment` — предыдущий отрезок в history, пользователь выбирает параметры следующего.

Критическое бизнес-правило: **параметры практики нельзя менять до полного завершения текущего отрезка. Следующий отрезок можно создать только после достижения текущим таймером значения `00:00`.** Это проверяет сама session model, а не только disabled-состояние controls.

- Start создаёт новый current segment из текущего production-расчёта и замораживает его параметры.
- Pause вычисляет реальный остаток по timestamp и фиксирует его.
- Resume создаёт новый `endAt` из сохранённого остатка, не накапливая ошибку.
- Finish автоматически ограничивает elapsed полной planned duration, даже если PWA открыли позже.
- Next переносит только completed segment в history и идемпотентно открывает настройку следующего.
- Reset очищает всю активную Workout Session, включая history и cumulative time.
- При reload состояние и выбранная практика восстанавливаются автоматически.
- При `visibilitychange`, `pageshow` и `focus` UI немедленно пересчитывается.
- Текущий слой всегда вычисляется из доли прошедшего времени, а не хранится как источник истины.
- Горизонтальная шкала всегда показывает пять слоёв. Её заполнение равно `(targetLayers * progress) / 5`, поэтому практика на три слоя завершается ровно на отметке 3, а не растягивается до отметки 5.

Суммарное активное время равно сумме planned duration завершённых отрезков плюс elapsed текущего. Pause, настройка между отрезками и ожидание после `00:00` не учитываются.

Persistence отделён функциями `loadWorkoutSession()`, `saveWorkoutSession()` и `clearWorkoutSession()`. Состояния старого ключа `easypracticecalc.timerState.v1` автоматически мигрируют в current segment №1 без потери running/paused/finished progress.

## Требования к hosting

- HTTPS (обязателен для service worker).
- Раздача папки как статических файлов по `/easypracticecalc/`.
- Scope service worker должен оставаться `/easypracticecalc/`.
- `manifest.webmanifest` должен отдаваться с корректным manifest MIME type.
- `sw.js` нельзя кешировать браузером надолго; при изменении frontend нужно увеличивать `CACHE_NAME`.

После первой полной загрузки калькулятор, активный таймер, Pause/Resume, восстановление и прогресс работают без сети.

## Будущий перенос и синхронизация

Приложение автономно и может быть передано разработчику учебной платформы отдельно от PostParser.

Синхронизация между компьютером и телефоном сейчас не реализована. Для неё потребуются API, идентификатор пользователя или session и server-side persistence. Текущая явная timer model подготовлена к такому расширению.
