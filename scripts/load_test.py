#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def create_request(url: str, api_key: str, payload: dict) -> urllib.request.Request:
    data = json.dumps(payload).encode("utf-8")
    return urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "vLLM-LoadTest/1.0",
        },
    )


def send_streaming_request(
    url: str,
    api_key: str,
    payload: dict,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    req = create_request(url, api_key, payload)
    t_start = time.perf_counter()
    t_first_token: Optional[float] = None
    output_tokens = 0
    full_text = []

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    usage = chunk.get("usage")
                    if usage and isinstance(usage, dict) and "completion_tokens" in usage:
                        output_tokens = usage["completion_tokens"]
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        if t_first_token is None:
                            t_first_token = time.perf_counter()
                        if not usage:
                            output_tokens += 1
                        full_text.append(content)
                except json.JSONDecodeError:
                    continue

        t_end = time.perf_counter()
        e2e_latency = t_end - t_start
        ttft = (t_first_token - t_start) if t_first_token is not None else e2e_latency

        return {
            "success": True,
            "ttft": ttft,
            "e2e_latency": e2e_latency,
            "output_tokens": output_tokens,
            "error": None,
        }
    except Exception as exc:
        t_end = time.perf_counter()
        return {
            "success": False,
            "ttft": 0.0,
            "e2e_latency": t_end - t_start,
            "output_tokens": 0,
            "error": str(exc),
        }


SHORT_PROMPT = (
    "Ответь кратко на вопрос: какие основные преимущества дает квантование "
    "весов нейросетей при развертывании моделей на CPU?"
)

LONG_PROMPT = (
    "Проанализируй следующий архитектурный контекст развертывания языковых моделей на CPU:\n"
    "Инференс больших языковых моделей (LLM) в среде центрального процессора (CPU) требует "
    "тщательной оптимизации работы с многоуровневым кэшем памяти и векторными инструкциями. "
    "В отличие от графических ускорителей (GPU) с высокой пропускной способностью HBM-памяти "
    "(до нескольких терабайт в секунду), пропускная способность оперативной памяти DDR4/DDR5 "
    "существенно ниже (от 50 до 100 ГБ/с на канал). Это делает фазу декодирования (autoregressive decode) "
    "строго ограниченной по скорости чтения памяти (memory-bound). "
    "В то же время фаза предварительного заполнения (prefill) характеризуется интенсивными "
    "матричными вычислениями над плотными тензорами (compute-bound) и может эффективно масштабироваться "
    "за счет использования инструкций AVX-512, AMX и оптимизированных библиотек BLAS, таких как Intel oneDNN "
    "или OpenBLAS. "
    "Для сглаживания задержек и поддержания высокой пропускной способности при обслуживании "
    "нескольких параллельных пользователей применяются техники непрерывного батчинга (continuous batching), "
    "страничного выделения памяти под KV-кэш (PagedAttention), квантования весов до 8-битных и 4-битных "
    "целочисленных форматов (INT8, INT4 AWQ/GPTQ), а также фрагментированного префилла (chunked prefill). "
    "Фрагментированный префилл позволяет дробить длинные входящие промпты на блоки фиксированного размера, "
    "перемежая их с шагами декодирования уже активных запросов. "
    "На основе приведенного текста выдели 3 ключевых фактора, ограничивающих скорость CPU-инференса."
)


def run_benchmark_scenario(
    name: str,
    url: str,
    api_key: str,
    model_name: str,
    prompt_text: str,
    max_tokens: int,
    concurrency: int,
    total_requests: int,
) -> Dict[str, Any]:
    print(f"\n=======================================================")
    print(f"[*] Сценарий: {name}")
    print(f"    Параллельность (Concurrency): {concurrency}")
    print(f"    Всего запросов: {total_requests}")
    print(f"    Длина промпта (символов): {len(prompt_text)}")
    print(f"    Max tokens: {max_tokens}")
    print(f"=======================================================")

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt_text}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    results: List[Dict[str, Any]] = []
    t_bench_start = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(send_streaming_request, url, api_key, payload)
            for _ in range(total_requests)
        ]
        for idx, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            res = fut.result()
            results.append(res)
            status = "OK" if res["success"] else f"ERR ({res['error']})"
            print(
                f"  [{idx}/{total_requests}] Status: {status} | "
                f"TTFT: {res['ttft']*1000:.1f}ms | Latency: {res['e2e_latency']:.2f}s | "
                f"Tokens: {res['output_tokens']}"
            )

    t_bench_total = time.perf_counter() - t_bench_start
    successful = [r for r in results if r["success"]]

    if not successful:
        print("[!] Все запросы завершились ошибкой.")
        return {}

    ttft_list = [r["ttft"] for r in successful]
    latency_list = [r["e2e_latency"] for r in successful]
    total_output_tokens = sum(r["output_tokens"] for r in successful)

    avg_ttft = statistics.mean(ttft_list)
    p50_ttft = statistics.median(ttft_list)
    p95_ttft = sorted(ttft_list)[int(len(ttft_list) * 0.95)] if len(ttft_list) > 1 else max(ttft_list)

    avg_latency = statistics.mean(latency_list)
    p50_latency = statistics.median(latency_list)
    p95_latency = sorted(latency_list)[int(len(latency_list) * 0.95)] if len(latency_list) > 1 else max(latency_list)

    token_throughput = total_output_tokens / t_bench_total if t_bench_total > 0 else 0.0
    request_throughput = len(successful) / t_bench_total if t_bench_total > 0 else 0.0

    stats = {
        "scenario": name,
        "concurrency": concurrency,
        "requests": total_requests,
        "success_rate": f"{len(successful)}/{total_requests}",
        "avg_ttft_ms": round(avg_ttft * 1000, 1),
        "p50_ttft_ms": round(p50_ttft * 1000, 1),
        "p95_ttft_ms": round(p95_ttft * 1000, 1),
        "avg_latency_s": round(avg_latency, 2),
        "p50_latency_s": round(p50_latency, 2),
        "p95_latency_s": round(p95_latency, 2),
        "token_throughput_tok_s": round(token_throughput, 2),
        "req_throughput_rps": round(request_throughput, 2),
        "total_time_s": round(t_bench_total, 2),
    }

    print(f"\n--- Итоги сценария: {name} ---")
    print(f"  TTFT (avg / p50 / p95): {stats['avg_ttft_ms']} ms / {stats['p50_ttft_ms']} ms / {stats['p95_ttft_ms']} ms")
    print(f"  Latency (avg / p50 / p95): {stats['avg_latency_s']} s / {stats['p50_latency_s']} s / {stats['p95_latency_s']} s")
    print(f"  Throughput (Tokens): {stats['token_throughput_tok_s']} tok/s")
    print(f"  Throughput (RPS):    {stats['req_throughput_rps']} req/s")
    print(f"  Total Duration:      {stats['total_time_s']} s")

    return stats


