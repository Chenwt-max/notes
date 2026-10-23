import pytest
from fastapi.testclient import TestClient
from lecture_notes import catalog,store,server


@pytest.fixture
def local_catalog(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'OUTPUT',tmp_path/'outputs')
    monkeypatch.setattr(server,'WORKSPACE',tmp_path)
    paths = [tmp_path/f'{i}.mp4' for i in range(1,4)]
    for path in paths:
        path.write_bytes(b'not decoded in catalog tests')
    return paths


def test_migration_groups_lessons_once_and_preserves_jobs(local_catalog):
    job = store.create_job({'path':str(local_catalog[0]),'title':'existing'})
    catalog.initialize(local_catalog)
    catalog.initialize(local_catalog)
    courses = catalog.list_courses()
    assert len(courses)==1
    assert [l['title'] for l in courses[0]['lessons']]==['第 1 节','第 2 节','第 3 节']
    assert store.get_job(job['id'])==job


def test_rename_move_reorder_and_reject_duplicate_assignment(local_catalog):
    catalog.initialize(local_catalog)
    first = catalog.list_courses()[0]
    second = catalog.create_course({'title':'另一门课'})['id']
    ids = [l['id'] for l in first['lessons']]
    catalog.reorder_lessons(first['id'],list(reversed(ids)))
    catalog.rename_course(first['id'],{'title':'数值分析'})
    catalog.update_lesson(ids[0],{'title':'绪论','course_id':second})
    courses = catalog.list_courses()
    assert courses[0]['title']=='数值分析'
    assert [l['id'] for l in courses[0]['lessons']]==list(reversed(ids[1:]))
    assert courses[1]['lessons'][0]['title']=='绪论'
    with pytest.raises(ValueError):
        catalog.add_lessons(second,[{'path':str(local_catalog[0])}])
    with pytest.raises(ValueError):
        catalog.reorder_lessons(first['id'],[ids[1],ids[1]])
    with pytest.raises(ValueError):
        catalog.update_lesson(ids[0],{'course_id':'missing'})
    assert len(catalog.list_courses()[1]['lessons'])==1


def test_catalog_api_adds_later_lesson_and_rejects_external_path(local_catalog,tmp_path):
    client = TestClient(server.app)
    first = client.get('/api/courses').json()[0]
    fourth = tmp_path/'4.mp4';fourth.write_bytes(b'new lesson')
    assert len(client.get('/api/courses').json()[0]['lessons'])==3
    response = client.post(f"/api/courses/{first['id']}/lessons",json={'lessons':[{'path':str(fourth),'title':'第 4 节'}]})
    assert response.status_code==200
    assert len(client.get('/api/courses').json()[0]['lessons'])==4
    assert client.post('/api/courses',json={'title':' '}).status_code==400
    assert client.post(f"/api/courses/{first['id']}/lessons",json={'lessons':[{'path':str(tmp_path.parent/'other.mp4')}]}).status_code==400
