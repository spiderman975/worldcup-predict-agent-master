from data.stages import football_data_stage_to_number, stage_key_from_number


def test_football_data_stage_mapping() -> None:
    assert football_data_stage_to_number("GROUP_STAGE") == 1
    assert football_data_stage_to_number("LAST_32") == 2
    assert football_data_stage_to_number("LAST_16") == 3
    assert football_data_stage_to_number("QUARTER_FINALS") == 4
    assert football_data_stage_to_number("SEMI_FINALS") == 5
    assert football_data_stage_to_number("THIRD_PLACE") == 6
    assert football_data_stage_to_number("FINAL") == 7


def test_backend_stage_names() -> None:
    assert stage_key_from_number(1) == "group"
    assert stage_key_from_number(2) == "round_of_32"
    assert stage_key_from_number(3) == "round_of_16"
    assert stage_key_from_number(4) == "quarter"
    assert stage_key_from_number(5) == "semi"
    assert stage_key_from_number(6) == "third_place"
    assert stage_key_from_number(7) == "final"
