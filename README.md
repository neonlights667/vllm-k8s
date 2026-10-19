# Инференс Qwen3.5-0.8B на vLLM (CPU) в Minikube

Конфигурация для запуска [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) через **vLLM (`v0.31.0`)** на CPU в локальном кластере Minikube. Манифесты и контейнеры настроены под rootless-режим, кэширование весов на PVC, Kustomize-деплой и маскирование чувствительных данных в логах.

## Что внутри и почему так устроено

```text
.
├── docker/
│   ├── downloader/          # initContainer для скачивания весов с Hugging Face
│   │   ├── Dockerfile       # rootless сборка на базе python:3.11-slim
│   │   ├── requirements.txt # зафиксированные зависимости (huggingface-hub и др.)
│   │   └── download_model.py # скрипт атомарной загрузки и проверки артефактов
│   └── vllm/                # основной образ vLLM CPU
│       ├── Dockerfile       # rootless сборка vLLM v0.31.0 под CPU
│       ├── requirements.txt # зафиксированные зависимости vLLM CPU (pip check)
│       ├── logging_config.json # конфигурация Python logging dictConfig
│       ├── privacy_filter.py # фильтр маскирования промптов и ответов
│       ├── auth_middleware.py # ASGI Middleware для строгой авторизации всех путей
│       └── entrypoint.sh    # запуск vllm serve с защитой параметров
├── k8s/                     # манифесты под Kustomize
│   ├── kustomization.yaml   # сборка всех ресурсов одной командой
│   ├── namespace.yaml       # неймспейс llm-inference с Pod Security restricted
│   ├── pvc.yaml             # PersistentVolumeClaim (5Gi) под веса модели
│   ├── configmap.yaml       # параметры рантайма vLLM и OpenMP
│   ├── secret.yaml          # токены HF_TOKEN и VLLM_API_KEY
│   ├── deployment.yaml      # Deployment (initContainer + vLLM CPU + health probes)
│   ├── service.yaml         # ClusterIP сервис (порт 8000)
│   └── networkpolicy.yaml   # сетевая изоляция (ingress 8000, egress 53/443)
└── scripts/
    ├── download_model.sh    # bash-обертка для ручного скачивания весов
    └── load_test.py         # нагрузочное тестирование (TTFT, Latency, Throughput)
```

Особенности архитектуры:

* **Модель и CPU-режим.** Выбрана [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) в `bfloat16`. В линейке Qwen 3.5 есть мультимодальный энкодер и рассуждения (`<think>`), поэтому в `entrypoint.sh` переданы флаги `--language-model-only` (не расходует память на визуальные блоки), `--enforce-eager` и `--default-chat-template-kwargs '{"enable_thinking": false}'`. Это экономит оперативную память и ускоряет инференс на CPU.
* **Кэширование весов (initContainer + PVC).** Загрузка вынесена из основного контейнера в отдельный легковесный `initContainer` (`model-downloader`). При первом старте он скачивает безопасные файлы (`*.safetensors`, конфиги и токенизатор, без `pickle`/`.bin`) во временную директорию на PVC, валидирует целостность, атомарно публикует папку и ставит маркер `.download_complete`. При повторных стартах пода скрипт находит маркер и сразу завершает работу. Контейнер vLLM монтирует том в режиме `readOnly: true` и работает с `HF_HUB_OFFLINE=1`.
* **Безопасность.** Контейнеры запускаются от непривилегированного пользователя `UID/GID 1000` с `readOnlyRootFilesystem: true`, сброшенными возможностями (`drop: ["ALL"]`) и профилем `seccomp: RuntimeDefault` (неймспейс размечен под политику Pod Security `restricted`). Вместо флага `--api-key` (раскрывающего токен в `ps aux`) написан легковесный ASGI-middleware (`auth_middleware.py`): он читает `VLLM_API_KEY` из окружения, сравнивает токен через `secrets.compare_digest` за константное время и закрывает все эндпоинты, кроме `/health` (для зондов Kubernetes). Также настроена `NetworkPolicy` и валидация аргументов в `entrypoint.sh`, защищающая от переопределения флагов через `ConfigMap`.
* **Приватность логов.** Включен `--enable-log-requests`, но через `VLLM_LOGGING_CONFIG_PATH` подключен фильтр `privacy_filter.py`. В консоль попадает сам факт обращения (`request_id`, параметры сэмплирования, статус ответа в `uvicorn.access`), а пользовательский промпт, сгенерированный текст, массивы `prompt_token_ids` и токены авторизации заменяются на `[REDACTED]`. Запросы от зондов Kubernetes к `/health` исключены из логов доступа, чтобы не засорять вывод.
* **Воспроизводимость окружения.** Базовые образы в обоих `Dockerfile` зафиксированы по SHA256-дайджесту. Зависимости жестко закреплены в `requirements.txt` с проверкой через `pip check`.

