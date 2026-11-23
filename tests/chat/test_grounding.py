import pytest

from elkollen_chat.grounding import check, extract_numbers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Priset är 55,6 öre/kWh", [[55.6]]),
        ("It costs 1 234,50 SEK", [[1234.5]]),
        ("Kl. 14:15 kostar det -2,19 öre", [[-2.19]]),
        ("Kl. 14:15 kostar det −2,19 öre", [[-2.19]]),  # Unicode minus sign
        ("Den 2025-10-04 mellan 13:00 och 15:00", []),
        ("Den 2025‑10‑04", []),  # non-breaking hyphens
        ("16 Nov – 22 Nov 2026", []),
        ("Priset i SE3 var 44.4", [[44.4]]),
    ],
)
def test_extract_numbers(text, expected):
    got = [sorted(values) for _, values in extract_numbers(text)]
    assert got == [sorted(v) for v in expected]


def test_comma_thousands_is_read_both_ways():
    [(raw, values)] = extract_numbers("≈ 1,045 SEK")
    assert raw == "1,045" and set(values) == {1.045, 1045.0}


RESULT = {"data": {"total_kwh": 129.734, "total_cost_sek": 1045.32, "avg_ore_per_kwh": 62.34}}
ARGS = {"start_date": "2026-11-16", "end_date": "2026-11-22"}


def test_numbers_from_tools_are_grounded_with_rounding_and_units():
    answer = "Du använde 129,7 kWh och betalade 1 045 kr, i snitt 62,3 öre/kWh (0,62 kr)."
    result = check(answer, [RESULT, ARGS])
    assert result["ok"], result
    assert result["numbers_checked"] == 4


def test_english_thousands_comma_is_grounded():
    assert check("It cost ≈ 1,045 SEK.", [RESULT])["ok"]


def test_invented_numbers_are_flagged():
    result = check("Priset blir 97,5 öre/kWh i morgon.", [RESULT])
    assert not result["ok"] and result["ungrounded"] == ["97,5"]


def test_dates_must_match_tool_dates():
    good = check("Last week (16 Nov – 22 Nov 2026) you used 129,7 kWh.", [RESULT, ARGS])
    assert good["ok"], good
    # The wrong year, written with non-breaking hyphens, as a real model did:
    bad = check("Imorgon (2024‑11‑24) ...", [{"day": "2026-11-24"}])
    assert not bad["ok"] and bad["unverified_dates"] == ["2024-11-24"]
    wrong_day = check("On 23 November you used 129,7 kWh.", [RESULT, ARGS])
    assert wrong_day["unverified_dates"] == ["23/11"]


SPIKE = {
    "observations": [
        {"kind": "vs_day_average", "day_avg_ore_per_kwh": 176.9946, "ratio": 1.44},
        {"kind": "area_spread", "prices_ore_per_kwh": {"SE2": 11.213, "SE4": 255.422}},
    ]
}


def test_real_spike_answer_rounding_percent_change_and_durations():
    # From a real model answer: "11" (11.213), "44 % above" (ratio 1.44), "30-day" label.
    answer = (
        "255 öre/kWh, about 44 % above the day's average and above the 30-day average. "
        "The cheapest area, SE2, was at 11 öre/kWh."
    )
    assert check(answer, [SPIKE])["ok"]


def test_truncated_rounding_is_still_flagged():
    # The day's average is 176.99; writing "176" (instead of 177) is wrong, and flagged.
    result = check("The day's average was 176 öre/kWh.", [SPIKE])
    assert result["ungrounded"] == ["176"]
    assert check("The day's average was 177 öre/kWh.", [SPIKE])["ok"]


def test_numbers_from_the_question_and_small_counts_are_ignored():
    result = check("De billigaste 3 timmarna i 120 minuter ...", [], question="120 minuter?")
    assert result["ok"] and result["numbers_checked"] == 0


def test_no_tools_means_every_number_is_unverified():
    result = check("Electricity costs about 150 öre today.", [])
    assert result["ungrounded"] == ["150"]
