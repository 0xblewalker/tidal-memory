import re

from .models import RecallPolicy


EXPLICIT = re.compile(
    r"(remember|recall|last time|before|previously|used to|"
    r"还记得|你记得|上次|以前|之前|当时|我们聊过|我说过|你说过)",
    re.IGNORECASE,
)
CONTEXTUAL = re.compile(
    r"(again|continue|what about|that person|that thing|"
    r"继续|又|那次|那个人|那个事|后来|怎么.*的)",
    re.IGNORECASE,
)


def should_recall(message: str, policy: RecallPolicy) -> bool:
    text = message.strip()
    if len(text) < 2:
        return False
    if policy.trigger == "active":
        return True
    if EXPLICIT.search(text):
        return True
    return policy.trigger == "balanced" and bool(CONTEXTUAL.search(text))

