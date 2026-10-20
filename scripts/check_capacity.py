"""Real HTTP/DB/RLS staircase, 20 tenants/100 sessions, separate synthetic AI pressure."""
import asyncio
from collections import Counter
from datetime import timedelta
import json, os
from pathlib import Path
import secrets, socket, statistics, subprocess, sys, time, uuid, tempfile
import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.engine import make_url
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from server.database import Base
from server import billing_models
from server.auth_models import Account, AccountMembership, AuthSession
from server.models import User, Ticket, utcnow
from server.services.accounts import provision_workspace, token_hash


def summary(rows,seconds):
    latencies=sorted(x[1] for x in rows)
    counts=Counter(x[0] for x in rows)
    return {'requests':len(rows),'statusCounts':dict(counts),'throughputRps':round(len(rows)/seconds,2),
        'latencyMs':{'median':round(statistics.median(latencies),2),'p95':round(latencies[max(0,int(len(rows)*.95)-1)],2),'max':round(max(latencies),2)},
        'unexpectedFailures':sum(count for status,count in counts.items() if status!=200)}

async def run_stage(base,users,level,ai=False):
    limits=httpx.Limits(max_connections=level+5,max_keepalive_connections=level+5)
    async with httpx.AsyncClient(base_url=base,limits=limits,timeout=30,headers={'Origin':base}) as client:
        barrier=asyncio.Event()
        async def perform(user):
            await barrier.wait();out=[]
            routes=[f"/api/ai/tickets/{user['ticket']}/suggest"] if ai else ['/api/bootstrap','/api/tickets','/api/knowledge','/api/reports/quality','/api/audit','/api/bootstrap','/api/tickets','/api/billing']
            for route in routes:
                started=time.perf_counter()
                try:
                    response=await (client.post(route,headers={'Cookie':'support_session='+user['token']}) if ai else client.get(route,headers={'Cookie':'support_session='+user['token']}))
                    status=response.status_code
                except httpx.HTTPError:status=0
                out.append((status,(time.perf_counter()-started)*1000))
            return out
        tasks=[asyncio.create_task(perform(user)) for user in users[:level]]
        started=time.perf_counter();barrier.set()
        nested=await asyncio.gather(*tasks)
        report=summary([row for rows in nested for row in rows],time.perf_counter()-started)
        report['concurrentUsers']=level
        if ai:
            report['capacityRejections']=report['statusCounts'].get(429,0)
            report['unexpectedFailures']=sum(v for k,v in report['statusCounts'].items() if k not in (200,429))
        return report


async def run_soak(base, users, level, duration):
    """Repeat real read workflows with six seconds of user think time.

    Keep production account/workspace limits. Only the generator IP limit is
    raised, as in the burst test. This is interactive load, not a tight loop.
    """
    deadline=time.monotonic()+duration
    async with httpx.AsyncClient(base_url=base,timeout=30,
            limits=httpx.Limits(max_connections=level+5,max_keepalive_connections=level+5)) as client:
        async def user_loop(user):
            rows=[]
            while time.monotonic()<deadline:
                for route in ('/api/bootstrap','/api/tickets','/api/knowledge','/api/reports/quality','/api/audit','/api/billing'):
                    started=time.perf_counter()
                    try:
                        response=await client.get(route,headers={'Cookie':'support_session='+user['token']})
                        status=response.status_code
                    except httpx.HTTPError:status=0
                    rows.append((status,(time.perf_counter()-started)*1000))
                if time.monotonic()<deadline:await asyncio.sleep(min(6,max(0,deadline-time.monotonic())))
            return rows
        started=time.perf_counter()
        results=await asyncio.gather(*(user_loop(u) for u in users[:level]))
        report=summary([r for rows in results for r in rows],time.perf_counter()-started)
        report.update(concurrentUsers=level,durationSeconds=round(time.perf_counter()-started,2),thinkTimeSeconds=6)
        return report


