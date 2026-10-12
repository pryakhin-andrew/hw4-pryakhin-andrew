import argparse
import json
import statistics
from math import comb
from pathlib import Path

from run import OUTPUTS, load_questions
from scoring import Answer, is_correct
from strategies import SAMPLES, STRATEGIES, Usage


def load_summary(name: str, key: str) -> dict | None:
    path = OUTPUTS / name / key / "summary.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_records(name: str, key: str) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((OUTPUTS / name / key).glob("Q-*.json"))]


def strategy_label(key: str) -> str:
    label = STRATEGIES[key][0]
    return f"{label} (k = {SAMPLES})" if key == "s2" else label


def totals_table(runs: list[str]) -> str:
    lines = [
        "| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for number, name in enumerate(runs, start=1):
        for key in STRATEGIES:
            if s := load_summary(name, key):
                lines.append(
                    f"| {number} | {strategy_label(key)} | {s['correct']} | {s['unanswered']} | {s['input_tokens']:,} "
                    f"| {s['output_tokens']:,} | {s['median_seconds']:.2f} | {s['total_seconds']:.1f} | {s['cost_usd']:.4f} |"
                )
    return "\n".join(lines)


def cost_table(runs: list[str]) -> str:
    lines = [
        "| Run | Strategy | Model calls | Cached input tokens | Cost with cache ($) | Cost if nothing was cached ($) | Wall-clock seconds |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for number, name in enumerate(runs, start=1):
        for key in STRATEGIES:
            if s := load_summary(name, key):
                usage = Usage.from_dict(s)
                lines.append(
                    f"| {number} | {strategy_label(key)} | {usage.calls} | {usage.cached_tokens:,} "
                    f"| {usage.cost:.4f} | {usage.cost_without_cache:.4f} | {s['wall_seconds']:.1f} |"
                )
    return "\n".join(lines)


def per_question_table(name: str) -> str:
    summaries = {key: load_summary(name, key) for key in STRATEGIES}
    ids = [q["id"] for q in next(s for s in summaries.values() if s)["per_question"]]
    marks = {
        key: {q["id"]: "–" if q["unanswered"] else ("✓" if q["correct"] else "✗") for q in s["per_question"]}
        for key, s in summaries.items() if s
    }
    lines = ["| Question | S1 | S2 | S3 |", "|---|:---:|:---:|:---:|"]
    lines += [f"| {qid} | " + " | ".join(marks.get(key, {}).get(qid, "") for key in STRATEGIES) + " |" for qid in ids]
    return "\n".join(lines)


def _correct_ids(name: str, key: str) -> set[str]:
    return {q["id"] for q in load_summary(name, key)["per_question"] if q["correct"]}


def _sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    tail = sum(comb(n, i) for i in range(0, min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def stability(runs: list[str]) -> str:
    first, second = runs[:2]
    lines = ["Questions whose result changed between the two runs:"]
    for key in STRATEGIES:
        changed = sorted(_correct_ids(first, key) ^ _correct_ids(second, key))
        lines.append(f"  {key}: {len(changed)} {changed}")

    lines.append("Paired S3 vs S2 (questions only one of them got right):")
    total_wins = total_losses = 0
    for name in runs:
        s3, s2 = _correct_ids(name, "s3"), _correct_ids(name, "s2")
        wins, losses = sorted(s3 - s2), sorted(s2 - s3)
        total_wins, total_losses = total_wins + len(wins), total_losses + len(losses)
        lines.append(f"  {name}: only S3 right {wins}, only S2 right {losses}, sign test p = {_sign_test(len(wins), len(losses)):.3f}")
    lines.append(f"  both runs: {total_wins} vs {total_losses}, sign test p = {_sign_test(total_wins, total_losses):.3f}")
    return "\n".join(lines)


def strict_accuracy(runs: list[str]) -> str:
    questions = {q["id"]: q for q in load_questions()}
    lines = ["Correct with no tolerance (number rounded to `decimals` must equal `value` exactly):"]
    for name in runs:
        for key in STRATEGIES:
            strict = sum(
                bool(row["answer"])
                and row["answer"]["name"] == questions[row["id"]]["answer"].lower()
                and round(row["answer"]["number"], questions[row["id"]]["decimals"]) == questions[row["id"]]["value"]
                for row in load_summary(name, key)["per_question"]
            )
            lines.append(f"  {name} {key}: {strict}/20 strict, {load_summary(name, key)['correct']}/20 with my rule")
    return "\n".join(lines)


def uncertainty(runs: list[str], z: float = 1.96) -> str:
    lines = [f"Uncertainty ({z} standard errors, both runs pooled):"]
    for key in STRATEGIES:
        hits = [row["correct"] for name in runs for row in load_summary(name, key)["per_question"]]
        p = sum(hits) / len(hits)
        half = z * (p * (1 - p) / 20) ** 0.5
        lines.append(f"  {key}: accuracy {p:.3f}, one run of 20 questions gives about ±{half:.3f}")

    differences = [
        int(a["correct"]) - int(b["correct"])
        for name in runs
        for a, b in zip(load_summary(name, "s3")["per_question"], load_summary(name, "s2")["per_question"])
    ]
    mean = statistics.mean(differences)
    variance = statistics.pvariance(differences)
    lines.append(f"  S3 minus S2 per question: mean {mean:.3f}, variance {variance:.3f}")
    lines.append(f"  20 questions: difference {mean:.3f} ± {z * (variance / 20) ** 0.5:.3f}")
    for half_width in (mean, 0.10, 0.05):
        needed = variance * (z / half_width) ** 2
        lines.append(f"  questions needed for ± {half_width:.3f}: {needed:.0f}")
    return "\n".join(lines)


def s2_samples(name: str) -> str:
    questions = {q["id"]: q for q in load_questions()}
    lines = ["S2 samples: correct samples out of 5, and whether the vote was correct"]
    sample_hits = vote_hits = 0
    for record in load_records(name, "s2"):
        samples = record["trace"]["samples"]
        hits = sum(bool(s["answer"]) and is_correct(Answer(**s["answer"]), questions[record["id"]]) for s in samples)
        names = {s["answer"]["name"] for s in samples if s["answer"]}
        sample_hits += hits
        vote_hits += record["correct"]
        lines.append(
            f"  {record['id']}: {hits}/5 samples, vote {'✓' if record['correct'] else '✗'}, "
            f"names {sorted(names)}, distinct answers {len(record['trace']['votes'])}"
        )
    total = len(load_records(name, "s2")) * SAMPLES
    lines.append(f"  single sample accuracy {sample_hits}/{total} = {sample_hits / total:.1%}, vote accuracy {vote_hits}/20")
    return "\n".join(lines)


def s3_rounds(name: str) -> str:
    lines = ["S3: model calls, tool calls and input tokens per model call"]
    by_round: dict[int, list[int]] = {}
    for record in load_records(name, "s3"):
        rounds = record["trace"]["rounds"]
        for r in rounds:
            by_round.setdefault(r["round"], []).append(r["usage"]["input_tokens"])
        lines.append(
            f"  {record['id']}: {len(rounds)} model calls, {len(record['trace']['tool_calls'])} tool calls, "
            f"input tokens per call {[r['usage']['input_tokens'] for r in rounds]}"
        )
    for number, tokens in sorted(by_round.items()):
        lines.append(f"  call {number}: median input tokens {statistics.median(tokens):.0f} over {len(tokens)} questions")
    return "\n".join(lines)


def compare_s3(base: str, other: str) -> str:
    base_rows = {q["id"]: q for q in load_summary(base, "s3")["per_question"]}
    lines = [
        "| Question | Calls (my description) | Calls (vague) | Answer (mine) | Answer (vague) |",
        "|---|---:|---:|---|---|",
    ]
    for row in load_summary(other, "s3")["per_question"]:
        mine = base_rows[row["id"]]
        lines.append(
            f"| {row['id']} | {mine['tool_calls']} | {row['tool_calls']} "
            f"| {_answer_cell(mine)} | {_answer_cell(row)} |"
        )
    return "\n".join(lines)


def _answer_cell(row: dict) -> str:
    if not row["answer"]:
        return "unanswered"
    mark = "✓" if row["correct"] else "✗"
    return f"{row['answer']['name']} {row['answer']['number']:g} {mark}"


def total_spend() -> str:
    usage = Usage()
    for path in OUTPUTS.glob("*/*/summary.json"):
        usage.add(Usage.from_dict(json.loads(path.read_text(encoding="utf-8"))))
    return f"All runs in outputs/: {usage.calls} model calls, ${usage.cost:.4f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the SUBMISSION.md tables and checks from outputs/.")
    parser.add_argument("--runs", nargs="+", default=["run1", "run2"])
    parser.add_argument("--compare-s3", nargs=2, metavar=("BASE", "OTHER"))
    args = parser.parse_args()

    if args.compare_s3:
        print(compare_s3(*args.compare_s3))
        return
    sections = [
        totals_table(args.runs),
        cost_table(args.runs),
        per_question_table(args.runs[0]),
        stability(args.runs),
        strict_accuracy(args.runs),
        uncertainty(args.runs),
        *(s2_samples(name) for name in args.runs),
        *(s3_rounds(name) for name in args.runs),
        total_spend(),
    ]
    print("\n\n".join(sections))


if __name__ == "__main__":
    main()
