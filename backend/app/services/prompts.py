PROMPT_SUFFIX_HEADER = "【全局补充要求】"


def compose_prompt(original: str, global_suffix: str | None) -> str:
    """Append a stage-specific global prompt without altering imported text."""
    suffix = (global_suffix or "").strip()
    if not suffix:
        return original
    return f"{original}\n\n{PROMPT_SUFFIX_HEADER}\n{suffix}"
