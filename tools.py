import ast
import difflib
import json
import operator
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "data" / "corpus.jsonl"

MAX_DISTRICT_LENGTH = 50
MAX_EVIDENCE_LENGTH = 300
MAX_EXPRESSION_LENGTH = 300
MAX_EXPONENT = 100
MAX_MAGNITUDE = 1e15
RESULT_DECIMALS = 10

CURRENT_YEAR = 2025
NUMBER = r"(?P<value>\d[\d,]*(?:\.\d+)?)"
THOUSANDS = r"(?P<value>\d{1,3}(?:,\d{3})+)"


@dataclass(frozen=True)
class Field:
    unit: str
    patterns: tuple[str, ...]
    years: tuple[int, ...] = (CURRENT_YEAR,)
    regional: bool = False


FIELDS = {
    "population": Field(
        unit="residents",
        patterns=(
            rf"(?P<year>\d{{4}}) census (?:had )?(?:recorded|counted) {THOUSANDS}",
            rf"{THOUSANDS} (?:in|at the) (?P<year>\d{{4}})",
        ),
        years=(2020, 2025),
    ),
    "area_km2": Field(unit="km2", patterns=(rf"{NUMBER} square kilometres",)),
    "budget_million_tenge": Field(unit="million tenge", patterns=(rf"{NUMBER} million tenge",)),
    "water_use_megalitres": Field(
        unit="megalitres",
        patterns=(rf"{NUMBER} (?P<unit>megalitres|cubic metres)",),
    ),
    "schools": Field(unit="schools", patterns=(rf"{NUMBER} schools",)),
    "pupils": Field(unit="pupils", patterns=(rf"{NUMBER} pupils",)),
    "paved_road_km": Field(unit="km", patterns=(rf"{NUMBER} km (?:of paved road|long)",)),
    "founded_year": Field(unit="year", patterns=(r"[Ff]ounded in (?P<value>\d{4})",)),
    "water_tariff_tenge_per_m3": Field(
        unit="tenge per m3",
        patterns=(rf"(?P<year>\d{{4}}) (?:the regional household water )?tariff (?:is|was) {NUMBER} tenge per cubic metre",),
        years=(2024, 2025),
        regional=True,
    ),
}

UNIT_CONVERSIONS = {
    ("cubic metres", "megalitres"): (1 / 1000, "1 ML = 1,000 m3 (NR-15)"),
}

PROFILE_TITLE = re.compile(r"^(?P<district>\w+) district profile")
CORRECTION_TITLE = re.compile(r"^Correction notice - (?P<district>\w+)")
CORRECTED_SENTENCE = re.compile(r"\bcorrect\b", re.IGNORECASE)
TARIFF_TITLE = "Household water tariff"
SENTENCE_END = re.compile(r"(?<=\.)\s+")


class LookupFailure(Exception):
    pass


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    text: str

    @property
    def archived(self) -> bool:
        return "ARCHIVED" in self.title

    def sentences(self) -> list[str]:
        return SENTENCE_END.split(self.text)


@dataclass(frozen=True)
class Match:
    value: float
    year: int | None
    unit: str | None
    sentence: str
    source: str


@lru_cache(maxsize=1)
def load_corpus(path: Path = CORPUS_PATH) -> tuple[Document, ...]:
    with path.open(encoding="utf-8") as file:
        return tuple(Document(**json.loads(line)) for line in file if line.strip())


def _documents_for(district: str, title_pattern: re.Pattern) -> list[Document]:
    return [
        doc for doc in load_corpus()
        if (match := title_pattern.match(doc.title)) and match["district"] == district
    ]


def known_districts() -> list[str]:
    return sorted({
        match["district"] for doc in load_corpus()
        if not doc.archived and (match := PROFILE_TITLE.match(doc.title))
    })


def _resolve_district(name: str) -> str:
    districts = known_districts()
    by_lower = {district.lower(): district for district in districts}
    cleaned = " ".join(name.split()).lower()
    if cleaned in by_lower:
        return by_lower[cleaned]
    suggestions = difflib.get_close_matches(cleaned, list(by_lower), n=3, cutoff=0.5)
    hint = f" Did you mean: {', '.join(by_lower[s] for s in suggestions)}?" if suggestions else ""
    raise LookupFailure(f"no district named '{name}'.{hint} Known districts: {', '.join(districts)}.")


