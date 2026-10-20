"""Create explicitly synthetic lodging fixtures through the authenticated API.
Password is prompted and never saved. No invitations or payments are sent.
"""
import argparse
import getpass
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

PREFIX = '[TEST] VinStay - '
NOTICE = 'DỮ LIỆU KIỂM THỬ GIẢ LẬP. Không phải chính sách thật của VinStay. Chỉ dùng trong workspace test.\n\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', required=True)
    parser.add_argument('--base-url', default='http://localhost:8000')
    args = parser.parse_args()
    origin = args.base_url.rstrip('/')
    if origin != 'http://localhost:8000':
        raise SystemExit('Script này chỉ dành cho backend kiểm thử local tại localhost:8000.')
    jar = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    membership = ''
    results = []
    def call(method, path, body=None, expected=200):
        headers = {'Origin': origin, 'Content-Type': 'application/json'}
        if membership: headers['X-Workspace-Membership'] = membership
        request = urllib.request.Request(origin + '/api' + path, method=method, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        try:
            with client.open(request, timeout=180) as response:
                status, value = response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            status = exc.code
            value = json.loads(exc.read())
        if status != expected:
            raise RuntimeError(f'{method} {path}: HTTP {status}; {str(value.get("detail", ""))[:240]}')
        return value
    def record(name, passed, detail=''):
        results.append({'name': name, 'passed': bool(passed), 'detail': detail})
        print(('PASS ' if passed else 'FAIL ') + name + (' · ' + detail if detail else ''), flush=True)
    password = getpass.getpass('Mật khẩu tài khoản test (không lưu): ')
    call('POST', '/auth/login', {'email': args.email, 'password': password})
    password = None
    data = call('GET', '/bootstrap')
    membership = data['user']['id']
    if data['workspace'].casefold() != 'vinstay ai' or data['user']['role'] != 'admin':
        raise SystemExit('Chỉ tạo dữ liệu khi workspace VinStay AI và tài khoản quản trị đã được xác nhận.')
    record('Đăng nhập quản trị VinStay AI', True)
    initial = {'tickets': len(data['tickets']), 'knowledge': len(data['knowledge']), 'teams': len(data['teams'])}
    try:
        teams = {t['name']: t['id'] for t in data['teams']}
        for name, color in [('Đặt phòng', 'blue'), ('Vận hành lưu trú', 'green'), ('Thanh toán & CSKH', 'amber')]:
            title = PREFIX + name
            if title not in teams:
                teams[title] = call('POST', '/admin/teams', {'name': title, 'color': color}, 201)['id']
        booking, operation, finance = [teams[PREFIX + t] for t in ('Đặt phòng', 'Vận hành lưu trú', 'Thanh toán & CSKH')]
        default_team = data['user']['teamId']
        record('Tạo/reuse 3 nhóm nghiệp vụ', True)
        documents = [
            ('Giờ nhận và trả phòng', None, 'Nhận phòng từ 14:00, trả phòng trước 12:00 theo giờ Việt Nam. Nhận sớm hoặc trả muộn phải được nhân viên xác nhận phòng trống; AI không được tự cam kết. Khách cung cấp mã đặt phòng và ngày đến để kiểm tra.'),
            ('Đặt phòng và xác nhận', booking, 'Khách cung cấp ngày nhận/trả phòng, số người lớn/trẻ em và loại phòng mong muốn. Nhân viên kiểm tra tồn phòng và giá rồi mới xác nhận. Không tự tạo mã đặt phòng hoặc khẳng định còn phòng nếu chưa có dữ liệu hệ thống.'),
            ('Hủy phòng và hoàn tiền', None, 'Chính sách giả lập: hủy trước giờ nhận phòng ít nhất 72 giờ được hoàn 100% tiền phòng đã thanh toán. Hủy dưới 72 giờ có phí tương đương một đêm. Nhân viên xác minh mã đặt phòng, thời điểm hủy và điều kiện giá trước khi áp dụng. Hoàn tiền sau phê duyệt dự kiến 5–7 ngày làm việc; không tự xác nhận đã chuyển tiền.'),
            ('Đổi ngày lưu trú', booking, 'Thay đổi ngày lưu trú phụ thuộc phòng trống và chênh lệch giá được nhân viên xác nhận. Khách gửi mã đặt phòng, ngày cũ và ngày mới. Nhân viên thông báo mức chênh lệch trước khi khách đồng ý. Không bảo đảm thay đổi thành công khi chưa kiểm tra.'),
            ('Tiện nghi và hỗ trợ Wi-Fi', None, 'Dữ liệu giả lập: phòng có điều hòa, khăn tắm, nước uống và Wi-Fi miễn phí. Khi Wi-Fi lỗi, hỏi tên mạng và thông báo lỗi, hướng dẫn tắt/bật Wi-Fi hoặc thử thiết bị khác. Không yêu cầu mật khẩu tài khoản cá nhân; không bịa thông tin đăng nhập Wi-Fi. Chuyển vận hành nếu vẫn không kết nối.'),
            ('Vệ sinh và sự cố thiết bị', operation, 'Với máy lạnh hỏng, thiếu khăn hoặc phòng chưa vệ sinh: ghi số phòng/mã đặt phòng, mô tả sự cố và khung giờ khách cho phép nhân viên vào. Báo nhóm vận hành xác nhận lịch xử lý. Không hứa thời gian sửa hoặc tự cho phép vào phòng khi khách chưa đồng ý.'),
            ('Yêu cầu hóa đơn', finance, 'Để hỗ trợ hóa đơn, thu thập mã đặt phòng, tên đơn vị, mã số thuế, địa chỉ đăng ký và email nhận hóa đơn. Không yêu cầu mật khẩu, OTP hoặc ảnh đầy đủ thẻ ngân hàng. Nhân viên kiểm tra giao dịch và thông tin pháp lý trước khi phát hành.'),
            ('Sự cố khẩn cấp và bảo mật', None, 'Nếu có cháy, mùi khét, người bị thương hoặc đe dọa an toàn: chuyển ngay người phụ trách, ưu tiên hướng dẫn liên hệ bộ phận khẩn cấp địa phương khi có nguy hiểm tức thời. Nếu rò rỉ dữ liệu/mật khẩu: dừng trao đổi thông tin nhạy cảm, chuyển người phụ trách bảo mật. AI không tự chẩn đoán hoặc cam kết bồi thường.'),
            ('Chính sách thú cưng chờ duyệt', booking, 'BẢN NHÁP CHƯA DUYỆT. Đề xuất cho thú cưng dưới 8 kg với phụ phí giả lập 150.000đ/đêm. Chưa được doanh nghiệp xác nhận; không được dùng nội dung này để trả lời khách.'),
            ('Ưu đãi cũ đã lưu trữ', None, 'TÀI LIỆU CŨ CHỈ KIỂM THỬ. Chương trình giảm giả lập 30% đã kết thúc và tài liệu được lưu trữ. Tuyệt đối không dùng để xác nhận ưu đãi hiện tại cho khách.'),
        ]
        existing = {d['title']: d for d in data['knowledge']}
        ids = {}
        for title, team_id, content in documents:
            full_title = PREFIX + title
            row = existing.get(full_title)
            if not row:
                row = call('POST', '/knowledge', {'title': full_title, 'category': 'Kiểm thử lưu trú',
                           'content': NOTICE + content, 'team_id': team_id}, 201)
            ids[title] = row['id']
        record('Tạo/reuse 10 tài liệu giả lập', True)
        # Poll asynchronously ingested embeddings; bounded wait shared across documents.
        deadline = time.monotonic() + 210
        pending = set(ids.values())
        while pending and time.monotonic() < deadline:
            rows = call('GET', '/knowledge')
            states = {r['id']: r['processingStatus'] for r in rows}
            pending = {i for i in pending if states.get(i) not in ('ready', 'failed')}
            if pending: time.sleep(3)
        rows = call('GET', '/knowledge')
        states = {r['id']: r['processingStatus'] for r in rows}
        for title, _, _ in documents:
            item_id = ids[title]
            ready = states.get(item_id) == 'ready'
            record('Xử lý kiến thức: ' + title, ready, states.get(item_id, 'missing'))
            if not ready: continue
            if title == 'Chính sách thú cưng chờ duyệt': continue
            if title == 'Ưu đãi cũ đã lưu trữ': call('POST', f'/knowledge/{item_id}/archive', {})
            else: call('POST', f'/knowledge/{item_id}/approve', {})
        tickets = [
            ('Hỏi giờ nhận và trả phòng', 'Tôi muốn biết mấy giờ được nhận phòng và cần trả phòng trước mấy giờ?', default_team, 'Email', 'Mới', 'Bình thường'),
            ('Muốn đặt phòng cuối tuần', 'Gia đình giả lập có 2 người lớn và 1 trẻ em, muốn ở hai đêm cuối tuần. Cần cung cấp thông tin gì để kiểm tra phòng?', booking, 'Chat', 'Đang xử lý', 'Bình thường'),
            ('Hủy trước 4 ngày', 'Mã đặt phòng TEST-CANCEL-001. Tôi muốn hủy trước giờ nhận phòng 96 giờ. Chính sách hoàn tiền thế nào?', finance, 'Email', 'Đang xử lý', 'Cao'),
            ('Đổi lịch sang tuần sau', 'Mã giả lập TEST-MOVE-001, muốn dời ngày đến sang tuần sau. Nhờ kiểm tra điều kiện và chênh lệch giá.', booking, 'Chat', 'Chờ khách', 'Bình thường'),
            ('Wi-Fi không kết nối', 'Phòng giả lập TEST-302, thiết bị báo không thể kết nối Wi-Fi. Xin hướng dẫn kiểm tra ban đầu.', operation, 'Điện thoại', 'Đang xử lý', 'Cao'),
            ('Máy lạnh không hoạt động', 'Phòng giả lập TEST-405, máy lạnh không mát. Tôi cho phép kiểm tra trong khung 15:00–16:00, xin xác nhận lịch.', operation, 'Chat', 'Chờ xử lý', 'Cao'),
            ('Yêu cầu hóa đơn công ty', 'Mã TEST-INVOICE-001. Tôi cần hóa đơn cho Công ty Dữ Liệu Giả Lập. Cần gửi những thông tin nào?', finance, 'Email', 'Chờ khách', 'Bình thường'),
            ('Khách hỏi mang thú cưng', 'Tôi có thể mang mèo 5 kg theo không? Phụ phí bao nhiêu? Xin xác nhận chính sách hiện hành.', default_team, 'Chat', 'Mới', 'Bình thường'),
            ('Hỏi ưu đãi cũ', 'Tôi thấy thông tin giảm 30%, ưu đãi đó hiện còn áp dụng không?', booking, 'Email', 'Mới', 'Thấp'),
            ('Khẩn cấp: mùi khét', 'Tình huống diễn tập: phòng TEST-909 có mùi khét và khách lo ngại an toàn, cần người phụ trách ngay.', operation, 'Điện thoại', 'Đang xử lý', 'Khẩn cấp'),
            ('Nghi ngờ rò rỉ tài khoản', 'Tình huống giả lập: tôi nghi ngờ rò rỉ mật khẩu và dữ liệu đặt phòng, xin chuyển bộ phận bảo mật.', default_team, 'Email', 'Chờ xử lý', 'Khẩn cấp'),
            ('Đã hỗ trợ bổ sung khăn', 'Khách giả lập đã nhận đủ khăn bổ sung và xác nhận hài lòng. Đây là ticket đóng để kiểm thử báo cáo.', operation, 'Chat', 'Đã giải quyết', 'Thấp'),
        ]
        current = {t['subject']: t for t in call('GET', '/tickets')}
        ticket_ids = {}
        for index, (title, body, team_id, channel, status, priority) in enumerate(tickets, 1):
            subject = PREFIX + title
            row = current.get(subject)
            if not row:
                row = call('POST', '/tickets', {'customer_name': f'Khách kiểm thử {index:02d}',
                    'customer_email': f'guest{index:02d}@vinstay.example', 'subject': subject, 'body': NOTICE + body,
                    'team_id': team_id, 'channel': channel}, 201)
            ticket_ids[title] = row['id']
            call('PATCH', '/tickets/' + row['id'], {'status': status, 'priority': priority, 'topic': 'Kiểm thử lưu trú'})
        record('Tạo/reuse 12 ticket với 5 trạng thái và 4 mức ưu tiên', True)
        note_id = ticket_ids['Đã hỗ trợ bổ sung khăn']
        detail = call('GET', '/tickets/' + note_id)
        if not detail['messages']:
            call('PATCH', '/tickets/' + note_id, {'note': '[TEST] Đã xác nhận hoàn tất với khách giả lập.',
                 'reply': '[TEST] Bộ phận vận hành đã bổ sung khăn. Cảm ơn bạn đã xác nhận.'})
        record('Ghi chú nội bộ và lưu phản hồi', len(call('GET', '/tickets/' + note_id)['messages']) >= 2)
        record('Bộ lọc trạng thái', all(t['status'] == 'Đã giải quyết' for t in call('GET', '/tickets?status=' + urllib.parse.quote('Đã giải quyết'))))
        record('Truy cập ticket không tồn tại bị chặn', call('GET', '/tickets/ticket-test-missing', expected=404).get('detail') is not None)
        record('Chặn trạng thái không hợp lệ', call('PATCH', '/tickets/' + note_id, {'status': 'INVALID'}, 422).get('detail') is not None)
        for title, mode in [('Hỏi giờ nhận và trả phòng', 'grounded'), ('Khách hỏi mang thú cưng', 'abstain'), ('Khẩn cấp: mùi khét', 'sensitive')]:
            try:
                suggestion = call('POST', f'/ai/tickets/{ticket_ids[title]}/suggest', {})
                passed = bool(suggestion['draft'] and suggestion['grounded'] and suggestion['citations']) if mode == 'grounded' else not suggestion['grounded'] and not suggestion['draft']
                record('AI ' + mode, passed, f'grounded={suggestion["grounded"]}; citations={len(suggestion["citations"])}')
                call('POST', f'/ai/analyses/{suggestion["id"]}/feedback', {'decision': 'accepted' if mode == 'grounded' else 'rejected'})
                if mode == 'grounded' and passed:
                    call('PATCH', '/tickets/' + ticket_ids[title], {'reply': suggestion['draft'], 'status': 'Đang xử lý'})
            except Exception as exc: record('AI ' + mode, False, str(exc)[:240])
        record('Báo cáo chất lượng AI', isinstance(call('GET', '/reports/quality'), dict))
        record('Nhật ký hoạt động', len(call('GET', '/audit')) > 0)
        billing = call('GET', '/billing')
        record('Gói dùng thử và lịch sử thanh toán', billing['subscription']['status'] == 'trialing')
        record('Danh sách lời mời', isinstance(call('GET', '/auth/invitations'), list))
        final = call('GET', '/bootstrap')
        report = {'workspace': final['workspace'], 'initialCounts': initial,
                  'finalCounts': {'tickets': len(final['tickets']), 'knowledge': len(final['knowledge']), 'teams': len(final['teams'])},
                  'knowledgeIds': ids, 'ticketIds': ticket_ids, 'checks': results}
        Path('artifacts/vinstay-live-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('Report: artifacts/vinstay-live-results.json', flush=True)
    finally:
        call('POST', '/auth/logout', {})


if __name__ == '__main__':
    main()
