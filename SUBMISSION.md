# HW4 — submission

**AI assistance:** I used Claude Code (Claude Opus 5.5) as a coding assistant. It helped me write the code (`tools.py`, `strategies.py`, `run.py`, the tests) and draft the text of this file. I chose the design, ran everything myself and checked all numbers against the files in `outputs/`.

---

## Part A — Plan on paper (Easy)

> Commit this whole part before any `.py` file exists.

### A1 — The steps

Example question: *"Which district is denser, Brightwater or Millbrook, and by how much?"*

| # | Step | What goes in (types) | What comes out (types) | When it goes wrong | Tool, loop, or model? |
|---|---|---|---|---|---|
| 1 | **Read the question** | `question: str` | `districts: list[str]` (2 or 3 names), `facts: list[str]` (field names like `population`, `area_km2`), `year: int` per fact, `formula: str` in words (for example "population / area, then subtract") | A name is not one of the 12 districts: keep the name as written, step 2 will report it. Question needs a fact we do not have: answer "unanswered". | model |
| 2 | **Find the district** | `district: str` (any spelling or case) | `canonical_name: str`, one of the 12 names | No match: error with the closest names (`"no district named Ossbrige; did you mean Ossbridge or Ossford?"`). Never guesses, even with one close match. | tool (`lookup`) |
| 3 | **Pick the right document** | `canonical_name: str`, `field: str` | `doc_id: str` of the current profile, plus `correction_id: str \| None` | More than one current (not archived) profile: error. Only an archived profile: error that says it is archived. A correction notice exists for this field: use the notice instead of the profile. | tool (`lookup`) |
| 4 | **Read the number** | `doc_text: str`, `field: str`, `year: int` | `value: float`, `unit: str`, `evidence: str` (the one sentence that holds the number) | Number not found in the text, or the year does not exist (for example 2019): error, not a guess. Text like `52,904` is read as `52904.0`. | tool (`lookup`) |
| 5 | **Make the unit standard** | `value: float`, `unit: str` | `value: float`, `unit: str` in the standard unit for the field | Water in cubic metres: divide by 1,000 to get megalitres and add a note. Unknown unit: error, never pass on a number with a unit we did not expect. | tool (`lookup`) |
| 6 | **Do the arithmetic** | `expression: str`, for example `"44675 / 921.4"` | `result: float` (not rounded) | Bad syntax, names or functions in the text, division by zero, a power that is too big, a result over 10^15: error with the reason. | tool (`calculate`) |
| 7 | **Compare and pick the winner** | `metric_per_district: dict[str, float]` | `winner: str` (name or `yes`/`no`), `difference: float` | Two values are equal: say so. The question asks for "fewest" or "largest": pick by that word, not always the bigger one. | model (the subtraction itself goes to step 6) |
| 8 | **Round and write the answer** | `winner: str`, `difference: float`, `decimals: int` from the question's unit | one line `ANSWER: <name or yes/no> \| <number>` | The model forgets the line or writes two: the answer counts as wrong. | model |
| 9 | **Run the conversation** | `messages: list[dict]`, `tools: list[dict]` | final `str` from the model, plus a log `list[dict]` | `arguments` is not valid JSON or has wrong types: send an error back as the tool result, do not run the tool. Round limit reached: mark "unanswered". | loop |
| 10 | **Score the answer** | model text `str`, gold `answer: str`, `value: float`, `decimals: int` | `correct: bool` | No `ANSWER:` line, or the number cannot be read: `correct = False`, and it is counted as unanswered. | loop (my scoring code, not the model) |

Steps 2 to 5 all live inside `lookup`, but they are separate jobs inside it: name, document, number, unit. Each one can fail in its own way and each one has its own error message. Step 10 is not part of answering. It is how I check the answer, and the model never sees it.

**How the steps connect:**

```text
question (str)
   │
   ▼
[1 model] read question ──► for each (district, field, year):
                               │
                               ▼
                    ┌──────── lookup ─────────────────────────┐
                    │ [2] find district ─► [3] pick document  │
                    │        ─► [4] read number ─► [5] unit   │
                    └─────────────────────────────────────────┘
                               │  {value, unit, source, evidence}
                               ▼
[6 calculate] metric per district  (e.g. 44675 / 921.4)
                               │  float per district
                               ▼
[7 model] compare ──► [6 calculate] difference
                               │  winner, float
                               ▼
[8 model] round ──► "ANSWER: Millbrook | 0.6"
                               │
                               ▼
[10 scoring code] compare with questions.json ──► correct / wrong

[9 loop] runs around 1 to 8: it carries every tool request to the
tool and every result back to the model, and stops after N rounds.
```

**What I am assuming:**

- **Year.** All numbers are for 2025 unless the question names another year (NR-00 says so). Population has two years, 2020 and 2025. Pupils are for the 2025/26 school year, which I treat as "2025".
- **Archived profiles** (NR-13 Tarnvale, NR-14 Kelmarsh) are never used. They hold 2018 and 2019 numbers that NR-00 says are superseded.
- **Corrections win.** NR-16 changes Brightwater's area from 912.4 to 921.4 km². `lookup` returns 921.4 and says where it came from.
- **Units.** Water is always handled in megalitres. Lindenmoor gives 2,151,400 cubic metres, which is 2,151.4 ML (1 ML = 1,000 m³, from NR-15). Budgets are in million tenge. For "per day", 2025 has 365 days. 1 ML = 1,000,000 litres.
- **Tariff.** The 2025 tariff is 142.35 tenge per cubic metre and is the same in every district (NR-15).
- **Rounding** happens only once, at the very end, to the number of decimals the question needs. All middle results stay unrounded inside `calculate`. Rounding early can move the last digit.
- **Differences** are always positive: the bigger value minus the smaller one. "Percentage points" means the difference between two percentages.
- **Text in the profiles can mislead.** For example, Stonecairn and Coldharbour say "up from" but their population actually went down. I trust the numbers, not the words around them.

