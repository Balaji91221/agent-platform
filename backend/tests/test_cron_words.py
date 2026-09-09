from app.scheduler.cron import describe


def test_common_shapes_get_plain_words():
    assert describe("0 7 * * *") == "Every day at 07:00"
    assert describe("30 9 * * 1-5") == "Weekdays at 09:30"
    assert describe("0 17 * * 5") == "Fridays at 17:00"
    assert describe("*/15 * * * *") == "Every 15 minutes"
    assert describe("0 */2 * * *") == "Every 2 hours"
    assert describe("0 * * * *") == "Every hour, on the hour"


def test_unknown_shapes_return_empty_not_the_rule():
    assert describe("0 9 1 * *") == ""
    assert describe("5 4 * * 1,3") == ""
