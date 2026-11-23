import pytest

from elkollen_chat.grounding import check, extract_numbers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Priset är 55,6 öre/kWh", [55.6]),
        ("It costs 1 234,50 SEK", [1234.5]),
        ("Kl. 14:15 kostar det -2,19 öre", [-2.19]),
        ("Den 2025-10-04 mellan 13:00 och 15:00", []),
        ("Priset i SE3 var 44.4", [44.4]),
    ],
)
def test_extract_numbers(text, expected):
    assert [v for _, v in extract_numbers(text)] == pytest.approx(expected)


RESULT = {"data": {"total_kwh": 129.734, "total_cost_sek": 80.88, "avg_ore_per_kwh": 62.34}}


def test_numbers_from_tools_are_grounded_with_rounding_and_units():
    answer = "Du använde 129,7 kWh och betalade 80,88 kr, i snitt 62,3 öre/kWh (0,62 kr)."
    result = check(answer, [RESULT])
    assert result["ok"], result
    assert result["numbers_checked"] == 4


def test_invented_numbers_are_flagged():
    result = check("Priset blir 97,5 öre/kWh i morgon.", [RESULT])
    assert not result["ok"] and result["ungrounded"] == ["97,5"]


def test_numbers_from_the_question_and_small_counts_are_ignored():
    result = check("De billigaste 3 timmarna i 120 minuter ...", [], question="120 minuter?")
    assert result == {"numbers_checked": 0, "ungrounded": [], "ok": True}


def test_no_tools_means_every_number_is_unverified():
    result = check("Electricity costs about 150 öre today.", [])
    assert result["ungrounded"] == ["150"]
