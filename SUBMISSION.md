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

<!-- what changed in your plan, and why. "None" is an answer too. -->

### B2 — Tests

```text
<!-- pytest output -->
```

### B3 — The loop

- Round limit, and why:
- Where the logs are:
- Real Q-09 conversation compared with my A3 version, what is different:

### B4 — Three strategies

**What I kept the same:**

<!-- model, temperature, k, prompts, answer format, anything else -->

**My rule for a correct answer** (written before the first full run):

| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | S1 direct | | | | | | | |
| 1 | S2 think and vote (k = ) | | | | | | | |
| 1 | S3 tools | | | | | | | |
| 2 | S1 direct | | | | | | | |
| 2 | S2 think and vote (k = ) | | | | | | | |
| 2 | S3 tools | | | | | | | |

**Per question (run 1):**

| Question | S1 | S2 | S3 |
|---|:---:|:---:|:---:|
| Q-01 | | | |
| Q-02 | | | |
| Q-03 | | | |
| Q-04 | | | |
| Q-05 | | | |
| Q-06 | | | |
| Q-07 | | | |
| Q-08 | | | |
| Q-09 | | | |
| Q-10 | | | |
| Q-11 | | | |
| Q-12 | | | |
| Q-13 | | | |
| Q-14 | | | |
| Q-15 | | | |
| Q-16 | | | |
| Q-17 | | | |
| Q-18 | | | |
| Q-19 | | | |
| Q-20 | | | |

---

## Part C — Explain and choose (Hard)

### C1 — Does the tool description matter?

| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|
| | | | | |

### C2 — Three mistakes explained

### C3 — Which strategy I would use, and what would change it

### C4 — How sure I can be

### Final questions

1.
2.
3.
4.
5.
6.
7.
8.
