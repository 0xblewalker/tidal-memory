"""Minimal framework-agnostic integration example."""

from tidal_memory import RecallPolicy, TidalMemory


memory = TidalMemory(
    "example.db",
    policy=RecallPolicy(
        trigger="balanced",
        association="direct_plus_one_hop",
        max_items=2,
        max_chars=900,
    ),
)


def build_model_messages(conversation_id: str, history: list[dict], user_text: str):
    messages = list(history)
    if not history:
        impression = memory.opening_context(conversation_id)
        if impression:
            messages.append({
                "role": "system",
                "content": "<memory source=\"impression\">\n" + impression + "\n</memory>",
            })
    detail = memory.recall(user_text)
    content = user_text
    if detail:
        content += "\n\n<memory source=\"recalled_detail\">\n" + detail + "\n</memory>"
    messages.append({"role": "user", "content": content})
    return messages


def close_window(conversation_id: str, messages: list[dict]):
    memory.close_window(conversation_id, messages, title="A normal conversation")
