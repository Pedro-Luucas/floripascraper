"""Rename each layer folder in ``data/shp_camadas/`` to the human-readable
name shown on https://geo.pmf.sc.gov.br/downloads/camadas-em-sig-do-mapa,
normalized to lowercase with spaces (e.g. ``- Cadastro - Quadras`` becomes
``cadastro quadras``).

The page is a React SPA, so the displayed names come from the same
geowise API the scraper already uses:

    GET https://geofloripa.pmf.sc.gov.br/geowise/mapa/get_map_by_target
            ?target=geoportal
    Headers:
        X-User-Login: geoportal
        X-User-Token: 3969c9daaccf836c6874c5de4f7b182a

For every WMS/WFS group, each ``layers[i].name`` is the text rendered
inside the row's ``<td class="p-2 w-100 align-middle font-weight-bold">``
on the public page. We pair that name with the ``layers[i].layer`` key
(== the ``typeName`` in the SHP URL), then look up the matching folder
in ``data/shp_camadas/`` (current naming is
``Geoportal__<layer>.zip``, but we match case-insensitively to be
robust against ``Geoportal__MDT``-style folder names).

Normalization rules
-------------------
  * Trim leading/trailing whitespace.
  * Replace every `` - `` separator with a single space.
  * Collapse repeated whitespace and lower-case the whole string.
  * Map ``²`` -> ``2`` and ``º`` -> ``no`` (the two non-accent
    non-ASCII characters the site uses, like ``m²`` and ``nº``).
"""

import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHPDIR = ROOT / "data" / "shp_camadas"

API_URL = (
    "https://geofloripa.pmf.sc.gov.br/geowise/mapa/get_map_by_target?target=geoportal"
)
API_HEADERS = {
    "X-User-Login": "geoportal",
    "X-User-Token": "3969c9daaccf836c6874c5de4f7b182a",
    "User-Agent": "Mozilla/5.0",
}

_WS_RE = re.compile(r"\s+")
# Word-level replacements for the two non-accent Latin-1 characters the
# site actually uses: superscript-2 in "m²" and ordinal indicator in
# "nº". Do these as whole-word swaps so "nº 480" doesn't become "nno 480".
_CHAR_MAP = str.maketrans({"²": "2", "º": "no"})
_TOKEN_REPL = [
    (re.compile(r"nº", re.IGNORECASE), "no"),
    (re.compile(r"m²", re.IGNORECASE), "m2"),
]
# Folder-name safety: keep word chars, parentheses, commas, dots, hyphens
# and Latin-1 letters (the accented range used in Portuguese names). Squash
# everything else to spaces; we then re-collapse those spaces. Necessary
# because the site uses "/" in things like "LC nº 480/2013" and Windows
# rejects "/" in directory names.
_DIR_SAFE_RE = re.compile(r"[^A-Za-z0-9À-ÖØ-öø-ÿ._(),\-]+")


def normalize(name: str) -> str:
    """Turn ``- Cadastro - Quadras`` into ``cadastro quadras`` (no leading ``-``)."""
    cleaned = name.strip()
    for pat, repl in _TOKEN_REPL:
        cleaned = pat.sub(repl, cleaned)
    cleaned = cleaned.translate(_CHAR_MAP)
    # Strip a single leading "- " that the site uses to mark group headers.
    if cleaned.startswith("- "):
        cleaned = cleaned[2:]
    cleaned = cleaned.replace(" - ", " ")
    cleaned = _WS_RE.sub(" ", cleaned)
    cleaned = _DIR_SAFE_RE.sub(" ", cleaned)
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    return cleaned.lower() or "camada"


def norm_no_dash(name: str) -> str:
    """Normalize a folder name that may still carry the leading ``- ``
    from an earlier buggy run. Same as ``normalize`` but tolerates the
    dash being already there (or not)."""
    return normalize(name)