def main():
    v=dotenv_values(ROOT/'.env');url=make_url(v.get('DATABASE_MIGRATION_URL') or v['DATABASE_URL'])
    schema='test_capacity_'+uuid.uuid4().hex;role='qa_capacity_'+uuid.uuid4().hex[:12];password=secrets.token_urlsafe(32)
    engine=create_engine(url,execution_options={'schema_translate_map':{None:schema}},hide_parameters=True)
    process=None;log=None;users=[];env_file=None;container_name=None
    try:
        with engine.begin() as db:
            db.execute(CreateSchema(schema))
            db.exec_driver_sql(f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS")
        Base.metadata.create_all(engine)
        from importlib import import_module
        tables=import_module('migrations.versions.0002_tenant_rls').TABLES
        with engine.begin() as db:
            for table in tables:
                db.exec_driver_sql(f'ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY')
                db.exec_driver_sql(f'ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY')
                db.exec_driver_sql(f"CREATE POLICY workspace_isolation ON {schema}.{table} USING (workspace_id=nullif(current_setting('app.workspace_id',true),'')) WITH CHECK(workspace_id=nullif(current_setting('app.workspace_id',true),''))")
            db.exec_driver_sql(f'GRANT USAGE ON SCHEMA {schema} TO {role}')
            db.exec_driver_sql(f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA {schema} TO {role}')
        with Session(engine) as db:
            for tenant in range(20):
                account=Account(id=uuid.uuid4().hex,email=f'qa-admin-{tenant}@example.com',name='QA admin',password_hash='disabled')
                db.add(account);db.flush()
                ws,admin=provision_workspace(db,account,'[QA CAPACITY] '+str(tenant))
                people=[(account,admin)]
                for member in range(1,5):
                    acc=Account(id=uuid.uuid4().hex,email=f'qa-{tenant}-{member}@example.com',name='QA member',password_hash='disabled');db.add(acc);db.flush()
                    person=User(id=uuid.uuid4().hex,workspace_id=ws.id,team_id=admin.team_id,name=acc.name,email=acc.email,role='manager' if member==1 else 'agent');db.add(person);db.flush()
                    db.add(AccountMembership(account_id=acc.id,user_id=person.id,workspace_id=ws.id));people.append((acc,person))
                ticket_ids=[]
                for index in range(10):
                    ticket=Ticket(id=uuid.uuid4().hex,workspace_id=ws.id,team_id=admin.team_id,code=f'QA-{tenant}-{index}',customer_name='Synthetic guest',customer_email='qa@example.com',subject='Capacity fixture',body='Synthetic content',channel='Chat')
                    db.add(ticket);ticket_ids.append(ticket.id)
                for acc,person in people:
                    token=secrets.token_urlsafe(32);db.add(AuthSession(token_hash=token_hash(token),account_id=acc.id,user_id=person.id,expires_at=utcnow()+timedelta(hours=1)))
                    users.append({'token':token,'ticket':ticket_ids[0]})
            db.commit()
        # Interleave tenants to avoid measuring only one workspace's limits at low levels.
        users=[users[t*5+m] for m in range(5) for t in range(20)]
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'SUPPORT_QA_SCHEMA':schema,'CAPACITY_DATABASE_URL':url.set(username=role,password=password).render_as_string(hide_password=False),
             'API_IP_PER_MINUTE':'100000','APP_ENV':'test',
             'SMTP_HOST':'','SMTP_USERNAME':'','SMTP_PASSWORD':'','SMTP_FROM_EMAIL':''}
        log_name='acceptance-zap-active-server.log' if '--zap-active' in sys.argv else 'acceptance-soak-server.log' if '--soak' in sys.argv else 'acceptance-capacity-server.log'
        log=open(ROOT/'artifacts'/log_name,'w')
        if '--docker' in sys.argv:
            image=subprocess.check_output(['docker','compose','images','-q','app'],cwd=ROOT,text=True).strip()
            if not image:raise RuntimeError('Build app image before container capacity measurement')
            container_name='support-qa-capacity-'+uuid.uuid4().hex[:12]
            descriptor,env_file=tempfile.mkstemp(prefix='support-capacity-',suffix='.env')
            docker_env={key:env[key] for key in ('SUPPORT_QA_SCHEMA','CAPACITY_DATABASE_URL','API_IP_PER_MINUTE','APP_ENV','SMTP_HOST','SMTP_USERNAME','SMTP_PASSWORD','SMTP_FROM_EMAIL')}
            docker_env['CAPACITY_DATABASE_URL']=url.set(host='host.docker.internal',username=role,password=password).render_as_string(hide_password=False)
            with os.fdopen(descriptor,'w') as handle:
                for key,value in docker_env.items():handle.write(key+'='+value+'\n')
            command=['docker','run','--rm','--init','--name',container_name,'--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
                '--cpus','2','--memory','1g','--pids-limit','128','--tmpfs','/tmp:size=128m,mode=1777','--env-file',env_file,
                '-v',str(ROOT/'tests')+':/app/tests:ro','-p',f'127.0.0.1:{port}:8000',image,
                'uvicorn','capacity_fixture_app:create_app','--factory','--app-dir','tests','--host','0.0.0.0','--port','8000',
                '--workers','1','--limit-concurrency','64','--timeout-keep-alive','5','--backlog','128','--no-access-log']
        else:
            command=[sys.executable,'-m','uvicorn','capacity_fixture_app:create_app','--factory','--app-dir','tests','--host','127.0.0.1','--port',str(port),'--workers','2','--no-access-log']
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=log)
        for _ in range(100):
            try:
                if httpx.get(base+'/_qa/worker',timeout=1).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        else:raise RuntimeError('Capacity fixture failed to start')
        if '--soak' in sys.argv:
            duration=int(sys.argv[sys.argv.index('--soak')+1])
            if not 60<=duration<=3600:raise ValueError('Soak stage must last 60–3600 seconds')
            levels=[int(x) for x in sys.argv[sys.argv.index('--levels')+1].split(',')] if '--levels' in sys.argv else [10,25,50,100]
            if not levels or any(level<1 or level>100 for level in levels):raise ValueError('Levels must be within the 100-user fixture')
            report={'tenantFixtures':20,'sessionFixtures':100,'workers':1 if '--docker' in sys.argv else 2,'externalAI':False,'stageSeconds':duration,'http':[],'containerLimits':{'cpus':2,'memoryGiB':1,'uvicornConcurrency':64} if '--docker' in sys.argv else None}
            output=ROOT/'artifacts'/('acceptance-soak-docker.json' if '--docker' in sys.argv else 'acceptance-soak-extended.json' if '--levels' in sys.argv else 'acceptance-soak.json')
            for level in levels:
                result=asyncio.run(run_soak(base,users,level,duration));report['http'].append(result)
                print('SOAK',level,json.dumps(result),flush=True)
                output.write_text(json.dumps(report,indent=2))
            report['slo']={'p95Ms':1000,'unexpectedFailures':0}
            passing=[x['concurrentUsers'] for x in report['http'] if x['unexpectedFailures']==0 and x['latencyMs']['p95']<1000]
            report['highestMeasuredConcurrencyWithinSlo']=max(passing,default=0)
            report['absoluteMaximumDetermined']=False
            output.write_text(json.dumps(report,indent=2))
            return 0
        if '--zap-only' in sys.argv or '--zap-active' in sys.argv:
            active='--zap-active' in sys.argv
            output=ROOT/('artifacts/zap-active' if active else 'artifacts/zap')
            output.mkdir(exist_ok=True)
            command=['docker','run','--rm','-v',str(output)+':/zap/wrk:rw']
            scan_env=dict(os.environ)
            if active:
                # Ephemeral fixture credential exists only in process environment.
                command+=['-e','ZAP_AUTH_HEADER','-e','ZAP_AUTH_HEADER_VALUE']
                scan_env.update(ZAP_AUTH_HEADER='Cookie',ZAP_AUTH_HEADER_VALUE='support_session='+users[0]['token'])
            command += [
                'ghcr.io/zaproxy/zaproxy:stable','zap-api-scan.py','-t',f'http://host.docker.internal:{port}/openapi.json',
                '-f','openapi','-T','3','-J','report.json','-r','report.html','-I','-s']
            if not active:command+=['-S']
            try:
                result=subprocess.run(command,cwd=ROOT,env=scan_env,timeout=900 if active else 300)
            finally:
                # ZAP reports may quote injected headers. Persist no session tokens.
                for path in output.glob('*'):
                    if path.is_file() and path.suffix in ('.json','.html','.md','.txt'):
                        value=path.read_text(errors='replace')
                        for user in users:value=value.replace(user['token'],'[REDACTED_QA_SESSION]')
                        path.write_text(value)
            print('OWASP ZAP '+('authenticated active' if active else 'unauthenticated passive')+' API scan exit:',result.returncode)
            return result.returncode
        report={'tenantFixtures':20,'sessionFixtures':100,'ticketsPerTenant':10,'workers':2,'externalAI':False,
                'syntheticModelLatencySeconds':1,'ipLimitRaisedForSharedLoadGenerator':True,'http':[],'ai':[]}
        for level in (10,25,50,100):
            result=asyncio.run(run_stage(base,users,level));report['http'].append(result);print('HTTP',level,json.dumps(result),flush=True)
        for level in (10,25,50,100):
            result=asyncio.run(run_stage(base,users,level,True));report['ai'].append(result);print('AI synthetic',level,json.dumps(result),flush=True)
        report['slo']={'p95Ms':1000,'unexpectedFailures':0}
        passing=[x['concurrentUsers'] for x in report['http'] if x['unexpectedFailures']==0 and x['latencyMs']['p95']<1000]
        report['highestMeasuredHttpConcurrencyWithinSlo']=max(passing) if passing else 0
        report['absoluteMaximumDetermined']=False
        (ROOT/'artifacts/acceptance-capacity.json').write_text(json.dumps(report,indent=2))
        return 0
    finally:
        if container_name:subprocess.run(['docker','stop','--time','5',container_name],capture_output=True,timeout=15)
        if process:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        if log:log.close()
        if env_file:Path(env_file).unlink(missing_ok=True)
        with engine.begin() as db:
            db.execute(DropSchema(schema,cascade=True));db.exec_driver_sql(f'DROP ROLE IF EXISTS {role}')
        engine.dispose()
if __name__=='__main__':raise SystemExit(main())
