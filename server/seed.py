import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Workspace, Team, User, Ticket, TicketMessage, KnowledgeItem, AuditEvent, utcnow

def seed_demo(db: Session):
    if db.scalar(select(Workspace.id).limit(1)):
        return []
    db.add(Workspace(id="ws-antam", name="An Tâm Market"))
    db.flush()
    teams = [
        Team(id="team-care", workspace_id="ws-antam", name="Chăm sóc khách hàng", color="blue"),
        Team(id="team-billing", workspace_id="ws-antam", name="Thanh toán", color="amber"),
        Team(id="team-delivery", workspace_id="ws-antam", name="Vận chuyển", color="green"),
    ]
    db.add_all(teams)
    db.flush()
    people = [
        User(id="u-admin", workspace_id="ws-antam", team_id="team-care", name="Ngọc Trần", email="ngoc@antam.example", role="admin"),
        User(id="u-manager", workspace_id="ws-antam", team_id="team-care", name="Minh Lê", email="minh@antam.example", role="manager"),
        User(id="u-agent", workspace_id="ws-antam", team_id="team-care", name="Linh Phạm", email="linh@antam.example", role="agent"),
        User(id="u-billing", workspace_id="ws-antam", team_id="team-billing", name="Huy Nguyễn", email="huy@antam.example", role="agent"),
        User(id="u-delivery", workspace_id="ws-antam", team_id="team-delivery", name="An Đỗ", email="an@antam.example", role="agent"),
    ]
    db.add_all(people)
    db.flush()
    records = [
        ("T-2841", "Mai Anh", "mai.anh@example.test", "Đơn hàng #AT-10842 chưa được hoàn tiền", "Mình đã trả hàng từ tuần trước, bên mình kiểm tra giúp tình trạng hoàn tiền được không?", "Email", "Đang xử lý", "Cao", "Hoàn tiền", "team-billing", "u-billing"),
        ("T-2840", "Quốc Bảo", "quoc.bao@example.test", "Tài khoản bị khóa sau khi đổi số điện thoại", "Tôi không thể đăng nhập, hệ thống báo thông tin không khớp. Tôi cần xác minh lại thế nào?", "Chat", "Mới", "Bình thường", "Tài khoản", "team-care", "u-agent"),
        ("T-2839", "Thảo Vy", "thao.vy@example.test", "Kiện hàng giao nhầm địa chỉ", "Đơn hàng giao đến số nhà 18 thay vì 81. Tôi đã gọi đơn vị giao hàng nhưng chưa liên hệ được.", "Email", "Chờ khách", "Cao", "Giao hàng", "team-delivery", "u-delivery"),
        ("T-2838", "Đức Minh", "duc.minh@example.test", "Hỏi về thời hạn đổi sản phẩm", "Sản phẩm nhận hôm qua còn nguyên hộp. Mình có thể đổi sang màu khác trong bao lâu?", "Web", "Mới", "Thấp", "Đổi trả", "team-care", "u-agent"),
        ("T-2837", "Khánh Linh", "khanh.linh@example.test", "Thanh toán hai lần cho cùng một đơn", "Tôi thấy tài khoản bị trừ tiền hai lần cho đơn #AT-10791. Nhờ kiểm tra giúp.", "Chat", "Đang xử lý", "Khẩn cấp", "Thanh toán", "team-billing", "u-billing"),
        ("T-2836", "Hoàng Nam", "hoang.nam@example.test", "Mã giảm giá không áp dụng được", "Mã XINCHAO không hoạt động trong giỏ hàng của tôi.", "Email", "Mới", "Bình thường", "Khuyến mãi", "team-care", "u-agent"),
        ("T-2835", "Ngọc Hà", "ngoc.ha@example.test", "Cập nhật địa chỉ trước khi giao", "Đơn hàng vừa đặt, tôi muốn đổi địa chỉ nhận hàng sang văn phòng.", "Web", "Đang xử lý", "Bình thường", "Giao hàng", "team-delivery", "u-delivery"),
        ("T-2834", "Gia Hân", "gia.han@example.test", "Sản phẩm có dấu hiệu gây kích ứng", "Tôi bị nổi mẩn sau khi sử dụng. Xin cho biết thành phần và hướng xử lý.", "Email", "Chờ xử lý", "Khẩn cấp", "An toàn sản phẩm", "team-care", "u-manager"),
        ("T-2833", "Tuấn Kiệt", "tuan.kiet@example.test", "Hóa đơn VAT cho đơn hàng", "Công ty cần hóa đơn VAT, mình có thể nhận hóa đơn sau khi đặt hàng không?", "Email", "Đã giải quyết", "Thấp", "Hóa đơn", "team-billing", "u-billing"),
        ("T-2832", "Phương Nhi", "phuong.nhi@example.test", "Không nhận được email xác nhận", "Tôi đã đặt đơn nhưng chưa nhận email xác nhận, có thể kiểm tra giúp không?", "Chat", "Mới", "Bình thường", "Đơn hàng", "team-care", "u-agent"),
    ]
    messages = []
    for code, customer, email, subject, body, channel, status, priority, topic, team_id, assignee in records:
        ticket_id = "ticket-" + code
        db.add(Ticket(
            id=ticket_id, workspace_id="ws-antam", team_id=team_id, assignee_id=assignee, code=code,
            customer_name=customer, customer_email=email, subject=subject, body=body, channel=channel,
            status=status, priority=priority, topic=topic,
        ))
        messages.append(TicketMessage(
            id=str(uuid.uuid4()), workspace_id="ws-antam", ticket_id=ticket_id, author_name=customer, body=body,
        ))
    db.flush()
    db.add_all(messages)
    docs = [
        ("Chính sách hoàn tiền", "Thanh toán", "Đơn hàng đủ điều kiện được hoàn tiền về phương thức thanh toán ban đầu trong 5–7 ngày làm việc sau khi yêu cầu được xác nhận. Một số ngân hàng có thể cần thêm thời gian xử lý.", None, True),
        ("Đổi sản phẩm", "Đổi trả", "Khách hàng có thể yêu cầu đổi sản phẩm trong vòng 7 ngày kể từ khi nhận hàng nếu sản phẩm còn nguyên trạng, đầy đủ bao bì và hóa đơn. Sản phẩm cá nhân hóa không áp dụng.", None, True),
        ("Thời gian giao hàng", "Vận chuyển", "Đơn hàng nội thành thường được giao trong 1–2 ngày làm việc. Đơn liên tỉnh thường cần 3–5 ngày làm việc. Thời gian có thể thay đổi vào ngày lễ hoặc thời tiết xấu.", "team-delivery", True),
        ("Hướng dẫn xác minh tài khoản", "Tài khoản", "Để xác minh tài khoản, khách hàng đăng nhập bằng email đã đăng ký và dùng mã xác thực gửi đến email. Nhân viên không yêu cầu khách cung cấp mật khẩu hoặc mã xác thực.", "team-care", True),
        ("Hóa đơn VAT", "Thanh toán", "Khách hàng có thể yêu cầu hóa đơn VAT trong vòng 7 ngày sau khi đơn hàng hoàn tất bằng cách cung cấp thông tin công ty và mã số thuế qua kênh hỗ trợ chính thức.", "team-billing", False),
    ]
    pending_ids = []
    for title, category, content, team_id, approved in docs:
        item_id = "kb-" + str(uuid.uuid4())[:8]
        db.add(KnowledgeItem(
            id=item_id, workspace_id="ws-antam", team_id=team_id, created_by="u-admin",
            approved_by="u-admin" if approved else None, title=title, category=category, content=content,
            status="approved" if approved else "pending", processing_status="queued", version=1,
        ))
        if approved:
            pending_ids.append(item_id)
    db.add(AuditEvent(id=str(uuid.uuid4()), workspace_id="ws-antam", actor_id="u-admin", kind="workspace.seed", detail="Đã khởi tạo dữ liệu demo"))
    db.commit()
    return pending_ids
