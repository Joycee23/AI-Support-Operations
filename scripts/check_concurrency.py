"""Bounded load/concurrency test in a disposable PG schema, no external AI/mail/payment."""
import concurrent.futures
import json
import os
from pathlib import Path
import secrets
import socket
import statistics
import subprocess
import sys
import time
import uuid
from datetime import timedelta
import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema,DropSchema

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from server.database import Base
from server.auth_models import Account,AccountMembership,AuthSession
from server.models import AIAnalysis,Ticket,TicketMessage,utcnow
from server.services.accounts import hash_password,provision_workspace,token_hash
from server.billing_models import Subscription


def main():
    url=os.getenv('TEST_DATABASE_URL') or (dotenv_values(ROOT/'.env').get('DATABASE_MIGRATION_URL') or dotenv_values(ROOT/'.env')['DATABASE_URL'])
    schema='test_concurrency_'+uuid.uuid4().hex
    engine=create_engine(url,execution_options={'schema_translate_map':{None:schema}})
    process=None
    log=None
    try:
        with engine.begin() as connection: connection.execute(CreateSchema(schema))
        Base.metadata.create_all(engine)
        token=secrets.token_urlsafe(32)
        with Session(engine) as db:
            account=Account(id=uuid.uuid4().hex,email='concurrency@example.com',name='QA concurrency',password_hash=hash_password(secrets.token_urlsafe(24)))
            db.add(account);db.flush()
            ws,user=provision_workspace(db,account,'Disposable concurrency fixture')
            db.add(AuthSession(token_hash=token_hash(token),account_id=account.id,user_id=user.id,expires_at=utcnow()+timedelta(hours=1)))
            ticket=Ticket(id=uuid.uuid4().hex,code='QA-CONCURRENCY',workspace_id=ws.id,team_id=user.team_id,customer_name='QA Guest',customer_email='guest@example.com',subject='Synthetic load test',body='Synthetic lodging data only.',status='Mới',priority='Bình thường',topic='QA',channel='Chat')
            db.add(ticket);db.flush()
            analysis=AIAnalysis(id=uuid.uuid4().hex,workspace_id=ws.id,ticket_id=ticket.id,requested_by=user.id,topic='QA',priority='Cao',reason='Synthetic fixture',draft='Synthetic concurrent reply.',grounded=True,citations='[]')
            db.add(analysis);db.commit()
            analysis_id,ticket_id=analysis.id,ticket.id
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'TEST_DATABASE_URL':url,'SUPPORT_QA_SCHEMA':schema}
        log=open(ROOT/'artifacts/retest-multiworker-server.log','w')
        process=subprocess.Popen([sys.executable,'-m','uvicorn','load_fixture_app:create_app','--factory','--app-dir','tests','--host','127.0.0.1','--port',str(port),'--workers','2','--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=log)
        for _ in range(100):
            try:
                if httpx.get(base+'/_qa/worker',timeout=1).status_code==200:break
            except httpx.HTTPError: pass
            time.sleep(.1)
        else: raise RuntimeError('QA workers did not start; see sanitized server log')
        headers={'Origin':base,'Cookie':'support_session='+token}
        routes=['/api/bootstrap','/api/tickets','/api/reports/quality','/api/knowledge','/api/audit']
        def read(index):
            started=time.monotonic()
            with httpx.Client(base_url=base,headers=headers,timeout=20) as client:
                worker=client.get('/_qa/worker').json()['pid']
                response=client.get(routes[index%len(routes)])
            return response.status_code,(time.monotonic()-started)*1000,worker
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(read,range(160)))
        def accept(index):
            return httpx.post(base+'/api/ai/analyses/'+analysis_id+'/feedback',headers=headers,json={'decision':'accepted','save_reply':True},timeout=20).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            accepted=list(pool.map(accept,range(20)))
        # Wrong passwords must count across both workers, even on rollback.
        def wrong_login(index):
            return httpx.post(base+'/api/auth/login',json={'email':'nobody@example.com','password':'synthetic-wrong-password'},headers={'Origin':base},timeout=20).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            attempts=list(pool.map(wrong_login,range(24)))
        with Session(engine) as db:
            replies=db.scalar(select(func.count(TicketMessage.id)).where(TicketMessage.ticket_id==ticket_id))
        elapsed=sorted(item[1] for item in results)
        report={'workersObserved':len({r[2] for r in results}),'concurrency':8,'readRequests':len(results),'readFailures':sum(r[0]!=200 for r in results),'latencyMs':{'median':round(statistics.median(elapsed),1),'p95':round(elapsed[int(len(elapsed)*.95)-1],1),'max':round(max(elapsed),1)},'concurrentAcceptRequests':len(accepted),'acceptFailures':sum(code!=200 for code in accepted),'savedReplies':replies,'wrongLoginStatusCounts':{str(code):attempts.count(code) for code in set(attempts)},'externalProvidersCalled':False}
        report['passed']=report['workersObserved']==2 and report['readFailures']==0 and report['acceptFailures']==0 and replies==1 and attempts.count(401)==10 and attempts.count(429)==14
        (ROOT/'artifacts/retest-concurrency.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        return 0 if report['passed'] else 1
    finally:
        if process:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        if log:log.close()
        with engine.begin() as connection:connection.execute(DropSchema(schema,cascade=True))
        engine.dispose()

if __name__=='__main__':raise SystemExit(main())
