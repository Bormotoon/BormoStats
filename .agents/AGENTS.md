# BormoStats — Session Memory

## Goal
- Проанализировать всех конкурентов BormoStats (аналитика WB/Ozon) и составить подробный список их функций, которых нет у нас
- BormoStats — единственный self-hosted продукт на рынке; все 19 аналогов — SaaS

## Source of Truth
- `/home/borm/VibeCoding/BormoStats/competitors-analysis.md` — полный анализ всех 19 конкурентов с детальным описанием функций каждого
- Настройки opencode: `/home/borm/VibeCoding/BormoStats/opencode.json`

## Environment & Tools
- Tavily MCP-server подключён в `opencode.json` с ключом `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` — используется как основной источник поиска
- Встроенный websearch выдаёт 403; Tavily — рабочая альтернатива

## Key Decisions
- Все данные собраны в единый `competitors-analysis.md` вместо нескольких файлов
- Ответы на русском языке

## Key Findings
- **Топ-конкуренты (детально разобраны):** MPSTATS, MarketGuru, SalesFinder, SellerStats, Moneyplace, Маяк, Shopstat, LikeStats, SellerFox, Ёж, Priceva, SelSup, EcomPlatform
- **Остальные:** Stat4Market, Sellmonitor, Eggheads, Topseller, Модульселлер, Market Vision
- **Основные гэпы BormoStats:** внешняя аналитика (категории, бренды, поисковые запросы), финансовая аналитика (P&L, юнит-экономика, ABC-XYZ), автоматизация (репрайсер, биддер), поддержка Яндекс Маркет

## Relevant Files
- `competitors-analysis.md` — обзор 19 аналогов с гэп-анализом
- `opencode.json` — конфигурация с MCP Tavily
