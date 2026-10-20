"""SMTP invitation delivery. Never log credentials, tokens or message bodies."""
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, formatdate
from html import escape
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    message: str


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    security: str
    username: str
    password: str
    sender: str
    sender_name: str
    public_url: str

    @classmethod
    def from_env(cls):
        return cls(host=os.getenv('SMTP_HOST', '').strip(), port=int(os.getenv('SMTP_PORT', '587')),
                   security=os.getenv('SMTP_SECURITY', 'starttls').strip().lower(),
                   username=os.getenv('SMTP_USERNAME', '').strip(), password=os.getenv('SMTP_PASSWORD', ''),
                   sender=os.getenv('SMTP_FROM_EMAIL', '').strip(),
                   sender_name=os.getenv('SMTP_FROM_NAME', 'AI Support Operations').strip(),
                   public_url=os.getenv('APP_PUBLIC_URL', '').strip().rstrip('/'))

    def invitation_url(self, token: str) -> str | None:
        parsed = urlsplit(self.public_url)
        # Use an explicit trusted base URL, never an incoming Host/Origin header.
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            return None
        return self.public_url + '/#invite=' + quote(token, safe='')


def invitation_url(token: str) -> str | None:
    try:
        return MailConfig.from_env().invitation_url(token)
    except ValueError:
        return None


def _send_account_link(*, recipient: str, token: str, purpose: str) -> DeliveryResult:
    try:
        config = MailConfig.from_env()
        base = config.invitation_url(token)
        if not base or not all((config.host, config.sender, config.username, config.password)) or not config.public_url.startswith('https://') or config.security not in ('ssl', 'starttls'):
            return DeliveryResult('not_configured', 'Email bảo mật chưa được cấu hình.')
        url = base.replace('#invite=', '#verify=' if purpose == 'verify' else '#reset=')
        label = 'Xác minh email' if purpose == 'verify' else 'Đặt lại mật khẩu'
        msg = EmailMessage()
        msg['Subject'] = label + ' · AI Support Operations'
        msg['From'] = formataddr((config.sender_name, config.sender))
        msg['To'] = recipient
        msg['Message-ID'] = make_msgid(domain=config.sender.rsplit('@', 1)[-1])
        msg['Date'] = formatdate(localtime=False, usegmt=True)
        msg['Auto-Submitted'] = 'auto-generated'
        msg['X-Auto-Response-Suppress'] = 'All'
        msg.set_content(f'{label} bằng link sau:\n{url}\n\nLink có hiệu lực 30 phút và chỉ dùng một lần. Nếu không yêu cầu thao tác này, hãy bỏ qua email. Không chia sẻ link với người khác.')
        context = ssl.create_default_context()
        client = smtplib.SMTP_SSL(config.host, config.port, timeout=10, context=context) if config.security == 'ssl' else smtplib.SMTP(config.host, config.port, timeout=10)
        try:
            if config.security == 'starttls':
                client.ehlo(); client.starttls(context=context); client.ehlo()
            client.login(config.username, config.password)
            refused = client.send_message(msg, from_addr=config.sender, to_addrs=[recipient])
        finally:
            client.close()
        if refused:
            return DeliveryResult('failed', 'Máy chủ email từ chối người nhận.')
        return DeliveryResult('sent', 'Máy chủ email đã tiếp nhận thư bảo mật.')
    except (OSError, smtplib.SMTPException, ValueError, UnicodeError):
        return DeliveryResult('failed', 'Chưa xác nhận được việc gửi thư bảo mật.')


