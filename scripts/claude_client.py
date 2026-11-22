"""
Claude as the reasoning model for the harness (planner and critic).

Uses the official Anthropic SDK. Reads ANTHROPIC_API_KEY from the environment
(harness.py loads .env first). Nothing here is called unless that key is set.
"""

import os

import anthropic

# names chosen not to clash with variables other tools set
MODEL = os.environ.get("REASONING_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("REASONING_EFFORT", "medium")


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def ask(prompt):
    """one reasoning call; returns (text, model that answered, summary of its reasoning)"""
    client = anthropic.Anthropic(max_retries=4)
    request = dict(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": EFFORT},  # thinking is always on for this model; effort sets its depth
        thinking={"type": "adaptive", "display": "summarized"},  # return a readable summary of the reasoning
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        try:
            # if the model declines, the API reruns the request on a fallback model in the same call
            response = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request)
        except (TypeError, anthropic.BadRequestError):
            response = client.messages.create(**request)
    except anthropic.AuthenticationError:
        raise SystemExit("Claude: the API key was rejected. Check ANTHROPIC_API_KEY in .env.")
    except anthropic.PermissionDeniedError:
        raise SystemExit("Claude: this key is not allowed to use " + MODEL)
    except anthropic.NotFoundError:
        raise SystemExit("Claude: model not found: " + MODEL)
    except anthropic.RateLimitError:
        raise SystemExit("Claude: rate limited after retries. Wait a minute and rerun; finished answers are cached.")
    except anthropic.APIStatusError as e:
        raise SystemExit(f"Claude: API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise SystemExit("Claude: network error.")
    if response.stop_reason == "refusal":
        raise SystemExit("Claude declined this request.")
    if response.stop_reason == "max_tokens":
        raise SystemExit("Claude: the answer was cut off at the token limit.")
    text = "".join(block.text for block in response.content if block.type == "text")
    reasoning = " ".join(block.thinking for block in response.content if block.type == "thinking" and block.thinking)
    return text, response.model, reasoning


# ------------------------------------------------------------------ web search
SEARCH_MODEL = os.environ.get("SEARCH_MODEL", MODEL)
SEARCH_EFFORT = os.environ.get("SEARCH_EFFORT", "medium")
USAGE = {"calls": 0, "searches": 0, "input_tokens": 0, "output_tokens": 0}


def search(prompt, max_uses=4):
    """one call with Claude's web search tool. returns (answer text, sources, queries, reasoning summary).
    max_uses caps how many searches this call may run, which caps what it can cost."""
    client = anthropic.Anthropic(max_retries=4)
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}]
    messages = [{"role": "user", "content": prompt}]
    response = None
    try:
        for _ in range(6):  # a long search turn can pause; sending it back resumes it
            response = client.messages.create(
                model=SEARCH_MODEL,
                max_tokens=16000,
                output_config={"effort": SEARCH_EFFORT},
                thinking={"type": "adaptive", "display": "summarized"},
                tools=tools,
                messages=messages,
            )
            USAGE["calls"] += 1
            USAGE["input_tokens"] += response.usage.input_tokens
            USAGE["output_tokens"] += response.usage.output_tokens
            if response.stop_reason != "pause_turn":
                break
            messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": response.content}]
    except anthropic.AuthenticationError:
        raise SystemExit("Claude: the API key was rejected. Check ANTHROPIC_API_KEY in .env.")
    except anthropic.PermissionDeniedError:
        raise SystemExit("Claude: this key is not allowed to use web search or " + SEARCH_MODEL)
    except anthropic.NotFoundError:
        raise SystemExit("Claude: model not found: " + SEARCH_MODEL)
    except anthropic.RateLimitError:
        raise SystemExit("Claude: rate limited after retries.")
    except anthropic.APIStatusError as e:
        raise SystemExit(f"Claude: API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise SystemExit("Claude: network error.")
    if response.stop_reason == "refusal":
        raise SystemExit("Claude declined this search.")
    text, reasoning, sources, queries = "", [], [], []
    for block in response.content:
        if block.type == "text":
            text += block.text
        elif block.type == "thinking" and block.thinking:
            reasoning.append(block.thinking)
        elif block.type == "server_tool_use" and block.name == "web_search":
            q = (block.input or {}).get("query")
            if q:
                queries.append(q)
        elif block.type == "web_search_tool_result" and isinstance(block.content, list):  # an error comes back as an object, not a list
            sources += [{"title": r.title, "url": r.url} for r in block.content]
    USAGE["searches"] += len(queries)
    return text, sources, queries, " ".join(reasoning)
