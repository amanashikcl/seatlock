import pytest

from apps.payments.signature import TOLERANCE_SECONDS, InvalidSignature, sign, verify

SECRET = "whsec_test"
BODY = b'{"id":"evt_1"}'
NOW = 1_700_000_000


def test_a_correctly_signed_payload_verifies() -> None:
    header = sign(BODY, SECRET, timestamp=NOW)
    verify(BODY, header, SECRET, now=NOW)


def test_wrong_secret_is_rejected() -> None:
    header = sign(BODY, "other-secret", timestamp=NOW)
    with pytest.raises(InvalidSignature):
        verify(BODY, header, SECRET, now=NOW)


def test_tampered_body_is_rejected() -> None:
    header = sign(BODY, SECRET, timestamp=NOW)
    with pytest.raises(InvalidSignature):
        verify(b'{"id":"evt_2"}', header, SECRET, now=NOW)


def test_stale_timestamp_is_rejected() -> None:
    header = sign(BODY, SECRET, timestamp=NOW)
    with pytest.raises(InvalidSignature):
        verify(BODY, header, SECRET, now=NOW + TOLERANCE_SECONDS + 1)


def test_future_timestamp_is_rejected() -> None:
    header = sign(BODY, SECRET, timestamp=NOW + TOLERANCE_SECONDS + 1)
    with pytest.raises(InvalidSignature):
        verify(BODY, header, SECRET, now=NOW)


def test_timestamp_inside_tolerance_is_accepted() -> None:
    header = sign(BODY, SECRET, timestamp=NOW)
    verify(BODY, header, SECRET, now=NOW + TOLERANCE_SECONDS)


@pytest.mark.parametrize(
    "header",
    ["", "garbage", "t=abc,v1=deadbeef", "t=1700000000", "v1=deadbeef"],
)
def test_malformed_headers_are_rejected(header: str) -> None:
    with pytest.raises(InvalidSignature):
        verify(BODY, header, SECRET, now=NOW)


def test_empty_secret_is_a_configuration_error() -> None:
    with pytest.raises(ValueError):
        sign(BODY, "", timestamp=NOW)
