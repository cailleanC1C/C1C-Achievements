import importlib
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]

if "cogs" not in sys.modules:
    cogs_pkg = types.ModuleType("cogs")
    cogs_pkg.__path__ = [str(ROOT / "cogs")]
    sys.modules["cogs"] = cogs_pkg

if "cogs.shards" not in sys.modules:
    shards_pkg = types.ModuleType("cogs.shards")
    shards_pkg.__path__ = [str(ROOT / "cogs" / "shards")]
    sys.modules["cogs.shards"] = shards_pkg

ocr = importlib.import_module("cogs.shards.ocr")

_OcrToken = ocr._OcrToken
_merge_band_tokens = ocr._merge_band_tokens


def test_merge_band_tokens_prefers_single_duplicate():
    tok1 = _OcrToken(left=10, top=5, width=20, height=12, conf=87.5, text="123")
    tok2 = _OcrToken(left=11, top=6, width=19, height=12, conf=65.0, text="123")

    merged = _merge_band_tokens([tok1, tok2])

    assert len(merged) == 1
    assert merged[0].text == "123"
    assert merged[0].conf == tok1.conf
