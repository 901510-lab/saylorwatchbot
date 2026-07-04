"""Печать шаблонов постов для X и Reddit (Day 27).

Примеры:
    python3 post_social.py x announce
    python3 post_social.py reddit weekly
    python3 post_social.py reddit comment
"""

import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from social_growth import POST_KINDS, format_share_message, list_share_options


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python3 post_social.py <x|reddit> <kind>")
        print()
        print(list_share_options())
        return 1

    platform = sys.argv[1].lower()
    kind = sys.argv[2].lower()
    variant = sys.argv[3].lower() if len(sys.argv) > 3 else None

    if kind not in POST_KINDS:
        print(f"Unknown kind: {kind}. Valid: {', '.join(POST_KINDS)}")
        return 1

    try:
        text = format_share_message(platform, kind, variant=variant)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    print(text)
    if platform == "x":
        print()
        print(f"--- {len(text)} characters ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