def _current_profile(district: str) -> Document:
    profiles = _documents_for(district, PROFILE_TITLE)
    current = [doc for doc in profiles if not doc.archived]
    if not current:
        archived_ids = ", ".join(doc.id for doc in profiles)
        raise LookupFailure(f"{district} only has ARCHIVED profiles ({archived_ids}), which must not be used.")
    if len(current) > 1:
        raise LookupFailure(f"{district} has more than one current profile: {', '.join(d.id for d in current)}.")
    return current[0]


def _find(doc: Document, field: Field, sentences: list[str] | None = None) -> list[Match]:
    matches = []
    for sentence in sentences if sentences is not None else doc.sentences():
        for pattern in field.patterns:
            for found in re.finditer(pattern, sentence):
                groups = found.groupdict()
                matches.append(Match(
                    value=float(groups["value"].replace(",", "")),
                    year=int(groups["year"]) if groups.get("year") else None,
                    unit=groups.get("unit"),
                    sentence=sentence,
                    source=doc.id,
                ))
    return matches


def _for_year(matches: list[Match], year: int) -> list[Match]:
    return [m for m in matches if m.year in (None, year)]


def _single(matches: list[Match], field_name: str, doc_id: str) -> Match:
    values = {m.value for m in matches}
    if not values:
        raise LookupFailure(f"could not find '{field_name}' in {doc_id}.")
    if len(values) > 1:
        raise LookupFailure(f"found more than one value for '{field_name}' in {doc_id}: {sorted(values)}.")
    return matches[0]


def _correction(district: str, field_name: str, field: Field, year: int) -> Match | None:
    for notice in _documents_for(district, CORRECTION_TITLE):
        corrected = [s for s in notice.sentences() if CORRECTED_SENTENCE.search(s)]
        matches = _for_year(_find(notice, field, corrected), year)
        if matches:
            return _single(matches, field_name, notice.id)
    return None


def _convert(match: Match, field: Field) -> tuple[float, str | None]:
    if match.unit in (None, field.unit):
        return match.value, None
    conversion = UNIT_CONVERSIONS.get((match.unit, field.unit))
    if conversion is None:
        raise LookupFailure(f"unexpected unit '{match.unit}' in {match.source}; expected {field.unit}.")
    factor, rule = conversion
    return match.value * factor, f"{match.source} gives {match.value:,.10g} {match.unit}; converted with {rule}."


def _clean_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, RESULT_DECIMALS)


def _validate_lookup_arguments(district, field, year) -> Field:
    if not isinstance(district, str) or not district.strip() or len(district) > MAX_DISTRICT_LENGTH:
        raise LookupFailure(f"argument 'district' must be a non-empty string of at most {MAX_DISTRICT_LENGTH} characters.")
    if field not in FIELDS:
        raise LookupFailure(f"unknown field '{field}'. Allowed fields: {', '.join(FIELDS)}.")
    spec = FIELDS[field]
    if isinstance(year, bool) or not isinstance(year, int):
        raise LookupFailure("argument 'year' must be a whole number such as 2025.")
    if year not in spec.years:
        years = " and ".join(map(str, spec.years))
        raise LookupFailure(
            f"{field} is only available for {years}. Older numbers are in ARCHIVED profiles and must not be used."
        )
    return spec


def _lookup(district: str, field: str, year: int) -> dict:
    spec = _validate_lookup_arguments(district, field, year)
    if spec.regional:
        doc = next(d for d in load_corpus() if d.title == TARIFF_TITLE)
        name = district.strip()
        note = f"The tariff is the same in every district ({doc.id})."
    else:
        name = _resolve_district(district)
        doc = _current_profile(name)
        note = None

    match = _single(_for_year(_find(doc, spec), year), field, doc.id)
    corrected = None if spec.regional else _correction(name, field, spec, year)
    if corrected is not None:
        note = f"Corrected by {corrected.source}. The profile {doc.id} says {match.value:,.10g}."
        match = corrected

    value, conversion_note = _convert(match, spec)
    result = {
        "district": name,
        "field": field,
        "year": year,
        "value": _clean_number(value),
        "unit": spec.unit,
        "source": match.source,
        "evidence": match.sentence[:MAX_EVIDENCE_LENGTH],
    }
    notes = [n for n in (note, conversion_note) if n]
    if notes:
        result["note"] = " ".join(notes)
    return result


def lookup(district: str, field: str, year: int = CURRENT_YEAR) -> dict:
    try:
        return _lookup(district, field, year)
    except LookupFailure as error:
        return {"error": str(error)}
    except Exception as error:
        return {"error": f"lookup failed: {type(error).__name__}"}


class CalculationError(Exception):
    pass


BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
ALLOWED_TEXT = "Only numbers, + - * / // % ** and parentheses are allowed."


