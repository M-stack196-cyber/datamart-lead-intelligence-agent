import json
from pathlib import Path
from typing import Any

from app.schemas.icp import IcpDefinition, IcpStatus, IcpVersionSummary


class IcpRepository:
    """File-backed ICP repository; replaceable by Supabase without changing callers."""

    def __init__(self, data_directory: Path | None = None) -> None:
        self.data_directory = data_directory or (
            Path(__file__).resolve().parents[2] / "data" / "icp_versions"
        )

    def _paths(self) -> list[Path]:
        return sorted(self.data_directory.glob("*.json"))

    def list_versions(self) -> list[IcpVersionSummary]:
        definitions = [self._read(path) for path in self._paths()]
        return [
            IcpVersionSummary(
                id=item.id,
                name=item.name,
                version=item.version,
                status=item.status,
                effective_date=item.effective_date,
                source=item.source,
            )
            for item in sorted(definitions, key=lambda value: value.version, reverse=True)
        ]

    def get_active(self) -> IcpDefinition:
        active = [item for item in (self._read(path) for path in self._paths()) if item.status == IcpStatus.ACTIVE]
        if len(active) != 1:
            raise RuntimeError(f"Expected exactly one active ICP version, found {len(active)}")
        return active[0]

    def get(self, icp_id: str) -> IcpDefinition:
        for path in self._paths():
            definition = self._read(path)
            if definition.id == icp_id:
                return definition
        raise KeyError(icp_id)

    def create_draft(self, changes: dict[str, Any]) -> IcpDefinition:
        """Create a new immutable-version candidate from the active definition."""
        active = self.get_active()
        next_version = max((item.version for item in self.list_versions()), default=0) + 1
        protected = {"id", "version", "status", "approved_by"}
        editable_changes = {key: value for key, value in changes.items() if key not in protected}
        draft = active.model_copy(
            update={
                **editable_changes,
                "id": f"datamart-icp-v{next_version}",
                "version": next_version,
                "status": IcpStatus.DRAFT,
                "approved_by": None,
            }
        )
        validated = IcpDefinition.model_validate(draft.model_dump())
        self._write(validated)
        return validated

    def publish(self, icp_id: str, approved_by: str) -> IcpDefinition:
        """Archive the active version and activate a reviewed draft."""
        candidate = self.get(icp_id)
        if candidate.status != IcpStatus.DRAFT:
            raise ValueError("Only a draft ICP can be published")
        active = self.get_active()
        self._write(active.model_copy(update={"status": IcpStatus.ARCHIVED}))
        published = candidate.model_copy(
            update={"status": IcpStatus.ACTIVE, "approved_by": approved_by}
        )
        self._write(published)
        return published

    def archive_draft(self, icp_id: str) -> IcpDefinition:
        candidate = self.get(icp_id)
        if candidate.status != IcpStatus.DRAFT:
            raise ValueError("Only a draft ICP can be archived directly")
        archived = candidate.model_copy(update={"status": IcpStatus.ARCHIVED})
        self._write(archived)
        return archived

    def _write(self, definition: IcpDefinition) -> None:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        destination = self.data_directory / f"{definition.id}.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(definition.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)

    @staticmethod
    def _read(path: Path) -> IcpDefinition:
        return IcpDefinition.model_validate(json.loads(path.read_text(encoding="utf-8")))


icp_repository = IcpRepository()