**The assumption my answers are most sensitive to:** that `lookup` returns the current, corrected number. If it used the uncorrected Brightwater area (912.4), the Q-09 answer would be 0.1 instead of 0.6, which is wrong by far more than one rounding step. If it used the archived Tarnvale or Kelmarsh numbers, the answer for Q-02 or Q-03 could even name the wrong district. Rounding and arithmetic errors move the last digit; a wrong source moves the whole answer. That is why the source rules live in the tool and not in the model.

### A2 — The two tools

#### `lookup`

```json
{
  "type": "function",
  "function": {
    "name": "lookup",
    "description": "Get one number about one district of the Nine Rivers Region from the official documents. It always reads the current 2025 profile, never the ARCHIVED 2019 profiles, and it applies correction notices. Water use is always given in megalitres (it converts if a profile uses cubic metres). The result has the number, its unit, the source document id and the sentence it came from. Use one call per district and field. You can make several calls at the same time. The household water tariff is the same in every district: use field 'water_tariff_tenge_per_m3' with any district name.",
    "parameters": {
      "type": "object",
      "properties": {
        "district": {
          "type": "string",
          "description": "District name, for example 'Ossford'. The spelling is checked and close names are never guessed."
        },
        "field": {
          "type": "string",
          "enum": [
            "population",
            "area_km2",
            "budget_million_tenge",
            "water_use_megalitres",
            "schools",
            "pupils",
            "paved_road_km",
            "founded_year",
            "water_tariff_tenge_per_m3"
          ]
        },
        "year": {
          "type": "integer",
          "enum": [2020, 2024, 2025],
          "description": "Optional. Census year for 'population' (2020 or 2025), or tariff year for 'water_tariff_tenge_per_m3' (2024 or 2025). Default 2025. Other fields only exist for 2025."
        }
      },
      "required": ["district", "field"],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"district": "Brightwater", "field": "population", "year": 2025, "value": 44675, "unit": "residents", "source": "NR-05", "evidence": "Census population: 39,902 in 2020 and 44,675 in 2025."}` |
| success with a correction | same shape, `"source": "NR-16"`, plus `"note": "Corrected by NR-16. The profile NR-05 says 912.4."` |
| success with a unit change | same shape, `"value": 2151.4, "unit": "megalitres"`, plus `"note": "Profile gives 2,151,400 cubic metres; converted with 1 ML = 1,000 m3 (NR-15)."` |
| unknown or misspelled district | `{"error": "no district named 'Ossbrige'. Did you mean: Ossbridge, Ossford? Known districts: ..."}` |
| unknown field | `{"error": "unknown field 'density'. Allowed fields: population, area_km2, ..."}` |
| year that does not exist | `{"error": "population is only available for 2020 and 2025. Older numbers are in an ARCHIVED profile and must not be used."}` |
| number not found in the text | `{"error": "could not find 'pupils' in NR-05"}` |
| bad arguments (missing, wrong type, too long) | `{"error": "argument 'district' must be a string of at most 50 characters"}` (checked by the loop and by the tool) |

**Worst thing it could do with strange or dangerous input:** the tool only reads one fixed local file and never runs its input, opens a path from it, or sends it anywhere. So strange input can only give an error. The real danger is quiet: if the text pattern grabs the wrong number from a sentence, the tool returns a wrong but normal-looking value, and the model has no way to notice. To lower that risk, every result includes the `evidence` sentence, and the tests check one value from each sentence template.

#### `calculate`

```json
{
  "type": "function",
  "function": {
    "name": "calculate",
    "description": "Work out one arithmetic expression and return the exact result. Use it for every calculation instead of doing math yourself. Allowed: numbers, + - * / // % **, unary minus and parentheses. Write numbers without thousands separators (44675, not 44,675). No names, functions or variables. The result is not rounded, so round the final answer yourself.",
    "parameters": {
      "type": "object",
      "properties": {
        "expression": {
          "type": "string",
          "description": "For example '44675 / 921.4' or '(90212 - 83609) / 83609 * 100'."
        }
      },
      "required": ["expression"],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"expression": "44675 / 921.4", "result": 48.4859995659}` |
| syntax error | `{"error": "could not read the expression: invalid syntax"}` |
| name, function, attribute or other code | `{"error": "not allowed: Call. Only numbers, + - * / // % ** and parentheses"}` |
| number with comma (`44,675`) | `{"error": "not allowed: Tuple. Write numbers without commas, for example 44675"}` |
| division by zero | `{"error": "division by zero"}` |
| power too big (`9**9**9`) | `{"error": "exponent too large (limit is 100)"}` |
| result too big | `{"error": "result is too large (limit is 1e15)"}` |
| expression too long | `{"error": "expression too long (limit is 300 characters)"}` |

**Worst thing it could do with strange or dangerous input:** with `eval`, a model could run any Python code, for example delete files or read `.env`. My tool never calls `eval` or `exec`. It reads the text into a syntax tree with `ast.parse` and only walks nodes for numbers and the listed operators, so names, calls and attributes are refused before anything runs. The remaining risk is a calculation that takes all the CPU or memory, like `9**9**9`. The limits on exponent size, result size and text length stop this before the big number is built.

### A3 — Q-09 by hand

Question Q-09: *"Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?"*

