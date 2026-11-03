"""The key: read from the environment or .env, never shown, and its absence is a normal state."""
from finn.llm.config import KEY_NAME, Settings, load_settings, read_env_file

FAKE_KEY = "sk-ant-test-0000-not-a-real-key"


def test_env_file_format(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nexport ANTHROPIC_API_KEY='sk-quoted'\nFINN_LLM=on  # trailing note\nBROKEN LINE\n",
                   encoding="utf-8")
    assert read_env_file(env) == {"ANTHROPIC_API_KEY": "sk-quoted", "FINN_LLM": "on"}


def test_missing_env_file_is_not_an_error(tmp_path):
    assert read_env_file(tmp_path / ".env") == {}


def test_no_key_anywhere_means_off_with_a_reason(tmp_path):
    s = load_settings(env={}, env_file=tmp_path / ".env")
    assert not s.enabled and KEY_NAME in s.reason and s.api_key == ""


def test_key_from_env_file(tmp_path):
    (tmp_path / ".env").write_text(f"{KEY_NAME}={FAKE_KEY}\n", encoding="utf-8")
    s = load_settings(env={}, env_file=tmp_path / ".env")
    assert s.enabled and s.source == ".env" and s.api_key == FAKE_KEY


def test_process_environment_wins_over_the_file(tmp_path):
    (tmp_path / ".env").write_text(f"{KEY_NAME}=from-file\n", encoding="utf-8")
    s = load_settings(env={KEY_NAME: "from-env"}, env_file=tmp_path / ".env")
    assert s.api_key == "from-env" and s.source == "environment"


def test_switch_off_beats_a_key(tmp_path):
    s = load_settings(env={KEY_NAME: FAKE_KEY, "FINN_LLM": "off"}, env_file=tmp_path / ".env")
    assert not s.enabled and "FINN_LLM=off" in s.reason and s.api_key == ""


def test_the_key_never_appears_in_text_forms(tmp_path):
    s = Settings(True, "API key found in the .env.", ".env", FAKE_KEY)
    for text in (repr(s), str(s), f"{s}", s.reason, str(vars(s).get("source"))):
        assert FAKE_KEY not in text
    assert "***" in repr(s)
