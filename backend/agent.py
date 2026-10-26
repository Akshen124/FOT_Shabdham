import ast
import json
import math
import operator
import time
from datetime import datetime
from typing import Callable, Generator
from zoneinfo import ZoneInfo

from .rag import (
    NOT_AVAILABLE_ANSWER,
    UNRELATED_REFUSAL_ANSWER,
    build_context,
    expand_query_for_retrieval,
    generate_answer,
    generate_answer_stream,
    generate_kb_discovery_answer,
    generate_kb_discovery_answer_stream,
    get_similarity_threshold,
    has_domain_affinity,
    is_basic_conversation,
    is_kb_discovery,
    is_unrelated_factual_or_math,
    rag_debug_log,
)
from .tts import split_into_sentences


SYSTEM_PROMPT = """You are a helpful assistant. Keep normal responses concise: strictly target 20–40 words, using 1–3 short sentences, unless the user explicitly requests more detail. Use the knowledge-base search for questions about the user's documents. Use the calculator for arithmetic and the current-time tool for date or time questions. For time questions, use UTC unless the user gives a location or timezone. Do not expose internal retrieval details in user-facing answers."""
MAX_TOOL_ROUNDS = 5

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search the user's indexed documents for relevant information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A concise search query for the user's documents.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a basic arithmetic expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic using numbers, parentheses, +, -, *, /, //, %, and **.",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time in an IANA timezone, such as UTC or Asia/Tokyo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone name. Defaults to UTC.",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
]

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def calculate(expression: str) -> int | float:
    """Evaluate arithmetic without allowing names, calls, or other Python syntax."""
    if len(expression) > 200:
        raise ValueError("Expression is too long.")

    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("Expression is too complex.")

    def evaluate(node: ast.AST) -> int | float:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](evaluate(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent must be between -100 and 100.")
            result = _BINARY_OPERATORS[type(node.op)](left, right)
            if not math.isfinite(result):
                raise ValueError("Result is outside the supported numeric range.")
            return result
        raise ValueError("Only basic arithmetic is allowed.")

    return evaluate(tree.body)


def execute_tool(name: str, arguments: dict, knowledge_base=None) -> str:
    if name == "search_knowledge_base":
        if knowledge_base is None:
            return "The knowledge base is unavailable."
        return knowledge_base.search(arguments["query"])
    if name == "calculate":
        return str(calculate(arguments["expression"]))
    if name == "get_current_time":
        timezone = arguments.get("timezone", "UTC")
        current_time = datetime.now(ZoneInfo(timezone))
        return current_time.isoformat(timespec="seconds")
    return f"Unknown tool: {name}"


def run_agent(
    client,
    model: str,
    messages: list[dict[str, str]],
    on_tool: Callable[[str, dict, str], None] | None = None,
    knowledge_base=None,
    top_k: int = 5,
) -> str:
    original_query = next(
        (
            message["content"]
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    ).strip()
    rag_debug_log(f"Incoming user question: {original_query}")

    # Stage 1: Fast Intent Classification (No unnecessary retrieval or LLM calls)
    # 1.1 Conversational greetings and acknowledgments
    is_conv, conv_reply = is_basic_conversation(original_query)
    if is_conv and conv_reply:
        rag_debug_log(f"Stage 1 basic conversation: {conv_reply}")
        return conv_reply

    # 1.2 Knowledge base discovery requests
    if is_kb_discovery(original_query):
        rag_debug_log("Stage 1 knowledge base discovery request.")
        if knowledge_base is None:
            return "The knowledge base is currently unavailable."
        overview_context = knowledge_base.get_knowledge_base_overview()
        return generate_kb_discovery_answer(client, model, overview_context)

    # 1.3 Arithmetic / explicit out-of-scope math
    if is_unrelated_factual_or_math(original_query):
        rag_debug_log("Stage 1 unrelated math/calculation detected -> Refusing.")
        return UNRELATED_REFUSAL_ANSWER

    # Stage 2: Knowledge Base Retrieval & Relevance Evaluation
    if knowledge_base is None:
        return NOT_AVAILABLE_ANSWER

    # 2.1 Query normalization and expansion for short / entity queries
    expanded_query = expand_query_for_retrieval(original_query)
    rag_debug_log(
        f"Stage 2 query normalization/expansion: '{original_query}' -> '{expanded_query}'"
    )

    # 2.2 Retrieve multiple relevant chunks with deduplication
    queries = [original_query]
    if expanded_query != original_query:
        queries.append(expanded_query)

    documents = knowledge_base.retrieve_multi_query(queries, limit=top_k)

    # 2.3 Evaluate relevance score using Qdrant distance metric semantics
    threshold = get_similarity_threshold()
    max_score = max(
        (d["score"] for d in documents if d.get("score") is not None),
        default=0.0,
    )
    has_domain = has_domain_affinity(original_query)
    rag_debug_log(
        f"Stage 2 relevance check: max_score={max_score:.4f}, threshold={threshold}, has_domain={has_domain}"
    )

    # Reject unrelated questions when sufficient relevant evidence is unavailable
    if (not documents or max_score < threshold) and not has_domain:
        rag_debug_log("Stage 2 low relevance and no domain affinity -> Refusing.")
        return UNRELATED_REFUSAL_ANSWER

    context = build_context(documents)
    if not context.strip():
        return NOT_AVAILABLE_ANSWER

    # 2.4 Grounded answer generation using only retrieved context
    history = [
        message
        for message in messages[:-1]
        if message.get("role") in {"user", "assistant"}
    ]
    return generate_answer(
        client, model, original_query, context, history=history
    )


def run_agent_stream(
    client,
    model: str,
    messages: list[dict[str, str]],
    knowledge_base=None,
    top_k: int = 5,
    on_first_token: Callable[[float], None] | None = None,
) -> Generator[str, None, None]:
    """Execute agent pipeline yielding complete, natural sentences as soon as they become available."""
    original_query = next(
        (
            message["content"]
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    ).strip()
    rag_debug_log(f"Incoming user question (stream): {original_query}")

    # Stage 1: Fast Intent Classification
    is_conv, conv_reply = is_basic_conversation(original_query)
    if is_conv and conv_reply:
        rag_debug_log(f"Stage 1 basic conversation: {conv_reply}")
        for s in split_into_sentences(conv_reply):
            yield s
        return

    if is_kb_discovery(original_query):
        rag_debug_log("Stage 1 knowledge base discovery request.")
        if knowledge_base is None:
            yield "The knowledge base is currently unavailable."
            return
        overview_context = knowledge_base.get_knowledge_base_overview()
        yield from generate_kb_discovery_answer_stream(
            client, model, overview_context, on_first_token=on_first_token
        )
        return

    if is_unrelated_factual_or_math(original_query):
        rag_debug_log("Stage 1 unrelated math/calculation detected -> Refusing.")
        yield UNRELATED_REFUSAL_ANSWER
        return

    # Stage 2: Knowledge Base Retrieval & Relevance Evaluation
    if knowledge_base is None:
        yield NOT_AVAILABLE_ANSWER
        return

    expanded_query = expand_query_for_retrieval(original_query)
    rag_debug_log(
        f"Stage 2 query normalization/expansion: '{original_query}' -> '{expanded_query}'"
    )

    queries = [original_query]
    if expanded_query != original_query:
        queries.append(expanded_query)

    documents = knowledge_base.retrieve_multi_query(queries, limit=top_k)

    threshold = get_similarity_threshold()
    max_score = max(
        (d["score"] for d in documents if d.get("score") is not None),
        default=0.0,
    )
    has_domain = has_domain_affinity(original_query)
    rag_debug_log(
        f"Stage 2 relevance check: max_score={max_score:.4f}, threshold={threshold}, has_domain={has_domain}"
    )

    if (not documents or max_score < threshold) and not has_domain:
        rag_debug_log("Stage 2 low relevance and no domain affinity -> Refusing.")
        yield UNRELATED_REFUSAL_ANSWER
        return

    context = build_context(documents)
    if not context.strip():
        yield NOT_AVAILABLE_ANSWER
        return

    history = [
        message
        for message in messages[:-1]
        if message.get("role") in {"user", "assistant"}
    ]
    yield from generate_answer_stream(
        client, model, original_query, context, history=history, on_first_token=on_first_token
    )