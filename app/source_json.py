"""One bounded, exact JSON decoder for official-source snapshots."""
import json
from decimal import Decimal

MAX_BYTES = 2_000_000


def load_source_json(raw: bytes):
    if len(raw) > MAX_BYTES:
        raise ValueError("source response exceeds maximum size")

    def number(token):
        if len(token) > 100:
            raise ValueError("numeric token too large")
        value = Decimal(token)
        if not value.is_finite() or abs(value.adjusted()) > 100:
            raise ValueError("non-finite or excessive numeric value")
        return value

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def no_constant(token):
        raise ValueError("non-finite JSON constant")

    return json.loads(raw.decode("utf-8"), parse_float=number, parse_int=number,
                      parse_constant=no_constant, object_pairs_hook=unique_object)
