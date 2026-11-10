class QuotaExceeded(Exception):
    pass


class QuotaService:
    """Placeholder for tenant quotas and usage accounting."""

    def ensure_capacity(self, *, current: int, limit: int) -> None:
        if current >= limit:
            raise QuotaExceeded("Quota exceeded")
