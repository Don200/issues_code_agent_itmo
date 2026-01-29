# SDLC Agent System

Автоматизированная агентная система для полного цикла разработки ПО (SDLC) внутри GitHub.

## Обзор

Система имитирует работу разработчика и ревьюера:
- Анализирует задачи из GitHub Issues
- Генерирует код и вносит изменения
- Создаёт Pull Requests
- Запускает CI/CD
- Выполняет автоматический code review
- Итеративно исправляет код до получения корректного результата

```
┌─────────┐    ┌──────────────┐    ┌─────────────┐    ┌────────────────┐
│  Issue  │───▶│  Code Agent  │───▶│     PR      │───▶│   CI/CD        │
│ Created │    │  (generates  │    │   Created   │    │   Pipeline     │
└─────────┘    │   code)      │    └─────────────┘    └───────┬────────┘
               └──────────────┘                               │
                      ▲                                       ▼
                      │                              ┌─────────────────┐
                      │         ┌────────────────────│  AI Reviewer    │
                      │         │  (if changes       │  Agent          │
                      │         │   requested)       └─────────────────┘
                      └─────────┘
```

## Быстрый старт

### Требования

- Python 3.11+
- Docker & Docker Compose
- GitHub Token с правами на репозиторий
- API ключ OpenAI или YandexGPT

### Установка

1. **Клонируйте репозиторий:**
```bash
git clone https://github.com/your-org/sdlc-agent.git
cd sdlc-agent
```

2. **Настройте переменные окружения:**
```bash
cp .env.example .env
# Отредактируйте .env и добавьте ваши ключи
```

3. **Запуск через Docker:**
```bash
docker-compose up -d
```

4. **Или локальная установка:**
```bash
pip install -e ".[dev]"
```

## Использование

### CLI команды

```bash
# Обработать Issue и создать PR
sdlc-agent process 42

# Провести review PR
sdlc-agent review 123 --issue 42

# Проверить статус PR и получить рекомендацию
sdlc-agent check 123 --issue 42

# Запустить полный цикл с автофиксами
sdlc-agent run-cycle 42 123 --max-iterations 5

# Показать конфигурацию
sdlc-agent config
```

### GitHub Actions

Система автоматически запускается при:

1. **Создании Issue** с меткой `agent` или `auto`:
   - Code Agent анализирует Issue
   - Генерирует код
   - Создаёт Pull Request

2. **Создании/обновлении PR**:
   - AI Reviewer анализирует изменения
   - Проверяет результаты CI
   - Публикует review
   - При необходимости запускает цикл исправлений

### Пример Issue

```markdown
## Описание
Добавить эндпоинт для получения списка пользователей

## Требования
- GET /api/users возвращает список пользователей
- Поддержка пагинации (limit, offset)
- Фильтрация по статусу (active, inactive)

## Acceptance Criteria
- Возвращает JSON с массивом пользователей
- Пустой массив если пользователей нет
- Правильная обработка невалидных параметров

## Файлы
- `src/api/routes.py`
- `src/api/schemas.py`
```

## Конфигурация

### Переменные окружения

| Переменная | Описание | Обязательная |
|------------|----------|--------------|
| `GITHUB_TOKEN` | GitHub API токен | Да |
| `GITHUB_REPOSITORY` | Репозиторий (owner/repo) | Да |
| `LLM_PROVIDER` | Провайдер LLM (openai/yandex) | Нет (default: openai) |
| `OPENAI_API_KEY` | Ключ OpenAI API | Если provider=openai |
| `YANDEX_API_KEY` | Ключ YandexGPT API | Если provider=yandex |
| `YANDEX_FOLDER_ID` | Yandex Cloud Folder ID | Если provider=yandex |
| `MAX_ITERATIONS` | Макс. итераций исправлений | Нет (default: 5) |

### GitHub Repository Secrets

Добавьте в Settings → Secrets → Actions:
- `OPENAI_API_KEY` или `YANDEX_API_KEY`/`YANDEX_FOLDER_ID`

### GitHub Repository Variables

Добавьте в Settings → Variables → Actions:
- `LLM_PROVIDER` - провайдер LLM
- `MAX_ITERATIONS` - максимум итераций

## Архитектура

```
src/
├── agents/
│   ├── code_agent.py      # Генерация кода
│   └── reviewer_agent.py  # Code review
├── core/
│   ├── config.py          # Конфигурация
│   ├── state_machine.py   # Жизненный цикл Issue
│   └── exceptions.py      # Исключения
├── github/
│   ├── client.py          # GitHub API клиент
│   ├── issue_parser.py    # Парсинг Issue
│   └── pr_manager.py      # Управление PR
├── llm/
│   └── gateway.py         # Интерфейс к LLM
├── prompts/
│   └── templates.py       # Промпты для LLM
└── cli.py                 # CLI интерфейс
```

## Разработка

### Запуск тестов

```bash
# Все тесты
pytest tests/ -v

# С покрытием
pytest tests/ -v --cov=src --cov-report=html

# Конкретный тест
pytest tests/test_issue_parser.py -v
```

### Линтинг

```bash
# Ruff
ruff check src/ tests/

# Black
black src/ tests/

# MyPy
mypy src/
```

### Docker

```bash
# Сборка образа
docker-compose build

# Запуск тестов в контейнере
docker-compose run test

# Линтинг в контейнере
docker-compose run lint
```

## Лицензия

MIT License
