import pytest

from lecture_notes import settings


@pytest.mark.parametrize('address', [
    'http://localhost:8080@remote.example/v1',
    'http://127.0.0.1:80@remote.example/v1',
    'https://',
    'https:///v1',
    'https://example.invalid:bad/v1',
    'https://example.invalid/v1#fragment',
    'https://example.invalid/v1?token=fixture',
    'https://example .invalid/v1',
])
def test_invalid_base_url_not_saved(tmp_path, monkeypatch, address):
    monkeypatch.setattr(settings, 'DATA', tmp_path)
    with pytest.raises(ValueError, match='接口地址'):
        settings.save_settings({'base_url': address})
    assert not (tmp_path / 'settings.json').exists()


@pytest.mark.parametrize('address', [
    '', 'https://api.example.invalid', 'https://api.example.invalid/v1',
    'http://127.0.0.1:8000/v1', 'http://localhost:8080/v1',
])
def test_compatible_base_url_saved_without_network(tmp_path, monkeypatch, address):
    monkeypatch.setattr(settings, 'DATA', tmp_path)
    assert settings.save_settings({'base_url': address})['base_url'] == address
