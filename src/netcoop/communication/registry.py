"""Capability registry and profile validation for tower interactions."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from netcoop.models.enums import TowerId


class TowerCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    input_schema: str
    output_schema: str
    read_only: bool = True


class TowerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    capabilities: list[TowerCapability] = Field(default_factory=list)


def get_capabilities_path() -> Path:
    current = Path(__file__).resolve().parent
    for _ in range(4):
        candidate = current / "config" / "capabilities.yaml"
        if candidate.exists():
            return candidate
        current = current.parent
    candidate = Path.cwd() / "config" / "capabilities.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError("Could not locate config/capabilities.yaml")


class CapabilityRegistry:
    """In-memory registry of tower capabilities loaded from config/capabilities.yaml."""

    def __init__(self, profiles: dict[TowerId, TowerProfile]) -> None:
        self._profiles = profiles
        self._capabilities: dict[str, tuple[TowerId, TowerCapability]] = {}
        for tower_id, profile in profiles.items():
            for cap in profile.capabilities:
                self._capabilities[cap.id] = (tower_id, cap)

    @classmethod
    def load(cls, path: Path | None = None) -> "CapabilityRegistry":
        file_path = path or get_capabilities_path()
        with open(file_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        profiles: dict[TowerId, TowerProfile] = {}
        towers_raw = raw.get("towers", {})
        for tower_key, data in towers_raw.items():
            tower_id = TowerId(tower_key)
            capabilities = [
                TowerCapability(
                    id=c["id"],
                    description=c["description"],
                    input_schema=c["input_schema"],
                    output_schema=c["output_schema"],
                    read_only=c.get("read_only", True),
                )
                for c in data.get("capabilities", [])
            ]
            profiles[tower_id] = TowerProfile(
                name=data["name"],
                description=data["description"],
                capabilities=capabilities,
            )

        return cls(profiles)

    def get_capability(self, capability_id: str) -> TowerCapability | None:
        pair = self._capabilities.get(capability_id)
        return pair[1] if pair else None

    def get_tower_for_capability(self, capability_id: str) -> TowerId | None:
        pair = self._capabilities.get(capability_id)
        return pair[0] if pair else None

    def list_capabilities_for_tower(self, tower_id: TowerId) -> list[TowerCapability]:
        profile = self._profiles.get(tower_id)
        return profile.capabilities if profile else []

    def validate_capability_exists(self, capability_id: str) -> bool:
        return capability_id in self._capabilities

    def validate_query(self, recipient: TowerId, capability_id: str) -> tuple[bool, str]:
        """Validates that the recipient tower owns the requested capability and it is read-only."""
        owner = self.get_tower_for_capability(capability_id)
        if owner is None:
            return False, f"Capability '{capability_id}' is not registered."
        if owner != recipient:
            return False, f"Capability '{capability_id}' is owned by '{owner.value}', not '{recipient.value}'."
        cap = self.get_capability(capability_id)
        if not cap or not cap.read_only:
            return False, f"Capability '{capability_id}' is not marked as read-only."
        return True, "Valid"
