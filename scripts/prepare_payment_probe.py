"""Create one immutable 2,000 VND order in an explicitly marked test workspace only."""
from datetime import timedelta
import json, os
from pathlib import Path
import sys, uuid
from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from server.auth_models import Account, AccountMembership
from server.models import Workspace, User, utcnow
from server.billing_models import PaymentOrder
from server.services.accounts import provision_workspace
from server.services.billing import payment_config
from server.routes.billing import serialize_order


def main():
    load_dotenv(ROOT/'.env')
    config=payment_config()
    if not config.ready:raise SystemExit('SePay configuration is incomplete.')
    engine=create_engine(os.environ['DATABASE_URL'],hide_parameters=True)
    with Session(engine,expire_on_commit=False) as db:
        account=db.scalar(select(Account).where(Account.email=='tuannguyen211982@gmail.com'))
        if not account:raise SystemExit('Authorized administrator not found.')
        name='[QA] SePay 2.000đ'
        workspace=db.scalar(select(Workspace).where(Workspace.name==name).join(AccountMembership,AccountMembership.workspace_id==Workspace.id).where(AccountMembership.account_id==account.id))
        if workspace is None:workspace,user=provision_workspace(db,account,name)
        order=db.scalar(select(PaymentOrder).where(PaymentOrder.workspace_id==workspace.id,PaymentOrder.amount==2000,PaymentOrder.paid_at.is_(None),PaymentOrder.expires_at>utcnow()))
        if order is None:
            order=PaymentOrder(id=uuid.uuid4().hex,workspace_id=workspace.id,transfer_code='ASO'+uuid.uuid4().hex[:20].upper(),amount=2000,bank=config.bank,account_number=config.account,account_name=config.name,created_at=utcnow(),expires_at=utcnow()+timedelta(hours=24))
            db.add(order)
        db.commit()
        output=serialize_order(order)
        output['workspace']=name;output['workspaceId']=workspace.id
        # Bank checkout information only; never include webhook credentials.
        (ROOT/'artifacts/acceptance-payment-probe.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
        print('Prepared 2,000 VND test order in '+name+'; real payment remains pending.')
    engine.dispose()
if __name__=='__main__':main()
