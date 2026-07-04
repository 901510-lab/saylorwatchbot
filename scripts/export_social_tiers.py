#!/usr/bin/env python3
"""Экспорт коллажей и текста для поста «Free vs Premium» в соцсетях.

Примеры:
  python3 scripts/export_social_tiers.py
  python3 scripts/export_social_tiers.py --lang ru --out assets/social
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plan_showcase import (  # noqa: E402
    build_social_collages,
    build_start_showcase_images,
    format_social_tiers_summary,
    get_showcase_sets,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export social tiers showcase")
    parser.add_argument("--lang", choices=("en", "ru"), default="en")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "assets" / "social",
        help="Output directory for PNG + text",
    )
    args = parser.parse_args()

    free_sigs, prem_sigs = get_showcase_sets()
    free_start, prem_start = build_start_showcase_images(free_sigs, prem_sigs, args.lang)
    free_soc, prem_soc = build_social_collages(free_sigs, prem_sigs)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    text = format_social_tiers_summary(args.lang)
    text_path = out_dir / f"tiers_post_{args.lang}.txt"
    text_path.write_text(text, encoding="utf-8")

    saved: list[str] = [str(text_path)]
    for name, img in (
        (f"start_free_{args.lang}.png", free_start),
        (f"start_premium_{args.lang}.png", prem_start),
        (f"social_free_{args.lang}.png", free_soc),
        (f"social_premium_{args.lang}.png", prem_soc),
    ):
        if img is None:
            continue
        path = out_dir / name
        path.write_bytes(img.getvalue())
        saved.append(str(path))

    print(format_social_tiers_summary(args.lang))
    print()
    print("Saved files:")
    for p in saved:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
