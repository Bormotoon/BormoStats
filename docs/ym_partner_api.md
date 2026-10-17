# Яндекс Маркет Partner API: разбор для интеграции

Разобрано 2026-10-17 по официальной OpenAPI-спецификации
[yandex-market/yandex-market-partner-api](https://github.com/yandex-market/yandex-market-partner-api)
(коммит `23dd461`, 2026-10-15) и [документации](https://yandex.ru/dev/market/partner-api/doc/ru/).
Контекст: этап 4 [плана по ценам](./pricing_plan.md).

## Основы

- **Base URL:** `https://api.partner.market.yandex.ru`.
- **Авторизация:** заголовок `Api-Key: <token>` (есть ещё OAuth, он нам не нужен).
- **Права токена (scopes):**
  - для чтения достаточно `all-methods:read-only`;
  - для записи цен нужен `pricing` или `all-methods`;
  - для выхода из акций — `promotion` или `pricing`;
  - для финансовых отчётов — `finance-and-accounting`.

  Рекомендуем просить у заказчика два токена: read-only для коллекторов и отдельный с `pricing` + `promotion` для репрайсера. Проверка токена: `POST /v2/auth/token`.
- **Иерархия:** *кабинет* (`businessId`) → *магазины* (`campaignId`, по одному на модель FBY/FBS/DBS/Express). Оба id отдаёт `GET /v2/campaigns`.
  - Каталог, цены и акции живут на уровне кабинета.
  - Статистика заказов и остатки живут на уровне магазина.
  - В `dim_account` для ЯМ храним `businessId` как `account_id`, а список `campaignId` получаем через `GET /v2/campaigns`.
- **Идентификатор товара:** `offerId` (он же `shopSku`) — SKU продавца. Это и есть «артикул поставщика» для таблицы сравнения. `vendorCode` в ЯМ — артикул *производителя*, не путать.
- **Лимиты:**
  - Превышение лимита возвращает **HTTP 420**, а не 429. Наш `JsonHttpClient` ретраит только 429 и 5xx ([collectors/common/http_client.py](../collectors/common/http_client.py)), поэтому 420 нужно добавить для `marketplace="ym"`.
  - Лимиты считаются по-разному: на запросы или на число товаров в запросе/ответе (`x-resource-limit-config.path`).
  - Ограничения по датам: в одном запросе статистики не больше 200 заказов, окно заказов кабинета — не больше 30 дней.
  - Генерация отчётов: 1 запрос в 1–2 минуты.

## Методы, которые нам нужны

Лимиты указаны для уровня `none` / `medium`. В спецификации два уровня, по чему продавец попадает в `medium`, из неё не ясно. Рассчитываем на `none`.

| Задача | Метод | Лимит | Заметки |
|---|---|---|---|
| Кабинет и магазины | `GET /v2/campaigns` | 1000/ч | `businessId`, `campaignId`, модель работы |
| Настройки кабинета | `POST /v2/businesses/{businessId}/settings` | — | `onlyDefaultPrice`: `true` значит, что цены можно задавать только для всего кабинета |
| Каталог | `POST /v2/businesses/{businessId}/offer-mappings` | 100/мин | `offerId`, название, `marketCategoryId`, габариты (`weightDimensions`), `basicPrice`, **`purchasePrice` (себестоимость)**, `additionalExpenses`, `marketSku` |
| Цены кабинета (чтение) | `POST /v2/businesses/{businessId}/offer-prices` | 5000 тов./мин | `value`, `discountBase` (зачёркнутая), `minimumForBestseller`, `excludedFromBestsellers`, `updatedAt` |
| Цены кабинета (запись) | `POST /v2/businesses/{businessId}/offer-prices/updates` | 10 000 тов./мин | `{offers:[{offerId, price:{value, currencyId:"RUR", discountBase?, minimumForBestseller?}}]}`. Применяется до нескольких минут |
| Цены магазина | `POST /v2/campaigns/{campaignId}/offer-prices[/updates]` | — | Только при `onlyDefaultPrice=false`. `GET .../offer-prices` устарел |
| Карантин цен | `POST /v2/businesses/{businessId}/price-quarantine`, `.../confirm` | 5000/мин | См. «Риски» |
| Заказы (быстро) | `POST /v1/businesses/{businessId}/orders` | 10 000/ч, 6 параллельно | Без задержки. `items[].prices`: `payment` (деньгами), `cashback` (баллы Плюса), `subsidy` (компенсация продавцу). `GET /v2/campaigns/{id}/orders` устарел |
| Заказы (финансы) | `POST /v2/campaigns/{campaignId}/stats/orders` | 10 000/ч | Задержка до 40 минут. Основной источник для маржи, см. ниже |
| Прогноз комиссий | `POST /v2/tariffs/calculate` | 100/мин | Вход: `campaignId`, `categoryId`, цена, габариты, вес. Выход: услуги по типам в ₽. Расчёт примерный |
| Акции | `POST /v2/businesses/{businessId}/promos`, `.../promos/offers` | 1000/ч, 5000/ч | Статус товара в акции: `AUTO` / `MANUAL` / …, `promoPrice`, `maxPromoPrice` |
| Выход из акции | `POST /v2/businesses/{businessId}/promos/offers/delete` | 5000/ч | `offerIds` или `deleteAllOffers`. Применяется **4–6 часов** |
| Рекомендации цен | `POST /v2/businesses/{businessId}/offers/recommendations` | 50/мин | Порог привлекательной цены, для справки |
| Остатки | `POST /v2/campaigns/{campaignId}/offers/stocks` | — | Для витрины остатков, вне задачи цен |
| Отчёты | `POST /v2/reports/goods-prices/generate`, `united-netting`, `united-marketplace-services` + `GET /v2/reports/info/{reportId}` | 1 за 1–2 мин | Асинхронно. Для P&L, на потом |

## Как собрать таблицу «Разбор цены» для ЯМ

| Колонка | Источник |
|---|---|
| Артикул поставщика | `offerId` |
| Цена зачёркнутая | `offer-prices` → `price.discountBase` |
| Цена со скидкой (цена продавца) | `offer-prices` → `price.value` |
| Скидка продавца | `1 − value / discountBase` |
| Скидка маркетплейса | Из последних заказов `stats/orders`, медиана по товару: цена продавца − `prices[type=BUYER].costPerItem`. Разбивка: `CASHBACK` — баллы Плюса, `MARKETPLACE` — купоны, `cofinanceValue` — скидка с Маркетом |
| Цена для покупателя | `prices[type=BUYER].costPerItem` из последних заказов, без заказов — «нет данных» |
| Себестоимость | Наша таблица, с фолбэком на `purchasePrice` из каталога ЯМ |
| Комиссии | Факт: `stats/orders` → `commissions[]` по типам (`FEE`, `DELIVERY_TO_CUSTOMER`, `AGENCY`, `PAYMENT_TRANSFER`, `LOYALTY_PARTICIPATION_FEE`, `AUCTION_PROMOTION`, `SORTING`, …). Прогноз для целевой цены: `tariffs/calculate` |
| Маржа | Цена продавца − комиссии − себестоимость, как у WB и Ozon |

Тонкость: `subsidies[]` в `stats/orders` — это **баллы, которые уменьшают стоимость размещения**, а не деньги на счёт. `YANDEX_CASHBACK` / `SUBSIDY` / `DELIVERY` учитываем как уменьшение комиссий, а не как выручку. Проверить на реальных заказах заказчика.

## Рычаги для «удержания цены»

1. **Своя цена** не меняется Маркетом. В отличие от WB, ЯМ не переписывает `price.value`. Итоговая цена для покупателя уменьшается за счёт:
   - баллов Плюса и купонов (за счёт Маркета);
   - акций, в которые товар попал автоматически (`AUTO` / `PARTIALLY_AUTO`, цена `promoPrice`);
   - «Бестселлеров Маркета».
2. **Акции:** раз в цикл смотреть `promos/offers` по текущим акциям. Товары со статусом `AUTO`, `PARTIALLY_AUTO` или `RENEWED` и `promoPrice` ниже порога заказчика убирать через `promos/offers/delete`. Для «Бестселлеров» не передавать `minimumForBestseller`: без него товар не попадёт в акцию этим способом.
3. **Компенсация баллов и купонов** (режим «держать цену для покупателя») — подъёмом `price.value` через `offer-prices/updates`. Опасна из-за карантина, см. ниже.

## Риски и открытые вопросы

- **Карантин цен.** Если цена меняется слишком резко или сильно отличается от рыночной (`PRICE_CHANGE`, `LOW_PRICE`, `LOW_PRICE_PROMO`), товар уходит в карантин и **скрывается с витрины**, пока цену не подтвердят.
  - Репрайсер должен менять цену мелкими шагами.
  - После каждой записи проверять `price-quarantine`.
  - Автоподтверждение (`confirm`) делать только для цен, которые выставили мы сами и которые укладываются в коридор правила. Остальное — алерт в Telegram.
- **Автодобавление в акции.** В спецификации не сказано явно, можно ли через `promos/offers/delete` убрать товар, добавленный автоматически. Проверить на реальном кабинете. Отключение автоучастия целиком в API не нашлось, вероятно, только в кабинете.
- **Выход из акции применяется 4–6 часов**, цена — несколько минут. Значит, удержание цены в ЯМ медленнее, чем в Ozon.
- **`onlyDefaultPrice`.** Если у заказчика несколько магазинов (FBS + FBY) с разными ценами, пишем цены на уровне магазина. Узнать у заказчика или прочитать из настроек.
- **Устаревшие поля.** `offer.category` и `customsCommodityCode` отключаются 2026-10-12 (уже прошло). Используем `marketCategoryId`.
- **Уровни лимитов `none` / `medium`.** Неясно, как продавец попадает в `medium`. Закладываемся на `none`.

## Что сделать в коде (уточнение этапа 4)

1. **Клиент и инфраструктура:**
   - `collectors/ym/endpoints.py`, `client.py`, `parsers.py` по образцу `collectors/ozon/`.
   - `JsonHttpClient(marketplace="ym")` с ретраем 420.
   - Пагинация по `pageToken` / `nextPageToken`.
2. **Ключи:** env `YM_API_KEY` (read-only), `YM_API_KEY_PRICING`, `YM_BUSINESS_ID`, `YM_ACCOUNT_ID`, плюс валидация в `common/env_validation.py`.
3. **History store:** снимок каталога ЯМ (repo `product`): `offer-mappings` + `offer-prices` + статус в акциях. Это даёт diff цен «было / стало» бесплатно.
4. **Заказы:**
   - `stats/orders` → `raw_ym_orders_stats` → `stg_orders` / `stg_sales`. Цены по типам, комиссии, субсидии.
   - Инкрементально по `updateFrom` / `updateTo`, окно 30 дней.
5. **Маркетплейс в системе:** `ym` в паттернах `^(wb|ozon)$` по всему API, в `dim_account`, `dim_product` (sync из history), в UI-переключателях.
6. **Запись:** `YmActionsClient` в [collectors/marketplace_actions.py](../collectors/marketplace_actions.py): `set_price(offer_id, price, discount_base)`, `remove_from_promo(promo_id, offer_ids)`, `quarantine()` / `confirm()`.
7. **Тесты:** парсеры на фикстурах из примеров спецификации, 420-ретрай, пагинация.
