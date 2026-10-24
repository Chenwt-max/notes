import json
import httpx
import pytest
from lecture_notes.chat_stream import stream_chat


def client_for(lines,status=200):
    calls=[]
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(status,text='\n'.join(lines),headers={'content-type':'text/event-stream'})
    return httpx.Client(transport=httpx.MockTransport(handle)),calls


def test_stream_collects_only_answer_and_receipt_without_reasoning():
    chunks=[{'choices':[{'delta':{'reasoning_content':'private reasoning'}}]},
            {'choices':[{'delta':{'content':'{"edits":'}}]},
            {'choices':[{'delta':{'content':'[]}'},'finish_reason':'stop'}]},
            {'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':20}}]
    client,calls=client_for([': keepalive']+['data: '+json.dumps(c) for c in chunks]+['data: [DONE]'])
    with client:response=stream_chat(client,'https://fixture.invalid',headers={},json={'model':'fixture'})
    result=response.json()
    assert result['choices'][0]['message']['content']=='{"edits":[]}'
    assert result['usage']['completion_tokens']==20 and 'private reasoning' not in response.text
    assert len(calls)==1 and calls[0]['stream_options']=={'include_usage':True}


def test_partial_stream_does_not_reconnect_or_apply_partial_edits():
    client,calls=client_for(['data: {"choices":[{"delta":{"content":"partial"}}]}'])
    with client,pytest.raises(httpx.ReadError,match='未自动重发'):
        stream_chat(client,'https://fixture.invalid',headers={},json={})
    assert len(calls)==1


def test_provider_rejection_preserves_status_for_zero_charge_settlement():
    client,calls=client_for(['rejected'],status=429)
    with client:response=stream_chat(client,'https://fixture.invalid',headers={},json={})
    assert response.status_code==429 and len(calls)==1
