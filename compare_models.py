"""
Replay saved LLM prompts against multiple models and write results to separate files.

Usage:
    python compare_models.py [--prompts llm_prompts.jsonl]

Reads prompts from llm_prompts.jsonl (written by llm_filter.py) and sends each
to gpt-5.4-mini, gpt-5.4-nano, and gpt-5.4. Results are written to:
    results_gpt-5.4-mini.jsonl
    results_gpt-5.4-nano.jsonl
    results_gpt-5.4.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

MODELS = ["gpt-5.4-mini", "gpt-5.4-nano"]

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "name": "alert_evaluation",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "interesting": {"type": "boolean"},
            "summary": {
                "type": "string",
                "description": "1 sentence internal summary for filtering log.",
            },
            "bullets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-3 short plain-English bullet points.",
            },
            "copy_action": {
                "type": "object",
                "properties": {
                    "outcome": {"type": "string"},
                    "side": {"type": "string"},
                    "entry_price": {"type": "number"},
                    "max_price": {"type": "number"},
                },
                "required": ["outcome", "side", "entry_price", "max_price"],
                "additionalProperties": False,
            },
        },
        "required": ["interesting", "summary", "bullets", "copy_action"],
        "additionalProperties": False,
    },
}


def load_prompts(path: Path) -> list[dict]:
    prompts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                prompts.append(json.loads(line))
    return prompts


def run_prompt(client: OpenAI, model: str, messages: list[dict]) -> dict:
    """Send a single prompt to a model and return the parsed result."""
    try:
        kwargs: dict = {
            "model": model,
            "max_output_tokens": 4000,
            "input": messages,
            "text": {"format": RESPONSE_SCHEMA},
        }
        if model in ("gpt-5.4-mini", "gpt-5.4-nano"):
            kwargs["reasoning"] = {"effort": "high"}
        response = client.responses.create(**kwargs)
        text = response.output_text
        result = json.loads(text)
        usage = response.usage
        return {
            "result": result,
            "prompt_tokens": usage.input_tokens if usage else 0,
            "completion_tokens": usage.output_tokens if usage else 0,
            "error": None,
        }
    except Exception as e:
        return {
            "result": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="Compare LLM models on saved prompts")
    parser.add_argument(
        "--prompts",
        type=Path,
        default=Path(__file__).parent / "llm_prompts.jsonl",
        help="Path to the prompt log file",
    )
    args = parser.parse_args()

    if not args.prompts.exists():
        print(f"Error: {args.prompts} not found. Run polybot.py first to generate prompts.")
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Error: OPENAI_API_KEY not set.")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    prompts = load_prompts(args.prompts)
    print(f"Loaded {len(prompts)} prompts from {args.prompts}")

    output_dir = Path(__file__).parent
    total_calls = len(prompts) * len(MODELS)
    overall = 0

    for model_idx, model in enumerate(MODELS, 1):
        output_path = output_dir / f"results_{model}.jsonl"
        print(f"\n{'='*60}")
        print(f"[Model {model_idx}/{len(MODELS)}] Running {len(prompts)} prompts against {model}")
        print(f"Output: {output_path}")
        print(f"{'='*60}")

        with open(output_path, "w") as out:
            for i, prompt_entry in enumerate(prompts, 1):
                overall += 1
                cache_key = prompt_entry.get("cache_key", "")
                messages = prompt_entry["messages"]

                print(f"  [{i}/{len(prompts)}] (overall {overall}/{total_calls}) {cache_key[:60]}...", end=" ", flush=True)

                resp = run_prompt(client, model, messages)

                entry = {
                    "cache_key": cache_key,
                    "model": model,
                    "result": resp["result"],
                    "prompt_tokens": resp["prompt_tokens"],
                    "completion_tokens": resp["completion_tokens"],
                    "error": resp["error"],
                }
                out.write(json.dumps(entry) + "\n")

                if resp["error"]:
                    print(f"ERROR: {resp['error'][:50]}")
                else:
                    verdict = "INTERESTING" if resp["result"]["interesting"] else "DISCARDED"
                    print(verdict)

        print(f"Done. Wrote {len(prompts)} results to {output_path}")

    print(f"\nAll done. Result files:")
    for model in MODELS:
        print(f"  results_{model}.jsonl")


if __name__ == "__main__":
    main()
