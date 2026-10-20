"""Install this user's macOS LaunchAgents; Linux example units are in deploy/."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
ROOT=Path(__file__).resolve().parent.parent


def main():
    if sys.platform!='darwin':raise SystemExit('Use deploy/systemd units on Linux.')
    python=ROOT/'.venv/bin/python'
    directory=Path.home()/'Library/LaunchAgents';directory.mkdir(parents=True,exist_ok=True)
    logs=ROOT/'data/ops-logs';logs.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,script,schedule in [('backup','backup_cycle.py',{'StartCalendarInterval':{'Hour':2,'Minute':0}}),
                                 ('monitor','monitor.py',{'StartInterval':300,'RunAtLoad':True})]:
        label='vn.supportoperations.'+name
        destination=directory/(label+'.plist')
        entry={'Label':label,'ProgramArguments':[str(python),str(ROOT/'scripts'/script)],'WorkingDirectory':str(ROOT),
               'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Applications/Docker.app/Contents/Resources/bin'},
               'StandardOutPath':str(logs/(name+'.log')),'StandardErrorPath':str(logs/(name+'.error.log')),**schedule}
        destination.write_bytes(plistlib.dumps(entry));destination.chmod(0o600)
        domain='gui/'+str(os.getuid())
        subprocess.run(['launchctl','bootout',domain,str(destination)],capture_output=True)
        subprocess.run(['launchctl','bootstrap',domain,str(destination)],check=True)
        print('Installed '+label)
    print('Backup daily at 02:00 local time; monitor every 5 minutes while this user session is active. Mac must be awake and Docker running.')

if __name__=='__main__':main()
