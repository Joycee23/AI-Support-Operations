"""Router contract checks use MockTransport, never a real provider or API key."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock
import httpx
from server.services.ninerouter import NineRouterService
from server.services.generation_factory import FallbackGenerationService
from server.services.model_pool import GenerationProviderError, ModelsUnavailable

PAYLOAD = {'topic':'Check-in','priority':'Bình thường','suggested_team_id':None,'reason':'Source found',
           'draft':'Synthetic answer','citations':['source-test'],'grounded':True}


def response_payload(payload=PAYLOAD):
    return {'status':'completed','output':[{'type':'reasoning','summary':[]},
        {'type':'message','content':[{'type':'output_text','text':json.dumps(payload)}]}]}


class RouterContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests=[]
        self.service=NineRouterService('fake-key','http://router.test/v1','cl/luna',['cl/sol'])
        await self.service.client.aclose()

    async def asyncTearDown(self):
        await self.service.aclose()

    def transport(self, handler):
        def record(request):
            self.requests.append(request)
            return handler(request)
        self.service.client=httpx.AsyncClient(base_url='http://router.test/v1/',headers={'Authorization':'Bearer fake-key'},transport=httpx.MockTransport(record))

    async def test_responses_request_and_typed_output(self):
        self.transport(lambda _:httpx.Response(200,json=response_payload()))
        result=await self.service.generate_suggestion('Only synthetic data')
        self.assertTrue(result.grounded)
        self.assertEqual(self.requests[0].url.path,'/v1/responses')
        body=json.loads(self.requests[0].content)
        self.assertFalse(body['store'])
        self.assertIs(body['stream'], False)
        self.assertEqual(body['text']['format']['type'],'json_schema')
        self.assertEqual(self.requests[0].headers['authorization'],'Bearer fake-key')

    async def test_validate_checks_models_without_generation(self):
        self.transport(lambda _:httpx.Response(200,json={'data':[]}))
        await self.service.validate()
        self.assertEqual(self.requests[0].method,'GET')
        self.assertEqual(self.requests[0].url.path,'/v1/models')

    async def test_overload_tries_next_and_cools_down(self):
        self.transport(lambda r:httpx.Response(429 if json.loads(r.content)['model']=='cl/luna' else 200,json=response_payload()))
        await self.service.generate_suggestion('Synthetic')
        await self.service.generate_suggestion('Synthetic')
        self.assertEqual([json.loads(r.content)['model'] for r in self.requests],['cl/luna','cl/sol','cl/sol'])

    async def test_malformed_output_tries_next(self):
        self.transport(lambda r:httpx.Response(200,json=response_payload([]) if json.loads(r.content)['model']=='cl/luna' else response_payload()))
        result=await self.service.generate_suggestion('Synthetic')
        self.assertTrue(result.grounded)
        self.assertEqual(len(self.requests),2)

    async def test_incomplete_output_tries_next(self):
        self.transport(lambda r:httpx.Response(200,json={'status':'incomplete'} if json.loads(r.content)['model']=='cl/luna' else response_payload()))
        await self.service.generate_suggestion('Synthetic')
        self.assertEqual(len(self.requests),2)

    async def test_auth_error_uses_gemini_fallback_and_provider_cooldown(self):
        self.transport(lambda _:httpx.Response(401,json={'error':'synthetic'}))
        fallback=AsyncMock()
        fallback.generate_suggestion.return_value='fallback-result'
        chain=FallbackGenerationService(self.service,fallback)
        self.assertEqual(await chain.generate_suggestion('test'),'fallback-result')
        self.assertEqual(await chain.generate_suggestion('test'),'fallback-result')
        self.assertEqual(len(self.requests),1)
        self.assertEqual(fallback.generate_suggestion.await_count,2)

    async def test_no_fallback_reports_unavailable(self):
        self.transport(lambda _:httpx.Response(503,json={'error':'synthetic'}))
        with self.assertRaises(ModelsUnavailable):
            await FallbackGenerationService(self.service,None).generate_suggestion('test')

    async def test_transport_failure_uses_fallback(self):
        def unavailable(r): raise httpx.ConnectError('synthetic',request=r)
        self.transport(unavailable)
        fallback=AsyncMock()
        fallback.generate_suggestion.return_value='fallback'
        self.assertEqual(await FallbackGenerationService(self.service,fallback).generate_suggestion('test'),'fallback')

    async def test_faq_typed_json(self):
        self.transport(lambda _:httpx.Response(200,json=response_payload({'title':'Synthetic FAQ','category':'QA','content':'Only synthetic content for a test FAQ.','notes':[]})))
        self.assertEqual((await self.service.draft_knowledge('Test',{'a':'Synthetic'}))['category'],'QA')

    async def test_provider_priority_is_normalized(self):
        self.transport(lambda _:httpx.Response(200,json=response_payload({**PAYLOAD,'priority':'normal'})))
        result=await self.service.generate_suggestion('Synthetic')
        self.assertEqual(result.priority,'Bình thường')

    async def test_remote_error_body_not_exposed(self):
        self.transport(lambda _:httpx.Response(401,text='secret-must-not-escape'))
        with self.assertRaises(GenerationProviderError) as captured:
            await self.service.generate_suggestion('test')
        self.assertNotIn('secret-must-not-escape',str(captured.exception))
