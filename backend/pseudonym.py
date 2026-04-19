"""Deterministic wallet alias generator (animal style for SignalView display)."""
import hashlib

_ANIMALS = [
    "RHINO","ORACLE","CICADA","WOLF","FOX","HERON",
    "OTTER","RAVEN","PANDA","HAWK","LYNX","GECKO",
    "KOI","MARLIN","FINCH","IBEX","MAMBA","OSPREY",
]

def alias_for_wallet(addr: str) -> str:
    if not addr:
        return "ANON"
    h = hashlib.md5(addr.lower().encode()).hexdigest()
    return _ANIMALS[int(h[:8], 16) % len(_ANIMALS)]
