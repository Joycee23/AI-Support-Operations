"""External-to-app health checks and deduplicated SMTP alerts/recovery notices."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, formataddr
import fcntl
import json
import os
from pathlib import Path
import shutil
import smtplib
import ssl
import certifi
import subprocess
import sys
import httpx
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from server.services.invitation_email import MailConfig


def send_alert(recipient, problems, recovered=False, test=False):
    config=MailConfig.from_env()
    if config.security not in ('ssl','starttls') or not all((config.host,config.username,config.password,config.sender)):
        raise RuntimeError('SMTP TLS required')
    msg=EmailMessage()
    msg['From']=formataddr((config.sender_name,config.sender));msg['To']=recipient
    msg['Date']=formatdate(usegmt=True);msg['Message-ID']=make_msgid(domain=config.sender.rsplit('@',1)[-1])
    msg['Subject']=('[KIỂM THỬ] ' if test else '')+('Đã phục hồi' if recovered else 'Cảnh báo vận hành')+' · AI Support Operations'
    msg.set_content(('Kiểm tra lúc '+datetime.now(timezone.utc).isoformat())+'\n\n'+'\n'.join(problems)+'\n\nKhông có khóa, mật khẩu hoặc dữ liệu khách hàng trong thông báo này.')
    ctx=ssl.create_default_context(cafile=certifi.where())
    client=smtplib.SMTP_SSL(config.host,config.port,timeout=15,context=ctx) if config.security=='ssl' else smtplib.SMTP(config.host,config.port,timeout=15)
    try:
        if config.security=='starttls':client.ehlo();client.starttls(context=ctx);client.ehlo()
        client.login(config.username,config.password)
        if client.send_message(msg,from_addr=config.sender,to_addrs=[recipient]):raise RuntimeError('Recipient refused')
    finally:client.close()


def inspect_health():
    now=datetime.now(timezone.utc);problems=[]
    url=os.getenv('MONITOR_APP_URL','http://localhost:8000').rstrip('/')
    try:
        response=httpx.get(url+'/api/ready',timeout=10,follow_redirects=False)
        if response.status_code!=200 or response.json().get('ok') is not True:problems.append('Ứng dụng chưa sẵn sàng hoặc không kết nối được database.')
    except Exception:problems.append('Không kết nối được ứng dụng trong 10 giây.')
    engine=create_engine(os.environ['DATABASE_URL'],hide_parameters=True,connect_args={'connect_timeout':5,'options':'-c statement_timeout=5000'})
    try:
        with engine.connect() as db:
            db.execute(text('SELECT 1'))
            for row in db.execute(text('SELECT name,consecutive_failures,last_failure FROM operational_signals')):
                if row.consecutive_failures>=int(os.getenv('MONITOR_AI_FAILURES','3')) and row.last_failure:
                    problems.append(f'Dịch vụ {row.name} lỗi liên tiếp {row.consecutive_failures} lần và chưa có lần thành công tiếp theo.')
    except Exception:problems.append('Không kết nối được database hoặc bảng giám sát chưa migration.')
    finally:engine.dispose()
    disk=shutil.disk_usage(ROOT)
    if disk.free < int(os.getenv('MONITOR_MIN_FREE_BYTES',str(2*1024**3))) or disk.used/disk.total > .90:
        problems.append('Dung lượng ổ đĩa máy chủ dưới ngưỡng an toàn (2 GiB hoặc còn dưới 10%).')
    try:
        result=subprocess.run(['docker','compose','exec','-T','app','python','-c',
            "import shutil,json; d=shutil.disk_usage('/app/data'); print(json.dumps([d.free,d.total]))"],cwd=ROOT,capture_output=True,text=True,timeout=15,check=True)
        free,total=json.loads(result.stdout)
        if free<int(os.getenv('MONITOR_MIN_FREE_BYTES',str(2*1024**3))) or free/total<.1:problems.append('Volume tài liệu Docker sắp hết dung lượng.')
    except Exception:problems.append('Không kiểm tra được volume tài liệu hoặc container app đã dừng.')
    try:
        state=json.loads((ROOT/'backups/status.json').read_text())
        if not state.get('offsiteVerified'):problems.append('Bản sao lưu gần nhất chưa được xác minh ngoài máy.')
        if now-datetime.fromisoformat(state['createdAt'])>timedelta(hours=26):problems.append('Bản sao lưu đã quá 26 giờ.')
    except Exception:problems.append('Chưa có trạng thái sao lưu hợp lệ.')
    return problems


def main():
    load_dotenv(ROOT/'.env');os.umask(0o077)
    folder=ROOT/'data/monitor';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (folder/'.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 0
        test='--test-alert' in sys.argv
        problems=['Đây là cảnh báo kiểm thử được bạn cho phép gửi.'] if test else inspect_health()
        path=folder/'state.json'
        try:state=json.loads(path.read_text())
        except (OSError,ValueError):state={}
        now=datetime.now(timezone.utc)
        failures=state.get('failures',0)+1 if problems else 0
        previous=state.get('notifiedProblems',[])
        last=datetime.fromisoformat(state.get('lastAlert','1970-01-01T00:00:00+00:00'))
        alert=test or failures>=2 and (problems!=previous or now-last>timedelta(hours=1))
        recovery=not problems and bool(previous)
        recipient=os.getenv('MONITOR_ALERT_EMAIL','').strip()
        if (alert or recovery) and recipient:
            send_alert(recipient,problems or ['Các kiểm tra đã trở lại bình thường.'],recovered=recovery,test=test)
            if not test:state.update(lastAlert=now.isoformat(),notifiedProblems=problems)
            print('Alert SMTP accepted; Inbox placement requires recipient confirmation.')
        elif alert and not recipient:print('Alert pending: set MONITOR_ALERT_EMAIL.')
        if not test:
            state.update(checkedAt=now.isoformat(),failures=failures,problems=problems)
            tmp=folder/'state.tmp';tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2));tmp.replace(path)
        print('Checks: '+str(len(problems))+' issue(s).')
        return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('Monitor failed ('+type(exc).__name__+'); no secrets printed.',file=sys.stderr)
        raise SystemExit(1) from None
