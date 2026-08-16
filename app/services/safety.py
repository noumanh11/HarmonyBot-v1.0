"""Crisis detection.

A bot that invites people to talk about feeling suicidal needs a path that
does not depend on the model behaving well. When these phrases appear we
prepend helpline information deterministically, before generation, so the
resources are shown even if the model output is poor or the API call fails.
"""

from __future__ import annotations

import re

_CRISIS_PATTERNS = [
    r"\bkill(ing)?\s+my\s?self\b",
    r"\bsuicid(e|al)\b",
    r"\bend(ing)?\s+(my|it)\s+(life|all)\b",
    r"\btake\s+my\s+own\s+life\b",
    r"\bself[\s-]?harm\b",
    r"\bcut(ting)?\s+my\s?self\b",
    r"\bdon'?t\s+want\s+to\s+(live|be\s+here)\b",
    r"\bwant\s+to\s+die\b",
    r"\bno\s+reason\s+to\s+live\b",
]

_CRISIS_RE = re.compile("|".join(_CRISIS_PATTERNS), re.IGNORECASE)

CRISIS_NOTICE = """
> **If you are in immediate danger, please reach out for help right now.**
>
> - **US:** call or text **988** (Suicide & Crisis Lifeline)
> - **UK & ROI:** call **116 123** (Samaritans)
> - **Pakistan:** call **1166** (Umang) or **042-35761999** (Rozan)
> - **Anywhere:** contact your local emergency number, or find a helpline at
>   [findahelpline.com](https://findahelpline.com)
>
> You deserve support from someone trained to give it. I am an AI and cannot
> provide crisis care.
""".strip()


def is_crisis(message: str) -> bool:
    return bool(_CRISIS_RE.search(message))
