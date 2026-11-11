"""Guards that the ru bundles stay in sync with en and are actually translated."""
import json
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_BUNDLES = {
    "frontend": _BACKEND.parent / "frontend" / "i18n",
    "backend": _BACKEND / "messages",
}
_TRANSLATED_UI_KEYS = (
    "preplanning.impactAnalysis", "phase.impactAnalysis", "diff.tree", "diff.list",
    "diff.sideBySide", "diff.inline", "diff.branch", "diff.uncommitted",
)


def _load(bundle, locale):
    return json.loads((_BUNDLES[bundle] / f"{locale}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("bundle", sorted(_BUNDLES))
def test_ru_bundle_has_every_en_key(bundle):
    missing = set(_load(bundle, "en")) - set(_load(bundle, "ru"))

    assert missing == set()


@pytest.mark.parametrize("key", _TRANSLATED_UI_KEYS)
def test_ru_frontend_value_differs_from_en(key):
    assert _load("frontend", "ru")[key] != _load("frontend", "en")[key]