```json
[
  {"role": "system", "content": "You answer questions about the Nine Rivers Region. Use the lookup tool for every fact and the calculate tool for every calculation. End with one line: ANSWER: <name or yes/no> | <number>"},
  {"role": "user", "content": "Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"population\"}"}},
    {"id": "call_2", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"area_km2\"}"}},
    {"id": "call_3", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"population\"}"}},
    {"id": "call_4", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"area_km2\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_1", "content": "{\"district\": \"Brightwater\", \"field\": \"population\", \"year\": 2025, \"value\": 44675, \"unit\": \"residents\", \"source\": \"NR-05\", \"evidence\": \"Census population: 39,902 in 2020 and 44,675 in 2025.\"}"},
  {"role": "tool", "tool_call_id": "call_2", "content": "{\"district\": \"Brightwater\", \"field\": \"area_km2\", \"year\": 2025, \"value\": 921.4, \"unit\": \"km2\", \"source\": \"NR-16\", \"evidence\": \"The correct area is 921.4 square kilometres.\", \"note\": \"Corrected by NR-16. The profile NR-05 says 912.4.\"}"},
  {"role": "tool", "tool_call_id": "call_3", "content": "{\"district\": \"Millbrook\", \"field\": \"population\", \"year\": 2025, \"value\": 37203, \"unit\": \"residents\", \"source\": \"NR-11\", \"evidence\": \"Census population: 34,590 in 2020 and 37,203 in 2025.\"}"},
  {"role": "tool", "tool_call_id": "call_4", "content": "{\"district\": \"Millbrook\", \"field\": \"area_km2\", \"year\": 2025, \"value\": 758.6, \"unit\": \"km2\", \"source\": \"NR-11\", \"evidence\": \"The district, founded in 1897, stretches along the Mill Brook over 758.6 square kilometres and keeps 360.1 km of paved road.\"}"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_5", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"44675 / 921.4\"}"}},
    {"id": "call_6", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"37203 / 758.6\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_5", "content": "{\"expression\": \"44675 / 921.4\", \"result\": 48.4859995659}"},
  {"role": "tool", "tool_call_id": "call_6", "content": "{\"expression\": \"37203 / 758.6\", \"result\": 49.0416556815}"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_7", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"37203 / 758.6 - 44675 / 921.4\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_7", "content": "{\"expression\": \"37203 / 758.6 - 44675 / 921.4\", \"result\": 0.5556561156}"},

  {"role": "assistant", "content": "Brightwater: 44,675 residents on 921.4 km2 (corrected area, NR-16) = 48.49 per km2. Millbrook: 37,203 on 758.6 km2 = 49.04 per km2. Millbrook is denser by 0.56 residents per km2.\nANSWER: Millbrook | 0.6"}
]
```

This takes 3 tool rounds and 7 tool calls, then one more model reply with the answer.

**My arithmetic:**

- Brightwater: 44,675 / 921.4 = 48.486 residents per km² (with the corrected area from NR-16)
- Millbrook: 37,203 / 758.6 = 49.042 residents per km²
- Difference: 49.042 − 48.486 = 0.556, rounded to 1 decimal = **0.6**, Millbrook is denser.
- Matches `questions.json`: answer `Millbrook`, value `0.6`.
- The trap: with the wrong area 912.4, Brightwater is 48.964 per km² and the difference is only 0.077, so the answer would be 0.1. Millbrook still wins, but the number is wrong.

### A4 — Why I split it this way

**The other way I considered:** a `lookup` that takes a free-text search phrase (for example `"Brightwater area"`) and returns the best matching sentences from the documents, and leaves everything else to the model.

**Why I did not choose it:**

1. **The traps would land on the model.** With search, the model would get back both NR-05 ("912.4 square kilometres") and maybe NR-16, and it would have to notice that the notice wins. For Kelmarsh it could get the archived NR-14 sentence. For Lindenmoor it would get cubic metres and have to convert. These are exactly the places where models slip, and an error there is not small (see the Q-09 trap above). In my design these rules are written once in code and tested.
2. **Search results are harder to check.** A search returns sentences that "look close", and ranking can put the wrong district first (Ossbridge and Ossford share most letters). A field lookup either finds one value for one exact district or returns an error.
3. **What search does better:** it can answer questions I did not plan for (for example a river name), because it has no fixed field list. For these 20 questions every needed fact is one of 9 fields, so the fixed list costs nothing here. If the questions were open-ended, I would add search as a third tool, not replace `lookup`.

I also rejected the opposite extreme, one tool per metric (`density(district)`, `growth(district)`, ...). That would make the model's job almost empty, but every new kind of question would need new code, and it would hide the arithmetic that this homework wants to test. Two small tools (find a fact, do the math) cover all 20 questions and still let the model plan the steps.

---

## Part B — Build it and run it (Medium)

### What I changed from Part A while coding

The two tool definitions and the steps stayed the same. Small changes:

1. **Who rounds.** In A1 step 8 the model rounds to the needed decimals. In the code the model does not know how many decimals a question needs (that would come from `questions.json`). So every prompt asks for "at least 3 decimal places", and `scoring.py` does the rounding. Reason: no data from `questions.json` reaches the prompt, and a model cannot lose points by rounding too early.
2. **Hidden reasoning is off.** `gpt-5.6-luna` accepts `reasoning_effort` = `none`, `low`, `medium`, `high`, `xhigh`. I fixed it to `none` for all three strategies. Otherwise S1 would not be a real "direct" answer, because the model would think in private before answering. All runs used 0 reasoning tokens (checked in `outputs/run*/*/summary.json`).
3. **Name suggestions.** `lookup("Ossbrige", ...)` suggests up to 3 close names (`Ossbridge, Ossford, Brightwater`), not only the closest one.
4. **Argument check.** `run_tool` in `tools.py` parses the JSON string and checks for missing or unknown argument names. The type checks (string, number, allowed field, allowed year) stay inside each tool, so the tool is still safe when called directly from a test.
5. **Extra helper scripts** that were not in my plan: `report.py` builds every table below from `outputs/`, and `measure_tools.py` measures the size of the tool definitions in tokens.

### B2 — Tests

33 tests in `tests/test_tools.py`: 18 for `lookup`, 14 for `calculate`, 1 for the argument parsing in `run_tool`. No API key needed. Saved in `outputs/pytest.txt`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.14.8, pytest-9.1.1, pluggy-1.6.0 -- ./.venv/bin/python
cachedir: .pytest_cache
rootdir: .
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.15.1
collecting ... collected 33 items