## Быстрый старт в Minikube

Для работы инференса на CPU требуется минимум 4 ядра и 8 ГБ оперативной памяти.

1. Запускаем Minikube с плагином Calico (он нужен для реальной работы правил `NetworkPolicy`):
   ```bash
   minikube start --cpus 4 --memory 8192 --cni=calico
   ```

2. Переключаем Docker CLI на демон внутри Minikube, чтобы использовать локальные образы без внешнего реестра:
   ```bash
   # Linux / macOS
   eval $(minikube -p minikube docker-env)

   # Windows (PowerShell)
   minikube -p minikube docker-env --shell powershell | Invoke-Expression
   ```

3. Собираем образы:
   ```bash
   docker build -t model-downloader:0.1.0 ./docker/downloader
   docker build -t vllm-cpu:0.1.0 ./docker/vllm
   ```

4. При необходимости обновляем секреты. Для модели `Qwen/Qwen3.5-0.8B` токен Hugging Face не требуется (репозиторий открытый), а ключ API по умолчанию в `k8s/secret.yaml` задан как `sk-local-secret-token-2026`:
   ```bash
   kubectl create secret generic vllm-secrets -n llm-inference \
     --from-literal=HF_TOKEN="" \
     --from-literal=VLLM_API_KEY="sk-local-secret-token-2026" \
     --dry-run=client -o yaml > k8s/secret.yaml
   ```

5. Разворачиваем все компоненты через Kustomize:
   ```bash
   kubectl apply -k ./k8s
   ```

При первом старте под находится в статусе `Init:0/1`, пока `model-downloader` скачивает веса модели (~1.6 ГБ). Отслеживать логи можно командами:
```bash
kubectl logs -n llm-inference deployment/vllm-server -c model-downloader -f
kubectl logs -n llm-inference deployment/vllm-server -c vllm -f
```

## Проверка работоспособности

Пробрасываем порт сервиса:
```bash
kubectl port-forward -n llm-inference svc/vllm-service 8000:8000
```

Проверяем блокировку неавторизованных запросов (`401 Unauthorized`) и успешный ответ с Bearer-токеном:
```bash
curl -i http://localhost:8000/v1/models

curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-local-secret-token-2026" \
  -d '{
    "model": "Qwen/Qwen3.5-0.8B",
    "messages": [{"role": "user", "content": "Назови столицу Франции одним словом."}],
    "max_tokens": 32,
    "temperature": 0.0
  }'
```

Проверяем логи контейнера `vllm`: текст промпта и сгенерированный ответ скрыты:
```bash
kubectl logs -n llm-inference deployment/vllm-server -c vllm --tail=20
# [INFO] vllm: Received request chatcmpl-9f8a12: prompt: '[REDACTED]', params: SamplingParams(...), prompt_token_ids: [REDACTED], lora_request: None.
# [INFO] uvicorn.access: 127.0.0.1:41234 - "POST /v1/chat/completions HTTP/1.1" 200 OK
```

Проверяем работу кэша при рестарте: повторное скачивание из сети не выполняется:
```bash
kubectl rollout restart deployment/vllm-server -n llm-inference
kubectl rollout status deployment/vllm-server -n llm-inference
kubectl logs -n llm-inference deployment/vllm-server -c model-downloader
# INFO: Model 'Qwen/Qwen3.5-0.8B' found in local cache (/models/Qwen--Qwen3.5-0.8B). Skipping network download.
```

## Настройки конфигурации

Параметры инференса задаются в `k8s/configmap.yaml` и применяются без пересборки образов:

| Параметр | Источник | Значение по умолчанию | Назначение |
| :--- | :--- | :--- | :--- |
| `MODEL_ID` | `ConfigMap` | `Qwen/Qwen3.5-0.8B` | Репозиторий модели на Hugging Face |
| `MODEL_CACHE_DIR` | `ConfigMap` | `/models` | Каталог монтирования тома PVC |
| `DTYPE` | `ConfigMap` | `bfloat16` | Формат вычислений на CPU |
| `MAX_MODEL_LEN` | `ConfigMap` | `2048` | Максимальный контекст модели |
| `VLLM_CPU_KVCACHE_SPACE` | `ConfigMap` | `1` | Объем памяти под KV-кэш (ГБ) |
| `OMP_NUM_THREADS` | `ConfigMap` | `3` | Количество потоков OpenMP |
| `VLLM_CPU_OMP_THREADS_BIND` | `ConfigMap` | `nobind` | Без привязки к NUMA (для rootless) |
| `KMP_BLOCKTIME` | `ConfigMap` | `0` | Время удержания потоков OpenMP перед сном (мс) |
| `EXTRA_ARGS` | `ConfigMap` | `"--max-num-seqs 16"` | Лимит параллельных последовательностей |
| `HOST` / `PORT` | `ConfigMap` | `0.0.0.0` / `8000` | Хост и порт сервиса |
| `HF_TOKEN` | `Secret` | `""` | Токен Hugging Face для закрытых моделей |
| `VLLM_API_KEY` | `Secret` | `sk-local-secret-token-2026` | Bearer-токен для авторизации клиентов |

