import importlib
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]

if "cogs" not in sys.modules:
    cogs_pkg = types.ModuleType("cogs")
    cogs_pkg.__path__ = [str(ROOT / "cogs")]
    sys.modules["cogs"] = cogs_pkg

if "cogs.shards" not in sys.modules:
    shards_pkg = types.ModuleType("cogs.shards")
    shards_pkg.__path__ = [str(ROOT / "cogs" / "shards")]
    sys.modules["cogs.shards"] = shards_pkg

constants = importlib.import_module("cogs.shards.constants")
ocr = importlib.import_module("cogs.shards.ocr")

ShardType = constants.ShardType
_LABEL_TO_ST = ocr._LABEL_TO_ST
_label_key = ocr._label_key


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Void Shardss", ShardType.VOID),
        ("Ancients", ShardType.ANCIENT),
        ("Mystery Shards", ShardType.MYSTERY),
        ("Sacredss", ShardType.SACRED),
    ],
)
def test_label_key_handles_extra_s(label: str, expected: ShardType) -> None:
    key = _label_key(label)
    assert key is not None
    assert _LABEL_TO_ST[key] == expected