def send_invitation(*, recipient: str, token: str, workspace: str, inviter: str,
                    team: str, role: str, expires_at: datetime) -> DeliveryResult:
    try:
        config = MailConfig.from_env()
        url = config.invitation_url(token)
        if not all((config.host, config.sender, config.username, config.password, url)):
            return DeliveryResult('not_configured', 'Chưa cấu hình email gửi hoặc địa chỉ ứng dụng. Bạn vẫn có thể sao chép link bên dưới.')
        parsed = urlsplit(config.public_url)
        if (parsed.scheme != 'https' or parsed.hostname in ('localhost', '127.0.0.1', '::1')
                or config.security not in ('starttls', 'ssl') or not 1 <= config.port <= 65535):
            return DeliveryResult('not_configured', 'Email cần địa chỉ ứng dụng HTTPS công khai và SMTP có TLS. Link lời mời vẫn dùng được để chia sẻ thủ công.')
        expiry = expires_at.astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%H:%M %d/%m/%Y')
        role_name = 'Quản lý nhóm' if role == 'manager' else 'Nhân viên hỗ trợ'
        msg = EmailMessage()
        msg['Subject'] = 'Lời mời tham gia workspace · AI Support Operations'
        msg['From'] = formataddr((config.sender_name, config.sender))
        msg['To'] = recipient
        msg['Message-ID'] = make_msgid(domain=config.sender.rsplit('@', 1)[-1])
        msg['Date'] = formatdate(localtime=False, usegmt=True)
        msg['Auto-Submitted'] = 'auto-generated'
        msg['X-Auto-Response-Suppress'] = 'All'
        msg.set_content(f'''Xin chào,

{inviter} mời bạn tham gia workspace {workspace} trên AI Support Operations.
Nhóm: {team}
Vai trò: {role_name}

Mở link để tham gia: {url}
Đăng nhập hoặc tạo tài khoản bằng đúng email {recipient}.
Lời mời có hiệu lực đến {expiry} (giờ Việt Nam), trừ khi đã bị thu hồi hoặc thay thế.

Nếu không nhận ra lời mời này, bạn có thể bỏ qua email.
''')
        msg.add_alternative(f'''<!doctype html><html lang="vi"><body style="font-family:Arial,sans-serif;color:#172b4d;line-height:1.7;max-width:600px;margin:32px auto;padding:0 20px">
<h1 style="font-size:24px">Bạn được mời tham gia workspace</h1>
<p><strong>{escape(inviter)}</strong> mời bạn vào <strong>{escape(workspace)}</strong> trên AI Support Operations.</p>
<p>Nhóm: {escape(team)}<br>Vai trò: {escape(role_name)}</p>
<p style="margin:28px 0"><a href="{escape(url, quote=True)}" style="background:#1d4ed8;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block">Tham gia workspace</a></p>
<p>Đăng nhập hoặc tạo tài khoản bằng đúng email <strong>{escape(recipient)}</strong>.</p>
<p>Lời mời có hiệu lực đến {expiry} (giờ Việt Nam), trừ khi đã bị thu hồi hoặc thay thế.</p>
<p>Nếu nút không mở được, sao chép link này vào trình duyệt:<br><a href="{escape(url, quote=True)}" style="overflow-wrap:anywhere">{escape(url)}</a></p>
<p style="color:#475569">Nếu không nhận ra lời mời này, bạn có thể bỏ qua email.</p>
</body></html>''', subtype='html')
        context = ssl.create_default_context()
        client = smtplib.SMTP_SSL(config.host, config.port, timeout=10, context=context) if config.security == 'ssl' else smtplib.SMTP(config.host, config.port, timeout=10)
        try:
            if config.security == 'starttls':
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            client.login(config.username, config.password)
            refused = client.send_message(msg, from_addr=config.sender, to_addrs=[recipient])
            if refused:
                return DeliveryResult('failed', 'Máy chủ email từ chối người nhận. Hãy kiểm tra địa chỉ hoặc sao chép link lời mời.')
        finally:
            # A QUIT failure after successful DATA must not misreport an accepted email.
            client.close()
        return DeliveryResult('sent', 'Máy chủ email đã nhận lời mời để gửi. Người nhận nên kiểm tra cả Hộp thư đến và Thư rác.')
    except smtplib.SMTPAuthenticationError:
        return DeliveryResult('failed', 'Không đăng nhập được máy chủ email. Đơn vị vận hành cần kiểm tra cấu hình SMTP; link lời mời vẫn dùng được.')
    except (OSError, smtplib.SMTPException, ValueError, UnicodeError):
        return DeliveryResult('failed', 'Chưa xác nhận được việc gửi email. Bạn có thể chia sẻ link trực tiếp; kiểm tra hộp thư trước khi mời lại.')


def send_account_link(*, recipient: str, token: str, purpose: str) -> DeliveryResult:
    result = _send_account_link(recipient=recipient, token=token, purpose=purpose)
    from .operational import record_signal
    record_signal('email', result.status == 'sent')
    import logging
    logging.getLogger(__name__).info('Account email delivery purpose=%s status=%s', purpose, result.status)
    return result
