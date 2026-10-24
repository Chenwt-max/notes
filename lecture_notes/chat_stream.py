"""Collect one streamed chat response without reconnecting or replaying a request."""
import json as jsonlib
import time
import httpx


def stream_chat(client,url,*,headers,json:dict,check=lambda:None):
    request={**json,'stream':True,'stream_options':{'include_usage':True}}
    text=[];usage=None;finish=None;done=False;started=time.monotonic()
    with client.stream('POST',url,headers=headers,json=request) as response:
        if response.status_code!=200:
            response.read()
            return response
        for line in response.iter_lines():
            check()
            if time.monotonic()-started>300:raise httpx.ReadTimeout('复核响应超过时限',request=response.request)
            if not line.startswith('data:'):continue
            raw=line[5:].strip()
            if raw=='[DONE]':done=True;break
            chunk=jsonlib.loads(raw)
            if chunk.get('usage'):usage=chunk['usage']
            for choice in chunk.get('choices',[]):
                part=choice.get('delta',{}).get('content')
                if part:text.append(part)
                if choice.get('finish_reason'):finish=choice['finish_reason']
        if not done or finish is None:raise httpx.ReadError('复核流未完整结束，未自动重发',request=response.request)
        return httpx.Response(200,request=response.request,json={
            'choices':[{'message':{'content':''.join(text)},'finish_reason':finish}],'usage':usage})
