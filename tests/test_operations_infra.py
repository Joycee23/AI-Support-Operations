"""Deterministic operations regression tests; no SMTP or cloud side effects."""
from datetime import datetime,timedelta,timezone
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch,MagicMock
ROOT=Path(__file__).resolve().parent.parent


def script(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class BackupRetentionTests(unittest.TestCase):
    def setUp(self):self.module=script('backup_cycle')
    def test_retention_preserves_daily_weekly_monthly_for_both_kinds(self):
        now=datetime(2026,10,20,tzinfo=timezone.utc)
        rows=[]
        for kind in ('database','files','application'):
            for day in range(400):
                date=now-timedelta(days=day)
                rows.append({'Key':f'ops/{kind}-{date:%Y%m%dT%H%M%SZ}.age','LastModified':date})
        keep=self.module.retained_keys(rows,now)
        for kind in ('database','files','application'):
            selected=[r for r in rows if r['Key'] in keep and r['Key'].startswith('ops/'+kind)]
            self.assertLessEqual(len(selected),23)
            for day in range(7):self.assertIn(f'ops/{kind}-{now-timedelta(days=day):%Y%m%dT%H%M%SZ}.age',keep)
            self.assertGreaterEqual(len({r['LastModified'].strftime('%Y-%m') for r in selected}),12)
    def test_latest_in_same_day_wins(self):
        now=datetime.now(timezone.utc)
        rows=[{'Key':'ops/database-a.age','LastModified':now},{'Key':'ops/database-b.age','LastModified':now-timedelta(seconds=1)}]
        self.assertEqual(self.module.retained_keys(rows,now),{'ops/database-a.age'})
    def test_unrelated_objects_never_selected(self):
        now=datetime.now(timezone.utc)
        self.assertEqual(self.module.retained_keys([{'Key':'ops/readme.txt','LastModified':now}],now),set())
    def test_empty_bucket(self):self.assertEqual(self.module.retained_keys([],datetime.now(timezone.utc)),set())


class MonitoringTests(unittest.TestCase):
    def setUp(self):self.module=script('monitor')
    @patch.dict('os.environ',{'SMTP_HOST':'smtp.example.com','SMTP_SECURITY':'plain','SMTP_USERNAME':'x','SMTP_PASSWORD':'x','SMTP_FROM_EMAIL':'x@example.com'})
    def test_alert_rejects_unencrypted_smtp(self):
        with self.assertRaises(RuntimeError):self.module.send_alert('qa@example.com',['Synthetic issue'])
    @patch.dict('os.environ',{'SMTP_HOST':'smtp.example.com','SMTP_SECURITY':'starttls','SMTP_USERNAME':'x','SMTP_PASSWORD':'x','SMTP_FROM_EMAIL':'x@example.com'})
    def test_alert_starttls_and_headers(self):
        with patch.object(self.module.smtplib,'SMTP') as smtp:
            client=smtp.return_value;client.send_message.return_value={}
            self.module.send_alert('qa@example.com',['Synthetic issue'],test=True)
            client.starttls.assert_called_once();client.login.assert_called_once()
            msg=client.send_message.call_args.args[0]
            self.assertIn('KIỂM THỬ',msg['Subject']);self.assertTrue(msg['Date']);self.assertTrue(msg['Message-ID'])
            self.assertIn('Synthetic issue',msg.get_content());client.close.assert_called_once()
    @patch.dict('os.environ',{'SMTP_HOST':'smtp.example.com','SMTP_SECURITY':'starttls','SMTP_USERNAME':'x','SMTP_PASSWORD':'x','SMTP_FROM_EMAIL':'x@example.com'})
    def test_refused_alert_not_success(self):
        with patch.object(self.module.smtplib,'SMTP') as smtp:
            smtp.return_value.send_message.return_value={'qa@example.com':(550,b'No')}
            with self.assertRaises(RuntimeError):self.module.send_alert('qa@example.com',['Synthetic issue'])



class MonitorFailureScenarios(unittest.TestCase):
    def setUp(self):
        import tempfile
        from types import SimpleNamespace
        self.module=script('monitor')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'backups').mkdir()
        (self.root/'backups/status.json').write_text(__import__('json').dumps({'createdAt':datetime.now(timezone.utc).isoformat(),'offsiteVerified':True}))
        self.addCleanup(patch.stopall)
        patch.object(self.module,'ROOT',self.root).start()
        patch.dict('os.environ',{'DATABASE_URL':'postgresql+psycopg://test@localhost/test','MONITOR_ALERT_EMAIL':'qa@example.com','MONITOR_MIN_FREE_BYTES':'100'}).start()
        patch.object(self.module,'load_dotenv').start()
        self.http=patch.object(self.module.httpx,'get').start();self.http.return_value.status_code=200;self.http.return_value.json.return_value={'ok':True}
        self.engine=patch.object(self.module,'create_engine').start().return_value
        self.db=self.engine.connect.return_value.__enter__.return_value
        self.db.execute.side_effect=[MagicMock(),[]]
        patch.object(self.module.shutil,'disk_usage',return_value=SimpleNamespace(free=1000,used=100,total=1100)).start()
        self.docker=patch.object(self.module.subprocess,'run',return_value=SimpleNamespace(stdout='[1000,1100]')).start()

    def test_healthy_all_checks(self):self.assertEqual(self.module.inspect_health(),[])

    def test_http_failure_detected(self):
        self.http.side_effect=TimeoutError()
        self.assertTrue(any('ứng dụng' in x for x in self.module.inspect_health()))

    def test_database_failure_detected(self):
        self.engine.connect.side_effect=ConnectionError()
        self.assertTrue(any('database' in x for x in self.module.inspect_health()))

    def test_host_disk_full_detected(self):
        from types import SimpleNamespace
        self.module.shutil.disk_usage.return_value=SimpleNamespace(free=10,used=1000,total=1010)
        self.assertTrue(any('ổ đĩa' in x for x in self.module.inspect_health()))

    def test_docker_volume_full_detected(self):
        self.docker.return_value.stdout='[10,1000]'
        self.assertTrue(any('Volume' in x for x in self.module.inspect_health()))

    def test_prolonged_ai_failure_does_not_falsely_recover_with_age(self):
        from types import SimpleNamespace
        self.db.execute.side_effect=[MagicMock(),[SimpleNamespace(name='ai',consecutive_failures=4,last_failure=datetime.now(timezone.utc)-timedelta(days=2))]]
        self.assertTrue(any('ai lỗi liên tiếp' in x for x in self.module.inspect_health()))

    def test_email_outage_detected(self):
        from types import SimpleNamespace
        self.db.execute.side_effect=[MagicMock(),[SimpleNamespace(name='email',consecutive_failures=3,last_failure=datetime.now(timezone.utc))]]
        self.assertTrue(any('email lỗi liên tiếp' in x for x in self.module.inspect_health()))

    def test_stale_or_unverified_backup_detected(self):
        import json
        (self.root/'backups/status.json').write_text(json.dumps({'createdAt':(datetime.now(timezone.utc)-timedelta(hours=27)).isoformat(),'offsiteVerified':False}))
        problems=self.module.inspect_health()
        self.assertTrue(any('26 giờ' in x for x in problems));self.assertTrue(any('ngoài máy' in x for x in problems))

    def test_alert_after_two_checks_deduplicates_and_recovers(self):
        with patch.object(self.module,'inspect_health',side_effect=[['Synthetic DB outage']]*3+[[],[]]),patch.object(self.module,'send_alert') as send,patch.object(self.module.sys,'argv',['monitor.py']):
            self.module.main();send.assert_not_called()
            self.module.main();self.assertEqual(send.call_count,1)
            self.module.main();self.assertEqual(send.call_count,1)
            self.module.main();self.assertEqual(send.call_count,2);self.assertTrue(send.call_args.kwargs['recovered'])
            self.module.main();self.assertEqual(send.call_count,2)

    def test_failed_smtp_is_retried_not_acknowledged(self):
        with patch.object(self.module,'inspect_health',return_value=['Synthetic outage']),patch.object(self.module,'send_alert',side_effect=[RuntimeError('SMTP down'),None]) as send,patch.object(self.module.sys,'argv',['monitor.py']):
            self.module.main()
            with self.assertRaises(RuntimeError):self.module.main()
            self.module.main();self.assertEqual(send.call_count,2)

    def test_hourly_repeat_and_changed_problem_alert(self):
        import json
        folder=self.root/'data/monitor';folder.mkdir(parents=True)
        (folder/'state.json').write_text(json.dumps({'failures':2,'notifiedProblems':['Synthetic outage'],'lastAlert':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()}))
        with patch.object(self.module,'inspect_health',side_effect=[['Synthetic outage'],['Synthetic disk outage']]),patch.object(self.module,'send_alert') as send,patch.object(self.module.sys,'argv',['monitor.py']):
            self.module.main();self.module.main();self.assertEqual(send.call_count,2)


if __name__=='__main__':unittest.main()
