from __future__ import annotations

from pyactivesync._codepages import CODEPAGES, PAGE_INDEX, PAGE_ORDER, REVERSE

# Real MS-ASWBXML codepage numbers, per the spec index -- pinned here so a
# future edit to _codepages.py can't silently drift from the protocol.
EXPECTED_PAGE_NUMBERS = {
    "AirSync": 0,
    "Contacts": 1,
    "Email": 2,
    "Move": 5,
    "ItemEstimate": 6,
    "FolderHierarchy": 7,
    "Tasks": 9,
    "ResolveRecipients": 10,
    "Ping": 13,
    "Provision": 14,
    "Search": 15,
    "GAL": 16,
    "AirSyncBase": 17,
    "Settings": 18,
    "ItemOperations": 20,
    "ComposeMail": 21,
    "Find": 25,
}


def test_page_numbers_match_spec() -> None:
    assert PAGE_INDEX == EXPECTED_PAGE_NUMBERS


def test_page_order_is_inverse_of_page_index() -> None:
    for name, num in PAGE_INDEX.items():
        assert PAGE_ORDER[num] == name


def test_no_duplicate_tokens_within_a_page() -> None:
    for page, tags in CODEPAGES.items():
        tokens = list(tags.values())
        assert len(tokens) == len(set(tokens)), f"duplicate token in {page}"


def test_every_page_in_codepages_has_a_page_number() -> None:
    assert set(CODEPAGES) == set(PAGE_INDEX)


def test_token_values_fit_in_five_bits() -> None:
    # The low 6 bits of a WBXML tag byte carry the token; bit 0x40 is the
    # "has content" flag, so every raw token must be < 0x40.
    for page, tags in CODEPAGES.items():
        for name, token in tags.items():
            assert 0 <= token < 0x40, f"{page}.{name} token 0x{token:02X} out of range"


def test_reverse_maps_back_to_original_tag_names() -> None:
    for page, tags in CODEPAGES.items():
        page_num = PAGE_INDEX[page]
        for name, token in tags.items():
            assert REVERSE[page_num][token & 0x3F] == name
