import re
from dataclasses import dataclass

ANSWER_LINE = re.compile(r"ANSWER:\s*(?P<name>[^|\n]+?)\s*\|\s*(?P<number>[-+]?[\d,]*\.?\d+)")


@dataclass(frozen=True)
class Answer:
    name: str
    number: float

    def key(self, decimals: int) -> tuple[str, float]:
        return self.name, round(self.number, decimals)


def parse_answer(text: str | None) -> Answer | None:
    if not text:
        return None
    matches = list(ANSWER_LINE.finditer(text.replace("*", "").replace("`", "")))
    if not matches:
        return None
    last = matches[-1]
    try:
        number = float(last["number"].replace(",", ""))
    except ValueError:
        return None
    return Answer(name=" ".join(last["name"].split()).lower(), number=number)


def is_correct(answer: Answer | None, question: dict) -> bool:
    if answer is None:
        return False
    decimals = question["decimals"]
    step = 10 ** -decimals
    name_ok = answer.name == question["answer"].lower()
    number_ok = abs(round(answer.number, decimals) - question["value"]) <= step + 1e-9
    return name_ok and number_ok