tests/test_tools.py::test_lookup_returns_2025_population_with_source PASSED [  3%]
tests/test_tools.py::test_lookup_returns_2020_population PASSED          [  6%]
tests/test_tools.py::test_lookup_misspelled_name_suggests_without_guessing PASSED [  9%]
tests/test_tools.py::test_lookup_keeps_similar_districts_apart PASSED    [ 12%]
tests/test_tools.py::test_lookup_ignores_archived_profiles[Tarnvale-schools-29-27] PASSED [ 15%]
tests/test_tools.py::test_lookup_ignores_archived_profiles[Kelmarsh-pupils-3268-2944] PASSED [ 18%]
tests/test_tools.py::test_lookup_ignores_archived_profiles[Kelmarsh-water_use_megalitres-1739-1652] PASSED [ 21%]
tests/test_tools.py::test_lookup_refuses_archived_year PASSED            [ 24%]
tests/test_tools.py::test_lookup_applies_correction_notice PASSED        [ 27%]
tests/test_tools.py::test_lookup_converts_cubic_metres_to_megalitres PASSED [ 30%]
tests/test_tools.py::test_lookup_reads_each_sentence_template PASSED     [ 33%]
tests/test_tools.py::test_lookup_water_tariff PASSED                     [ 36%]
tests/test_tools.py::test_lookup_never_crashes_on_bad_input[Ossford-density-2025] PASSED [ 39%]
tests/test_tools.py::test_lookup_never_crashes_on_bad_input[-population-2025] PASSED [ 42%]
tests/test_tools.py::test_lookup_never_crashes_on_bad_input[None-population-2025] PASSED [ 45%]
tests/test_tools.py::test_lookup_never_crashes_on_bad_input[500-character-name] PASSED [ 48%]
tests/test_tools.py::test_lookup_never_crashes_on_bad_input[Ossford-population-2025] PASSED [ 51%]
tests/test_tools.py::test_lookup_never_crashes_on_bad_input[Ossford-area_km2-2020] PASSED [ 54%]
tests/test_tools.py::test_calculate_multiplication PASSED                [ 57%]
tests/test_tools.py::test_calculate_density PASSED                       [ 60%]
tests/test_tools.py::test_calculate_refuses_dangerous_input_quickly[__import__('os').system('echo hi')] PASSED [ 63%]
tests/test_tools.py::test_calculate_refuses_dangerous_input_quickly[(1).__class__] PASSED [ 66%]
tests/test_tools.py::test_calculate_refuses_dangerous_input_quickly[9**9**9] PASSED [ 69%]
tests/test_tools.py::test_calculate_returns_errors[1 / 0-division by zero] PASSED [ 72%]
tests/test_tools.py::test_calculate_returns_errors[10 ** 15 * 10-too large] PASSED [ 75%]
tests/test_tools.py::test_calculate_returns_errors[44,675 / 2-without commas] PASSED [ 78%]
tests/test_tools.py::test_calculate_returns_errors[abs(-1)-not allowed] PASSED [ 81%]
tests/test_tools.py::test_calculate_returns_errors[x + 1-not allowed] PASSED [ 84%]
tests/test_tools.py::test_calculate_returns_errors['a' * 3-not allowed] PASSED [ 87%]
tests/test_tools.py::test_calculate_returns_errors[1 +-could not read] PASSED [ 90%]
tests/test_tools.py::test_calculate_returns_errors[400-character-expression] PASSED [ 93%]
tests/test_tools.py::test_calculate_returns_errors[(-8) ** 0.5-not a real number] PASSED [ 96%]
tests/test_tools.py::test_run_tool_handles_bad_arguments PASSED          [100%]

