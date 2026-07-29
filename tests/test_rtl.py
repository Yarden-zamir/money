"""RTL guards for the web app.

Hebrew is a first-class language here, and the ways an RTL layout breaks are boring and
repetitive: someone writes `ml-4` instead of `ms-4`, or formats an amount by hand. These
checks are cheap and catch exactly that, without adding a JavaScript lint toolchain.

See specs/web-and-rtl.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB_SRC = Path(__file__).resolve().parents[1] / "web" / "src"

# Physical direction utilities. Their logical counterparts (ms-/me-/ps-/pe-/start-/end-) are
# what keeps a layout correct when `dir` flips.
PHYSICAL = re.compile(
    r"(?<![\w-])(ml|mr|pl|pr|left|right|border-l|border-r|rounded-l|rounded-r|text-left|text-right)-"
)

REPLACEMENTS = {
    "ml": "ms",
    "mr": "me",
    "pl": "ps",
    "pr": "pe",
    "left": "start",
    "right": "end",
    "text-left": "text-start",
    "text-right": "text-end",
}


def app_sources() -> list[Path]:
    """Hand-written sources only. The generated API client is not ours to style."""
    return [
        path
        for path in WEB_SRC.rglob("*.ts*")
        if "api/" not in path.relative_to(WEB_SRC).as_posix()
    ]


@pytest.mark.parametrize("path", app_sources(), ids=lambda p: p.name)
def test_no_physical_direction_classes(path: Path) -> None:
    matches = PHYSICAL.findall(path.read_text(encoding="utf-8"))
    assert not matches, (
        f"{path.name} uses physical direction utilities {sorted(set(matches))}. "
        f"Use logical ones instead: {REPLACEMENTS}"
    )


def test_amounts_render_through_one_component() -> None:
    """`Intl.NumberFormat` for currency belongs in exactly one place.

    Formatting money ad hoc is how a minus sign ends up on the wrong side of a number inside
    Hebrew text, so the bidi isolation in lib/format.ts must stay the only path.
    """
    offenders = [
        path.name
        for path in app_sources()
        if 'style: "currency"' in path.read_text(encoding="utf-8") and path.name != "format.ts"
    ]
    assert not offenders, f"currency formatting outside lib/format.ts: {offenders}"


def test_the_formatter_isolates_amounts() -> None:
    """The isolate characters are invisible; a well-meaning cleanup could delete them.

    It must be FIRST STRONG ISOLATE, not LEFT-TO-RIGHT ISOLATE. Intl already emits the
    directional marks each locale needs, and forcing LTR fought them — that is what made the
    shekel symbol land on a different side depending on the sign.
    """
    source = (WEB_SRC / "lib" / "format.ts").read_text(encoding="utf-8")
    assert "\u2068" in source, "missing FIRST STRONG ISOLATE in formatMoney"
    assert "\u2069" in source, "missing POP DIRECTIONAL ISOLATE in formatMoney"
    assert "\u2066" not in source, "LEFT-TO-RIGHT ISOLATE overrides the locale's own marks"


def test_fixed_width_fields_opt_out_of_full_width() -> None:
    """`Input`/`Select` add `w-full` unless told not to.

    A caller passing `w-24` alongside it is fighting a utility of equal specificity, so which
    one wins depends on stylesheet order — that is how the assign field silently became full
    width. A fixed width must come with `fullWidth={false}`.
    """
    # Matches a whole self-closing <Input .../> or <Select .../> element, across lines.
    element = re.compile(r"<(?:Input|Select)\b[^>]*?/>", re.DOTALL)
    # A width utility at the start of a class or after a space, so min-w-/max-w- do not match.
    fixed_width = re.compile(r'(?<![-\w])w-(?:\d|\[)')

    offenders: list[str] = []
    for path in app_sources():
        for block in element.findall(path.read_text(encoding="utf-8")):
            classes = re.findall(r'className="([^"]*)"', block)
            if not any(fixed_width.search(value) for value in classes):
                continue
            if "fullWidth={false}" not in block:
                offenders.append(f"{path.name}: {' '.join(classes)[:60]}")

    assert not offenders, f"fixed-width field without fullWidth={{false}}: {offenders}"


def test_no_styles_reference_removed_theme_tokens() -> None:
    """A class naming a colour the theme no longer defines renders as nothing at all.

    Tailwind simply does not emit the rule, so the element loses its background silently
    rather than failing the build.
    """
    theme = (WEB_SRC / "index.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"--color-([a-z-]+):", theme))

    used: set[str] = set()
    for path in app_sources():
        for match in re.findall(
            r'(?:bg|text|border|ring|divide|from|to)-([a-z][a-z-]*)', path.read_text("utf-8")
        ):
            used.add(match)

    # Only colour-ish names are checked; layout utilities share the same prefixes.
    suspects = {name for name in used if name.split("/")[0] in {"surface-raised", "ink-soft"}}
    assert not suspects, f"styles reference removed theme tokens: {sorted(suspects)}"
    assert "card" in defined and "surface" in defined


def test_both_locales_define_the_same_keys() -> None:
    """A missing Hebrew key silently falls back to English, which is easy not to notice."""
    import json

    def flatten(data: dict, prefix: str = "") -> set[str]:
        keys: set[str] = set()
        for key, value in data.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                keys |= flatten(value, f"{path}.")
            else:
                keys.add(path)
        return keys

    english = flatten(json.loads((WEB_SRC / "locales/en/common.json").read_text("utf-8")))
    hebrew = flatten(json.loads((WEB_SRC / "locales/he/common.json").read_text("utf-8")))

    assert english - hebrew == set(), f"missing Hebrew translations: {sorted(english - hebrew)}"
    orphans = sorted(hebrew - english)
    assert not orphans, f"Hebrew keys with no English source: {orphans}"


def test_the_document_starts_in_hebrew() -> None:
    index = (WEB_SRC.parent / "index.html").read_text(encoding="utf-8")
    assert 'lang="he"' in index
    assert 'dir="rtl"' in index
