import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

from scoring import is_correct
from strategies import MAX_ROUNDS, MODEL, REASONING_EFFORT, SAMPLES, STRATEGIES, TEMPERATURE, ModelClient, Usage
from tools import VAGUE_LOOKUP_DESCRIPTION

QUESTIONS_PATH = Path(__file__).parent / "data" / "questions.json"
OUTPUTS = Path(__file__).parent / "outputs"


def load_questions(ids: list[str] | None = None) -> list[dict]:
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    return [q for q in questions if not ids or q["id"] in ids]


def prompt_view(question: dict) -> dict:
    return {key: question[key] for key in ("id", "question", "decimals")}


def answer_question(question: dict, strategy, client: ModelClient, out_dir: Path) -> dict:
    result = strategy(prompt_view(question), client)
    correct = is_correct(result.answer, question)
    unanswered = result.answer is None
    record = {
        "id": question["id"],
        "question": question["question"],
        "expected": {"answer": question["answer"], "value": question["value"], "decimals": question["decimals"]},
        "answer": asdict(result.answer) if result.answer else None,
        "correct": correct,
        "unanswered": unanswered,
        "hit_round_limit": result.hit_round_limit,
        "seconds": round(result.seconds, 3),
        "usage": result.usage.to_dict(),
        "final_text": result.text,
        "trace": result.trace,
    }
    (out_dir / f"{question['id']}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    mark = "✓" if correct else ("–" if unanswered else "✗")
    print(f"  {question['id']} {mark} {record['answer']} in {record['seconds']}s", flush=True)
    return record


def summarize(records: list[dict], label: str, wall_seconds: float, settings: dict) -> dict:
    usage = Usage()
    for record in records:
        usage.add(Usage(**{k: v for k, v in record["usage"].items() if k != "cost_usd"}))
    seconds = [record["seconds"] for record in records]
    return {
        "strategy": label,
        "settings": settings,
        "questions": len(records),
        "correct": sum(record["correct"] for record in records),
        "unanswered": sum(record["unanswered"] for record in records),
        **usage.to_dict(),
        "median_seconds": round(statistics.median(seconds), 3),
        "total_seconds": round(sum(seconds), 3),
        "wall_seconds": round(wall_seconds, 3),
        "per_question": [
            {
                "id": record["id"],
                "correct": record["correct"],
                "unanswered": record["unanswered"],
                "answer": record["answer"],
                "seconds": record["seconds"],
                "input_tokens": record["usage"]["input_tokens"],
                "output_tokens": record["usage"]["output_tokens"],
                "model_calls": record["usage"]["calls"],
                "tool_calls": len(record["trace"].get("tool_calls", [])),
            }
            for record in records
        ],
    }


def run_strategy(key: str, questions: list[dict], out_dir: Path, workers: int, vague: bool) -> dict:
    label, strategy = STRATEGIES[key]
    if vague and key == "s3":
        strategy = partial(strategy, lookup_description=VAGUE_LOOKUP_DESCRIPTION)
    settings = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "reasoning_effort": REASONING_EFFORT,
        "samples": SAMPLES if key == "s2" else 1,
        "max_rounds": MAX_ROUNDS if key == "s3" else None,
        "lookup_description": ("vague" if vague else "full") if key == "s3" else None,
        "workers": workers,
    }
    strategy_dir = out_dir / key
    strategy_dir.mkdir(parents=True, exist_ok=True)
    client = ModelClient()

    print(f"{label} -> {strategy_dir}", flush=True)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(lambda q: answer_question(q, strategy, client, strategy_dir), questions))
    summary = summarize(records, label, time.perf_counter() - start, settings)
    (strategy_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{label}: {summary['correct']}/{summary['questions']} correct, ${summary['cost_usd']}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the three strategies on the HW4 questions.")
    parser.add_argument("--name", required=True, help="output folder inside outputs/, for example run1")
    parser.add_argument("--strategies", nargs="+", choices=list(STRATEGIES), default=list(STRATEGIES))
    parser.add_argument("--questions", nargs="*", help="question ids, default all twenty")
    parser.add_argument("--workers", type=int, default=4, help="questions answered at the same time")
    parser.add_argument("--vague-lookup", action="store_true", help="S3 only: use the one-line lookup description")
    args = parser.parse_args()

    load_dotenv(Path(__file__).parent / ".env")
    questions = load_questions(args.questions)
    for key in args.strategies:
        run_strategy(key, questions, OUTPUTS / args.name, args.workers, args.vague_lookup)


if __name__ == "__main__":
    main()
