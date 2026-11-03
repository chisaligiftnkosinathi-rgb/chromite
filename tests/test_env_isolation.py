from app.core.config import settings


def test_real_env_file_not_loaded_during_tests():
    assert settings.SUPABASE_URL == "https://test-project.invalid"
    assert settings.SUPABASE_SERVICE_ROLE_KEY is None