## Нагрузочное тестирование

Для тестирования подготовлен автономный скрипт [scripts/load_test.py](./scripts/load_test.py) без сторонних библиотек. Он отправляет потоковые запросы (`stream: true`), фиксирует время до первого токена (TTFT), полную задержку ответа (Latency) и сквозную пропускную способность (Throughput):

```bash
python scripts/load_test.py --url http://localhost:8000/v1/chat/completions --api-key sk-local-secret-token-2026
```

Результаты замеров на 4 ядрах CPU и лимите памяти 8 ГБ:

| Сценарий | Concurrency | Запросов | TTFT avg (мс) | TTFT p50 (мс) | Latency avg (с) | Latency p50 (с) | Throughput (tok/s) | RPS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Короткие промпты (~30 токенов, `max_tokens=32`) | 1 | 4 | 2579.9 | 2628.6 | 5.85 | 6.05 | 5.47 | 0.17 |
| Короткие промпты (~30 токенов, `max_tokens=32`) | 2 | 4 | 4170.8 | 4114.5 | 10.50 | 10.48 | 6.08 | 0.19 |
| Длинные промпты (~500 токенов, `max_tokens=64`) | 1 | 2 | 21513.9 | 21513.9 | 28.45 | 28.45 | 2.25 | 0.04 |
| Длинные промпты (~500 токенов, `max_tokens=64`) | 2 | 2 | 42181.2 | 42181.2 | 55.12 | 55.12 | 2.32 | 0.04 |

На коротких запросах при росте параллельности с 1 до 2 за счет непрерывного батчинга (continuous batching) общая пропускная способность возрастает с 5.47 до 6.08 tok/s. На длинных промптах время до первого токена увеличивается до ~21.5 с из-за вычислительной нагрузки на фазе prefill.

## Аналитика: параметры vLLM для роста Throughput

На CPU фаза предварительного заполнения (prefill) ограничена вычислительной мощностью процессорных ядер, а фаза декодирования (decode) упирается в скорость чтения данных из оперативной памяти. Конфигурация подбирается под характер входящего потока.

### Случай А: большой поток запросов с коротким контекстом

Фаза prefill короткая, расход KV-кэша минимален. Основная задача: объединять больше запросов в один шаг декодирования, чтобы считывать веса модели из оперативной памяти один раз на группу последовательностей:
* **Увеличить `--max-num-seqs` (до 32–64).** Позволяет планировщику обрабатывать больше параллельных запросов в едином батче.
* **Увеличить `--max-num-batched-tokens` (до 2048–4096).** Несколько коротких входящих промптов будут обрабатываться за одну итерацию prefill.
* **Включить `--enable-prefix-caching`.** При наличии общего системного промпта vLLM переиспользует уже вычисленный KV-кэш, исключая повторные вычисления.
* **Уменьшить `--block-size` (до 16).** Меньший размер блока в PagedAttention снижает неиспользуемые остатки памяти при частых коротких запросах.
* **Настроить параметры OpenMP (`KMP_BLOCKTIME=0`, `OMP_NUM_THREADS`).** Нулевой интервал `KMP_BLOCKTIME` исключает холостое ожидание (spin-wait) вычислительных потоков, освобождая процессорные ресурсы для асинхронного цикла Uvicorn.

### Случай Б: небольшое число запросов с большим контекстом

Один длинный запрос занимает вычислительные ядра на десятки секунд, а объемный KV-кэш быстро исчерпывает оперативную память:
* **Включить `--enable-chunked-prefill` и ограничить `--max-num-batched-tokens` (до 256–512).** Длинный входящий промпт делится на фрагменты фиксированного размера, которые чередуются с шагами генерации токенов для других активных задач. Это предотвращает блокировку сервера.
* **Снизить `--max-num-seqs` (до 2–4) и увеличить `VLLM_CPU_KVCACHE_SPACE`.** Предотвращает нехватку памяти под KV-кэш и исключает сброс активных последовательностей (preemption/swapping), приводящий к резкому падению пропускной способности.
* **Использовать квантование KV-кэша (`--kv-cache-dtype fp8` или `int8`).** Снижает объем памяти под контекст вдвое и уменьшает нагрузку на шину оперативной памяти.
* **Ограничить `--max-model-len` реальной потребностью сценария.** Исключает резервирование избыточных структур под максимальную длину контекста модели.

## Удаление ресурсов

```bash
kubectl delete -k ./k8s
```
