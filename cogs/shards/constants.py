from enum import Enum

class ShardType(str, Enum):
    MYSTERY = "mystery"   # 🟩
    ANCIENT = "ancient"   # 🟦
    VOID    = "void"      # 🟪
    PRIMAL  = "primal"    # 🟥
    SACRED  = "sacred"    # 🟨

# Canonical display order everywhere
DISPLAY_ORDER = [
    ShardType.MYSTERY,
    ShardType.ANCIENT,
    ShardType.VOID,
    ShardType.PRIMAL,
    ShardType.SACRED,
]

class Rarity(str, Enum):
    EPIC = "epic"
    LEGENDARY = "legendary"
    MYTHICAL = "mythical"  # Primal only

# Short pity labels (mobile-tidy)
# Rendered in this order on the pity line
PITY_LABELS = [
    ("L-Anc", ShardType.ANCIENT,  Rarity.LEGENDARY),
    ("E-Anc", ShardType.ANCIENT,  Rarity.EPIC),
    ("L-Void",ShardType.VOID,     Rarity.LEGENDARY),
    ("E-Void",ShardType.VOID,     Rarity.EPIC),
    ("L-Pri", ShardType.PRIMAL,   Rarity.LEGENDARY),
    ("M-Pri", ShardType.PRIMAL,   Rarity.MYTHICAL),
    ("L-Sac", ShardType.SACRED,   Rarity.LEGENDARY),
]
