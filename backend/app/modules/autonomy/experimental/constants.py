"""Single source of ADR025 experimental constants (ADR-028).

Lab-side values come from the versioned stdlib contract ``emulation.lab_contracts``
(drift-tested against the frozen v4 files and the ai-engine routing contract); nothing
here is re-derived or duplicated elsewhere in the experimental package.
"""

from emulation.lab_contracts import (
    ACTION_IDS,
    ACTION_PATHS,
    FOREGROUND_PAIRS,
    UDP_DATAGRAM_BYTES,
    validate_route_readback,
)

# route id -> exact frozen v4 switch path (access1 -> dist{1,2} -> access2).
ROUTE_PATHS = dict(zip(ACTION_IDS, ACTION_PATHS, strict=True))
# Frozen v4 UDP workload payload: receiver bytes == packets * DATAGRAM_BYTES.
DATAGRAM_BYTES = UDP_DATAGRAM_BYTES
# Exact frozen v4 client contract digest carried by every passive snapshot.
CONTRACT_HASH = "bbcbbadec55792fa3f01bef511c1e38b0e433e125f896cdc3e64f823325e0fe6"
FOREGROUND_KEYS = tuple(f"{source}->{destination}" for source, destination in FOREGROUND_PAIRS)

__all__ = ["CONTRACT_HASH", "DATAGRAM_BYTES", "FOREGROUND_KEYS", "ROUTE_PATHS", "validate_route_readback"]
