"""Regression coverage using an isolated PostgreSQL schema and fake external providers."""
import asyncio
import os
import secrets
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from pathlib import Path
from server.models import Ticket
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from google.genai.errors import APIError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from server import database
from server.auth_models import Account, AccountMembership, AuthSession, Invitation, InvitationDelivery
from server.billing_models import Subscription, PaymentOrder, PaymentReceipt
from server.database import Base, get_db
from server.main import protect_browser_requests
from server.models import KnowledgeChunk, KnowledgeItem, Team, User, utcnow
from server.routes import ai, auth, billing, knowledge, reports, tickets, workspace, account_security, account_recovery
from server.services.accounts import hash_password, provision_workspace, token_hash
from server.services.billing import PaymentConfig, add_month
from server.services.gemini import GeminiService, KnowledgeDraftPayload, SuggestionPayload
from server.services.invitation_email import DeliveryResult, send_invitation
from server.services.model_pool import GenerationModelPool, ModelsUnavailable


class CalendarAndModelTests(unittest.TestCase):
    def test_calendar_month_end_and_year(self):
        value = datetime(2026, 1, 31, 10, tzinfo=timezone.utc)
        self.assertEqual(add_month(value).day, 28)
        self.assertEqual(add_month(datetime(2026, 12, 20, tzinfo=timezone.utc)).year, 2027)

    def test_failover_overload_to_next_model(self):
        operation = AsyncMock(side_effect=[APIError(503, {'error': {'message': 'busy'}}), 'ok'])
        pool = GenerationModelPool('primary', ['backup', 'backup'])
        self.assertEqual(asyncio.run(pool.call(operation)), 'ok')
        self.assertEqual([c.args[0] for c in operation.call_args_list], ['primary', 'backup'])

    def test_failover_cooldown_skips_busy_model(self):
        pool = GenerationModelPool('primary', ['backup'])
        pool._cooldowns['primary'] = float('inf')
        operation = AsyncMock(return_value='ok')
        self.assertEqual(asyncio.run(pool.call(operation)), 'ok')
        operation.assert_awaited_once_with('backup')

    def test_auth_error_does_not_fallback(self):
        operation = AsyncMock(side_effect=APIError(401, {'error': {'message': 'invalid'}}))
        with self.assertRaises(APIError): asyncio.run(GenerationModelPool('primary', ['backup']).call(operation))
        self.assertEqual(operation.await_count, 1)

    def test_all_models_unavailable(self):
        operation = AsyncMock(side_effect=APIError(503, {'error': {'message': 'busy'}}))
        with self.assertRaises(ModelsUnavailable): asyncio.run(GenerationModelPool('primary', ['backup']).call(operation))

    def test_faq_uses_typed_object_schema(self):
        service=GeminiService.__new__(GeminiService)
        service.client=MagicMock()
        service.client.aio.models.generate_content=AsyncMock(return_value=SimpleNamespace(text='{"title":"Test FAQ","category":"Test","content":"A long enough synthetic FAQ content.","notes":[]}'))
        service.pool=GenerationModelPool('test-model')
        result=asyncio.run(service.draft_knowledge('Test FAQ',{'answer':'Synthetic input'}))
        self.assertIsInstance(result,dict)
        config=service.client.aio.models.generate_content.call_args.kwargs['config']
        self.assertIs(config.response_schema,KnowledgeDraftPayload)

    @patch.dict(os.environ, {'SMTP_USERNAME': '', 'SMTP_PASSWORD': '', 'APP_PUBLIC_URL': ''})
    def test_email_unconfigured_does_not_send(self):
        with patch('smtplib.SMTP') as smtp:
            result = send_invitation(recipient='guest@example.com', token='x', workspace='Test', inviter='Admin', team='Team', role='agent', expires_at=utcnow())
        self.assertEqual(result.status, 'not_configured')
        smtp.assert_not_called()

    @patch.dict(os.environ, {'SMTP_HOST': 'smtp.gmail.com', 'SMTP_PORT': '587', 'SMTP_SECURITY': 'starttls',
                            'SMTP_USERNAME': 'sender@example.com', 'SMTP_PASSWORD': 'fake-password',
                            'SMTP_FROM_EMAIL': 'sender@example.com', 'APP_PUBLIC_URL': 'https://test.example.com'})
    def test_email_tls_content_and_link_with_mock_smtp(self):
        with patch('smtplib.SMTP') as smtp:
            smtp.return_value.send_message.return_value = {}
            result = send_invitation(recipient='guest@example.com', token='test-token', workspace='<script>test</script>',
                                     inviter='Admin', team='Team', role='agent', expires_at=utcnow())
        self.assertEqual(result.status, 'sent')
        smtp.return_value.starttls.assert_called_once()
        message = smtp.return_value.send_message.call_args.args[0]
        self.assertIn('/#invite=test-token', message.get_body(preferencelist=('plain',)).get_content())
        html = message.get_body(preferencelist=('html',)).get_content()
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'PostgreSQL test database URL required')
class OperationsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = 'test_operations_' + uuid.uuid4().hex
        cls.engine = create_engine(os.environ['TEST_DATABASE_URL'], execution_options={'schema_translate_map': {None: cls.schema}})
        with cls.engine.begin() as conn: conn.execute(CreateSchema(cls.schema))
        Base.metadata.create_all(cls.engine)
        database.SessionLocal = sessionmaker(bind=cls.engine, expire_on_commit=False, autoflush=False)

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as conn: conn.execute(DropSchema(cls.schema, cascade=True))
        cls.engine.dispose()

    def setUp(self):
        self.upload_dir = tempfile.TemporaryDirectory(prefix="support-ops-test-")
        self.addCleanup(self.upload_dir.cleanup)
        settings_patch = patch("server.routes.knowledge.get_settings", return_value=SimpleNamespace(upload_dir=self.upload_dir.name))
        settings_patch.start(); self.addCleanup(settings_patch.stop)
        self.db = database.SessionLocal()
        account = Account(id=uuid.uuid4().hex, email=uuid.uuid4().hex+'@example.com', name='Test Admin', password_hash=hash_password('fake-test-password'))
        self.db.add(account); self.db.flush()
        self.ws, self.admin = provision_workspace(self.db, account, 'Isolated test workspace')
        self.other, self.other_admin = provision_workspace(self.db, account, 'Other test workspace')
        self.team = self.db.get(Team, self.admin.team_id)
        self.second = Team(id=uuid.uuid4().hex, workspace_id=self.ws.id, name='Other team', color='blue')
        self.db.add(self.second); self.db.flush()
        self.agent = User(id=uuid.uuid4().hex, workspace_id=self.ws.id, team_id=self.team.id, name='Test agent', email=uuid.uuid4().hex+'@example.com', role='agent')
        self.db.add(self.agent); self.db.flush()
        # Global account membership here is test-only, never persisted in the application schema.
        second_account = Account(id=uuid.uuid4().hex, email=self.agent.email, name='Test agent', password_hash=hash_password('fake-test-password'))
        self.db.add(second_account); self.db.flush()
        self.db.add(AccountMembership(account_id=second_account.id, user_id=self.agent.id, workspace_id=self.ws.id))
        self.db.commit()
        app = FastAPI()
        for router in (auth.router, workspace.router, tickets.router, knowledge.router, ai.router, billing.router, reports.router, account_security.router, account_recovery.router): app.include_router(router)
        app.middleware('http')(protect_browser_requests)
        app.dependency_overrides[get_db] = lambda: self.db
        app.state.embedding = type('Embedding', (), {'embed_document': AsyncMock(return_value=[1.0]+[0.0]*767), 'embed_query': AsyncMock(return_value=[1.0]+[0.0]*767)})()
        app.state.gemini = type('Gemini', (), {'generate_suggestion': AsyncMock(), 'draft_knowledge': AsyncMock()})()
        self.app = app
        self.client = TestClient(app, headers={'Origin': 'http://testserver'})
        self.login_as(self.admin)
        self.addCleanup(self.client.close)
        self.addCleanup(self.db.close)
        self.config = PaymentConfig(499000, 'MB', '0000000000', 'TEST ONLY', 'x'*40)

    def login_as(self, user):
        link = self.db.get(AccountMembership, user.id)
        token = secrets.token_urlsafe(32)
        self.db.add(AuthSession(token_hash=token_hash(token), account_id=link.account_id, user_id=user.id, expires_at=utcnow()+timedelta(days=1)))
        self.db.commit()
        self.client.cookies.set('support_session', token)

    def create_ticket(self, *, team_id=None, subject='Test ticket'):
        response = self.client.post('/api/tickets', json={'customer_name':'Guest test','customer_email':'guest@example.com','subject':subject,'body':'Test lodging question','team_id':team_id or self.team.id,'channel':'Chat'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def create_knowledge(self, title='Original knowledge'):
        response = self.client.post('/api/knowledge', json={'title':title,'category':'Test category','content':'Initial content for isolated testing, never a real policy.','team_id':None})
        self.assertEqual(response.status_code,201,response.text)
        self.db.expire_all()
        return response.json()['id']

    def test_unauthenticated_access_denied(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/bootstrap').status_code,401)

    def test_stale_membership_denied(self):
        self.assertEqual(self.client.get('/api/bootstrap',headers={'X-Workspace-Membership':'invalid-user'}).status_code,409)

    def test_cross_workspace_ticket_and_knowledge_hidden(self):
        self.login_as(self.other_admin)
        ticket = self.create_ticket(team_id=self.other_admin.team_id)
        item_id = self.create_knowledge()
        self.login_as(self.admin)
        self.assertEqual(self.client.get('/api/tickets/'+ticket['id']).status_code,404)
        self.assertEqual(self.client.get('/api/knowledge/'+item_id+'/versions').status_code,404)
        self.assertNotIn(ticket['id'],[t['id'] for t in self.client.get('/api/tickets').json()])

    def test_agent_cannot_manage_knowledge_teams_invitations(self):
        self.login_as(self.agent)
        self.assertEqual(self.client.post('/api/admin/teams',json={'name':'Denied'}).status_code,403)
        self.assertEqual(self.client.post('/api/knowledge',json={'title':'Denied title','category':'Test','content':'Enough content for validation','team_id':self.team.id}).status_code,403)
        self.assertEqual(self.client.post('/api/auth/invitations',json={'email':'nobody@example.com','team_id':self.team.id,'role':'agent'}).status_code,403)

    def test_agent_cannot_see_other_team_ticket(self):
        ticket = self.create_ticket(team_id=self.second.id)
        self.login_as(self.agent)
        self.assertEqual(self.client.get('/api/tickets/'+ticket['id']).status_code,404)

    def test_expired_trial_read_only_billing_available(self):
        sub = self.db.get(Subscription,self.ws.id)
        sub.trial_ends_at = utcnow()-timedelta(days=1); self.db.commit()
        self.assertEqual(self.client.get('/api/bootstrap').status_code,200)
        self.assertEqual(self.client.post('/api/admin/teams',json={'name':'No write'}).status_code,402)
        with patch('server.routes.billing.payment_config',return_value=self.config):
            self.assertEqual(self.client.post('/api/billing/orders').status_code,201)

    def test_invitation_email_failure_preserves_link_and_revocation(self):
        with patch('server.routes.auth.send_invitation',return_value=DeliveryResult('failed','SMTP failure for test')):
            response=self.client.post('/api/auth/invitations',json={'email':'invitee@example.com','team_id':self.team.id,'role':'agent'})
        self.assertEqual(response.status_code,201,response.text)
        result=response.json()
        self.assertEqual(result['emailDelivery']['status'],'failed')
        self.assertEqual(self.client.post('/api/auth/invitations/preview',json={'token':result['token']}).status_code,200)
        listing=self.client.get('/api/auth/invitations').json()
        self.assertEqual(listing[0]['emailDelivery']['status'],'failed')
        self.assertEqual(self.client.delete('/api/auth/invitations/'+listing[0]['id']).status_code,200)
        self.assertEqual(self.client.post('/api/auth/invitations/preview',json={'token':result['token']}).status_code,410)

    def test_knowledge_history_no_duplicate_or_wrong_previous_title(self):
        item_id=self.create_knowledge('First title')
        response=self.client.put('/api/knowledge/'+item_id,json={'title':'Second title','category':'New category','content':'Updated isolated test document content.','team_id':None,'change_note':'Change title/content'})
        self.assertEqual(response.status_code,200,response.text)
        versions=self.client.get('/api/knowledge/'+item_id+'/versions').json()
        self.assertEqual([v['version'] for v in versions],[2,1])
        self.assertEqual(versions[1]['title'],'First title')

    def test_upload_blank_metadata_rejected(self):
        response=self.client.post('/api/knowledge/upload',params={'title':' ','category':' '},files={'file':('test.txt',b'Only isolated fixture content','text/plain')})
        self.assertEqual(response.status_code,422,response.text)

    def test_valid_text_upload_ingested_and_approved(self):
        response=self.client.post('/api/knowledge/upload',params={'title':'Uploaded test fixture','category':'Test'},files={'file':('test.md',b'# Test fixture\nOnly synthetic content for ingestion testing.','text/markdown')})
        self.assertEqual(response.status_code,202,response.text)
        item_id=response.json()['id']
        self.db.expire_all()
        self.assertEqual(self.db.get(KnowledgeItem,item_id).processing_status,'ready')
        self.assertEqual(self.client.post('/api/knowledge/'+item_id+'/approve').status_code,200)

    def test_manager_cannot_invite_other_team_or_promote(self):
        self.agent.role='manager';self.db.commit();self.login_as(self.agent)
        for role,team in [('manager',self.team.id),('agent',self.second.id)]:
            self.assertEqual(self.client.post('/api/auth/invitations',json={'email':'guest@example.com','team_id':team,'role':role}).status_code,403)

    def test_whitespace_knowledge_fields_rejected(self):
        response=self.client.post('/api/knowledge',json={'title':'   ','category':'Test','content':'This is enough content for a valid body.'})
        self.assertEqual(response.status_code,422)

    def test_invitation_wrong_email_and_single_use(self):
        account=Account(id=uuid.uuid4().hex,email=uuid.uuid4().hex+'@example.com',name='Invitee test',password_hash=hash_password('fake-test-password'))
        self.db.add(account);self.db.flush()
        _,invitee=provision_workspace(self.db,account,'Invitee source');self.db.commit()
        with patch('server.routes.auth.send_invitation',return_value=DeliveryResult('sent','Mock SMTP accepted')):
            response=self.client.post('/api/auth/invitations',json={'email':account.email,'team_id':self.team.id,'role':'agent'})
        self.assertEqual(response.status_code,201,response.text)
        payload={'token':response.json()['token']}
        self.assertEqual(self.client.post('/api/auth/invitations/accept',json=payload).status_code,403)
        self.login_as(invitee)
        self.assertEqual(self.client.post('/api/auth/invitations/accept',json=payload).status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap').json()['workspaceId'],self.ws.id)
        self.assertEqual(self.client.post('/api/auth/invitations/accept',json=payload).status_code,410)

    def test_ai_rejects_citations_without_approved_context(self):
        ticket=self.create_ticket()
        self.app.state.gemini.generate_suggestion.return_value=SuggestionPayload(topic='Test',priority='Bình thường',suggested_team_id=None,reason='Test',draft='Invented answer',citations=['fake-id'],grounded=True)
        response=self.client.post('/api/ai/tickets/'+ticket['id']+'/suggest')
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['grounded'])
        self.assertEqual(response.json()['draft'],'')
        report=self.client.get('/api/reports/quality').json()
        self.assertEqual(report['recent'][0]['ticketCode'],ticket['code'])

    def test_pending_archived_other_team_not_retrieved(self):
        self.login_as(self.agent)
        from server.services.retrieval import retrieve_approved_context
        item_ids=[]
        for status,team in [('approved',self.team.id),('pending',self.team.id),('archived',self.team.id),('approved',self.second.id)]:
            item=KnowledgeItem(id=uuid.uuid4().hex,workspace_id=self.ws.id,team_id=team,created_by=self.admin.id,title='Test source',category='Test',content='Test source content',status=status,processing_status='ready')
            self.db.add(item);self.db.flush()
            self.db.add(KnowledgeChunk(id=uuid.uuid4().hex,workspace_id=self.ws.id,team_id=team,knowledge_id=item.id,chunk_index=0,content='Test source content',embedding=[1.0]+[0.0]*767))
            item_ids.append(item.id)
        self.db.commit()
        ticket=type('Ticket',(),{'subject':'Test','body':'Test body','topic':'Test'})()
        rows=asyncio.run(retrieve_approved_context(self.db,self.agent,ticket,self.app.state.embedding))
        self.assertEqual([r['knowledge_id'] for r in rows],[item_ids[0]])

    def test_register_login_logout_and_empty_workspace(self):
        self.client.cookies.clear()
        email=uuid.uuid4().hex+'@example.com'
        data={'name':'QA Account','email':email,'password':'temporary-test-password','workspace_name':'QA Register'}
        self.assertEqual(self.client.post('/api/auth/register',json=data).status_code,201)
        bootstrap=self.client.get('/api/bootstrap').json()
        self.assertEqual(bootstrap['tickets'],[])
        self.assertEqual(bootstrap['knowledge'],[])
        self.assertEqual(bootstrap['subscription']['status'],'trialing')
        self.assertEqual(self.client.post('/api/auth/logout').status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap').status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'email':email,'password':'wrong'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'email':email,'password':data['password']}).status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap').json()['workspaceId'],bootstrap['workspaceId'])

    def test_origin_rejected_and_cookie_header_not_impersonation(self):
        response=self.client.post('/api/admin/teams',json={'name':'Blocked origin'},headers={'Origin':'https://attacker.example'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.client.get('/api/bootstrap',headers={'X-Workspace-Membership':self.other_admin.id}).status_code,409)

    def test_ticket_all_states_priorities_and_messages(self):
        ticket=self.create_ticket()
        for status in tickets.VALID_STATUSES:
            self.assertEqual(self.client.patch('/api/tickets/'+ticket['id'],json={'status':status}).status_code,200)
        for priority in tickets.VALID_PRIORITIES:
            self.assertEqual(self.client.patch('/api/tickets/'+ticket['id'],json={'priority':priority}).status_code,200)
        self.assertEqual(self.client.patch('/api/tickets/'+ticket['id'],json={'priority':'invalid'}).status_code,422)
        self.assertEqual(self.client.patch('/api/tickets/'+ticket['id'],json={'note':' QA internal ','reply':' QA reply '}).status_code,200)
        messages=self.client.get('/api/tickets/'+ticket['id']).json()['messages']
        self.assertEqual([m['body'] for m in messages],['QA internal','QA reply'])
        self.assertEqual([m['internal'] for m in messages],[True,False])

    def test_assignment_and_filter_scope(self):
        ticket=self.create_ticket()
        self.assertEqual(self.client.patch('/api/tickets/'+ticket['id'],json={'team_id':self.second.id,'assignee_id':self.agent.id}).status_code,422)
        self.assertEqual(self.client.patch('/api/tickets/'+ticket['id'],json={'assignee_id':self.agent.id}).status_code,200)
        self.login_as(self.agent)
        self.assertEqual([t['id'] for t in self.client.get('/api/tickets',params={'scope':'mine','search':'Test ticket'}).json()],[ticket['id']])
        self.assertEqual(self.client.patch('/api/tickets/'+ticket['id'],json={'assignee_id':None}).status_code,403)

    def test_manager_cannot_edit_global_knowledge(self):
        item_id=self.create_knowledge()
        self.agent.role='manager';self.db.commit();self.login_as(self.agent)
        self.assertEqual(self.client.get('/api/knowledge/'+item_id+'/versions').status_code,200)
        self.assertEqual(self.client.post('/api/knowledge/'+item_id+'/approve').status_code,403)
        self.assertEqual(self.client.put('/api/knowledge/'+item_id,json={'title':'Denied title','category':'QA','content':'Enough synthetic text for validation.','team_id':self.team.id}).status_code,403)

    def test_upload_invalid_empty_and_oversize(self):
        params={'title':'QA Upload','category':'QA'}
        for filename,content,expected in [('bad.exe',b'bad',415),('empty.txt',b'',422),('bad.pdf',b'not-a-pdf',415),('huge.txt',b'x'*(10*1024*1024+1),413)]:
            response=self.client.post('/api/knowledge/upload',params=params,files={'file':(filename,content)})
            self.assertEqual(response.status_code,expected,response.text)
            if expected==202:
                self.db.expire_all()
                self.assertEqual(self.db.get(KnowledgeItem,response.json()['id']).processing_status,'failed')

    def test_feedback_atomic_and_idempotent(self):
        from server.models import AIAnalysis
        ticket=self.create_ticket()
        analysis=AIAnalysis(id=uuid.uuid4().hex,workspace_id=self.ws.id,ticket_id=ticket['id'],requested_by=self.admin.id,
            topic='QA',priority='Cao',reason='Synthetic',draft='Original synthetic reply',citations='[]',grounded=True)
        self.db.add(analysis);self.db.commit()
        body={'decision':'edited','edited_draft':'Edited synthetic reply','save_reply':True}
        path='/api/ai/analyses/'+analysis.id+'/feedback'
        for _ in range(2): self.assertEqual(self.client.post(path,json=body).status_code,200)
        detail=self.client.get('/api/tickets/'+ticket['id']).json()
        self.assertEqual([m['body'] for m in detail['messages']],['Edited synthetic reply'])
        self.assertEqual(detail['ticket']['priority'],'Cao')
        self.assertEqual(self.client.post(path,json={'decision':'rejected'}).status_code,409)

    def test_ungrounded_feedback_cannot_save_reply(self):
        from server.models import AIAnalysis
        ticket=self.create_ticket()
        analysis=AIAnalysis(id=uuid.uuid4().hex,workspace_id=self.ws.id,ticket_id=ticket['id'],requested_by=self.admin.id,
            topic='QA',priority='Cao',reason='Synthetic',draft='',citations='[]',grounded=False)
        self.db.add(analysis);self.db.commit()
        path='/api/ai/analyses/'+analysis.id+'/feedback'
        self.assertEqual(self.client.post(path,json={'decision':'accepted','save_reply':True}).status_code,422)
        self.assertEqual(self.client.post(path,json={'decision':'rejected'}).status_code,200)

    def test_old_ingestion_does_not_publish_over_new_version(self):
        from server.services.ingestion import ingest_item
        item_id=self.create_knowledge()
        self.db.expire_all()
        async def edit_while_embedding(text):
            with database.SessionLocal() as other:
                item=other.get(KnowledgeItem,item_id)
                item.version+=1;item.content='New content must not be overwritten by old worker.';item.processing_status='queued'
                other.commit()
            return [1.0]+[0.0]*767
        self.db.get(KnowledgeItem,item_id).processing_status='queued'
        self.db.commit()
        provider=SimpleNamespace(embed_document=edit_while_embedding)
        asyncio.run(ingest_item(item_id,provider))
        self.db.expire_all()
        item=self.db.get(KnowledgeItem,item_id)
        self.assertEqual(item.processing_status,'queued')
        self.assertTrue(item.content.startswith('New content'))

    @patch.dict(os.environ, {'APP_PUBLIC_URL':'https://public-test.example.com'})
    def test_public_https_origin_allowed_but_other_origin_rejected(self):
        response=self.client.post('/api/auth/invitations/preview',json={'token':'nonexistent-token-for-test'},headers={'Origin':'https://public-test.example.com'})
        self.assertEqual(response.status_code,410)
        response=self.client.post('/api/auth/invitations/preview',json={'token':'nonexistent-token-for-test'},headers={'Origin':'https://evil.example.com'})
        self.assertEqual(response.status_code,403)

    def test_shared_rate_limit_is_atomic(self):
        from concurrent.futures import ThreadPoolExecutor
        from server.services.abuse import consume_limits
        from fastapi import HTTPException
        key='qa-rate:'+uuid.uuid4().hex
        def attempt(_):
            try:
                consume_limits([(key,5,60)])
                return 200
            except HTTPException as exc:
                self.assertIn('Retry-After',exc.headers)
                return exc.status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses=list(pool.map(attempt,range(16)))
        self.assertEqual(statuses.count(200),5)
        self.assertEqual(statuses.count(429),11)

    def test_ai_workspace_quota_rejects_before_provider(self):
        from server.services.abuse import consume_limits
        consume_limits([('ai:daily:'+self.ws.id,1,86400)])
        ticket=self.create_ticket()
        with patch.dict(os.environ,{'AI_WORKSPACE_PER_DAY':'1'}):
            response=self.client.post('/api/ai/tickets/'+ticket['id']+'/suggest')
        self.assertEqual(response.status_code,429)
        self.app.state.gemini.generate_suggestion.assert_not_awaited()
        self.app.state.embedding.embed_query.assert_not_awaited()

    def test_resource_concurrency_release_and_expiry(self):
        from server.services.abuse import resource_slot
        from server.auth_models import ResourceLease
        from fastapi import HTTPException
        async def run():
            async with resource_slot(self.ws.id,self.admin.id):
                with self.assertRaises(HTTPException):
                    async with resource_slot(self.ws.id,self.admin.id): pass
            async with resource_slot(self.ws.id,self.admin.id): pass
        asyncio.run(run())
        with database.SessionLocal() as db:
            self.assertEqual(list(db.scalars(select(ResourceLease))),[])

    def test_change_password_revokes_previous_session(self):
        old=self.client.cookies.get('support_session')
        response=self.client.post('/api/auth/change-password',json={'current_password':'fake-test-password','new_password':'new-fake-test-password'})
        self.assertEqual(response.status_code,200)
        self.assertIsNone(self.db.get(AuthSession,token_hash(old)))
        self.assertEqual(self.client.get('/api/bootstrap').status_code,200)
        self.assertEqual(self.client.post('/api/auth/logout-all').status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap').status_code,401)

    def test_mfa_encryption_login_replay_and_recovery(self):
        import time
        from cryptography.fernet import Fernet
        from server.services.mfa import totp
        from server.auth_models import AccountMFA
        with patch.dict(os.environ,{'APP_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
            response=self.client.post('/api/auth/security/mfa/setup',json={'password':'fake-test-password'})
            self.assertEqual(response.status_code,200)
            secret=response.json()['secret']
            counter=int(time.time())//30
            response=self.client.post('/api/auth/security/mfa/enable',json={'code':totp(secret,counter)})
            self.assertEqual(response.status_code,200)
            codes=response.json()['recoveryCodes']
            link=self.db.get(AccountMembership,self.admin.id)
            record=self.db.get(AccountMFA,link.account_id)
            self.assertNotIn(secret,record.secret_encrypted)
            self.assertNotIn(codes[0].replace('-',''),record.recovery_hashes)
            body={'email':self.admin.email,'password':'fake-test-password'}
            self.client.post('/api/auth/logout')
            self.assertEqual(self.client.post('/api/auth/login',json=body).status_code,401)
            self.assertEqual(self.client.post('/api/auth/login',json={**body,'code':totp(secret,counter)}).status_code,401)
            self.assertEqual(self.client.post('/api/auth/login',json={**body,'code':codes[0]}).status_code,200)
            self.client.post('/api/auth/logout')
            self.assertEqual(self.client.post('/api/auth/login',json={**body,'code':codes[0]}).status_code,401)

    @patch('server.routes.account_recovery.send_account_link')
    def test_email_verification_and_password_reset_single_use(self,send):
        self.assertEqual(self.client.post('/api/auth/request-verification').status_code,200)
        verification=send.call_args.kwargs['token']
        self.assertEqual(self.client.post('/api/auth/verify-email',json={'token':verification}).status_code,200)
        self.assertTrue(self.client.get('/api/auth/security').json()['emailVerified'])
        self.assertEqual(self.client.post('/api/auth/verify-email',json={'token':verification}).status_code,410)
        old=self.client.cookies.get('support_session')
        self.assertEqual(self.client.post('/api/auth/forgot-password',json={'email':self.admin.email}).status_code,200)
        token=send.call_args.kwargs['token']
        body={'token':token,'password':'new-password-for-test'}
        self.assertEqual(self.client.post('/api/auth/reset-password',json=body).status_code,200)
        self.assertIsNone(self.db.get(AuthSession,token_hash(old)))
        self.assertEqual(self.client.post('/api/auth/reset-password',json=body).status_code,410)

    @patch.dict(os.environ,{'APP_ENV':'production'})
    def test_production_requires_verified_email_for_mutations(self):
        response=self.client.post('/api/admin/teams',json={'name':'Unverified team'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.client.get('/api/bootstrap').status_code,200)

    def test_http_ip_limit_cannot_be_bypassed_with_forwarded_headers(self):
        from server.http_security import SecurityMiddleware
        self.app.add_middleware(SecurityMiddleware)
        with patch.dict(os.environ,{'API_IP_PER_MINUTE':'2'}):
            codes=[self.client.get('/api/bootstrap',headers={'X-Forwarded-For':'192.0.2.'+str(i)}).status_code for i in range(3)]
        self.assertEqual(codes,[200,200,429])

    @patch.dict(os.environ,{'APP_ENV':'production'})
    def test_production_privileged_mutations_require_mfa(self):
        from server.auth_models import AccountEmailVerification
        link=self.db.get(AccountMembership,self.admin.id)
        self.db.add(AccountEmailVerification(account_id=link.account_id));self.db.commit()
        self.assertEqual(self.client.post('/api/admin/teams',json={'name':'Needs MFA'}).status_code,403)

    def test_expired_resource_lease_is_reclaimed(self):
        from server.services.abuse import resource_slot
        from server.auth_models import ResourceLease
        self.db.add(ResourceLease(id=uuid.uuid4().hex,resource='generation',workspace_id=self.ws.id,user_id=self.admin.id,expires_at=utcnow()-timedelta(seconds=1)))
        self.db.commit()
        async def run():
            async with resource_slot(self.ws.id,self.admin.id): pass
        asyncio.run(run())
        self.assertEqual(list(self.db.scalars(select(ResourceLease))),[])

    def test_document_count_and_upload_storage_limits(self):
        self.create_knowledge()
        with patch.dict(os.environ,{'KNOWLEDGE_WORKSPACE_MAX_ITEMS':'1'}):
            response=self.client.post('/api/knowledge',json={'title':'Over limit title','category':'Test','content':'Synthetic text for quota test.'})
        self.assertEqual(response.status_code,409)
        with patch.dict(os.environ,{'UPLOAD_WORKSPACE_BYTES':'10'}):
            response=self.client.post('/api/knowledge/upload?title=Quota%20test&category=Test',files={'file':('qa.txt',b'This synthetic text exceeds ten bytes.','text/plain')})
        self.assertEqual(response.status_code,413)

    def test_upload_admission_rejects_unauthenticated_before_parsing(self):
        from server.http_security import SecurityMiddleware
        self.app.add_middleware(SecurityMiddleware)
        self.client.cookies.clear()
        response=self.client.post('/api/knowledge/upload',content=b'not-multipart')
        self.assertEqual(response.status_code,401)

    def order(self):
        with patch('server.routes.billing.payment_config',return_value=self.config):
            response=self.client.post('/api/billing/orders')
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def event(self, order, event_id, amount=499000):
        return {'id':event_id,'accountNumber':self.config.account,'transferType':'in','transferAmount':amount,'content':order['transferCode'],'code':None,'referenceCode':'TEST-REF'}

    def deliver(self,event):
        with patch('server.routes.billing.payment_config',return_value=self.config):
            return self.client.post('/api/billing/sepay/webhook',json=event,headers={'Authorization':'Apikey '+self.config.secret})

    def test_webhook_rejects_missing_auth(self):
        order=self.order()
        with patch('server.routes.billing.payment_config',return_value=self.config):
            self.assertEqual(self.client.post('/api/billing/sepay/webhook',json=self.event(order,uuid.uuid4().int%10**12)).status_code,401)

    def test_webhook_idempotent_and_preserves_remaining_trial(self):
        order=self.order()
        self.assertEqual(order['id'],self.order()['id'])
        trial_end=self.db.get(Subscription,self.ws.id).trial_ends_at
        event=self.event(order,uuid.uuid4().int%10**12)
        self.assertEqual(self.deliver(event).status_code,200)
        self.db.expire_all()
        paid_until=self.db.get(Subscription,self.ws.id).paid_until
        self.assertEqual(paid_until,add_month(trial_end))
        self.assertEqual(self.deliver(event).status_code,200)
        self.db.expire_all()
        self.assertEqual(self.db.get(Subscription,self.ws.id).paid_until,paid_until)
        self.assertEqual(self.client.get('/api/billing/orders/'+order['id']).json()['status'],'paid')

    def test_webhook_wrong_amount_does_not_grant_access(self):
        order=self.order()
        response=self.deliver(self.event(order,uuid.uuid4().int%10**12,amount=1000))
        self.assertEqual(response.status_code,200)
        self.db.expire_all()
        self.assertIsNone(self.db.get(Subscription,self.ws.id).paid_until)
        self.assertIsNone(self.db.get(PaymentOrder,order['id']).paid_at)


    def test_search_injection_is_data_not_sql(self):
        self.create_ticket(subject='Safe QA title')
        for payload in ["' OR 1=1 --", "%; DROP TABLE tickets; --", "../.env", "<script>alert(1)</script>"]:
            response=self.client.get('/api/tickets',params={'search':payload})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json(),[])
        self.assertTrue(self.client.get('/api/tickets').json())

    def test_forged_role_and_workspace_fields_cannot_escalate(self):
        self.login_as(self.agent)
        response=self.client.post('/api/admin/teams',json={'name':'Injected team','role':'admin','workspace_id':self.other.id})
        self.assertEqual(response.status_code,403)
        ticket=self.create_ticket(subject='QA forged workspace')
        result=self.client.patch('/api/tickets/'+ticket['id'],json={'workspace_id':self.other.id,'role':'admin','team_id':self.other_admin.team_id})
        self.assertEqual(result.status_code,403)
        self.db.rollback();self.db.expire_all()
        self.assertEqual(self.db.get(User,self.agent.id).role,'agent')
        self.assertEqual(self.db.get(Ticket,ticket['id']).workspace_id,self.ws.id)

    def test_webhook_overpayment_outbound_and_wrong_account_do_not_renew(self):
        order=self.order()
        for mode in ('overpaid','outbound','wrong_account','two_codes'):
            event=self.event(order,uuid.uuid4().int%10**12)
            if mode=='overpaid':event['transferAmount']=500000
            elif mode=='outbound':event['transferType']='out'
            elif mode=='wrong_account':event['accountNumber']='not-our-account'
            else:event['content']+=' ASO'+uuid.uuid4().hex[:20].upper()
            self.assertEqual(self.deliver(event).status_code,200)
            self.db.expire_all()
            self.assertIsNone(self.db.get(PaymentOrder,order['id']).paid_at)
            self.assertIsNone(self.db.get(Subscription,self.ws.id).paid_until)

    def test_late_settlement_honors_original_snapshot(self):
        order=self.order()
        self.db.get(PaymentOrder,order['id']).expires_at=utcnow()-timedelta(minutes=1);self.db.commit()
        event=self.event(order,uuid.uuid4().int%10**12)
        self.assertEqual(self.deliver(event).status_code,200)
        self.db.expire_all()
        self.assertIsNotNone(self.db.get(PaymentOrder,order['id']).paid_at)

    def test_paid_order_second_bank_transaction_does_not_extend_twice(self):
        order=self.order()
        self.assertEqual(self.deliver(self.event(order,uuid.uuid4().int%10**12)).status_code,200)
        self.db.expire_all();paid=self.db.get(Subscription,self.ws.id).paid_until
        self.assertEqual(self.deliver(self.event(order,uuid.uuid4().int%10**12)).status_code,200)
        self.db.expire_all();self.assertEqual(self.db.get(Subscription,self.ws.id).paid_until,paid)

    def test_upload_path_and_executable_disguises_rejected(self):
        for filename,data in [('payload.html',b'<script>evil()</script>'),('fake.pdf',b'not a real pdf'),('binary.txt',bytes([0,0])),('bad.txt',bytes([255,254]))]:
            response=self.client.post('/api/knowledge/upload',params={'title':'QA upload attack','category':'QA'},files={'file':(filename,data,'application/octet-stream')})
            self.assertIn(response.status_code,(415,422))
        self.assertEqual(list(Path(self.upload_dir.name).glob('**/*')),[])

    def test_faq_answer_limits_reject_before_generation(self):
        for answers in ({str(x):'a' for x in range(21)}, {'a':'x'*4001}):
            response=self.client.post('/api/knowledge/draft-faq',json={'subject':'QA FAQ','answers':answers})
            self.assertEqual(response.status_code,422)
        self.app.state.gemini.draft_knowledge.assert_not_awaited()

    def test_logout_all_revokes_existing_sessions(self):
        self.assertEqual(self.client.post('/api/auth/logout-all').status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap').status_code,401)

    def test_failed_knowledge_retry_reprocesses_without_new_version(self):
        item_id=self.create_knowledge('Retry test knowledge')
        item=self.db.get(KnowledgeItem,item_id);version=item.version
        item.processing_status='failed';self.db.commit()
        response=self.client.post('/api/knowledge/'+item_id+'/retry')
        self.assertEqual(response.status_code,202,response.text)
        self.db.expire_all();item=self.db.get(KnowledgeItem,item_id)
        self.assertEqual(item.processing_status,'ready')
        self.assertEqual(item.version,version)
        self.assertEqual(self.client.post('/api/knowledge/'+item_id+'/retry').status_code,409)

    def test_agent_and_cross_workspace_cannot_retry_knowledge(self):
        item_id=self.create_knowledge('Retry permission knowledge')
        item=self.db.get(KnowledgeItem,item_id);item.processing_status='failed';self.db.commit()
        self.login_as(self.agent)
        self.assertEqual(self.client.post('/api/knowledge/'+item_id+'/retry').status_code,403)
        self.login_as(self.other_admin)
        self.assertEqual(self.client.post('/api/knowledge/'+item_id+'/retry').status_code,404)

    def test_archived_failed_knowledge_cannot_retry(self):
        item_id=self.create_knowledge('Archived retry knowledge')
        item=self.db.get(KnowledgeItem,item_id);item.processing_status='failed';item.status='archived';self.db.commit()
        self.assertEqual(self.client.post('/api/knowledge/'+item_id+'/retry').status_code,409)



    def test_workspace_switch_rename_create_and_isolation(self):
        self.create_ticket(subject='Only in first workspace')
        self.assertEqual(self.client.patch('/api/admin/workspace',json={'name':'Renamed QA workspace'}).status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap').json()['workspace'],'Renamed QA workspace')
        self.assertEqual(self.client.post('/api/auth/switch-workspace',json={'membership_id':self.agent.id}).status_code,404)
        self.assertEqual(self.client.post('/api/auth/switch-workspace',json={'membership_id':self.other_admin.id}).status_code,200)
        self.assertEqual(self.client.get('/api/tickets').json(),[])
        result=self.client.post('/api/admin/workspaces',json={'name':'New isolated workspace'})
        self.assertEqual(result.status_code,201)
        self.assertEqual(self.client.get('/api/bootstrap').json()['workspace'],'New isolated workspace')
        self.assertEqual(self.client.get('/api/tickets').json(),[])

    def test_team_creation_duplicate_and_scoped_listing(self):
        result=self.client.post('/api/admin/teams',json={'name':'QA coverage team','color':'blue'})
        self.assertEqual(result.status_code,201)
        self.assertEqual(self.client.post('/api/admin/teams',json={'name':'QA coverage team','color':'blue'}).status_code,409)
        teams=self.client.get('/api/teams')
        self.assertEqual(teams.status_code,200)
        self.assertIn(result.json()['id'],[row['id'] for row in teams.json()])
        self.login_as(self.other_admin)
        self.assertNotIn(result.json()['id'],[row['id'] for row in self.client.get('/api/teams').json()])

    def test_knowledge_listing_archive_and_scoped_audit(self):
        item_id=self.create_knowledge('Searchable QA knowledge')
        result=self.client.get('/api/knowledge',params={'search':'Searchable','status':'pending'})
        self.assertEqual(result.status_code,200)
        self.assertIn(item_id,[row['id'] for row in result.json()])
        self.assertEqual(self.client.post('/api/knowledge/'+item_id+'/archive').status_code,200)
        self.assertIn(item_id,[row['id'] for row in self.client.get('/api/knowledge',params={'status':'archived'}).json()])
        self.assertTrue(any(row['kind']=='knowledge.archived' for row in self.client.get('/api/audit').json()))
        self.login_as(self.other_admin)
        self.assertEqual(self.client.get('/api/knowledge').json(),[])
        self.assertEqual(self.client.get('/api/audit').json(),[])

    def test_billing_overview_hides_orders_from_agent(self):
        with patch('server.routes.billing.payment_config',return_value=self.config):
            self.assertEqual(self.client.post('/api/billing/orders').status_code,201)
            result=self.client.get('/api/billing')
            self.assertEqual(result.status_code,200);self.assertEqual(len(result.json()['orders']),1)
            self.login_as(self.agent)
            self.assertEqual(self.client.get('/api/billing').json()['orders'],[])
            self.assertEqual(self.client.post('/api/billing/orders').status_code,403)

    def test_faq_success_provider_error_and_agent_denial(self):
        self.app.state.logger=MagicMock()
        self.app.state.gemini.draft_knowledge.return_value={'title':'QA FAQ','category':'Test','content':'Test only, not a real policy.','notes':[]}
        payload={'subject':'QA FAQ','answers':{'answer':'Only approved synthetic facts'}}
        result=self.client.post('/api/knowledge/draft-faq',json=payload)
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['status'],'pending_review')
        self.app.state.gemini.draft_knowledge.side_effect=RuntimeError('DO_NOT_LEAK_PROVIDER_SECRET')
        result=self.client.post('/api/knowledge/draft-faq',json=payload)
        self.assertEqual(result.status_code,502);self.assertNotIn('DO_NOT_LEAK',result.text)
        self.login_as(self.agent)
        self.assertEqual(self.client.post('/api/knowledge/draft-faq',json=payload).status_code,403)

    def test_mfa_disable_requires_password_and_one_use_code(self):
        import time
        from cryptography.fernet import Fernet
        from server.services.mfa import totp
        with patch.dict(os.environ,{'APP_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
            secret=self.client.post('/api/auth/security/mfa/setup',json={'password':'fake-test-password'}).json()['secret']
            codes=self.client.post('/api/auth/security/mfa/enable',json={'code':totp(secret,int(time.time())//30)}).json()['recoveryCodes']
            self.assertEqual(self.client.post('/api/auth/security/mfa/disable',json={'password':'incorrect-test-password','code':codes[0]}).status_code,401)
            self.assertEqual(self.client.post('/api/auth/security/mfa/disable',json={'password':'fake-test-password','code':codes[0]}).status_code,200)
            self.assertFalse(self.client.get('/api/auth/security').json()['mfaEnabled'])

    def test_readiness_probes_database_and_hides_sql_failure(self):
        from server.main import ready
        from sqlalchemy.exc import OperationalError
        self.app.get('/api/ready')(ready)
        self.assertEqual(self.client.get('/api/ready').status_code,200)
        with patch.object(self.db,'execute',side_effect=OperationalError('sensitive-sql',{},Exception('private-host'))):
            result=self.client.get('/api/ready')
        self.assertEqual(result.status_code,503);self.assertEqual(result.json(),{'ok':False})


if __name__=='__main__': unittest.main()
