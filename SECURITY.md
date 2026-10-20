# Bảo mật và triển khai

## Đã triển khai trong mã nguồn

- Session ngẫu nhiên 256 bit; DB chỉ giữ SHA-256 của token. Cookie HttpOnly, SameSite=Lax; Secure bắt buộc ở production. Tối đa 10 phiên thông thường/tài khoản. Có đổi mật khẩu và đăng xuất mọi thiết bị; đổi/khôi phục mật khẩu thu hồi phiên cũ.
- Scrypt N=32768/r=8/p=1 cho mật khẩu mới; hash cũ được nâng khi đăng nhập thành công. Lỗi validation không trả lại đầu vào nhạy cảm.
- TOTP RFC 6238: secret mã hóa Fernet; thiết lập hết hạn sau 10 phút; chống dùng lại mã. Tám mã khôi phục một lần chỉ lưu hash. Bật/tắt MFA thu hồi phiên khác. Khôi phục mật khẩu vẫn yêu cầu MFA nếu đã bật.
- Link xác minh email/đặt lại mật khẩu chỉ lưu hash, hết hạn sau 30 phút, dùng một lần. SMTP TLS; URL từ cấu hình tin cậy. Quên mật khẩu trả thông báo chung cho email tồn tại/không tồn tại.
- Production yêu cầu email được xác minh trước thao tác nghiệp vụ; admin/manager còn cần MFA. API bảo mật vẫn dùng được khi workspace hết hạn.
- Kiểm tra quyền workspace/nhóm tại backend; kiểm tra lại quyền ticket sau khi model trả về. Retrieval chỉ dùng kiến thức được phép và đã duyệt/xử lý xong.
- Chống CSRF qua Origin, Host allowlist, CSP, chống framing, nosniff, referrer policy, permissions policy, no-store API. HSTS ở production.
- Rate limit theo IP/tài khoản/workspace; giới hạn write/upload/xác thực. Bộ đếm PostgreSQL + khóa giao dịch dùng chung giữa worker/server. Không tin IP do client tự khai qua header.
- AI có quota phút/ngày và lease giới hạn đồng thời; tối đa 4 lần thử generation qua toàn bộ chuỗi model/provider. Hết quota trả 429 + Retry-After trước khi gọi nhà cung cấp. Lease tự hết hạn nếu process chết.
- Indexing: 3 tác vụ toàn hệ thống, 1/workspace, quota chunk/ngày. Trạng thái tài liệu là hàng chờ bền vững trong PostgreSQL; vòng phục hồi lấy tối đa 30 mục/lượt. Tác vụ lỗi không tự retry vô hạn.
- JSON tối đa 128 KiB; upload request 11 MiB, tệp 10 MiB; áp cả body chunked. Nhận body tối đa 30 giây, không nhận body nén.
- PDF/TXT/MD: kiểm tra magic header/UTF-8, PDF tối đa 100 trang, không mã hóa; tối đa 100.000 ký tự/100 chunk. Đọc PDF trong process riêng: timeout 15 giây, CPU 10 giây, address space 384 MiB trên Linux. macOS không có lớp address-space tương đương; production Docker/Linux mới áp được lớp này.
- Tệp tên ngẫu nhiên/quyền 0600, không có đường dẫn tải công khai. Key ở backend. .env/.secrets/backups/artifacts không vào Docker context.
- SePay xác thực webhook, đối chiếu tài khoản/số tiền/mã đơn, unique receipt và khóa hàng chống lặp. Không gia hạn từ xác nhận trình duyệt.
- App UID 10001, filesystem chỉ đọc, bỏ capability, no-new-privileges, giới hạn RAM/CPU/PID. App/DB local chỉ bind 127.0.0.1; production không publish hai cổng này.

## Hạn mức mặc định

