from uuid import UUID


class UUIDNotFoundError(Exception):
    def __init__(self, uuid: UUID | None = None):
        detail = f"UUID not found: {uuid}" if uuid else "UUID not found"
        super().__init__(detail)
