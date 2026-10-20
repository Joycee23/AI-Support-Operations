# Triển khai AI Support Operations: GitHub Actions → Railway

Hướng dẫn cho repo https://github.com/Joycee23/AI-Support-Operations.
Không cần VPS, Vercel, Caddy hoặc GHCR trong phương án này. Railway tự build Dockerfile từ GitHub sau CI.
Các thao tác bên dưới tạo dịch vụ tính phí; tài khoản dùng thử có thể giới hạn số dịch vụ, dung lượng, lịch chạy hoặc SMTP. Kiểm tra hạn mức tại Railway trước khi bật.

## 1. Kiến trúc và điều kiện cần

| Dịch vụ Railway | Nguồn | Chạy gì | Dữ liệu/khóa |
|---|---|---|---|
| `postgres` | Docker image `pgvector/pgvector:pg16` | PostgreSQL 16 + pgvector | Volume database; không có domain công khai |
| `migrate` | Repo GitHub | Provision role và Alembic, rồi thoát | URL quản trị + URL runtime + URL backup; không public |
| `web` | Repo GitHub | FastAPI + React; dispatcher kiến thức đã nằm trong app | Volume `/app/data`; chỉ URL runtime |
| `db-backup` | Repo GitHub | Dump mã hóa → R2, rồi thoát | URL backup chỉ đọc, được đọc xuyên RLS; không có khóa quản trị hoặc khóa giải mã |

- Bắt đầu **một replica web**, một vùng Singapore nếu gói hỗ trợ. Không bật Serverless/sleep: app có dispatcher và lịch vận hành bên trong.
- Web backup tệp + mã ứng dụng sau khởi động 60 giây và mỗi ngày 02:00 Việt Nam; kiểm tra vận hành mỗi 5 phút.
- `db-backup` chạy cron `0 19 * * *` UTC = 02:00 Việt Nam. Volume không chia sẻ giữa dịch vụ; vì vậy database và tệp được backup riêng.
- Volume gắn vào web có thể khiến deploy có khoảng gián đoạn. Không hứa zero downtime.
- AI gọi API ngoài; **không triển khai model trên Railway**. 9router trên Mac không thể truy cập bằng `localhost` từ Railway.
- Healthcheck deploy chỉ kiểm tra lúc phát hành. Có workflow uptime riêng mỗi 10 phút; lịch GitHub có thể trễ, không thay thế dịch vụ uptime chuyên dụng.

## 2. GitHub: xem CI đầu tiên

1. Mở repo → **Actions** → workflow **CI**.
2. Nếu GitHub yêu cầu bật Actions, bật cho repo này.
3. Chờ bốn job xanh:
   - `Frontend build and audit`: TypeScript, Vite, npm audit mức high/critical.
   - `Backend, migrations and tenant isolation`: PostgreSQL/pgvector tạm, regression và migration/RLS.
   - `Dependency and secret checks`: pip-audit và Gitleaks quét Git history, che giá trị tìm được.
   - `Docker packaging`: build cả Dockerfile local và Dockerfile Railway; kiểm tra assets/tools.
4. CI không cần API key AI, SMTP, SePay hoặc database production. Không thêm các khóa này vào GitHub Secrets cho CI.
5. Có thể tải báo cáo ở mục **Artifacts → ci-test-reports**, giữ 7 ngày.
6. Nếu có job đỏ, mở bước lỗi. Sửa và push lại; không tắt job để vượt cổng kiểm tra.

GitHub Actions đã được pin bằng commit SHA. Dependabot đề nghị cập nhật hằng tuần; cần xem PR và CI trước khi merge.

### Bảo vệ nhánh (nếu gói GitHub cho phép)

Repo → Settings → Rules → Rulesets (hoặc Branch protection):
- Áp dụng `main`.
- Require pull request trước khi merge.
- Require status checks: chọn bốn tên job CI sau khi chúng đã chạy ít nhất một lần.
- Block force pushes và branch deletion.
- Với repo một người, không đặt yêu cầu người khác review nếu không có người review.

Việc sửa ruleset thay đổi quyền cộng tác; chủ repo tự áp dụng sau khi xem cấu hình.

## 3. Railway: tạo project và database

