"""Static-resource acquisition over the shared streaming HTTP boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from ..catalogs.endpoints import STATIC_RESOURCE_ENDPOINTS
from ..codecs.http_date import HttpDateCodec
from ..platform import EndpointSpec, HttpTransport
from ..stores.resources import StaticDownload, StaticResourceStore


class TfnswStaticResourceRepository(StaticResourceStore):
    def __init__(
        self,
        transport: HttpTransport,
        *,
        endpoints: Mapping[str, EndpointSpec] = STATIC_RESOURCE_ENDPOINTS,
        dates: HttpDateCodec | None = None,
    ) -> None:
        self._transport = transport
        self._endpoints = dict(endpoints)
        self._dates = dates or HttpDateCodec()

    def download(
        self,
        resource: str,
        destination: Path,
        *,
        if_modified_since: datetime | None = None,
    ) -> StaticDownload:
        payload = self._transport.download(
            self._endpoints[resource],
            destination,
            if_modified_since=self._dates.encode(if_modified_since),
        )
        return StaticDownload(
            not_modified=payload.not_modified,
            last_modified=self._dates(payload.last_modified),
        )
