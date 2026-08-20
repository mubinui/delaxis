"""Tests for the PII detection and redaction tools.

The point of these tests is not that the regexes fire — it is that they fire on
the right things. A PII detector that flags every 16-digit order number is worse
than none, because people stop reading its output. So the negative cases carry
as much weight here as the positive ones.
"""

import json

import pytest

from src.tools.pii import (
    REDACTION_STRATEGIES,
    SUPPORTED_ENTITIES,
    _iban_ok,
    _luhn_ok,
    _us_ssn_ok,
    detect_pii,
    find_pii,
    list_pii_entity_types,
    redact_pii,
)

# Credential-shaped samples for exercising the scanner. None are real, and each
# is assembled from parts so no literal `ghp_...` / `sk_live_...` / `AKIA...`
# appears contiguously in this file — such a literal trips GitHub push
# protection and every other scanner that will ever read this repository, and a
# test fixture is not worth a permanent repo-wide scanner exception.
SAMPLE_AWS_KEY = "AKIA" "3FJK2LMNQ4XZ7BVC"
SAMPLE_AWS_DOC_KEY = "AKIA" "IOSFODNN7EXAMPLE"
SAMPLE_GITHUB_TOKEN = "ghp_" "aB3xY9zQ1mN7pR2sT4uV6wX8yZ0aB1cD2eF3"
SAMPLE_SLACK_TOKEN = "xoxb-" "2451233-abcDEF123456"
SAMPLE_STRIPE_KEY = "sk_" "live_aB3xY9zQ1mN7pR2sT4uV6wX8"
SAMPLE_GOOGLE_KEY = "AIza" "SyD3xY9zQ1mN7pR2sT4uV6wX8yZ0aB1cD2e"
SAMPLE_OPENAI_KEY = "sk-" "proj-Xk92mQvR4tYuIoPa8sDfGhJk1LzXcVbNm3"


def types_found(text: str, **kwargs) -> set[str]:
    return {match.entity_type for match in find_pii(text, **kwargs)}


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


class TestValidators:
    @pytest.mark.parametrize("number", ["4111111111111111", "5500005555555559", "4111 1111 1111 1111"])
    def test_luhn_accepts_valid_cards(self, number):
        assert _luhn_ok(number)

    @pytest.mark.parametrize("number", ["4111111111111112", "1234567890123456", "0000000000000001"])
    def test_luhn_rejects_invalid_cards(self, number):
        assert not _luhn_ok(number)

    def test_luhn_rejects_short_input(self):
        assert not _luhn_ok("4111")

    @pytest.mark.parametrize("iban", ["GB82WEST12345698765432", "DE89370400440532013000"])
    def test_iban_accepts_valid(self, iban):
        assert _iban_ok(iban)

    @pytest.mark.parametrize("iban", ["GB82WEST12345698765433", "XX00NOTANIBAN", "GB82"])
    def test_iban_rejects_invalid(self, iban):
        assert not _iban_ok(iban)

    @pytest.mark.parametrize("ssn", ["123-45-6789", "001-01-0001"])
    def test_ssn_accepts_issuable(self, ssn):
        assert _us_ssn_ok(ssn)

    @pytest.mark.parametrize(
        "ssn",
        [
            "000-12-3456",  # area 000 is never issued
            "666-12-3456",  # area 666 is never issued
            "900-12-3456",  # 900+ is never issued
            "123-00-6789",  # group 00 is never issued
            "123-45-0000",  # serial 0000 is never issued
        ],
    )
    def test_ssn_rejects_unissuable_ranges(self, ssn):
        assert not _us_ssn_ok(ssn)


# ---------------------------------------------------------------------------
# Detection — true positives
# ---------------------------------------------------------------------------


