from research_companion.connectors import base


def test_rate_limiter_spaces_calls_using_injected_clock():
    now = [0.0]
    slept = []
    rl = base.RateLimiter(0.34, clock=lambda: now[0], sleep=lambda s: slept.append(s))
    rl.wait()                 # first call: no wait
    assert slept == []
    rl.wait()                 # immediate second call: must wait ~0.34s
    assert slept and abs(slept[0] - 0.34) < 1e-6


def test_rate_limiter_no_wait_when_enough_time_passed():
    now = [0.0]
    slept = []
    rl = base.RateLimiter(0.34, clock=lambda: now[0], sleep=lambda s: slept.append(s))
    rl.wait()
    now[0] = 1.0              # a full second elapsed
    rl.wait()
    assert slept == []


def test_user_agent_names_the_project():
    assert "research-companion" in base.USER_AGENT
