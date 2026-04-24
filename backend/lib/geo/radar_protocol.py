from typing import Protocol

from .radar_models import RadarReverseGeocodeResponse


class RadarHttpClientProtocol(Protocol):
    async def reverse_geocode(
        self, lat: float, lng: float
    ) -> RadarReverseGeocodeResponse: ...
    async def close(self) -> None: ...
