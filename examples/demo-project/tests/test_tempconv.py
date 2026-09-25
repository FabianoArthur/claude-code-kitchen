from tempconv import celsius_to_fahrenheit, fahrenheit_to_celsius


def test_freezing_point():
    assert celsius_to_fahrenheit(0) == 32


def test_round_trip():
    assert fahrenheit_to_celsius(celsius_to_fahrenheit(37.5)) == 37.5
