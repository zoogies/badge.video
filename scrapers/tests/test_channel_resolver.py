from channel_resolver import extract_handle_from_url

def test_handle_url():
    assert extract_handle_from_url("https://www.youtube.com/@MidwestSafety") == ("handle", "MidwestSafety")

def test_channel_id_url():
    assert extract_handle_from_url("https://www.youtube.com/channel/UC123abc") == ("id", "UC123abc")

def test_user_url():
    assert extract_handle_from_url("https://www.youtube.com/user/SomeUser") == ("user", "SomeUser")