def main():
    parser = argparse.ArgumentParser(description="vLLM CPU Load Testing Tool")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/v1/chat/completions",
        help="vLLM chat completions URL",
    )
    parser.add_argument(
        "--api-key",
        default="sk-local-secret-token-2026",
        help="Bearer API key",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3.5-0.8B",
        help="Model ID",
    )
    args = parser.parse_args()

    print("[*] Проверка доступности сервиса...")
    try:
        health_req = urllib.request.Request("http://localhost:8000/health")
        with urllib.request.urlopen(health_req, timeout=5) as resp:
            if resp.status == 200:
                print("  [+] Эндпоинт доступен и готов к нагрузке (HTTP 200 OK).")
    except Exception as e:
        print(f"  [!] Ошибка связи с эндпоинтом: {e}")
        return

    scenarios = [
        {
            "name": "Короткие промпты (C=1, 4 запроса)",
            "prompt": SHORT_PROMPT,
            "max_tokens": 32,
            "concurrency": 1,
            "total_requests": 4,
        },
        {
            "name": "Короткие промпты (C=2, 4 запроса)",
            "prompt": SHORT_PROMPT,
            "max_tokens": 32,
            "concurrency": 2,
            "total_requests": 4,
        },
        {
            "name": "Длинные промпты (C=1, 2 запроса)",
            "prompt": LONG_PROMPT,
            "max_tokens": 64,
            "concurrency": 1,
            "total_requests": 2,
        },
        {
            "name": "Длинные промпты (C=2, 2 запроса)",
            "prompt": LONG_PROMPT,
            "max_tokens": 64,
            "concurrency": 2,
            "total_requests": 2,
        },
    ]

    all_stats = []
    for sc in scenarios:
        st = run_benchmark_scenario(
            name=sc["name"],
            url=args.url,
            api_key=args.api_key,
            model_name=args.model,
            prompt_text=sc["prompt"],
            max_tokens=sc["max_tokens"],
            concurrency=sc["concurrency"],
            total_requests=sc["total_requests"],
        )
        if st:
            all_stats.append(st)

    print("\n\n" + "=" * 80)
    print("ИТОГОВАЯ СВОДНАЯ ТАБЛИЦА НАГРУЗОЧНОГО ТЕСТИРОВАНИЯ (MARKDOWN)")
    print("=" * 80)
    print(
        "| Сценарий тестирования | Concurrency | Запросы | TTFT (avg, мс) | TTFT (p50, мс) | "
        "Latency (avg, с) | Latency (p50, с) | Throughput (tok/s) | Throughput (RPS) |"
    )
    print(
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    )
    for s in all_stats:
        print(
            f"| {s['scenario']} | {s['concurrency']} | {s['requests']} | "
            f"{s['avg_ttft_ms']} | {s['p50_ttft_ms']} | "
            f"{s['avg_latency_s']} | {s['p50_latency_s']} | "
            f"**{s['token_throughput_tok_s']}** | {s['req_throughput_rps']} |"
        )
    print("=" * 80)


if __name__ == "__main__":
    main()
