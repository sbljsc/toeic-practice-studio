"""Standalone distribution paths and source-inventory privacy."""
from toeic_practice import config
from test_pool_runtime import pool_root, pool_client


def test_bundled_bank_is_found_from_project_without_external_sources(tmp_path, monkeypatch):
    monkeypatch.delenv('TOEIC_LIBRARY_DIR', raising=False)
    monkeypatch.setattr(config, 'PROJECT_ROOT', tmp_path)
    bundled = tmp_path / 'content' / 'question-pool'
    bundled.mkdir(parents=True)
    (bundled / 'manifest.json').write_text('{}', encoding='utf-8')
    assert config.library_dir() == bundled
    # An explicitly prepared local bank may override the bundled copy.
    local = tmp_path / '.data' / 'question-pool'
    local.mkdir(parents=True)
    (local / 'manifest.json').write_text('{}', encoding='utf-8')
    assert config.library_dir() == local
    custom = tmp_path / 'override'
    monkeypatch.setenv('TOEIC_LIBRARY_DIR', str(custom))
    assert config.library_dir() == custom.resolve()


def test_flat_bank_never_serves_private_source_inventory(pool_client, tmp_path, monkeypatch):
    private = tmp_path / 'inventory.json'
    private.write_text('{"private_source":"must-never-be-served"}', encoding='utf-8')
    monkeypatch.setattr('toeic_practice.routers.misc.SOURCE_INVENTORY', private)
    response = pool_client.get('/api/sources')
    assert response.status_code == 404
    assert 'must-never-be-served' not in response.text
