# Vận hành và nghiệm thu

## 1. Tạo Cloudflare R2 để lưu ngoài máy

R2 là kho lưu trữ tệp trên hạ tầng Cloudflare. Bản sao ở đó vẫn tồn tại khi máy chạy ứng dụng bị mất hoặc hỏng. Chỉ tải dữ liệu **đã mã hóa bằng age**; bucket phải riêng tư.

1. Mở https://dash.cloudflare.com/, đăng nhập/tạo tài khoản và bật MFA cho tài khoản Cloudflare.
2. Chọn **R2 Object Storage**. Nếu dashboard yêu cầu thông tin thanh toán hoặc điều khoản, bạn tự xem và quyết định chấp nhận; kiểm tra giá hiện hành tại https://developers.cloudflare.com/r2/pricing/.
3. **Create bucket**, ví dụ `support-ops-backups`. Giữ Public access tắt; không bật `r2.dev` hay tên miền công khai.
4. Trong quản lý API token của R2, tạo token **Object Read & Write**, giới hạn **chỉ bucket này**. Quyền xóa cần cho chính sách giữ bản sao. Không dùng Global API Key.
5. Sao chép **Access Key ID**, **Secret Access Key**, và **S3 API endpoint**. Secret thường chỉ hiển thị khi tạo; lưu trong trình quản lý mật khẩu. Không gửi vào chat.
6. Điền các biến đã có trong `.env`:

```dotenv
BACKUP_S3_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
BACKUP_S3_BUCKET=support-ops-backups
BACKUP_S3_ACCESS_KEY_ID=<Access Key ID của R2>
BACKUP_S3_SECRET_ACCESS_KEY=<Secret Access Key của R2>
BACKUP_S3_REGION=auto
BACKUP_S3_PREFIX=support-ops/
```

Nếu R2 cung cấp endpoint theo khu vực pháp lý cụ thể, dùng chính xác endpoint trong dashboard. Xem https://developers.cloudflare.com/r2/api/tokens/ và https://developers.cloudflare.com/r2/get-started/.

Chạy từ thư mục dự án:

```sh
.venv/bin/python scripts/backup_cycle.py
```

Thành công phải có `offsiteVerified: true` trong `backups/status.json`. Script tải lại ciphertext để đối chiếu SHA-256; không coi HTTP upload thành công là đủ. Thử khôi phục một bản đã tải về bằng `scripts/restore_verify.py` trước khi công nhận offsite hoạt động.

**Khóa giải mã:** lưu bản sao `.secrets/backup-age-key.txt` và `APP_ENCRYPTION_KEY` trong kho bí mật tách khỏi máy chạy app và tách khỏi bucket backup. Mất khóa age thì không thể giải mã backup. Mất APP_ENCRYPTION_KEY thì không đọc được bí mật MFA đã mã hóa. Không đổi/xóa các khóa hiện tại.

### Chính sách giữ bản sao

- Mỗi ngày lúc **02:00 giờ máy**: một database dump và một archive tài liệu, mã hóa trước khi ghi đĩa.
- Ngoài máy: giữ bản mới nhất của 7 ngày, 4 tuần, 12 tháng **có bản sao**, riêng cho database/tệp; các tập này có thể trùng nhau.
- Trên máy: giữ 7 bản gần nhất mỗi loại sau khi cả hai bản mới đã xác minh ngoài máy.
- Chỉ dọn đối tượng backup `.age` đúng prefix, không đụng tệp khác; không dọn khi upload/đọc lại thất bại. Chưa có Object Lock/PITR; account hoặc token có quyền xóa vẫn có thể xóa bản sao. Nên bật retention/bucket lock hoặc bản sao sang tài khoản khác sau khi kiểm tra chính sách nhà cung cấp.
- `--local-only` dùng để kiểm tra bản mã hóa trên máy, **không chứng minh offsite đã hoàn tất**.

## 2. Lịch tự động

Đã cài LaunchAgents của tài khoản macOS hiện tại:

- `vn.supportoperations.backup`: 02:00 hằng ngày.
- `vn.supportoperations.monitor`: 5 phút/lần.
- Logs: `data/ops-logs/`. Theo dõi lỗi lịch chạy ở `*.error.log`.

Máy cần thức, tài khoản đã đăng nhập và Docker hoạt động. Khi chuyển sang Linux, dùng các unit mẫu `deploy/systemd/`, sửa đường dẫn/user rồi cài bằng quản trị viên. Lịch local không thay cho một máy chủ luôn chạy.

Có thể cài lại bằng `.venv/bin/python scripts/install_ops_schedule.py`. Muốn gỡ, dùng `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/vn.supportoperations.backup.plist` và tương tự monitor, rồi xóa hai plist nếu muốn.

## 3. Cảnh báo

`MONITOR_ALERT_EMAIL` đã đặt tới email quản trị viên được người dùng chọn. Kiểm tra:

```sh
.venv/bin/python scripts/monitor.py --test-alert
.venv/bin/python scripts/monitor.py
```

Kiểm tra API `/api/ready` + kết nối database riêng, dung lượng ổ máy/volume tài liệu, tín hiệu lỗi AI/email liên tiếp, backup quá 26 giờ hoặc chưa được xác minh ngoài máy. Sau 2 lần kiểm tra lỗi liên tiếp thì gửi; lặp tối đa mỗi giờ, gửi lại khi tập lỗi đổi và gửi thư khi phục hồi. Tín hiệu AI là lỗi toàn bộ yêu cầu tạo gợi ý/FAQ sau fallback, không phải từng lần một model dự phòng thất bại. HTTP 429 giới hạn chủ động không tính là provider outage.