| Phạm vi | Mặc định |
|---|---|
| API | 600/IP/phút; 180/tài khoản/phút; 1800/workspace/phút |
| Ghi dữ liệu | 40/tài khoản/phút |
| Đăng nhập | 20/IP/5 phút và 10/email/15 phút |
| Đăng ký | 3/IP/giờ, thêm giới hạn xác thực chung |
| AI/thành viên | 5/phút, 1 tác vụ đồng thời |
| AI/workspace | 20/phút, 300/24 giờ, 3 tác vụ đồng thời |
| AI/toàn hệ thống | 5000/24 giờ, 12 tác vụ đồng thời |
| Upload/workspace | 20/giờ; 256 MiB tệp tải lên; tối đa 1000 mục kiến thức |
| Embedding | 2000 chunk/workspace/24 giờ; 20000 chunk toàn hệ thống/24 giờ |

Upload còn giữ ít nhất 1 GiB trống trên volume để tránh lấp đầy ổ đĩa. Điều chỉnh bằng biến trong .env.example. Đây là quota kỹ thuật, chưa phải tính tiền usage. Bucket 24 giờ tính từ lần dùng đầu, không reset vào 00:00. Lỗi provider vẫn tiêu quota để hạn chế retry phát sinh chi phí. Quota không phải ngân sách tiền chính xác từ provider. Hạn mức IP khá rộng để hỗ trợ mạng chung; cần trusted proxy đúng cấu hình để nhận IP thực.

## Khóa và production

```sh
.venv/bin/python scripts/init_security.py
```

Lệnh tạo khóa còn thiếu trực tiếp vào .env, quyền 0600, không in/không xoay khóa hiện có. APP_ENCRYPTION_KEY cần sao lưu vào kho bí mật riêng: mất khóa sẽ không đọc được secret MFA. Local hiện tại đã khởi tạo.

Chuẩn bị máy chủ/tên miền, DNS và điền:

- APP_DOMAIN: hostname không có https; APP_PUBLIC_URL: https://hostname, không path/query/hash.
- POSTGRES_PASSWORD riêng ít nhất 24 ký tự; DOCKER_DATABASE_URL chứa đúng mật khẩu đã URL-encode.
- SMTP TLS hoạt động, key AI/SePay và APP_ENCRYPTION_KEY trong kho bí mật của máy chủ.

Chỉ sửa POSTGRES_PASSWORD không đổi mật khẩu volume PostgreSQL cũ. Dùng database production riêng, hoặc đổi mật khẩu bằng quy trình quản trị DB phù hợp. Không chuyển nguyên DB chứa dữ liệu thử sang production.

Trước lần chạy đầu/nâng schema, điền DATABASE_MIGRATION_URL trên máy quản trị bằng role quản trị riêng, cùng tên database với DOCKER_DATABASE_URL. Runtime URL dùng user khác và mật khẩu riêng. Chuẩn bị schema/quyền:

