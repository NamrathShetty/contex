from __future__ import annotations

import re

try:
    import tiktoken as _tiktoken  # type: ignore[import-untyped]

    _ENC = _tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_ENC.encode(text))

    TOKENIZER_LABEL = "tiktoken cl100k_base"

except Exception:
    _ENC = None  # type: ignore[assignment]
    _WORD_RE = re.compile(r"\S+")

    def count_tokens(text: str) -> int:  # type: ignore[misc]
        """Approximates cl100k token count without tiktoken (~4 chars/token)."""
        return max(1, len(text) // 4) if text else 0

    TOKENIZER_LABEL = "approx (÷4)"