1. Ở New Project, chọn **Empty Project**. Đặt tên `AI Support Operations`.
2. Chọn region Singapore cho các service nếu có; để database và web cùng vùng.
3. Thêm service từ **Docker Image**, nhập `pgvector/pgvector:pg16`, đặt tên `postgres`.
4. Trong Variables của `postgres`, đặt:

```dotenv
POSTGRES_USER=postgres
POSTGRES_DB=support_ops
POSTGRES_PASSWORD=<mật khẩu ngẫu nhiên riêng, ít nhất 32 ký tự>
PGDATA=/var/lib/postgresql/data/pgdata
```

Tự tạo mật khẩu bằng trình quản lý mật khẩu. Không dùng `support`, không gửi mật khẩu trong chat.

5. Gắn volume vào **`/var/lib/postgresql/data`** trước khi sử dụng database.
6. Deploy database. Log phải báo sẵn sàng nhận kết nối. Bật lịch backup volume trong Railway nếu gói hỗ trợ.
7. Không Generate Domain cho database và không bật TCP Proxy ra Internet nếu không cần.
8. Xem Settings → Networking → Private Networking để lấy hostname thật, thường giống `postgres.railway.internal`.
9. Tự chuẩn bị URL private trong trình quản lý mật khẩu:

```text
postgresql://postgres:<PASSWORD>@<PRIVATE_HOST>:5432/support_ops
```

Nếu mật khẩu chứa ký tự đặc biệt, phải URL-encode phần mật khẩu. Dùng mật khẩu chữ/số ngẫu nhiên sẽ đơn giản hơn. URL private chỉ dùng trong cùng project/environment Railway, không kết nối trực tiếp từ Mac.

**Không dùng PostgreSQL image thường rồi mặc định có pgvector.** Image ở trên có extension; script migration sẽ tạo extension.

## 4. Tạo web và lấy domain trước

1. Thêm service **GitHub Repo** → chọn `Joycee23/AI-Support-Operations`, đặt tên `web`.
2. Cấp Railway GitHub App quyền đúng repo. Không cần toàn bộ repo trong tài khoản nếu chỉ deploy repo này.
3. Nếu build/deploy đầu thất bại vì chưa có Variables, đó là trạng thái chưa cấu hình. Hoàn thành các bước dưới rồi Redeploy.
4. Settings → Source: branch `main`, root directory `/`.
5. Config as Code: dùng `/railway.json` (file mặc định tại root).
6. Settings → Networking → Generate Domain, target port **8000**. Ghi lại hostname `...up.railway.app`.
7. Chưa gắn tên miền riêng cũng được; dùng HTTPS domain Railway để nghiệm thu trước.
8. Đặt replicas = 1; không bật sleep/serverless. Gắn volume **`/app/data`**.

`railway.json` chọn `deploy/railway/Dockerfile`, healthcheck `/api/ready`, timeout 300 giây, restart khi lỗi tối đa 5 lần. Dockerfile này hỗ trợ PORT và công cụ backup. Không cần sửa Dockerfile local.

## 5. Chuẩn bị Variables an toàn trên Mac

### 5.1 Chọn AI trước

- Muốn giữ 9router: `NINEROUTER_BASE_URL` phải là endpoint HTTPS có xác thực, Railway truy cập được. Không dùng `localhost`, `127.0.0.1` hay `host.docker.internal`.
- Nếu chưa có host 9router: có thể **chủ động chọn** `AI_PROVIDER=gemini` trong `.env` trước khi tạo tệp. App vẫn yêu cầu Gemini API key để embedding kể cả khi dùng 9router.
- Chọn model mà key thực sự dùng được; không tự chép các tên model ví dụ nếu chưa xác nhận.
- SMTP cần hoạt động từ gói Railway bạn dùng. Nếu gói chặn SMTP outbound, phải chuyển sang gói cho phép hoặc bổ sung nhà cung cấp email qua HTTPS; không bỏ email verification để vượt lỗi.

### 5.2 Chạy công cụ tạo ba tệp riêng tư

Mở Terminal tại thư mục dự án:

```sh
cd '/Users/jerry/AI-Vin/AI Support Operations'
.venv/bin/python scripts/prepare_railway_env.py
```

Công cụ hỏi:
1. URL database **private của Railway** (ẩn nội dung khi nhập).
2. Hostname web, không có `https://` và không có `/`.

