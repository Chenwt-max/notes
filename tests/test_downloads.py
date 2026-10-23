import asyncio
import io
import zipfile
from lecture_notes import server
from lecture_notes.common import write_json


def test_compact_download_only_includes_posters_and_leaves_no_zip(tmp_path,monkeypatch):
    output=tmp_path/'job';(output/'images').mkdir(parents=True)
    (output/'images/a.png').write_bytes(b'poster')
    (output/'images/b.png').write_bytes(b'supplement')
    write_json(output/'visuals.json',[
        {'id':'a','is_representative':True,'image':'images/a.png','capture_ts':3},
        {'id':'b','is_representative':False,'image':'images/b.png','capture_ts':1}])
    monkeypatch.setattr(server,'OUTPUT',tmp_path)
    monkeypatch.setattr(server,'get_job',lambda _: {'status':'materials_ready','spec':{'title':'第一节'}})
    response=server.download_pages('job')
    async def collect():return b''.join([chunk async for chunk in response.body_iterator])
    with zipfile.ZipFile(io.BytesIO(asyncio.run(collect()))) as bundle:
        assert set(bundle.namelist())=={'images/a.png','index.html'}
        assert bundle.read('images/a.png')==b'poster'
    assert not list(output.glob('*.zip'))