def fetch_layer_index() -> list[dict]:
    """Fetch the raw ``content`` array from the geowise API."""
    req = urllib.request.Request(API_URL, headers=API_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("content", []) if isinstance(payload, dict) else []


def build_mapping(content: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``({layer_key: normalized_name}, {normalized_name: layer_key})``.

    ``layer_key`` is the same string used to build the on-disk folder
    (``<workspace>__<layer>``, lowercased) so we can look it up
    case-insensitively against ``SHPDIR``. The reverse map supports
    folders left behind by a previous buggy run that kept the leading
    ``- `` from the site header.

    The display name on the site is ``<group name> - <layer name>``
    (e.g. ``- Cadastro - Quadras``); the API splits them into separate
    fields so we re-join here.
    """
    mapping: dict[str, str] = {}
    api_to_layer: dict[str, str] = {}
    for group in content:
        if (group.get("type") or "").upper() not in ("WMS", "WFS"):
            continue
        workspace = group.get("workspace") or ""
        if not workspace:
            continue
        group_name = group.get("name") or ""
        for layer in group.get("layers") or []:
            layer_name = layer.get("layer")
            if not layer_name:
                continue
            display = layer.get("name") or layer_name
            full = f"{group_name} - {display}" if group_name else display
            key = f"{workspace}__{layer_name}".lower()
            norm = normalize(full)
            mapping[key] = norm
            api_to_layer[norm] = key
    return mapping, api_to_layer


def find_folder(layer_key: str, api_to_layer: dict[str, str]) -> Path | None:
    """Return the existing folder for ``layer_key``, or ``None``.

    Lookup order:
      1. Exact case-insensitive folder name (the normal happy path:
         ``Geoportal__gvw_quadras``).
      2. Folder whose display name (with the leading ``"- "`` that an
         earlier buggy run left in place) normalizes to the same string
         as the API's full display name for some layer.
      3. Trailing-underscore / trailing-space tolerance, since the
         scraper's ``_safe_filename`` replaces whitespace with ``_`` and
         may also strip a final ``_``.
    """
    for entry in SHPDIR.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.lower() == layer_key:
            return entry
    for entry in SHPDIR.iterdir():
        if not entry.is_dir():
            continue
        if not entry.name.startswith("- "):
            continue
        if api_to_layer.get(norm_no_dash(entry.name)) == layer_key:
            return entry
    bare = layer_key.rstrip("_").strip()
    for entry in SHPDIR.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.lower() == bare:
            return entry
    return None


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    content = fetch_layer_index()
    mapping, api_to_layer = build_mapping(content)
    print(f"API returned {len(mapping)} layer entries")

    planned: list[tuple[Path, Path, str]] = []
    unmatched: list[str] = []
    for key, target_name in mapping.items():
        folder = find_folder(key, api_to_layer)
        if folder is None:
            unmatched.append(key)
            continue
        target = SHPDIR / target_name
        planned.append((folder, target, target_name))

    if unmatched:
        print("WARN: layers with no matching folder on disk (skipped):")
        for k in sorted(unmatched):
            print(f"  {k}")

    # Folders on disk that no API entry references.
    expected = {f for f, _, _ in planned}
    extras = sorted(
        p.name for p in SHPDIR.iterdir() if p.is_dir() and p not in expected
    )
    if extras:
        print("WARN: folders on disk with no API entry (left untouched):")
        for n in extras:
            print(f"  {n}")

    # Collision check on the normalized targets.
    names = [n for _, _, n in planned]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        print("ERROR: normalized name collisions:", sorted(dupes))
        return 1

    print(f"\nPlan: rename {len(planned)} folder(s) under {SHPDIR}")
    for current, target, _ in planned:
        if current.name == target.name:
            print(f"  = {current.name}")
        else:
            print(f"  {current.name}\n    -> {target.name}")

    print()
    if not apply:
        try:
            answer = input("Apply renames? [y/N] ").strip().lower()
        except EOFError:
            print("No TTY available; re-run with --apply to rename.")
            return 0
        if answer != "y":
            print("Aborted.")
            return 0

    renamed = skipped = 0
    for current, target, _ in planned:
        if current == target:
            continue
        if not current.exists():
            print(f"  SKIP (missing): {current.name}")
            skipped += 1
            continue
        if target.exists():
            print(f"  SKIP (target exists): {target.name}")
            skipped += 1
            continue
        current.rename(target)
        renamed += 1
    print(f"Done. {renamed} renamed, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
