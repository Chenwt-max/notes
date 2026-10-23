"""Malformed provider envelopes must retain text/ledger and never auto-rebill."""
import json

import httpx
import pytest

from lecture_notes import assistant, chapters, settings, store
from lecture_notes.common import write_json
from lecture_notes.synthesis import build_sections, organize


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(store, 'OUTPUT', tmp_path / 'outputs')
    job = store.create_job({'path': 'selfmade.mp4', 'budget_cny': 1})
    store.update_job(job['id'], status='ready')
    sections = build_sections([{'id': 's1', 'start': 0, 'end': 20, 'text': '完整课程定义与前提。'}], [], [[0, 60]])
    body = '## 定义\n完整课程定义、前提与推导。'
    sections[0].update(body=body, organized=True)
    out = store.OUTPUT / job['id']
    write_json(out / 'notes.json', sections)
    config = {**settings.DEFAULTS, 'api_key': 'fixture', 'base_url': 'https://fixture.invalid/v1',
              'model': 'generic-fixture', 'input_price': 1, 'output_price': 2,
              'input_tokens_per_hour': 600000, 'max_output_tokens': 1000}
    return job['id'], out, sections, config


def provider(monkeypatch, payload):
    calls = []
    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            calls.append(kwargs['json'])
            return httpx.Response(200, request=httpx.Request('POST', url), json=payload)
    monkeypatch.setattr(httpx, 'Client', Client)
    return calls


def run(stage, local):
    job, out, sections, config = local
    if stage == 'chapters':
        return chapters.divide_chapters(job, sections, 3600, out, config, lambda: None)
    if stage == 'assistant':
        return assistant.explain(job, {'request_id': 'envelope_fixture', 'note_id': sections[0]['id'],
                                       'question': '解释定义。'}, config)
    return organize(job, sections, 3600, out, config, lambda *args: None, lambda: None,
                    review_mode=stage == 'review')


@pytest.mark.parametrize('stage', ['organize', 'review', 'chapters', 'assistant'])
@pytest.mark.parametrize('usage', [None, {}, [], ['bad'], 'bad', 17, True])
def test_bad_usage_container_keeps_valid_content_and_reservation(local, monkeypatch, stage, usage):
    job, out, sections, config = local
    content = (json.dumps({'edits': []}) if stage == 'review' else
               json.dumps({'chapters': [{'title': '课程定义', 'ids': [sections[0]['id']]}]}) if stage == 'chapters' else
               '## 定义\n完整课程定义、前提与推导。')
    calls = provider(monkeypatch, {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}], 'usage': usage})
    result = run(stage, local)
    if stage == 'assistant':
        assert '完整课程定义' in result['answer'] and result['cost_is_estimate']
    else:
        notes, message = result
        assert not message and '完整课程定义' in notes[0]['body']
    recorded = store.usage_for(job)['calls']
    assert len(calls) == len(recorded) == 1
    assert recorded[0]['status'] == 'completed_usage_unknown' and recorded[0]['actual'] is None
    assert recorded[0]['reserved'] > 0


@pytest.mark.parametrize('stage', ['organize', 'review', 'chapters', 'assistant'])
@pytest.mark.parametrize('payload', [None, [], {'choices': []}, {'choices': None}, {'choices': [None]}])
def test_bad_envelope_is_controlled_and_not_retried(local, monkeypatch, stage, payload):
    calls = provider(monkeypatch, payload)
    old = local[2][0]['body']
    if stage == 'chapters':
        for _ in range(2):
            notes, message = run(stage, local)
            assert notes is None and ('未能确认' in message or '先核对' in message)
    else:
        with pytest.raises(ValueError, match='确认'):
            run(stage, local)
        try:
            run(stage, local)
        except ValueError:
            pass
    assert len(calls) == 1 and local[2][0]['body'] == old
    assert store.usage_for(local[0])['calls'][0]['status'] == 'uncertain'


@pytest.mark.parametrize('content', [None, [], {'unexpected': 'object'}, 17])
def test_non_text_content_is_not_stringified_into_notes(local, monkeypatch, content):
    calls = provider(monkeypatch, {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}],
                                 'usage': {'prompt_tokens': 100, 'completion_tokens': 30}})
    old = local[2][0]['body']
    with pytest.raises(ValueError, match='未能确认'):
        run('organize', local)
    assert len(calls) == 1 and local[2][0]['body'] == old
