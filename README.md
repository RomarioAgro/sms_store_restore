# SMS Store Restore

Небольшой HTTPS-сервер на Python для приема, хранения, выдачи и удаления сообщений.

## Возможности

- `POST /messages` сохраняет сообщение в SQLite
- `GET /messages` возвращает сообщения по `chat_id` и времени
- `DELETE /messages` удаляет сообщения по `message_id` или временному диапазону
- Авторизация через `Authorization: Bearer <token>`
- Логи пишутся в папку `logs/`, которая создается автоматически при старте

## Формат сообщения

```json
{
  "chat_id": "phone-123",
  "text": "hello"
}
```

## Формат времени

Все временные значения используются в UTC ISO-8601, например:

```text
2026-05-05T08:30:00Z
```

## Запуск

Установить зависимости:

```bash
pip install -r requirements.txt
```

Задать токен:

```powershell
$env:SMS_STORE_TOKEN="very-long-secret-token"
```

Запустить сервер:

```bash
SSL_CERTFILE=./certs/server.crt SSL_KEYFILE=./certs/server.key python app.py
```

Или через `make`:

```bash
make cert-ca
make run-server
```

Скрипт `make cert-ca` создаст:

- `certs/ca.crt` - корневой CA
- `certs/ca.key` - ключ CA
- `certs/server.crt` - сертификат сервера для `195.208.118.32`
- `certs/server.key` - ключ сервера

Если нужно выпустить сертификат для другого IP, можно переопределить переменную:

```bash
make cert-ca SERVER_IP=195.208.118.32
```

## Доверие на iPhone

Чтобы iPhone доверял серверу, нужно установить не `server.crt`, а `ca.crt`.

Порядок:

1. Скопировать `certs/ca.crt` на iPhone
2. Установить его как профиль сертификата
3. Открыть `Настройки`
4. Перейти в `Основные`
5. Открыть `Об этом устройстве` или `VPN и управление устройством`
6. Найти `Доверие сертификатам`
7. Включить полное доверие для твоего CA

После этого сервер должен открываться по адресу:

```text
https://195.208.118.32:8000
```

## Примеры

Сохранение:

```bash
curl -X POST https://127.0.0.1:8000/messages ^
  -H "Authorization: Bearer very-long-secret-token" ^
  -H "Content-Type: application/json" ^
  -d "{\"chat_id\":\"phone-123\",\"text\":\"hello\"}"
```

Для внешнего доступа по IP:

```bash
curl -X POST https://195.208.118.32:8000/messages ^
  -H "Authorization: Bearer very-long-secret-token" ^
  -H "Content-Type: application/json" ^
  -d "{\"chat_id\":\"phone-123\",\"text\":\"hello\"}"
```

Получение:

```bash
curl "https://127.0.0.1:8000/messages?chat_id=phone-123&from=2026-05-05T00:00:00Z&to=2026-05-06T00:00:00Z" ^
  -H "Authorization: Bearer very-long-secret-token"
```

Удаление по `message_id`:

```bash
curl -X DELETE "https://127.0.0.1:8000/messages?message_id=1" ^
  -H "Authorization: Bearer very-long-secret-token"
```

Удаление по времени:

```bash
curl -X DELETE "https://127.0.0.1:8000/messages?from=2026-05-05T00:00:00Z&to=2026-05-06T00:00:00Z" ^
  -H "Authorization: Bearer very-long-secret-token"
```

## Логи

- Файл логов: `logs/app.log`
- Папка `logs` создается автоматически, если ее нет
- Если в текущем окружении нельзя писать в корень проекта, можно задать запасной путь через `SMS_STORE_FALLBACK_LOG_DIR`

## Импорт тестовых данных

Для загрузки строк из `data_for_test.txt` в SQLite:

```bash
python import_data.py data_for_test.txt
```

Формат строки:

```text
"chat_id":"text"
```

## Локальный тест сервера

Скрипт читает `data_for_test.txt`, отправляет записи в API и проверяет выборку:

```bash
python test_app.py --token very-long-secret-token
```

Если нужно удалить импортированные записи после проверки:

```bash
python test_app.py --token very-long-secret-token --delete
```

## Клиентский класс

Для обращения к серверу с другого компьютера есть отдельный файл [sms_client.py](/D:/PythonProject/sms_store_restore/sms_client.py).

Пример использования:

```python
from sms_client import SmsStoreClient

client = SmsStoreClient()
message = client.get_last_message_by_chat_id("-1003420941669")
if message is not None:
    result = client.delete_last_message_by_chat_id("-1003420941669")
    print(result.deleted)
```

## Запуск клиента

Есть готовый CLI-скрипт [run_client.py](/D:/PythonProject/sms_store_restore/run_client.py):

```bash
set BASE_URL=https://127.0.0.1:8000
set TOKEN=very-long-secret-token
python run_client.py --chat-id -1003420941669
```

Для доступа по IP:

```bash
set BASE_URL=https://195.208.118.32:8000
set TOKEN=very-long-secret-token
python run_client.py --chat-id -1003420941669
```

Удалить последнее найденное сообщение:

```bash
python run_client.py --chat-id -1003420941669 --delete
```

Через `make`:

```bash
CHAT_ID=-1003420941669 TOKEN=very-long-secret-token make run-client
```

Логирование клиента:

- если передать `logger=` в `SmsStoreClient`, он будет использовать ваш логгер из вызывающего кода
- если `logger=` не передавать, используется `logging.getLogger(__name__)`
- `BASE_URL` и `TOKEN` берутся из переменных окружения, если не переданы явно в конструктор

Исключения клиента:

- `SmsClientHTTPError`
- `SmsClientNetworkError`
- `SmsClientError`

Пример обработки ошибок:

```python
from sms_client import SmsStoreClient, SmsClientError

client = SmsStoreClient()

try:
    result = client.delete_last_message_by_chat_id("-1003420941669")
    print(result.deleted)
except SmsClientError as exc:
    print(f"client error: {exc}")
```