class TestDetection:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Write to jane.doe@example.com today", "EMAIL_ADDRESS"),
            ("Card 4111 1111 1111 1111 on file", "CREDIT_CARD"),
            ("SSN 123-45-6789 on record", "US_SSN"),
            ("IBAN GB82WEST12345698765432 confirmed", "IBAN"),
            ("Server at 192.168.1.10 is down", "IP_ADDRESS"),
            ("Date of birth: 1990-04-12", "DATE_OF_BIRTH"),
            (f"Key {SAMPLE_AWS_KEY} leaked", "AWS_ACCESS_KEY"),
            ("NID 1234567890123 verified", "BD_NID"),
            ("Passport number: X1234567", "US_PASSPORT"),
            ("MRN: AB-12345 attached", "MEDICAL_RECORD_NUMBER"),
        ],
    )
    def test_detects_entity(self, text, expected):
        assert expected in types_found(text)

    @pytest.mark.parametrize(
        "phone",
        [
            "+1 (415) 555-0132",
            "+8801712345678",       # bare E.164, no separators
            "415-555-0132",
            "+44 20 7946 0958",
        ],
    )
    def test_detects_phone_formats(self, phone):
        assert "PHONE_NUMBER" in types_found(f"Call {phone} tomorrow.")

    def test_detects_phone_at_end_of_sentence(self):
        # A trailing full stop must not swallow the number's boundary.
        assert "PHONE_NUMBER" in types_found("Reach me on +1 (415) 555-0132.")

    def test_private_key_block(self):
        assert "PRIVATE_KEY" in types_found("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")

    def test_reports_position_and_confidence(self):
        text = "Contact jane.doe@example.com now"
        [match] = [m for m in find_pii(text) if m.entity_type == "EMAIL_ADDRESS"]
        assert text[match.start : match.end] == "jane.doe@example.com"
        assert 0.0 < match.confidence <= 1.0


# ---------------------------------------------------------------------------
# Detection — false positives are the expensive failure
# ---------------------------------------------------------------------------


class TestFalsePositives:
    @pytest.mark.parametrize(
        "text",
        [
            "Order number 987654321 shipped",
            "Version 1.2.3 released",
            "Total came to 1,299.00 after tax",
            "Ratio 12-34 in the report",
            "Invoice 1234567890123456 is not a card",  # 16 digits, fails Luhn
        ],
    )
    def test_ignores_ordinary_numbers(self, text):
        assert types_found(text) == set(), f"false positive on: {text}"

    def test_ignores_unissuable_ssn_shaped_numbers(self):
        assert "US_SSN" not in types_found("Reference 000-12-3456 in the ticket")

    def test_min_confidence_filters(self):
        text = "Call 415-555-0132"
        assert "PHONE_NUMBER" in types_found(text, min_confidence=0.5)
        assert "PHONE_NUMBER" not in types_found(text, min_confidence=0.95)


# ---------------------------------------------------------------------------
# Overlap handling
# ---------------------------------------------------------------------------


class TestOverlap:
    def test_one_match_per_span(self):
        # A card also matches the phone shape; only the stronger one survives, or
        # the redaction offsets would be corrupted by double-counting.
        matches = find_pii("Card 4111 1111 1111 1111 on file")
        spans = [(m.start, m.end) for m in matches]
        for index, (start, end) in enumerate(spans):
            for other_start, other_end in spans[index + 1 :]:
                assert not (start < other_end and other_start < end), "overlapping matches"

    def test_card_wins_over_phone(self):
        found = types_found("Card 4111 1111 1111 1111 on file")
        assert "CREDIT_CARD" in found
        assert "PHONE_NUMBER" not in found


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestEntityFilter:
    def test_restricts_to_requested_types(self):
        text = "jane@example.com and card 4111 1111 1111 1111"
        assert types_found(text, entity_types=["EMAIL_ADDRESS"]) == {"EMAIL_ADDRESS"}

    def test_empty_filter_means_everything(self):
        text = "jane@example.com and card 4111 1111 1111 1111"
        assert types_found(text, entity_types=[]) == types_found(text)

    def test_filter_is_case_insensitive(self):
        assert types_found("jane@example.com", entity_types=["email_address"]) == {"EMAIL_ADDRESS"}


# ---------------------------------------------------------------------------
# detect_pii tool contract
# ---------------------------------------------------------------------------


