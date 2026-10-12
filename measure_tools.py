import json
from pathlib import Path

from dotenv import load_dotenv

from run import OUTPUTS, load_questions
from strategies import TOOLS_INSTRUCTION, ModelClient, system_prompt
from tools import VAGUE_LOOKUP_DESCRIPTION, tool_definitions


def prompt_tokens(client: ModelClient, messages: list[dict], tools: list[dict] | None) -> int:
    return client.chat(messages, tools).usage.input_tokens


def main() -> None:
    load_dotenv(Path(__file__).parent / ".env")
    client = ModelClient()
    question = load_questions(["Q-09"])[0]["question"]
    messages = [
        {"role": "system", "content": system_prompt(TOOLS_INSTRUCTION)},
        {"role": "user", "content": question},
    ]
    without_tools = prompt_tokens(client, messages, None)
    with_tools = prompt_tokens(client, messages, tool_definitions())
    with_vague = prompt_tokens(client, messages, tool_definitions(VAGUE_LOOKUP_DESCRIPTION))
    result = {
        "question": "Q-09",
        "input_tokens_without_tools": without_tools,
        "input_tokens_with_tools": with_tools,
        "input_tokens_with_vague_lookup": with_vague,
        "tool_definition_tokens": with_tools - without_tools,
        "tool_definition_tokens_vague": with_vague - without_tools,
    }
    (OUTPUTS / "tool_tokens.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
