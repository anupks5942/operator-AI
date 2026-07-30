import re

SYMBOL_REPLACEMENTS = [
    (re.compile(r"\s*==\s*"), " is "),
    (re.compile(r"\s*->\s*"), " leads to "),
    (re.compile(r"\s*!=\s*"), " is not "),
    (re.compile(r"[_]+"), " "),
    (re.compile(r"[{}\[\]<>|~^*#]+"), " "),
]


def format_for_voice(text: str):
    # Symbol/token cleanup first — must run before the generic "-" strip
    # below, otherwise things like "->" get mangled instead of expanded.
    for pattern, replacement in SYMBOL_REPLACEMENTS:
        text = pattern.sub(replacement, text)

    text = text.replace("**", "")
    text = text.replace("#", "")
    text = text.replace("\n", " ")
    text = text.replace("-", " ")

    text = re.sub(r"\s+", " ", text)

    return text.strip()