class TestDetectTool:
    def test_returns_structured_json(self):
        report = json.loads(detect_pii("Write to jane@example.com"))
        assert report["found"] is True
        assert report["count"] == 1
        assert report["summary"] == {"EMAIL_ADDRESS": 1}
        assert report["entities"][0]["entity_type"] == "EMAIL_ADDRESS"

    def test_clean_text_reports_nothing_found(self):
        report = json.loads(detect_pii("The quarterly report is attached."))
        assert report["found"] is False
        assert report["count"] == 0

    def test_never_echoes_the_full_value(self):
        # Calling the detector must not copy the secret into the transcript.
        report = json.loads(detect_pii("Write to jane.doe@example.com"))
        assert "jane.doe@example.com" not in json.dumps(report)
        assert "*" in report["entities"][0]["preview"]

    def test_empty_text_is_not_an_error(self):
        report = json.loads(detect_pii(""))
        assert report["found"] is False


# ---------------------------------------------------------------------------
# redact_pii tool contract
# ---------------------------------------------------------------------------


class TestRedactTool:
    @pytest.mark.parametrize("strategy", REDACTION_STRATEGIES)
    def test_every_strategy_removes_the_value(self, strategy):
        result = json.loads(redact_pii("Write to jane.doe@example.com now", strategy))
        assert "jane.doe@example.com" not in result["redacted"]
        assert result["redaction_count"] == 1

    def test_label_strategy_numbers_each_type(self):
        result = json.loads(redact_pii("a@x.com and b@y.com", "label"))
        assert "<EMAIL_ADDRESS_1>" in result["redacted"]
        assert "<EMAIL_ADDRESS_2>" in result["redacted"]

    def test_hash_strategy_is_stable(self):
        first = json.loads(redact_pii("a@x.com", "hash"))["redacted"]
        second = json.loads(redact_pii("a@x.com", "hash"))["redacted"]
        assert first == second

    def test_hash_strategy_distinguishes_values(self):
        one = json.loads(redact_pii("a@x.com", "hash"))["redacted"]
        two = json.loads(redact_pii("b@y.com", "hash"))["redacted"]
        assert one != two

    def test_mask_keeps_card_tail_for_human_matching(self):
        result = json.loads(redact_pii("Card 4111 1111 1111 1111", "mask"))
        assert result["redacted"].endswith("1111")
        assert "4111 1111" not in result["redacted"]

    def test_remove_strategy_deletes_outright(self):
        result = json.loads(redact_pii("Write to a@x.com now", "remove"))
        assert result["redacted"] == "Write to  now"

    def test_surrounding_text_is_preserved(self):
        result = json.loads(redact_pii("Dear a@x.com, your order shipped.", "placeholder"))
        assert result["redacted"] == "Dear <EMAIL_ADDRESS>, your order shipped."

    def test_multiple_entities_keep_text_intact(self):
        text = "Mail a@x.com or call +1 (415) 555-0132 today"
        result = json.loads(redact_pii(text, "placeholder"))
        assert result["redacted"].startswith("Mail ")
        assert result["redacted"].endswith(" today")
        assert result["redaction_count"] == 2

    def test_unknown_strategy_is_rejected_clearly(self):
        result = json.loads(redact_pii("a@x.com", "obliterate"))
        assert "error" in result
        assert "obliterate" in result["error"]

    def test_clean_text_is_returned_unchanged(self):
        text = "Nothing sensitive here."
        result = json.loads(redact_pii(text))
        assert result["redacted"] == text
        assert result["redaction_count"] == 0


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestListEntityTypes:
    def test_lists_supported_entities_and_strategies(self):
        report = json.loads(list_pii_entity_types())
        assert set(report["pattern_entities"]) == set(SUPPORTED_ENTITIES)
        assert set(report["strategies"]) == set(REDACTION_STRATEGIES)
        assert isinstance(report["ner_available"], bool)

    def test_ner_entities_are_advertised_even_when_unavailable(self):
        # An agent asking for PERSON deserves to learn it needs a package, rather
        # than silently getting no matches.
        report = json.loads(list_pii_entity_types())
        assert "PERSON" in report["ner_entities"]
        assert "presidio" in report["note"].lower()