Kết quả nằm tại:

```text
.secrets/railway-app.env
.secrets/railway-migrate.env
.secrets/railway-backup.env
```

Tệp có quyền 0600, bị Git bỏ qua. Công cụ giữ nguyên `.env`, giữ `APP_ENCRYPTION_KEY` hiện có, tạo mật khẩu riêng cho runtime/backup, không in khóa ra terminal.

**Chỉ chạy một lần cho một database.** Công cụ từ chối ghi đè; lưu lại cả ba tệp trong trình quản lý mật khẩu. Đừng xóa rồi chạy lại sau khi role đã được tạo: mật khẩu mới sẽ không khớp role cũ.

Finder → Cmd+Shift+G → đường dẫn:

```text
/Users/jerry/AI-Vin/AI Support Operations/.secrets/
```

Mở từng tệp bằng TextEdit và copy vào **Variables → Raw Editor** đúng service. Không gửi các tệp hoặc ảnh có giá trị khóa vào chat.

### 5.3 Ý nghĩa các nhóm biến

| Service | Nhập tệp | Có gì |
|---|---|---|
| `web` | `railway-app.env` | Runtime DB, AI, SMTP, SePay, APP_ENCRYPTION_KEY, R2, age **public recipient** |
| `migrate` | `railway-migrate.env` | Admin DB + cấu hình tạo runtime/backup role |
| `db-backup` | `railway-backup.env` | Backup DB reader + R2 + age public recipient |

- Không đưa `DATABASE_MIGRATION_URL` hay `BACKUP_DATABASE_URL` vào `web`.
- Không upload `.secrets/backup-age-key.txt` lên Railway; khóa giải mã giữ ngoài máy chủ.
- Không cần đặt `VITE_API_URL`: frontend dùng API cùng origin.
- `APP_ENV=production`, `COOKIE_SECURE=true`, public URL HTTPS và ALLOWED_HOSTS chính xác là bắt buộc.
- `healthcheck.railway.app` nằm trong ALLOWED_HOSTS để Railway kiểm tra readiness được.
- `RAILWAY_RUN_UID=0` chỉ để entrypoint chuẩn bị quyền volume; sau đó chạy bằng UID 10001 qua gosu.
- Runtime không tin tùy ý X-Forwarded-For. Hiện bucket IP có thể gộp theo IP proxy; user/workspace limits vẫn riêng. Đo lại traffic thực tế trước khi tăng hạn mức.

## 6. Chạy migration trước web

1. Thêm GitHub service thứ hai, cùng repo, đặt tên **`migrate`**.
2. Settings → Config as Code → đường dẫn **`/deploy/railway/migrate.json`**.
3. Variables → Raw Editor: nhập **chỉ `railway-migrate.env`**.
4. Không domain, không volume, không healthcheck. Start command từ config là:

```sh
python scripts/provision_database.py
```

5. Deploy service, chờ thông báo schema được chuẩn bị và process **exit 0**. Đây là tác vụ một lần; trạng thái completed/stopped sau thành công là bình thường.
6. Kiểm tra script không báo lỗi. Nó tạo extension, chạy Alembic có khóa serialize, cấp quyền runtime hạn chế và tạo backup role chỉ đọc xuyên RLS. Runtime không có SUPERUSER/BYPASSRLS/CREATE.
7. **Tắt tự động deploy service `migrate`** sau lần đầu. Chỉ chạy có chủ đích khi release thay đổi schema; không để web và migration tự chạy đua nhau.

Nếu lỗi, không đổi web sang user `postgres` để chạy tạm. Kiểm tra host/private URL, tên database, quyền admin, pgvector và log đã che thông tin bí mật.

## 7. Deploy web và bật CD

1. `web` → Variables → Raw Editor: nhập `railway-app.env`.
2. Kiểm tra volume `/app/data`, config `/railway.json`, PORT=8000.
3. Settings → Source: bật **Autodeploy**, bật **Wait for CI**. Nếu chưa có công tắc, chờ workflow CI trên `main` chạy; kiểm tra quyền Railway GitHub App được cập nhật.
4. Chỉ Redeploy commit có CI xanh. Nếu bấm deploy thủ công, tự đối chiếu commit và kết quả CI; không coi thao tác thủ công là đã được cổng CI bảo vệ.
5. Xem deploy log: migration đúng revision, runtime role hợp lệ, provider generation/embedding validate thành công và uvicorn chạy.
6. Chờ readiness pass. Mở domain HTTPS và đăng ký workspace thử riêng.
7. Không tạo worker thứ hai: bản hiện tại đã có dispatcher kiến thức trong `server.main`.