============================== 33 passed in 0.04s ==============================
```

### B3 — The loop

The loop is `tools_loop` in `strategies.py`.

- It adds the model's message to the conversation exactly as the API returns it (with its `tool_calls`), then runs every tool call and sends back one `tool` message for **every** `tool_call_id`.
- `arguments` is a JSON string. `run_tool` parses it with `json.loads`, checks it is an object with the right argument names, and only then calls the tool. A bad request becomes an error result for the model, it never crashes the loop.

- **Round limit, and why:** 10 model calls per question. My plan for Q-09 needs 4 calls (facts, per-district values, difference, answer), and a question with three districts needs the same 4 calls, just with more tools per call. 10 gives room for a few mistakes and retries after a tool error, but stops a model that keeps asking for the same thing. A question that hits the limit is marked unanswered. In the real runs no question used more than 4 calls, so the limit was never reached.
- **Where the logs are:** `outputs/run1/s3/Q-XX.json` and `outputs/run2/s3/Q-XX.json`. Each file has `trace.tool_calls` (round, id, tool name, raw arguments, result, seconds the tool took), `trace.rounds` (tokens and seconds of every model call) and `trace.messages` (the whole conversation). The S1 and S2 folders have the same kind of file. `outputs/run1.log` and `outputs/run2.log` show progress.
- **Real Q-09 conversation compared with my A3 version, what is different:** (from `outputs/run1/s3/Q-09.json`)
  - The plan is the same as mine: 4 `lookup` calls in parallel, then `44675 / 921.4` and `37203 / 758.6` in parallel, then `37203 / 758.6 - 44675 / 921.4`, then the answer. Same 7 tool calls, same 4 model calls, and `lookup` returned the corrected area 921.4 from NR-16.
  - The model always added `"year": 2025` to `lookup`, even though it is optional.
  - The ids are long random strings (`call_309jzoXSsTyKgib3LagLfCnW`), not `call_1`.
  - The assistant message also has an empty `annotations` field and no `content`.
  - In the third call the model wrote `{"expression":"37203 / 758.6 - 44675 / 921.4"}` without spaces, while earlier calls had spaces. This shows that arguments are just text the model writes.
  - The final line is `ANSWER: Millbrook | 0.556`, not `0.6`, because my prompt asks for at least 3 decimals. The scorer rounds it to 0.6.
  - Something I did not plan for: input tokens grow every call (650, 1,090, 1,207, 1,280) because the whole conversation is sent again. From the second call on, almost all of it was cached (0, 1,087, 1,204, 1,277 cached tokens).

### B4 — Three strategies

**What I kept the same:**

- **Model:** `gpt-5.6-luna` for every call, through the Chat Completions API.
- **Temperature:** 1 for every call. This model only accepts the default value 1. I tried `temperature = 0.7` and got error 400: "Only the default (1) value is supported." So S2's 5 samples vary only because of the model's normal sampling at temperature 1. This is enough: in S2 run 1, 10 of 20 questions got more than one different answer from the 5 samples.
- **Reasoning effort:** `none` for every call (0 reasoning tokens in all runs).
- **k = 5** samples in S2.
- **Questions:** the same 20 from `data/questions.json`. The user message is only the question text, the same in all three strategies.
- **Prompt:** the same first sentence ("You answer questions about the Nine Rivers Region...") and the same answer-format text at the end. Only one sentence changes per strategy: "Answer directly. Do not show your working." (S1), "Think step by step: first write down each fact you need with its document id, then do each calculation, then give the answer." (S2), "You do not have the documents. Use the lookup tool..." (S3). S1 and S2 also get all 17 documents in the same order. S3 gets the two tools instead.
- **Answer format:** `ANSWER: <district name or yes/no> | <number>`, with at least 3 decimals.
- **Scoring:** the same code (`scoring.py`) for all strategies.
- **No token limit** on answers, the same API client settings (5 retries, 180 s timeout).
- **How runs were timed:** 4 questions run at the same time in every strategy. "Seconds per question" is measured inside each question, from the first request to the final answer. S2 sends its 5 samples at the same time, so its time is the slowest of the 5, not the sum. "Total seconds" is the sum over the 20 questions.

**Why 20 questions and this rule.** I used all 20 questions because each one tests something different (similar names, archived profiles, the correction, the unit change, three-district questions, yes/no questions), and 20 kept the cost low enough to run everything twice. The name must match exactly because choosing the right district is the main decision. The number gets one step of tolerance in the last digit because a model that rounds a middle value can move the last digit, and that is not a reasoning mistake. A weakness I found later: with 1 decimal this tolerance is wide. S2 voted 5.2 on Q-03 (true value 5.34, which rounds to 5.3) and it counted as correct. `report.py` also counts with no tolerance at all (see C4).

**Prices used** (OpenAI list price for `gpt-5.6-luna` after the July 2026 price cut): $0.20 per million input tokens, $0.02 per million cached input tokens, $1.20 per million output tokens. Costs are computed from the `usage` field of every call, including cached tokens.

| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | S1 direct | 3 | 0 | 44,280 | 484 | 1.30 | 26.1 | 0.0016 |
| 1 | S2 think and vote (k = 5) | 15 | 0 | 223,200 | 15,793 | 2.39 | 53.3 | 0.0236 |
| 1 | S3 tools | 20 | 0 | 72,511 | 4,586 | 5.27 | 105.7 | 0.0141 |
| 2 | S1 direct | 4 | 0 | 44,280 | 506 | 1.28 | 25.8 | 0.0015 |
| 2 | S2 think and vote (k = 5) | 16 | 0 | 223,200 | 15,917 | 2.46 | 50.1 | 0.0236 |
| 2 | S3 tools | 19 | 0 | 70,515 | 4,436 | 5.16 | 108.4 | 0.0109 |

Most input tokens were cached, because the documents (S1, S2) and the tool definitions (S3) are the same at the start of every request. This changes the cost a lot, so here is the same data with and without the cache discount:

| Run | Strategy | Model calls | Cached input tokens | Cost with cache ($) | Cost if nothing was cached ($) | Wall-clock seconds |
|---|---|---:|---:|---:|---:|---:|
| 1 | S1 direct | 20 | 43,585 | 0.0016 | 0.0094 | 6.8 |
| 1 | S2 think and vote (k = 5) | 100 | 222,104 | 0.0236 | 0.0636 | 17.1 |
| 1 | S3 tools | 69 | 32,654 | 0.0141 | 0.0200 | 28.2 |
| 2 | S1 direct | 20 | 44,220 | 0.0015 | 0.0095 | 6.8 |
| 2 | S2 think and vote (k = 5) | 100 | 222,900 | 0.0236 | 0.0637 | 14.0 |
| 2 | S3 tools | 68 | 47,355 | 0.0109 | 0.0194 | 30.3 |

**What everything cost me:** $0.087 for all 424 model calls in `outputs/` (the trial run, both full runs and the C1 test), plus 3 small calls in `measure_tools.py`. The two full runs alone cost $0.075.

**Per question (run 1):**

| Question | S1 | S2 | S3 |
|---|:---:|:---:|:---:|
| Q-01 | ✗ | ✓ | ✓ |
| Q-02 | ✗ | ✓ | ✓ |
| Q-03 | ✗ | ✓ | ✓ |
| Q-04 | ✗ | ✓ | ✓ |
| Q-05 | ✗ | ✗ | ✓ |
| Q-06 | ✗ | ✓ | ✓ |
| Q-07 | ✗ | ✗ | ✓ |
| Q-08 | ✗ | ✓ | ✓ |
| Q-09 | ✗ | ✓ | ✓ |
| Q-10 | ✓ | ✓ | ✓ |
| Q-11 | ✗ | ✓ | ✓ |
| Q-12 | ✗ | ✗ | ✓ |
| Q-13 | ✓ | ✓ | ✓ |
| Q-14 | ✗ | ✓ | ✓ |
| Q-15 | ✗ | ✓ | ✓ |
| Q-16 | ✓ | ✓ | ✓ |
| Q-17 | ✗ | ✗ | ✓ |
| Q-18 | ✗ | ✓ | ✓ |
| Q-19 | ✗ | ✓ | ✓ |
| Q-20 | ✗ | ✗ | ✓ |

Run 2 differs in three places only: S1 also got Q-18 right, S2 also got Q-07 right, and S3 got Q-11 wrong.

---

## Part C — Explain and choose (Hard)

### C1 — Does the tool description matter?

I ran S3 again on 5 questions with the `lookup` description changed to `"Looks things up."` (`python run.py --name c1_vague --strategies s3 --vague-lookup --questions Q-03 Q-08 Q-09 Q-11 Q-17`). Everything else stayed the same, including the parameter schema. I picked questions with traps: a unit change (Q-03), the tariff (Q-08, Q-17), the correction (Q-09) and three districts (Q-11). "Mine" is run 1. Logs: `outputs/c1_vague/s3/`.

| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|
| Q-03 | 7 | 7 | Lindenmoor 5.34 ✓ | Lindenmoor 5.34 ✓ |
| Q-08 | 6 | 7 | Brightwater 72.456 ✓ | Brightwater 72.456 ✓ |
| Q-09 | 7 | 7 | Millbrook 0.556 ✓ | Millbrook 0.556 ✓ |
| Q-11 | 10 | 10 | Redfen 56.1 ✓ | Redfen 53.508 ✗ |
| Q-17 | 6 | 9 | Harrowfield 884.457 ✓ | Harrowfield 884.457 ✓ |

**What changed:**

- **More calls on the tariff questions.** My description says "The household water tariff is the same in every district". Without that sentence, the model looked up the tariff once for each district in Q-08 and Q-17 (two `water_tariff_tenge_per_m3` calls instead of one). In Q-17 it also split the math into 3 `calculate` calls instead of 1, which added a fourth model call.
- **The inputs did not get worse.** Every `lookup` call still used a correct field name and a correct district. The reason is that the schema still holds most of the information: the `field` enum lists names like `water_use_megalitres` and `area_km2`, and the `district` and `year` parameters keep their own descriptions. The model reads the names of the fields as if they were documentation.
- **The traps were still handled.** In Q-09 the vague version still got 921.4 from NR-16, and in Q-03 it still got 2,151.4 ML for Lindenmoor. The model never knew about archived profiles or corrections in either version, because that logic is inside the tool code. This is what I expected in A1: rules in code do not depend on the model reading a description.
- **The one wrong answer is not caused by the description.** The vague run got Q-11 wrong (53.508), but S3 with my full description made exactly the same mistake on Q-11 in run 2. It is a planning error, explained in C2.
- **Tokens:** the vague definitions are 383 tokens, my full ones are 506 (`outputs/tool_tokens.json`). So each call was 123 tokens cheaper, but the extra calls on Q-08 and Q-17 used up that saving.

**Why:** the model uses the description to decide *how* to use a tool when the schema does not tell it. Here the schema was already very clear, and the hard rules were in the code, so the vague description only cost some extra calls. If my `lookup` had been a free-text search (my A4 alternative), the description would be the only place to tell the model about archived profiles and corrections, and I expect a vague description would then lead to wrong answers.

### C2 — Three mistakes explained

**S1: Q-09 (run 1).** The whole reply was one line:

```text
ANSWER: Brightwater | 1.265
```

In run 2 it was again Brightwater, with 0.958. The correct answer is Millbrook by 0.556. The model writes its answer one token at a time from left to right, and in S1 the district name is written **before** any calculation exists. To choose the name, it would have to know that 44,675 / 921.4 = 48.49 is smaller than 37,203 / 758.6 = 49.04 without writing anything down. The two values are only about 1% apart, so this is a guess. The number after it is not computed either, the median S1 reply was only 27 output tokens. The same thing happens across S1: it named the right district in only 11 of 20 questions in run 1 and 10 of 20 in run 2. For questions with two choices that is the same as tossing a coin. In run 1, S1 got right only Q-10 (1845 − 1837 = 8), Q-16 (adding two areas) and Q-13.

**S2: Q-17 (run 1).** All 5 samples had the right facts and the right formula, but the long division was wrong in every sample. Sample 1 from `outputs/run1/s2/Q-17.json`:

```text
- Harrowfield water cost per resident = \(7,146,000 \times 142.35 \div 90,212 = 11,278.229\) tenge.
- Ossbridge water cost per resident = \(3,862,000 \times 142.35 \div 52,904 = 10,391.314\) tenge.
- Difference = \(11,278.229 - 10,391.314 = 886.915\) tenge per resident.
```

The true values are 11,276.029 and 10,391.572, so the true difference is 884.457. The 5 votes were 887 (2 times), 888 (2 times) and 889 (1 time). No sample was close to 884, so voting could not help.

Why voting fixes some mistakes but not others: voting works when the errors are **random** and the right answer is still the most common one. Then the wrong answers spread out and the right one wins. Q-08 in run 1 shows this: only 2 of 5 samples were right (72.46), but the other 3 were all different (72.04, 71.74, 72.64), so 72.46 still won. Voting cannot fix an error that is **systematic**, when the model makes the same kind of mistake every time. Here the model does 7 to 8 digit multiplication and division by writing digits, and it usually ends up a little too high. Q-05, Q-12, Q-17 and Q-20 all ask for tenge per resident or per pupil, with big numbers, and S2 got them wrong in both runs (0 or 1 correct samples out of 5). More samples reduce the spread of answers around the model's average answer, but they do not move that average. If the average is wrong, k = 50 would give the same wrong answer, just more confidently. And it costs a lot: 5 times the input tokens, and about 825 output tokens per question instead of 27.

**S3: Q-11 (run 2).** S3 got everything right in run 1, and this is its only mistake. From `outputs/run2/s3/Q-11.json`, round 2:

```text
2 calculate {"expression": "3147 / 10"}             -> 314.7
2 calculate {"expression": "8837 / 24"}             -> 368.2083333333
2 calculate {"expression": "5562 / 15"}             -> 370.8
2 calculate {"expression": "8837 / 24 - 3147 / 10"} -> 53.5083333333
```

The model asked for the difference **in the same round** as the three per-school values, so it had not seen them yet. It guessed that Ashgrove would be the highest, but Millbrook (370.8) is higher. The calculator computed the wrong expression perfectly. In run 1 the model waited for the three results and then sent `370.8 - 314.7` in round 3, which gave 56.1, the right answer.

Why a calculator removes mistakes the model cannot avoid on its own: a model does not compute 7,146,000 × 142.35 ÷ 90,212. It predicts the next digits from patterns, so long numbers come out a little wrong, and nothing inside the model checks them. `calculate` uses Python's real arithmetic, so the error from the arithmetic itself becomes close to zero (floating point, about 15 digits). That is why S3 got Q-05, Q-12, Q-17 and Q-20 right in both runs. But a calculator only makes arithmetic exact. It cannot check that the expression is the right one, so a planning mistake like this one passes through untouched.

Why the loop needed that many rounds: S3 used 3 or 4 model calls on every question. Each call depends on the results of the one before it: first get the facts, then compute a value per district, then the difference, then write the answer. The model can only see a result in the next call. Some questions took 3 calls because the model put the whole formula into one `calculate` call (Q-17 run 1: `7146 * 142.35 * 1000 / 90212 - 3862 * 142.35 * 1000 / 52904`).

Why each round costs more than the one before: the API has no memory, so every call sends the whole conversation again: the system prompt, the 506 tokens of tool definitions, the question and every earlier tool call and result. In run 1 the median input was 656 tokens for call 1, 1,104 for call 2, 1,236 for call 3 and 1,324 for call 4. So the total input grows roughly with the square of the number of rounds. The cache made this cheaper in practice (on Q-09, calls 2 to 4 were about 99% cached), but it does not reduce the token count.

### C3 — Which strategy I would use, and what would change it

**I would use S3, the tools loop.**

| | S1 direct | S2 think and vote | S3 tools |
|---|---:|---:|---:|
| Correct (run 1 / run 2) | 3 / 4 | 15 / 16 | 20 / 19 |
| Cost per 20 questions, with cache | $0.0016 | $0.0236 | $0.0109 to $0.0141 |
| Cost per 20 questions, no cache | $0.0094 | $0.0636 | $0.0194 to $0.0200 |
| Median seconds per question | 1.3 | 2.4 | 5.2 |

- **S3 is the most accurate, and the reason is a principle, not luck.** Its 1 mistake in 40 answers was a planning error. S2's 9 mistakes in 40 were all arithmetic errors, mostly on big numbers, and S3 removes exactly that type of error. The traps (correction, archived profiles, unit change) are handled by tested code.
- **Why not S2:** it costs 1.7 to 2.2 times more than S3 with the cache, and 3.2 to 3.3 times more without it, and it is still wrong on the same 4 questions in both runs. More samples would raise the cost further and would not fix those 4 questions, because the error is systematic (see C2). Its only advantage is speed: 2.4 s against 5.2 s, because its 5 samples run in parallel while S3's calls must wait for each other.
- **Why not S1:** it is the cheapest and the fastest, but it gets 80 to 85% of the answers wrong, and it picks the right district only about half of the time. A cheap wrong answer has no value here.
- **The cost of S3:** it is the slowest, about 2 times slower than S2 and 4 times slower than S1, because it needs 3 to 4 calls one after another. For a homework question that is fine.

**Situations that would change my choice:**

1. **A strict time limit, for example an answer within 3 seconds.** S3 cannot meet it (median 5.2 s). I would pick S2 with the 5 samples in parallel (median 2.4 s) and accept about 4 wrong answers in 20. If the limit is under 2 seconds, only S1 fits, but at 15 to 20% correct I would rather say the system cannot answer.
2. **1,000 times more documents (about 2.3 million tokens).** The documents no longer fit in one prompt, since the model's context window is about 1 million tokens. Even if they did, S1 and S2 would pay for every document on every call. S3 does not grow with the corpus: it only reads the few facts it needs. So S3 becomes even more clearly the best choice, with a better `lookup` (see final question 6).
3. **Questions with no arithmetic, like "When was Stonecairn founded?"** The tools add nothing, and S1 would answer from the documents in one cheap, fast call. S1 already got Q-10 right in both runs, where the math was only 1845 − 1837. I would pick S1.
4. **A much smaller budget.** S1 is the cheapest, but it is useless here. Between the useful two, S3 is also the cheaper one, so a small budget makes the choice of S3 stronger, not weaker. Without a prompt cache the gap grows: $0.020 against $0.064 per 20 questions.

### C4 — How sure I can be

All numbers here come from `python report.py` (saved in `outputs/report.txt`).

- **How different were my two runs?** Each strategy changed on exactly one question between run 1 and run 2: S1 on Q-18, S2 on Q-07, S3 on Q-11. That is a change of 1 in 20, or 5 percentage points. The token counts were almost the same (S2 used exactly 223,200 input tokens both times), and the median times differed by about 0.1 s or less.
- **Is the gap between my two best strategies bigger than that?** Yes. S3 beat S2 by 5 questions in run 1 and by 3 in run 2, so the gap is 3 to 5 times larger than the change between runs. Looking at single questions: there were 9 cases where only S3 was right and 1 case where only S2 was right (both runs together). A sign test gives p = 0.021 for both runs together, but p = 0.062 for run 1 alone and p = 0.375 for run 2 alone. So one run of 20 questions is not enough to be sure, and two runs on the **same** 20 questions are not two independent samples either.
- **The gap depends on the question mix.** S2 failed on the same 4 questions in both runs (Q-05, Q-12, Q-17, Q-20), all with big numbers in tenge. If the set had 10 questions like that, the gap would be much larger. With none, it would almost disappear. So my result says "S3 is better on questions like these", not "S3 is better by 20 points" in general.
- **The scoring rule matters for S2.** With no tolerance at all (the rounded number must equal `value` exactly), S3 stays at 20 and 19, but S2 drops from 15 and 16 to 13 and 12, and S1 from 4 to 3 in run 2. S2 often lands one step away from the right number, so the ±1 tolerance helps it the most.
- **Error bars.** With 20 questions, one run gives roughly ±0.18 on S2's accuracy (0.775) and ±0.07 on S3's (0.975), with 95% confidence. The paired difference S3 − S2 is 0.20 ± 0.20. That is just enough to say the difference is not zero, and not enough to say how big it is.
- **How many questions I would need:** from the variance of the per-question differences (0.21), about **20** questions to tell this gap from zero, about **80** to know the gap within ±10 points, and about **320** to know it within ±5 points. They should be new questions of many kinds, not the same 20 run more times, because repeating runs only measures the model's randomness, not the variety of questions. In short: I trust the order S3 > S2 > S1 on this kind of task. I do not trust the exact size of the gaps.

### Final questions

1. **When the model sends a `tool_calls` message, what has actually run so far?** Only the model. It has produced text: a tool name and a JSON string of arguments. No tool has run yet, and the model does not run anything. My loop reads the request, decides whether it is valid, and runs `lookup` or `calculate` on my machine. My logs show this split: in Q-09, `lookup` took about 0.0002 seconds in my process, while each model call took over a second on OpenAI's servers.

2. **Why does `arguments` arrive as a string, and what goes wrong if you pass it straight into your function?** Because the model writes the arguments as text, token by token, and that text is not guaranteed to be valid JSON or to match the schema. The API passes it on as it is. In my logs the model wrote both `{"expression": "..."}` and `{"expression":"..."}`, which shows it is just text. If I passed it straight in, `calculate('{"expression": "44675 / 921.4"}')` would try to compute the braces and the word "expression", and `lookup(**arguments)` would crash because you cannot unpack a string. Broken JSON or unknown keys would also crash the loop. So `run_tool` uses `json.loads`, checks that it is an object with the right keys, and returns an error result instead of crashing.

3. **How many tokens do your two tool definitions add to every S3 request?** **506 tokens**. I measured it with `measure_tools.py`: the same Q-09 messages cost 144 input tokens without tools and 650 with tools (`outputs/tool_tokens.json`). With the vague `lookup` description it is 383. Run 1 had 69 S3 model calls, so the definitions alone were about 69 × 506 = 34,914 of the 72,511 S3 input tokens, almost half.

4. **How much more did S2 cost than S1?** In run 1, $0.0236 against $0.0016, which is **14.8 times** more (15.7 times in run 2). S2 sends 5 requests instead of 1, so it has 5 times the input tokens (223,200 against 44,280). But the bigger part is output: S2 writes its working, so it produced 15,793 output tokens against 484, which is 33 times more (about 825 tokens per question against 27). Output tokens cost 6 times more than input tokens, and most input tokens were cached at one tenth of the price, so output decides most of S2's bill. Without the cache, S2 would cost $0.0636 against $0.0094, which is 6.8 times more.

5. **Which question needed the most rounds in S3, and why?** No question needed more than 4 model calls. Nine questions needed 4 calls in run 1, and the biggest were **Q-11 and Q-20**, each with 4 model calls and 10 tool calls (Q-20 had the most input tokens: 5,021). Both ask about three districts, so the model needed 6 facts (2 per district), 3 per-district values and 1 difference. These are 4 steps that depend on each other (facts, values, difference, answer), so they need 4 calls. The model already did the 6 lookups in parallel in one call. It could only save a call by putting the whole formula into one expression, which it sometimes did (Q-13 took 3 calls).

6. **What would you change in `lookup` if there were 100,000 documents?** Today, every call scans all document titles and runs regular expressions over one document's sentences. That is fine for 17 documents. For 100,000 I would: (a) read every document once at start-up and build an index from (district, field, year) to value, source and sentence, so a lookup is one dictionary read; (b) store archived and correction status as real data fields (which document replaces which) instead of reading it from titles; (c) use a faster name search, for example an index of letter groups, because `difflib` against thousands of names is slow; (d) add a second tool for free-text search over an index (BM25 or embeddings) that returns only the top few sentences, for facts that are not in my fixed field list; and (e) when one search finds too many results, return the first few and say how many more there are, so the result stays short.

7. **What stops your `calculate` from running dangerous code? Could the model still make it misbehave?** It never uses `eval` or `exec`. `ast.parse` only turns the text into a tree, it runs nothing. My `_evaluate` walks that tree and only accepts number constants, the 7 operators and unary plus and minus. Any other node (a name, a function call, an attribute like `__class__`, a string, a list) gives an error before anything runs. The tests show `__import__('os').system('echo hi')`, `(1).__class__` and `9**9**9` are all refused in under a second. To stop huge calculations it limits text length (300 characters), exponents (at most 100) and the size of every middle result (at most 10^15). The model can still make it give a **wrong answer**: a correct calculation of the wrong expression, as in Q-11 run 2. Also, floating point is not exact (results are rounded to 10 decimals), and an expression can contain up to 300 characters of math, but all of that is bounded and safe.

8. **For which kind of question did tools help most, and for which did they not help at all?** They helped most on questions with **large-number arithmetic**: Q-05, Q-12, Q-17 and Q-20 (tenge per resident or per pupil, with 7 to 8 digit numbers). S2 got these wrong in both runs, with 0 or 1 correct samples out of 5, and S3 got them right in both runs. They did not help at all on questions where the math is small, like Q-10 (1845 − 1837) and Q-16, which S1 already got right, or on questions where reading carefully was enough: S2 handled the correction in Q-09 and the unit change in Q-03 correctly in 5 of 5 samples with the documents in the prompt. Tools also did not help with planning: in Q-11 run 2 the calculator computed a wrong plan exactly.