```sh
.venv/bin/python scripts/provision_database.py
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

provision_database.py tạo role runtime nếu chưa có, tạo bảng/extension và chỉ cấp SELECT/INSERT/UPDATE/DELETE. App production không tự tạo/sửa schema và từ chối role có superuser/bypass-RLS/createdb/createrole hoặc CREATE trên public. Không truyền DATABASE_MIGRATION_URL vào container app. Đã thử quy trình bằng database/role cô lập, xác nhận runtime đọc được và không CREATE TABLE được.

Production override cần Compose 2.24.4+ hỗ trợ !reset. Caddy cấp HTTPS, chỉ publish 80/443. App chỉ tin forwarded headers từ proxy 10.89.0.2; không đặt FORWARDED_ALLOW_IPS=*. Nếu subnet 10.89.0.0/24 bị trùng, đổi subnet và IP tin cậy cùng nhau. Swagger/OpenAPI tắt ở production. Startup từ chối thiếu HTTPS, Secure cookie, SMTP TLS, encryption key hoặc DB password đủ dài.

Volume upload cũ cần chuyển quyền /app/data sang 10001:10001 trước khi đổi sang user không phải root. Volume local đã chuyển quyền. Không chạy app bằng root để né lỗi quyền.

Cloudflare/firewall thuộc hạ tầng thật: bật proxy DNS, SSL Full (strict), managed WAF, chống bot và rate limit tại biên cho /api/auth/*. Nếu dùng Cloudflare, hạn chế origin chỉ nhận mạng Cloudflare để tránh bypass. Hoặc dùng tunnel cố định, chặn origin trực tiếp. Quick Tunnel chỉ để thử. Các mục này chưa thể bật khi chưa có tài khoản/tên miền/máy chủ production được chọn.

Trong app, tự xác minh email và bật Authenticator ở Cấu hình → Bảo mật tài khoản; giữ mã khôi phục riêng. Không tự bật MFA cho tài khoản thật khi người dùng chưa giữ secret/mã khôi phục.

## Backup mã hóa và diễn tập phục hồi

Công cụ dùng age chính thức, không tự thiết kế mã hóa. Cài age từ package manager. Khởi tạo recipient local ban đầu và sao lưu:

```sh
.venv/bin/python scripts/init_security.py --with-local-backup-key
.venv/bin/python scripts/backup_secure.py
.venv/bin/python scripts/backup_secure.py --kind files
```

Database pg_dump custom-format và tài liệu tar.gz stream trực tiếp vào age, không ghi dump plaintext. Tệp hoàn thành quyền 0600; xóa tệp dở khi lỗi. Không tự xóa backup cũ.

Private identity local: .secrets/backup-age-key.txt. Chuyển một bản identity và APP_ENCRYPTION_KEY ra nơi ngoại tuyến/kho bí mật riêng. Production nên chỉ giữ public recipient trên máy chủ, cất private identity bên ngoài. Bản sao cùng máy chủ chưa đủ chống mất máy/ransomware: cần offsite có versioning/immutability và chính sách lưu giữ.

```sh
.venv/bin/python scripts/restore_verify.py backups/database-<timestamp>.age --identity /path/to/private-identity --target-db restore_drill_20261020
```

Script chỉ tạo database mới tên restore_*, không ghi đè database có sẵn; phục hồi một transaction. Kiểm tra trước khi chuyển app sang database đã phục hồi. Giải mã tệp upload vào thư mục phục hồi riêng, kiểm tra trước khi thay volume; ghép đúng DB/upload/APP_ENCRYPTION_KEY.

Đã tạo backup mã hóa DB/tệp và phục hồi thử vào database cô lập, đối chiếu số account/workspace/ticket/knowledge. Chưa có lịch backup định kỳ/offsite/PITR do chưa có hạ tầng production. Production nên dùng managed PostgreSQL PITR hoặc pgBackRest và diễn tập phục hồi định kỳ.

## Giám sát và giới hạn xác nhận

- HTTP log có request ID, nhóm endpoint, status, thời gian; không ghi query/body/token/IP/email khách hàng. SQLAlchemy che query parameters trong lỗi. Docker xoay tối đa 3 log × 10 MB.
- Gắn hệ thống giám sát hạ tầng để cảnh báo 429/5xx, độ trễ, DB/disk, backlog và chi phí provider. /api/health chỉ là liveness, không phải kiểm tra DB/provider end-to-end.
- Chạy npm audit và pip-audit -r requirements.txt khi cập nhật. Không có CVE đã biết không chứng minh không có lỗi mới/logic. Cần quét/cập nhật cả image/host OS trong CI production.
- Limiter trong app vẫn cần WAF phía trước để chặn DDoS trước khi tới Python/DB. Có thể chuyển admission counters sang Redis khi lưu lượng tăng.
- Chưa áp PostgreSQL RLS: production đã tách role migration/runtime; quyền tenant/nhóm hiện được kiểm tra ở backend và có regression tests. RLS cần bổ sung cùng thiết kế ngữ cảnh tenant cho phiên/tác vụ nền và migration; không bật policy hình thức làm hỏng các luồng nhiều workspace. Role local development vẫn có quyền tạo schema.
- Kiểm thử nội bộ không thay thế pentest độc lập. Không có cấu hình bảo đảm an toàn tuyệt đối.
