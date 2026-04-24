from typing import Optional

from pydantic import BaseModel, ConfigDict


class RadarBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow")  # Accept unknown fields


class MetaResult(BaseModel):
    code: int


class Geometry(RadarBaseModel):
    type: str
    coordinates: list[float]  # [lng, lat]


class TimeZoneInfo(RadarBaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    code: Optional[str] = None
    currentTime: Optional[str] = None
    utcOffset: Optional[int] = None
    dstOffset: Optional[int] = None


class RadarAddress(RadarBaseModel):
    addressLabel: Optional[str] = None
    number: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    stateCode: Optional[str] = None
    postalCode: Optional[str] = None
    county: Optional[str] = None
    country: Optional[str] = None
    countryCode: Optional[str] = None
    countryFlag: Optional[str] = None
    formattedAddress: Optional[str] = None
    placeLabel: Optional[str] = None
    layer: Optional[str]
    latitude: float
    longitude: float
    distance: Optional[float] = None
    geometry: Optional[Geometry] = None
    timeZone: Optional[TimeZoneInfo] = None


class RadarReverseGeocodeResponse(RadarBaseModel):
    meta: MetaResult
    addresses: list[RadarAddress]
