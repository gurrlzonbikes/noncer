import pytest

from noncer.payload import build_intent, parse_intent


def test_intent_roundtrip():
    payload = build_intent(7, 'echo "x y"')
    n, action = parse_intent(payload)
    assert n == 7
    assert action == 'echo "x y"'


def test_invalid_nonce():
    with pytest.raises(ValueError):
        parse_intent('{"nonce":"1","action":"x"}')