Script chạy ngoài tiến trình web nên phát hiện được app dừng. **Máy bị tắt/mất mạng hoàn toàn, SMTP cùng hỏng, hoặc scheduler dừng thì nó không thể tự gửi email.** Cần thêm một dịch vụ uptime bên ngoài và cấu hình báo không nhận heartbeat để phát hiện các tình huống này. Không coi cảnh báo cùng máy là giám sát độc lập toàn hạ tầng.

## 4. Migration database

- `alembic.ini`, `migrations/versions/`: mỗi thay đổi schema là một revision được lưu cố định. Không sửa revision đã áp dụng.
- `DATABASE_MIGRATION_URL`: chỉ ở máy quản trị/job migration, tài khoản có DDL.
- `DATABASE_URL` / `DOCKER_DATABASE_URL`: tài khoản runtime `support_app`, không superuser/BYPASSRLS/DDL. Ứng dụng không còn gọi `create_all` lúc startup.
- `DOCKER_DATABASE_MIGRATION_URL`: migration URL với hostname `db`, chỉ truyền vào container profile `migration`; không truyền vào app.

Quy trình release:

1. Tạo backup và xác minh khôi phục trên database mới.
2. Trên bản sao, chạy `.venv/bin/python scripts/migrate.py` và test ứng dụng với runtime role.
3. Dùng thay đổi tương thích ngược theo kiểu expand → chuyển code/backfill → contract; lên lịch bảo trì nếu DDL có khóa dài. Không chạy tự động destructive downgrade.
4. Dừng ghi khi migration yêu cầu; chạy script một lần bằng migration role. Script có advisory lock tránh hai release đồng thời.
5. Chạy `scripts/provision_database.py` để đảm bảo quyền/default privileges, khởi động app, kiểm tra `/api/ready` và quyền tenant.
6. Rollback code chỉ khi schema tương thích; nếu không, sửa bằng revision tiếp theo hoặc phục hồi backup vào database mới, không ghi đè database đang chạy.

Database cũ chỉ được `--adopt-existing` nếu cấu trúc khớp baseline. Database trống được upgrade từ đầu. Không dùng `alembic stamp head` để bỏ qua DDL. Tạo revision mới bằng `.venv/bin/alembic revision --autogenerate -m 'description'`, đọc và sửa kỹ cả upgrade/downgrade trước khi chạy. Autogenerate không tự nhận biết ý định rename hoặc chính sách RLS; phải review bằng tay.

Compose migration tùy chọn:

```sh
docker compose --profile migration run --rm migrate
```

Bản local hiện tại đã được migrate. Khi cài mới: khởi động `db`, provision/migrate bằng admin, rồi khởi động `app`.

## 5. RLS và phạm vi

RLS bắt buộc cho `tickets`, `ticket_messages`, `knowledge_items`, `knowledge_versions`, `knowledge_chunks`, `ai_analyses`, `audit_events`. Thiếu phạm vi workspace sẽ không đọc được hàng nào; INSERT/UPDATE khác workspace bị chặn. Phạm vi được lấy từ session thật và đặt bằng SET LOCAL, áp lại sau commit, không lấy từ header do client tự khai.

Account, membership, phiên đăng nhập, lời mời, workspace/team/user, billing, quota/lease và metadata dispatcher thuộc control plane, chưa có RLS; được backend kiểm tra quyền. Không gọi đây là RLS cho toàn bộ bảng. RLS này bảo vệ trước truy vấn bỏ sót điều kiện tenant; **không thay thế chống SQL injection**: nếu kẻ tấn công chạy tùy ý SQL bằng runtime role, họ có thể đổi custom setting. Backend vẫn phải kiểm tra quyền và dùng truy vấn tham số hóa.

## 6. Đo tải

`check_capacity.py`: 20 workspace/100 tài khoản giả lập, 10 ticket/workspace, 2 worker, HTTP thật, PostgreSQL và RLS thật. Các mức 10/25/50/100 người dùng chạy liên tục 8 request/người; không có thời gian nghỉ như người sử dụng thực. Nâng riêng IP quota cho máy phát tải chung, giữ quota người dùng/workspace và AI concurrency. Provider AI giả lập trễ 1 giây, không gọi provider thật trong bài tải.

Đây là staircase ngắn trên máy phát triển, không đo được số doanh nghiệp đăng ký tối đa, giới hạn RAM/CPU trên máy triển khai, hay model thật có thể phục vụ bao nhiêu request/giây. Số người dùng đang đăng nhập khác với số người phát request liên tục. Kết quả JSON có p95/throughput/lỗi và mức cao nhất trong các mức thử đáp ứng p95 <1 giây. Không ngoại suy thành cam kết tải tối đa.

## 7. Kiểm tra bảo mật

Kiểm thử API chủ động nằm trong schema test, provider/email/tiền giả lập. Bandit là công cụ phân tích tĩnh bên thứ ba; pip-audit/npm audit là kiểm tra lỗ hổng dependency đã biết. Chúng không phải pentest do đơn vị độc lập thực hiện. Muốn có đánh giá độc lập, cần thuê đơn vị khác, thống nhất scope, môi trường và quy tắc kiểm thử; không thể tự cấp chứng nhận độc lập từ cùng tác giả code.
