"""Tests for the pure (no Tk, no network, no filesystem) helper functions.

These are the pieces most likely to break silently while editing a file
this size - a mis-tweaked regex or an off-by-one in a math helper won't
throw, it'll just quietly give the wrong answer to one specific input.
"""
import multi_roblox as mr


class TestVersionTuple:
    def test_simple(self):
        assert mr._version_tuple("3.10.2") == (3, 10, 2)

    def test_leading_v(self):
        assert mr._version_tuple("v3.1") == (3, 1)

    def test_numeric_comparison_not_lexicographic(self):
        # "3.10" must sort ABOVE "3.9" numerically, not below it as a string
        # comparison would (since "1" < "9" lexicographically).
        assert mr._version_tuple("3.10") > mr._version_tuple("3.9")

    def test_non_numeric_suffix_stops_there(self):
        assert mr._version_tuple("3.1-beta") == (3,)

    def test_empty(self):
        assert mr._version_tuple("") == (0,)


class TestParseJoinTarget:
    def test_bare_place_id(self):
        assert mr.parse_join_target("6516141723") == ("6516141723", None, None)

    def test_game_url(self):
        place, code, job = mr.parse_join_target(
            "https://www.roblox.com/games/6516141723/Some-Game-Name")
        assert place == "6516141723"
        assert code is None
        assert job is None

    def test_private_server_link(self):
        place, code, job = mr.parse_join_target(
            "https://www.roblox.com/games/6516141723/?privateServerLinkCode=abc123XYZ")
        assert place == "6516141723"
        assert code == "abc123XYZ"

    def test_specific_server_link(self):
        place, code, job = mr.parse_join_target(
            "https://www.roblox.com/games/6516141723?gameId="
            "1a2b3c4d-1234-5678-9abc-def012345678")
        assert place == "6516141723"
        assert job == "1a2b3c4d-1234-5678-9abc-def012345678"

    def test_blank(self):
        assert mr.parse_join_target("") == (None, None, None)
        assert mr.parse_join_target("   ") == (None, None, None)

    def test_unrecognised_text(self):
        place, code, job = mr.parse_join_target("not a link at all")
        assert place is None and code is None and job is None


class TestCleanCookie:
    def test_strips_wrapping_quotes(self):
        assert mr.clean_cookie('"abc123"') == "abc123"

    def test_strips_roblosecurity_prefix(self):
        assert mr.clean_cookie(".ROBLOSECURITY=abc123") == "abc123"

    def test_strips_internal_whitespace_from_a_wrapped_paste(self):
        assert mr.clean_cookie("abc\n123  456") == "abc123456"

    def test_finds_the_warning_marker_after_leading_junk(self):
        # copying the whole row out of dev tools brings the cookie's name
        # along with it - the real value always starts at "_|WARNING:"
        assert mr.clean_cookie("junkbefore_|WARNING:realvalue") == "_|WARNING:realvalue"

    def test_empty(self):
        assert mr.clean_cookie("") == ""
        assert mr.clean_cookie(None) == ""


class TestCookieWarning:
    def test_none_for_empty(self):
        assert mr.cookie_warning("") is None

    def test_too_short(self):
        assert mr.cookie_warning("short") is not None

    def test_missing_warning_prefix(self):
        long_but_wrong_prefix = "x" * 250
        assert mr.cookie_warning(long_but_wrong_prefix) is not None

    def test_looks_valid(self):
        plausible = "_|WARNING:" + ("x" * 800)
        assert mr.cookie_warning(plausible) is None


class TestHandlerExeFromCommand:
    def test_quoted_path_with_args(self):
        assert (mr.handler_exe_from_command('"C:\\Program Files\\Bloxstrap\\Bloxstrap.exe" -player "%1"')
                == "C:\\Program Files\\Bloxstrap\\Bloxstrap.exe")

    def test_unquoted_path(self):
        assert mr.handler_exe_from_command("C:\\Roblox\\RobloxPlayerBeta.exe %1") == "C:\\Roblox\\RobloxPlayerBeta.exe"

    def test_empty(self):
        assert mr.handler_exe_from_command("") is None
        assert mr.handler_exe_from_command(None) is None


class TestCpuRateValue:
    def test_half_of_one_core_on_eight_cores(self):
        # 50% of one core, on an 8-core machine, is 6.25% of total system
        # capacity -> 625 in the job object's 1/10000 units.
        assert mr.cpu_rate_value(50, 8) == 625

    def test_full_core_on_one_core_machine(self):
        assert mr.cpu_rate_value(100, 1) == 10000

    def test_clamped_to_valid_range(self):
        assert mr.cpu_rate_value(0, 4) == mr.cpu_rate_value(1, 4)  # 0 clamps to 1
        assert mr.cpu_rate_value(500, 4) == mr.cpu_rate_value(100, 4)  # >100 clamps to 100

    def test_never_zero(self):
        # a rate of 0 would mean "no cap at all" to the OS, not "tiny cap"
        assert mr.cpu_rate_value(1, 64) >= 1