**Luồng từ lần sau:** push/merge `main` → bốn job CI xanh → Railway build Docker → chạy web mới → `/api/ready` xanh → Railway chuyển traffic.

Tín dụng 5 USD/30 ngày không đảm bảo chạy miễn phí cả tháng với bốn service. `migrate` thoát sau khi chạy; `db-backup` chỉ chạy cron; web và database chạy liên tục.

## 8. Bật backup database và kiểm tra R2

1. Thêm GitHub service **`db-backup`**, cùng repo.
2. Config path **`/deploy/railway/backup.json`**.
3. Variables nhập `railway-backup.env`. Không domain; không gắn volume web.
4. Cron lấy từ config `0 19 * * *` UTC. Run một lần thủ công để nghiệm thu, sau đó để lịch chạy.
5. Log cần `Backup complete: offsite ciphertext verified`, rồi exit 0.
6. R2 bucket vẫn private; cần thấy bản mới có tiền tố `database-`, `files-`, `application-` từ môi trường Railway.
7. Chọn **prefix riêng production**, ví dụ `support-ops/railway-production/`, cập nhật cùng giá trị ở web và db-backup. Không trộn retention local/dev với production.
8. Lưu khóa age identity và APP_ENCRYPTION_KEY trong trình quản lý mật khẩu. Có dữ liệu trên R2 chưa đủ để chứng minh khôi phục được.
9. Thực hiện restore drill vào database/môi trường riêng sau deploy. `scripts/check_disaster_recovery.py` hiện dành cho môi trường Docker local; không trỏ nó vào database Railway production. Dùng máy quản trị tách biệt và URL đích khôi phục riêng.

Backup tệp được thực hiện khi app đang chạy: kiểm tra hash bảo vệ tính toàn vẹn ciphertext, không đảm bảo một snapshot nguyên tử giữa database và tệp. Khi đổi schema hoặc chuyển dữ liệu quan trọng, tạm dừng ghi và tạo bộ backup nhất quán trước.

## 9. Giám sát ngoài app

1. GitHub repo → Settings → Secrets and variables → Actions → **Variables**.
2. Tạo repository variable **`PRODUCTION_URL`** = `https://<domain-web>` (URL công khai, không phải secret).
3. Actions → **Public uptime check** → Run workflow.
4. Bật nhận thông báo workflow failures trong tài khoản GitHub. Lịch mỗi 10 phút chỉ hoạt động sau khi workflow ở default branch; GitHub có thể chạy trễ hoặc ngừng lịch ở repo công khai không hoạt động lâu ngày.
5. Bật cảnh báo deploy/crash/resource/cron failure trong Railway theo tính năng gói. Nên bổ sung dịch vụ uptime ngoài GitHub để nhận email ngay cả khi Railway ngừng.
6. Web gửi email cảnh báo AI/DB/volume/backup tệp mỗi 5 phút với cơ chế khử trùng lặp. Nếu container hoặc nền tảng ngừng hẳn, monitor bên trong cũng ngừng; phải dựa vào lớp ngoài.
7. Sau deploy, gửi một cảnh báo kiểm thử có ghi nhãn và xác nhận Inbox. Không coi SMTP accepted là đã đến Inbox.

## 10. Cập nhật SePay, email và tên miền

1. SePay webhook URL đổi sang:

```text
https://<domain-web>/api/billing/sepay/webhook
```

