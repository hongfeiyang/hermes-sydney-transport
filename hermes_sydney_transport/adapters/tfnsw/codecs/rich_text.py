"""Bounded rich-text decoding before typed wire records reach mappers."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from ..wire.live_traffic import FeatureCollectionWire, FeatureWire, WebLinkWire
from ..wire.trip_planner import (
    AlertsPayloadWire,
    AlertWire,
    JourneyLegWire,
    JourneyPayloadWire,
    JourneyWire,
    SystemMessageEnvelopeWire,
    SystemMessageWire,
)

_WEB_URL = re.compile(
    r"^https?://(?![^/@\s]*@)[^/\s?#]+(?:[/?#][^\s]*)?$", re.IGNORECASE
)


class _PlainTextExtractor(HTMLParser):
    _BREAK_TAGS = frozenset({"br", "div", "li", "p", "tr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in self._BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: str | None, *, max_chars: int = 2_000) -> str:
    """Parse untrusted provider HTML into bounded display text."""

    if not value:
        return ""
    parser = _PlainTextExtractor()
    parser.feed(value)
    parser.close()
    text = " ".join("".join(parser.parts).split())
    return text if len(text) <= max_chars else f"{text[: max_chars - 1].rstrip()}…"


def safe_web_url(value: str | None) -> str | None:
    return value if value and _WEB_URL.fullmatch(value) else None


def normalise_live_traffic(payload: FeatureCollectionWire) -> FeatureCollectionWire:
    return payload.model_copy(
        update={
            "features": tuple(_normalise_feature(item) for item in payload.features)
        }
    )


def normalise_journeys(payload: JourneyPayloadWire) -> JourneyPayloadWire:
    messages = payload.system_messages
    if isinstance(messages, SystemMessageEnvelopeWire):
        messages = messages.model_copy(
            update={
                "response_messages": tuple(
                    _normalise_system_message(item)
                    for item in messages.response_messages
                )
            }
        )
    elif isinstance(messages, tuple):
        messages = tuple(_normalise_system_message(item) for item in messages)
    return payload.model_copy(
        update={
            "journeys": tuple(_normalise_journey(item) for item in payload.journeys),
            "system_messages": messages,
        }
    )


def normalise_alerts(payload: AlertsPayloadWire) -> AlertsPayloadWire:
    if payload.infos is None:
        return payload
    return payload.model_copy(
        update={
            "infos": payload.infos.model_copy(
                update={
                    "current": tuple(
                        _normalise_alert(item) for item in payload.infos.current
                    )
                }
            )
        }
    )


def _normalise_feature(item: FeatureWire) -> FeatureWire:
    properties = item.properties.model_copy(
        update={
            "other_advice": plain_text(item.properties.other_advice, max_chars=1_200),
            "public_transport": plain_text(
                item.properties.public_transport, max_chars=1_200
            ),
            "web_links": tuple(
                _normalise_link(link) for link in item.properties.web_links
            ),
        }
    )
    return item.model_copy(update={"properties": properties})


def _normalise_link(item: WebLinkWire) -> WebLinkWire:
    return item.model_copy(update={"url": safe_web_url(item.url)})


def _normalise_journey(item: JourneyWire) -> JourneyWire:
    return item.model_copy(
        update={"legs": tuple(_normalise_leg(leg) for leg in item.legs)}
    )


def _normalise_leg(item: JourneyLegWire) -> JourneyLegWire:
    return item.model_copy(
        update={
            "hints": tuple(
                hint.model_copy(
                    update={"info_text": plain_text(hint.info_text, max_chars=300)}
                )
                for hint in item.hints
            )
        }
    )


def _normalise_system_message(item: SystemMessageWire) -> SystemMessageWire:
    return item.model_copy(
        update={
            "error": plain_text(item.error, max_chars=500),
            "text": plain_text(item.text, max_chars=500),
        }
    )


def _normalise_alert(item: AlertWire) -> AlertWire:
    return item.model_copy(
        update={
            "subtitle": plain_text(item.subtitle, max_chars=500),
            "content": plain_text(item.content, max_chars=2_000),
            "url": safe_web_url(item.url),
            "url_text": plain_text(item.url_text, max_chars=200),
            "properties": item.properties.model_copy(
                update={"sms_text": plain_text(item.properties.sms_text, max_chars=500)}
            ),
        }
    )
