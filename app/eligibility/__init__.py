"""Stage 4: Seller Eligibility Engine.

Deterministic eligibility evaluation based on:
- Stage 3B deterministic fields
- Stage 3C grounded requirements
- Seller profile (attributes, documents)

No LLM or external dependencies.
"""

from typing import Optional, Dict, List, Any

__all__ = [
    "constants",
    "engine",
    "models",
    "service",
    "utils",
]
