import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from openai import OpenAI

from scoring import Answer, parse_answer
from tools import LOOKUP_DESCRIPTION, load_corpus, run_tool, tool_definitions

MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "none"
TEMPERATURE = 1
SAMPLES = 5
MAX_ROUNDS = 10
PRICE_PER_MILLION = {"input": 0.20, "cached_input": 0.02, "output": 1.20}

ANSWER_INSTRUCTION = (
    "End your reply with exactly one line in this format:\n"
    "ANSWER: <district name or yes/no> | <number>\n"
    "Use only the district name, or yes/no for a yes/no question. "
    "Write the number without units or thousands separators, "
    "with at least 3 decimal places unless it is a whole count."
)
BASE_PROMPT = "You answer questions about the Nine Rivers Region, a fictional region. Use only the information you are given."
DIRECT_INSTRUCTION = "Answer directly. Do not show your working."
THINK_INSTRUCTION = (
    "Think step by step: first write down each fact you need with its document id, "
    "then do each calculation, then give the answer."
)
TOOLS_INSTRUCTION = (
    "You do not have the documents. Use the lookup tool to get every fact "
    "and the calculate tool for every calculation."
)


def _documents_block() -> str:
    documents = "\n\n".join(f"[{doc.id}] {doc.title}\n{doc.text}" for doc in load_corpus())
    return f"Documents:\n\n{documents}"


def system_prompt(*parts: str) -> str:
    return "\n\n".join((BASE_PROMPT, *parts, ANSWER_INSTRUCTION))


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def add(self, other: "Usage") -> "Usage":
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        return self

    @property
    def cost(self) -> float:
        uncached = self.input_tokens - self.cached_tokens
        return (
            uncached * PRICE_PER_MILLION["input"]
            + self.cached_tokens * PRICE_PER_MILLION["cached_input"]
            + self.output_tokens * PRICE_PER_MILLION["output"]
        ) / 1_000_000

    def to_dict(self) -> dict:
        return {**asdict(self), "cost_usd": round(self.cost, 6)}


@dataclass
class Reply:
    message: dict
    usage: Usage
    seconds: float


@dataclass
class StrategyResult:
    text: str | None
    answer: Answer | None
    usage: Usage
    seconds: float
    trace: dict = field(default_factory=dict)
    hit_round_limit: bool = False


class ModelClient:
    def __init__(self, client: OpenAI | None = None):
        self.client = client or OpenAI(max_retries=5, timeout=180)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Reply:
        options = {"tools": tools} if tools else {}
        start = time.perf_counter()
        response = self.client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=TEMPERATURE,
            reasoning_effort=REASONING_EFFORT,
            **options,
        )
        seconds = time.perf_counter() - start
        usage = response.usage
        return Reply(
            message=response.choices[0].message.model_dump(exclude_none=True),
            usage=Usage(
                calls=1,
                input_tokens=usage.prompt_tokens,
                cached_tokens=getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0,
                output_tokens=usage.completion_tokens,
                reasoning_tokens=getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0,
            ),
            seconds=seconds,
        )


def _conversation(system: str, question: dict) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": question["question"]}]


def direct(question: dict, client: ModelClient) -> StrategyResult:
    messages = _conversation(system_prompt(_documents_block(), DIRECT_INSTRUCTION), question)
    reply = client.chat(messages)
    text = reply.message.get("content")
    return StrategyResult(
        text=text,
        answer=parse_answer(text),
        usage=reply.usage,
        seconds=reply.seconds,
        trace={"messages": [*messages, reply.message]},
    )


def think_and_vote(question: dict, client: ModelClient, samples: int = SAMPLES) -> StrategyResult:
    messages = _conversation(system_prompt(_documents_block(), THINK_INSTRUCTION), question)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=samples) as pool:
        replies = list(pool.map(lambda _: client.chat(messages), range(samples)))
    seconds = time.perf_counter() - start

    answers = [parse_answer(reply.message.get("content")) for reply in replies]
    votes = Counter(answer.key(question["decimals"]) for answer in answers if answer)
    winner = None
    if votes:
        winning_key = votes.most_common(1)[0][0]
        winner = next(a for a in answers if a and a.key(question["decimals"]) == winning_key)

    usage = Usage()
    for reply in replies:
        usage.add(reply.usage)
    return StrategyResult(
        text=f"ANSWER: {winner.name} | {winner.number}" if winner else None,
        answer=winner,
        usage=usage,
        seconds=seconds,
        trace={
            "messages": messages,
            "samples": [
                {
                    "text": reply.message.get("content"),
                    "answer": asdict(answer) if answer else None,
                    "usage": reply.usage.to_dict(),
                    "seconds": round(reply.seconds, 3),
                }
                for reply, answer in zip(replies, answers)
            ],
            "votes": [{"answer": list(key), "count": count} for key, count in votes.most_common()],
        },
    )


def tools_loop(
    question: dict,
    client: ModelClient,
    max_rounds: int = MAX_ROUNDS,
    lookup_description: str = LOOKUP_DESCRIPTION,
) -> StrategyResult:
    tools = tool_definitions(lookup_description)
    messages = _conversation(system_prompt(TOOLS_INSTRUCTION), question)
    usage = Usage()
    tool_log, rounds_log = [], []
    start = time.perf_counter()

    for round_number in range(1, max_rounds + 1):
        reply = client.chat(messages, tools)
        usage.add(reply.usage)
        messages.append(reply.message)
        tool_calls = reply.message.get("tool_calls") or []
        rounds_log.append({
            "round": round_number,
            "tool_calls": len(tool_calls),
            "usage": reply.usage.to_dict(),
            "model_seconds": round(reply.seconds, 3),
        })
        if not tool_calls:
            text = reply.message.get("content")
            return StrategyResult(
                text=text,
                answer=parse_answer(text),
                usage=usage,
                seconds=time.perf_counter() - start,
                trace={"rounds": rounds_log, "tool_calls": tool_log, "messages": messages},
            )
        if round_number == max_rounds:
            break
        for call in tool_calls:
            tool_start = time.perf_counter()
            result = run_tool(call["function"]["name"], call["function"]["arguments"])
            tool_log.append({
                "round": round_number,
                "id": call["id"],
                "name": call["function"]["name"],
                "arguments": call["function"]["arguments"],
                "result": result,
                "seconds": round(time.perf_counter() - tool_start, 6),
            })
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})

    return StrategyResult(
        text=None,
        answer=None,
        usage=usage,
        seconds=time.perf_counter() - start,
        trace={"rounds": rounds_log, "tool_calls": tool_log, "messages": messages},
        hit_round_limit=True,
    )


STRATEGIES = {
    "s1": ("S1 direct", direct),
    "s2": ("S2 think and vote", think_and_vote),
    "s3": ("S3 tools", tools_loop),
}