def _checked(value) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalculationError(f"result is not a real number. {ALLOWED_TEXT}")
    if abs(value) > MAX_MAGNITUDE:
        raise CalculationError(f"result is too large (limit is {MAX_MAGNITUDE:g}).")
    return value


def _evaluate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return _checked(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
        return _checked(UNARY_OPERATORS[type(node.op)](_evaluate(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculationError(f"exponent too large (limit is {MAX_EXPONENT}).")
        try:
            return _checked(BINARY_OPERATORS[type(node.op)](left, right))
        except ZeroDivisionError:
            raise CalculationError("division by zero.")
        except OverflowError:
            raise CalculationError(f"result is too large (limit is {MAX_MAGNITUDE:g}).")
    if isinstance(node, ast.Tuple):
        raise CalculationError("not allowed: Tuple. Write numbers without commas, for example 44675.")
    raise CalculationError(f"not allowed: {type(node).__name__}. {ALLOWED_TEXT}")


def calculate(expression: str) -> dict:
    if not isinstance(expression, str) or not expression.strip():
        return {"error": "argument 'expression' must be a non-empty string."}
    if len(expression) > MAX_EXPRESSION_LENGTH:
        return {"error": f"expression too long (limit is {MAX_EXPRESSION_LENGTH} characters)."}
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _evaluate(tree)
    except SyntaxError as error:
        return {"error": f"could not read the expression: {error.msg}."}
    except CalculationError as error:
        return {"error": str(error)}
    except (RecursionError, MemoryError, ValueError):
        return {"error": "expression is too complex."}
    return {"expression": expression, "result": _clean_number(result)}


LOOKUP_DESCRIPTION = (
    "Get one number about one district of the Nine Rivers Region from the official documents. "
    "It always reads the current 2025 profile, never the ARCHIVED 2019 profiles, and it applies correction notices. "
    "Water use is always given in megalitres (it converts if a profile uses cubic metres). "
    "The result has the number, its unit, the source document id and the sentence it came from. "
    "Use one call per district and field. You can make several calls at the same time. "
    "The household water tariff is the same in every district: use field 'water_tariff_tenge_per_m3' with any district name."
)
VAGUE_LOOKUP_DESCRIPTION = "Looks things up."

CALCULATE_DESCRIPTION = (
    "Work out one arithmetic expression and return the exact result. "
    "Use it for every calculation instead of doing math yourself. "
    "Allowed: numbers, + - * / // % **, unary minus and parentheses. "
    "Write numbers without thousands separators (44675, not 44,675). "
    "No names, functions or variables. The result is not rounded, so round the final answer yourself."
)


def tool_definitions(lookup_description: str = LOOKUP_DESCRIPTION) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": lookup_description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "district": {
                            "type": "string",
                            "description": "District name, for example 'Ossford'. The spelling is checked and close names are never guessed.",
                        },
                        "field": {"type": "string", "enum": list(FIELDS)},
                        "year": {
                            "type": "integer",
                            "enum": sorted({year for spec in FIELDS.values() for year in spec.years}),
                            "description": (
                                "Optional. Census year for 'population' (2020 or 2025), or tariff year for "
                                "'water_tariff_tenge_per_m3' (2024 or 2025). Default 2025. Other fields only exist for 2025."
                            ),
                        },
                    },
                    "required": ["district", "field"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calculate",
                "description": CALCULATE_DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "For example '44675 / 921.4' or '(90212 - 83609) / 83609 * 100'.",
                        }
                    },
                    "required": ["expression"],
                    "additionalProperties": False,
                },
            },
        },
    ]


TOOL_FUNCTIONS = {"lookup": lookup, "calculate": calculate}


def _parameters(name: str) -> dict:
    return next(t["function"]["parameters"] for t in tool_definitions() if t["function"]["name"] == name)


def run_tool(name: str, raw_arguments: str) -> dict:
    if name not in TOOL_FUNCTIONS:
        return {"error": f"unknown tool '{name}'. Available tools: {', '.join(TOOL_FUNCTIONS)}."}
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as error:
        return {"error": f"arguments are not valid JSON: {error.msg}."}
    if not isinstance(arguments, dict):
        return {"error": "arguments must be a JSON object."}

    schema = _parameters(name)
    missing = [key for key in schema["required"] if key not in arguments]
    unknown = [key for key in arguments if key not in schema["properties"]]
    if missing or unknown:
        return {"error": f"missing arguments: {missing}, unknown arguments: {unknown}."}
    return TOOL_FUNCTIONS[name](**arguments)
