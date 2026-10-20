"""Scheduled encrypted backup with verified S3/R2 upload and bounded retention."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent.parent


def retained_keys(objects, now, daily=7, weekly=4, monthly=12):
    """Retain newest object per UTC day/week/month, separately for database/files."""
    keep = set()
    for kind in ('database-', 'files-', 'application-'):
        rows = sorted((x for x in objects if Path(x['Key']).name.startswith(kind) and x['Key'].endswith('.age')),
                      key=lambda x: x['LastModified'], reverse=True)
        for period, count in [('day', daily), ('week', weekly), ('month', monthly)]:
            buckets = set()
            for row in rows:
                stamp = row['LastModified'].astimezone(timezone.utc)
                group = stamp.strftime('%Y-%m-%d') if period == 'day' else stamp.strftime('%G-%V') if period == 'week' else stamp.strftime('%Y-%m')
                if group not in buckets and len(buckets) < count:
                    buckets.add(group); keep.add(row['Key'])
    return keep


def main():
    load_dotenv(ROOT / '.env')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only', action='store_true', help='Explicitly skip offsite upload; not a complete backup policy')
    args=parser.parse_args()
    os.umask(0o077)
    folder=ROOT/'backups'; folder.mkdir(mode=0o700,exist_ok=True)
    with (folder/'.cycle.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return
        paths=[]
        for kind in ('database','files','application'):
            result=subprocess.run([sys.executable,str(ROOT/'scripts/backup_secure.py'),'--kind',kind],cwd=ROOT,
                                  capture_output=True,text=True,timeout=360,check=True)
            paths.append(Path(result.stdout.strip()))
        state={'createdAt':datetime.now(timezone.utc).isoformat(),'localComplete':True,'offsiteVerified':False}
        try:
            if not args.local_only:
                import boto3
                from botocore.config import Config
                keys=['BACKUP_S3_ENDPOINT','BACKUP_S3_BUCKET','BACKUP_S3_ACCESS_KEY_ID','BACKUP_S3_SECRET_ACCESS_KEY']
                if not all(os.getenv(k) for k in keys):
                    raise RuntimeError('Configure private R2/S3 bucket credentials in .env; local encrypted backups have been retained.')
                client=boto3.client('s3',endpoint_url=os.environ['BACKUP_S3_ENDPOINT'],
                    aws_access_key_id=os.environ['BACKUP_S3_ACCESS_KEY_ID'],aws_secret_access_key=os.environ['BACKUP_S3_SECRET_ACCESS_KEY'],
                    region_name=os.getenv('BACKUP_S3_REGION','auto'),config=Config(retries={'max_attempts':3},connect_timeout=10,read_timeout=60))
                bucket=os.environ['BACKUP_S3_BUCKET']; prefix=os.getenv('BACKUP_S3_PREFIX','support-ops/').strip('/')+'/'
                if prefix=='/' or '..' in prefix.split('/'):
                    raise RuntimeError('A dedicated nonempty backup prefix is required')
                for path in paths:
                    with path.open('rb') as handle:
                        digest=hashlib.file_digest(handle,'sha256').hexdigest()
                    key=prefix+path.name
                    client.upload_file(str(path),bucket,key,ExtraArgs={'Metadata':{'sha256':digest}})
                    head=client.head_object(Bucket=bucket,Key=key)
                    if head['ContentLength']!=path.stat().st_size or head.get('Metadata',{}).get('sha256')!=digest:
                        raise RuntimeError('Remote size/metadata verification failed')
                    # Read back ciphertext to verify actual bytes, not only metadata.
                    stream=client.get_object(Bucket=bucket,Key=key)['Body']
                    check=hashlib.sha256()
                    try:
                        for chunk in stream.iter_chunks(1024*1024):check.update(chunk)
                    finally:stream.close()
                    if check.hexdigest()!=digest:raise RuntimeError('Remote ciphertext hash mismatch')
                state['offsiteVerified']=True
                objects=[]
                for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket,Prefix=prefix):
                    objects.extend(page.get('Contents',[]))
                keep=retained_keys(objects,datetime.now(timezone.utc))
                for row in objects:
                    name=Path(row['Key']).name
                    # Never prune unrelated objects, recent uploads, or before both backups verify.
                    if name.startswith(('database-','files-','application-')) and name.endswith('.age') and row['Key'] not in keep and row['LastModified'] < datetime.now(timezone.utc)-timedelta(days=7):
                        client.delete_object(Bucket=bucket,Key=row['Key'])
                for kind in ('database','files','application'):
                    for old in sorted(folder.glob(kind+'-*.age'),reverse=True)[7:]:old.unlink()
            print('Backup complete: '+('local only' if args.local_only else 'offsite ciphertext verified'))
        finally:
            tmp=folder/'status.tmp';tmp.write_text(json.dumps(state));tmp.replace(folder/'status.json')
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('Backup cycle failed ('+type(exc).__name__+'); see configuration and backup status; no secrets printed.',file=sys.stderr)
        raise SystemExit(1) from None
