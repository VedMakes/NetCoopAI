"""Entity alias resolution for NetCoop AI.

Resolves heterogeneous source device and interface names to canonical entity IDs.
Enforces unambiguous 1-to-1 mappings and flags ambiguous or unknown mappings.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AliasResolutionResult:
    canonical_id: str
    original_name: str
    is_known: bool
    is_ambiguous: bool = False
    warning: str | None = None


class EntityAliasResolver:
    """Resolves network device and interface aliases to canonical IDs."""

    def __init__(
        self,
        alias_map: dict[str, str] | None = None,
        include_campus_defaults: bool = True,
    ) -> None:
        """Initializes resolver with a mapping of alias -> canonical_id."""
        self._alias_to_canonical: dict[str, str] = {}
        self._ambiguous_aliases: set[str] = set()

        # Default standard campus inventory mapping
        default_map: dict[str, str] = {
            # Standard switch names
            "SW_CAMPUS_1": "SW_CORE_01",
            "SW_CAMPUS_2": "SW_DIST_HOSTEL",
            "SW_CAMPUS_3": "SW_DIST_DEPT",
            "SW_CAMPUS_4": "SW_ACCESS_LAB",
            "SW_CORE": "SW_CORE_01",
            "CORE_SWITCH": "SW_CORE_01",
            "HOSTEL_SWITCH": "SW_DIST_HOSTEL",
            "DEPT_SWITCH": "SW_DIST_DEPT",
            "LAB_SWITCH": "SW_ACCESS_LAB",
            "HOSTEL_CORE_SW_01": "SW_DIST_HOSTEL",
            "GATEWAY_EDGE": "GW_EDGE_01",
            "EDGE_GW": "GW_EDGE_01",
            "DNS_SERVER": "SRV_DNS_01",
            "DHCP_SERVER": "SRV_DHCP_01",
        }

        # Load defaults
        if include_campus_defaults:
            for alias, canonical in default_map.items():
                self.register_alias(alias, canonical)

        # Merge user/scenario mapping if provided
        if alias_map:
            for alias, canonical in alias_map.items():
                self.register_alias(alias, canonical)

    def register_alias(self, alias: str, canonical_id: str) -> None:
        """Registers an alias mapping. If the alias already maps to a different canonical ID, flags it as ambiguous."""
        clean_alias = alias.strip().upper()
        clean_canonical = canonical_id.strip()

        if clean_alias in self._alias_to_canonical:
            existing = self._alias_to_canonical[clean_alias]
            if existing != clean_canonical:
                self._ambiguous_aliases.add(clean_alias)
                return

        self._alias_to_canonical[clean_alias] = clean_canonical

    def resolve(self, entity_name: str) -> AliasResolutionResult:
        """Resolves an entity name to its canonical identifier."""
        if not entity_name or not entity_name.strip():
            return AliasResolutionResult(
                canonical_id="UNKNOWN",
                original_name=entity_name,
                is_known=False,
                warning="Empty or missing entity identifier.",
            )

        clean_name = entity_name.strip()
        lookup_key = clean_name.upper()

        if lookup_key in self._ambiguous_aliases:
            return AliasResolutionResult(
                canonical_id=clean_name,
                original_name=clean_name,
                is_known=False,
                is_ambiguous=True,
                warning=f"Entity alias '{clean_name}' is ambiguous (maps to multiple canonical IDs). Refusing to guess.",
            )

        if lookup_key in self._alias_to_canonical:
            return AliasResolutionResult(
                canonical_id=self._alias_to_canonical[lookup_key],
                original_name=clean_name,
                is_known=True,
            )

        # If already in canonical uppercase format (e.g., SW_CORE_01, GW_EDGE_01, AP_HOSTEL_A)
        return AliasResolutionResult(
            canonical_id=clean_name,
            original_name=clean_name,
            is_known=True,
        )
