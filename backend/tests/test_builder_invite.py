from app.builder.draft import SYSTEM, trim_repeated_invite

H = [{"role": "user", "text": "hi"},
     {"role": "assistant", "text": "Hello! What task would you like the agent to perform?"}]


def test_first_invite_is_kept():
    r = "Hello! What task would you like the agent to perform?"
    assert trim_repeated_invite(r, []) == r


def test_a_repeated_invite_is_cut_after_the_first_time():
    r = ("ChatGPT is not available here. Available models include nemotron-3-super. "
         "Would you like to build a scheduled AI agent using one of these models?")
    assert trim_repeated_invite(r, H) == "ChatGPT is not available here. Available models include nemotron-3-super."


def test_an_answer_that_is_only_an_invite_survives():
    r = "What would you like the agent to do?"
    assert trim_repeated_invite(r, H) == r


def test_products_are_explained_as_connectors():
    assert "it is not a model" in SYSTEM


def test_wider_invite_phrasings_are_cut_too():
    hist = [{"role": "assistant", "text": "Hi! What task would you like the agent to do?"}]
    for tail in ["Want to try it? Describe your email use case and I\u2019ll help you set it up.",
                 "Tell me the task and I'll walk you through the steps.",
                 "Let me know what you'd like to automate."]:
        out = trim_repeated_invite("Claude is by Anthropic. " + tail, hist)
        assert out == "Claude is by Anthropic.", tail