2. Dùng khóa `SEPAY_WEBHOOK_API_KEY` đã cấu hình, giữ xác thực `Apikey`. Không đổi bank/account nếu tiếp tục dùng tài khoản hiện tại.
3. Dùng chức năng gửi lại webhook/test của SePay để kiểm tra HTTP 200 và log đã che dữ liệu. Không chuyển thêm tiền chỉ để kiểm tra lại một giao dịch đã xử lý.
4. Link xác minh/reset/lời mời phải dùng APP_PUBLIC_URL Railway, không còn localhost hoặc trycloudflare.
5. Khi có tên miền riêng: thêm custom domain tại Railway; nhập DNS record **đúng Railway hiển thị** vào nhà cung cấp DNS; chờ TLS sẵn sàng.
6. Đổi APP_PUBLIC_URL, CORS_ORIGINS, ALLOWED_HOSTS, PRODUCTION_URL và SePay webhook sang tên miền mới; redeploy và thử lại login/email/webhook.
7. Với email theo domain riêng: cấu hình SPF/DKIM/DMARC theo nhà cung cấp mail; không cam kết Inbox chỉ bằng code.

## 11. Nghiệm thu bản Railway

- [ ] CI xanh trên đúng commit đang chạy; readiness HTTP 200.
- [ ] Đăng ký, xác minh email, login/logout, quên mật khẩu, mời thành viên.
- [ ] Hai workspace không nhìn thấy dữ liệu của nhau; staff bị giới hạn quyền đúng.
- [ ] Tạo ticket, ghi chú, trả lời, phân công và trạng thái.
- [ ] Upload → xử lý → duyệt kiến thức; gợi ý AI có nguồn/handoff đúng.
- [ ] Refresh và redeploy không mất tệp upload.
- [ ] Billing hiển thị đúng; webhook xác thực, không gia hạn lặp.
- [ ] Database backup cron và web files/application backup đều được xác minh trên R2.
- [ ] Cảnh báo thử và phục hồi đến đúng người; uptime chạy ngoài app.
- [ ] Restore drill vào môi trường riêng và đo tải lại trên cấu hình Railway.

Database local và volume trên Mac **không tự xuất hiện trên Railway**. Hướng dẫn mặc định tạo database mới. Nếu cần giữ tài khoản/ticket/kiến thức/thanh toán thật: lên lịch tạm dừng ghi, tạo backup cuối, restore DB + uploads vào môi trường mới, giữ nguyên APP_ENCRYPTION_KEY, rebase đường dẫn source_file từ local sang `/app/data/uploads`, chạy migration/grants và xác minh trước khi đổi webhook/domain. Không seed dữ liệu giả vào production.

## 12. Release, migration và rollback

### Code không đổi schema

Tạo branch → commit → push → PR → CI xanh → merge main → Wait for CI → Railway deploy.

### Có thay đổi schema

1. Thiết kế migration tương thích bản app đang chạy (expand/contract); không sửa migration đã phát hành.
2. Tạm dừng autodeploy `web` trước khi merge thay đổi schema.
3. Tạo và xác minh backup production.
4. Chạy `migrate` bằng **đúng commit release**, chờ exit 0; kiểm tra revision/grants.
5. Deploy web đúng commit đã kiểm tra, smoke test; bật lại autodeploy/Wait for CI.
6. Nếu migration lỗi, giữ bản web trước và điều tra; không bỏ kiểm tra revision để ép khởi động.

### Rollback

- Code lỗi, schema vẫn tương thích: Railway → Deployments → chọn bản thành công trước → Rollback/Redeploy theo UI.
- Bản app hiện kiểm tra revision Alembic chính xác; rollback code có thể không khởi động sau đổi schema. Phải đánh giá tương thích trước.
- Schema/data lỗi: không tự `alembic downgrade`; baseline chặn downgrade phá hủy. Restore backup vào database mới, kiểm tra dữ liệu/tệp/khóa, rồi chuyển URL khi đã xác minh. Việc này có thể mất các thay đổi sau thời điểm backup.

## Nguồn tài liệu

- Railway GitHub autodeploy / Wait for CI: https://docs.railway.com/guides/github-autodeploys
- Config as code: https://docs.railway.com/reference/config-as-code
- Healthchecks: https://docs.railway.com/guides/healthchecks
- Volumes/permissions: https://docs.railway.com/guides/volumes
- Cron: https://docs.railway.com/guides/cron-jobs

Chỉ kết luận deploy thành công khi dịch vụ thật đã chạy, các biến thật đã điền, readiness và nghiệm thu trên domain thật đạt. File cấu hình và build local không chứng minh tài khoản Railway đã được triển khai.
