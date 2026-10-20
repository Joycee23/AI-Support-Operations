# AI Support Operations

Ứng dụng SaaS hỗ trợ đa doanh nghiệp bằng ticket, kho kiến thức được duyệt và gợi ý AI có trích dẫn. Lời mời thành viên có thể gửi qua SMTP; chưa tích hợp CRM hoặc gửi phản hồi khách hàng ra hệ thống ticketing.

## Chạy local bằng Docker Compose

Cần Docker Compose, Node.js 20+ và Python 3.11+ nếu chạy frontend/API ngoài container.

```bash
cp .env.example .env
```

Điền `GEMINI_API_KEY` thật vào `.env` trên máy chạy. Sau đó:

```bash
docker compose up --build
```

Mở http://localhost:8000. Compose khởi động PostgreSQL 16 với pgvector, chờ healthcheck, rồi chạy app. API xác thực Gemini và kiểm tra model sinh cùng model embedding khi khởi động. Thiếu `DATABASE_URL` hoặc `GEMINI_API_KEY`, key sai, model không truy cập được, PostgreSQL/pgvector không sẵn sàng thì backend dừng với thông báo cấu hình. Không có chế độ AI giả lập.

## Chạy từng phần khi phát triển

```bash
docker compose up -d db
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server.main:app --reload --port 8000
```

Trong terminal khác:

```bash
npm install
npm run dev
```

Mở http://localhost:5173. `DATABASE_URL` trong `.env.example` dùng cổng PostgreSQL local. Vite gọi API tại `VITE_API_URL`. Trong production, FastAPI phục vụ frontend đã build cùng API.

## Lệnh hay dùng

```bash
npm run build
python -m compileall -q server
docker compose down       # dừng dịch vụ, giữ dữ liệu volume
docker compose down -v    # xóa toàn bộ database và file đã tải lên
```

`docker compose down -v` xóa toàn bộ dữ liệu trong Postgres và file đã tải lên. Ứng dụng không tự seed dữ liệu mẫu khi khởi động.

## Kiến trúc

- `src/`: React + TypeScript, Vite; trang, component, client API và kiểu dữ liệu tách riêng.
- `server/routes/`: endpoint workspace, ticket, kiến thức, AI và báo cáo.
- `server/services/`: Gemini, RAG retrieval, ingestion/extraction.
- `server/models.py`: SQLAlchemy models; mọi bản ghi nghiệp vụ có workspace scope; vector trong PostgreSQL/pgvector.
- `server/security.py`: kiểm tra vai trò và phạm vi workspace/nhóm ở backend.
- `server/services/ingestion.py`: nhận TXT/MD/PDF tối đa 10 MB, lưu file local, trích xuất văn bản, chia đoạn và tạo embedding.
- Docker Compose chỉ thêm Postgres/pgvector. Ingestion dùng FastAPI BackgroundTasks; chưa thêm Redis/Celery cho một instance và không có nhu cầu bền vững/hàng đợi đa worker.

## Gemini, embedding và RAG

`GEMINI_API_KEY` chỉ tồn tại ở backend, không đưa vào frontend, Git, log hay README. Model sinh mặc định `gemini-3.5-flash-lite`. Model embedding mặc định `gemini-embedding-001`, cấu hình được bằng `GEMINI_EMBEDDING_MODEL`. Startup gọi API bằng key hiện tại để xác thực model sinh và embedding; lỗi model/quyền truy cập làm app dừng. `gemini-embedding-001` được cấu hình vector 768 chiều để khớp kiểu `Vector(768)`.

Ingestion lưu trạng thái `queued / processing / ready / failed`. Chỉ tài liệu đã duyệt, xử lý xong và trong quyền truy cập của người dùng mới được truy xuất. RAG dùng cosine distance từ pgvector, sau đó nhà cung cấp AI được chọn tạo phân loại, ưu tiên, nhóm đề xuất, lý do, bản nháp, citations hoặc trạng thái abstain. Backend lọc citation theo nguồn đã truy xuất; nếu không có nguồn hợp lệ hoặc ticket nhạy cảm thì xóa bản nháp và yêu cầu chuyển người. Lỗi AI trả HTTP 502 và giao diện báo thất bại.

FastAPI BackgroundTasks phù hợp với một instance nhưng không durable: process tắt giữa ingestion thì lần khởi động sau thử lại các mục đang chờ/thất bại. Khi cần nhiều worker, retry policy và công việc dài, chuyển ingestion sang Celery/RQ + Redis hoặc queue managed.

Tệp dùng local storage tại `UPLOAD_DIR` trong local/container. Khi deploy nhiều instance, thay storage adapter bằng object storage; giữ metadata, trạng thái và nội dung đã trích xuất trong Postgres. Không có upload gửi tới Gemini; chỉ nội dung ticket và đoạn kiến thức được phép trong các lời gọi AI.

## Tài khoản và nhiều doanh nghiệp

- Mở ứng dụng, đăng ký email/mật khẩu (từ 12 ký tự) và tên doanh nghiệp. Tài khoản mới sở hữu workspace trống cùng một nhóm hỗ trợ mặc định.
- Mỗi workspace dùng thử 1 tháng theo lịch, sau đó 499.000đ/tháng. Thanh toán VietQR qua SePay; không tự trừ tiền.
- Mỗi tài khoản có thể sở hữu/tham gia nhiều workspace, chuyển bằng bộ chọn ở đầu thanh bên.
- Quản trị viên tạo nhóm và mời nhân viên/quản lý; quản lý chỉ mời nhân viên vào nhóm mình. Link lời mời có hạn 7 ngày, chỉ email được mời mới nhận được. Lời mời được gửi qua SMTP nếu đã cấu hình; link vẫn hiển thị một lần để sao chép và có thể thu hồi.
- Đã thay hoàn toàn `X-Demo-User` bằng cookie phiên HttpOnly, SameSite=Lax; token phiên được băm trong PostgreSQL, thời hạn 14 ngày, đăng xuất thu hồi phiên. Mật khẩu dùng scrypt và salt ngẫu nhiên.
- Danh tính và quyền lấy từ phiên server, không tin user/workspace ID do trình duyệt gửi. Header membership chỉ phát hiện khi workspace đổi ở tab khác để ngăn thao tác nhầm.
- Ticket, kiến thức, vector retrieval, báo cáo và audit đều kiểm tra workspace và quyền. Workspace mới không được nạp dữ liệu công ty mẫu. Dữ liệu mẫu cũ được giữ trong DB nhưng không truy cập được bằng header giả lập.
- Tạo ticket thủ công trong Hộp thư; nhập/tải tài liệu trong Kho kiến thức rồi duyệt. Phản hồi chỉ lưu sau xác nhận, chưa gửi tới email/ticketing bên ngoài.
- Đổi tên doanh nghiệp trong Cấu hình. Các workspace dùng chung hạ tầng và key AI của nhà vận hành; doanh nghiệp đăng ký không phải tự cài server hoặc nhập API key.

### Cấu hình khi đưa lên Internet

- Dùng HTTPS và đặt `COOKIE_SECURE=true`. Phục vụ frontend/API cùng origin và cấu hình origin được phép chính xác.
- Phần thay đổi schema chỉ bổ sung các bảng accounts, account_memberships, auth_sessions, invitations khi startup, giữ nguyên dữ liệu cũ. Cần đưa schema vào quy trình migration có phiên bản khi vận hành nhiều instance.
- Đã tích hợp email mời thành viên qua SMTP; chưa có xác minh email độc lập, quên mật khẩu/khôi phục tài khoản, SSO hoặc quản trị gỡ thành viên.
- Giới hạn đăng nhập/đăng ký hiện theo IP, 20 lần/5 phút trong từng process. Khi có reverse proxy/nhiều worker, cấu hình rate limit dùng chung ở gateway/Redis. Giới hạn sử dụng AI theo workspace và chính sách dữ liệu là các phần vận hành tiếp theo.

## Cấu hình

Sao chép `.env.example` thành `.env` và đặt:

- `GEMINI_API_KEY`: bắt buộc, chỉ dùng ở backend.
- `DATABASE_URL`: bắt buộc, PostgreSQL có extension pgvector.
- `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL`: model cần API key có quyền gọi.
- `UPLOAD_DIR`: thư mục file local hoặc mount volume.
- `CORS_ORIGINS`: origin frontend trong môi trường phát triển tách dịch vụ.
- `VITE_API_URL`: API URL tại thời điểm build frontend.

## Deploy

Dockerfile build Vite và chạy FastAPI phục vụ frontend/API cùng origin. Trên nền tảng container, cấp `DATABASE_URL` tới PostgreSQL có pgvector và `GEMINI_API_KEY` qua secret manager. Gắn persistent volume hoặc thay upload adapter bằng object storage. CORS origin, TLS, backup và retention phải được đặt theo môi trường đích. Repo chỉ cung cấp cấu hình, không deploy hay tạo tài nguyên cloud.

## Giới hạn hiện tại

- Không tự nạp dữ liệu seed cho doanh nghiệp đăng ký mới.
- Tài khoản email/mật khẩu và phiên server đã thay header demo; chưa tích hợp SSO hoặc email khôi phục.
- SQLite không được hỗ trợ; PostgreSQL + pgvector là bắt buộc.
- Upload hỗ trợ PDF/TXT/MD tối đa 10 MB; PDF scan không có lớp text cần OCR chưa được hỗ trợ.
- Ingestion background trong process không bền vững như queue riêng.
- Chưa gửi phản hồi khách hàng qua email/hệ thống ticket bên ngoài, chưa có SSO hoặc retention policy.
- Báo cáo chỉ phản ánh feedback được lưu; không đo hay tuyên bố hiệu quả AI.


### Tự động chuyển model khi quá tải

`GEMINI_MODEL` là model chính. `GEMINI_FALLBACK_MODELS` là danh sách model sinh nội dung dự phòng, cách nhau bằng dấu phẩy, thử từ trái sang phải. Cấu hình local:

```dotenv
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODELS=gemini-3.6-flash,gemini-3.5-flash,gemini-3.1-flash-lite
```

- Phân tích ticket và soạn FAQ dùng chung cơ chế chuyển model tự động.
- Lỗi 500/502/503/504 hoặc timeout: chuyển ngay sang model tiếp theo, tạm bỏ qua model lỗi 60 giây.
- Lỗi 429: chuyển model và tạm bỏ qua model đó 120 giây. Quota dùng chung có thể khiến cả danh sách đều thất bại.
- Model không tồn tại hoặc không được phép gọi (404/403): bỏ qua 300 giây. Key không hợp lệ (401) dừng ngay để sửa cấu hình.
- Mỗi model chỉ được gọi một lần trong một yêu cầu, tối đa 25 giây; tổng ngân sách gọi là 90 giây. Khi hết cooldown, model chính được ưu tiên lại.
- Cooldown nằm trong bộ nhớ của từng process và được đặt lại khi restart. Khi tất cả model đang cooldown, trả lỗi ngay thay vì gọi dồn nhà cung cấp.
- Chỉ báo lỗi trên giao diện khi không có model nào hoàn thành được yêu cầu hoặc có lỗi ngoài phạm vi chuyển model. Không tạo câu trả lời giả khi dịch vụ không khả dụng.
- Embedding vẫn dùng một model cố định để giữ vector nhất quán; bước này có retry riêng tối đa 3 lần, 40 giây/lần. Chuyển model sinh nội dung không khắc phục sự cố dịch vụ embedding.
- Log ghi tên model, bước lỗi và HTTP status, không ghi API key hoặc nội dung ticket. Danh sách model có trên API không bảo đảm quota hoặc khả dụng mọi thời điểm.

Sửa `.env` rồi chạy `docker compose up -d --build app` để áp dụng.


## SePay: dùng thử và gia hạn

Giá đã chốt: **499.000đ/doanh nghiệp/tháng**, trả trước từng tháng. Mỗi workspace mới dùng thử **1 tháng theo lịch** từ lúc tạo, theo múi giờ Việt Nam (ngày cuối tháng được điều chỉnh nếu tháng sau ngắn hơn). Workspace có sẵn được cấp trial một lần khi triển khai tính năng này. Trial được lưu trong DB, không bắt đầu lại khi đăng nhập, thêm thành viên hay khởi động lại server.

Khi hết hạn, người dùng vẫn xem được dữ liệu và cấu hình thanh toán; backend chặn thay đổi nghiệp vụ và gọi AI với HTTP 402. Đăng nhập, đăng xuất, đổi workspace, chấp nhận lời mời và tạo workspace mới vẫn khả dụng. Thanh toán sớm cộng 1 tháng vào thời hạn còn lại; thanh toán sau khi hết hạn bắt đầu từ lúc webhook xác nhận. Không tự trừ tiền, không lưu thẻ.

### 1. Điền `.env` trên máy chủ

```dotenv
SUBSCRIPTION_MONTHLY_PRICE_VND=499000
SEPAY_BANK_CODE=VCB
SEPAY_ACCOUNT_NUMBER=
SEPAY_ACCOUNT_NAME=
SEPAY_WEBHOOK_API_KEY=
```

- `SEPAY_BANK_CODE`: mã ngân hàng thực tế được SePay/VietQR hỗ trợ, ví dụ VCB chỉ là ví dụ.
- `SEPAY_ACCOUNT_NUMBER`: số tài khoản nhận tiền đã liên kết SePay. Dùng tài khoản ngân hàng chính cho tích hợp này, chưa hỗ trợ VA/subAccount riêng.
- `SEPAY_ACCOUNT_NAME`: tên chủ tài khoản, đối chiếu chính xác với ngân hàng trước khi đưa vào sử dụng.
- `SEPAY_WEBHOOK_API_KEY`: khóa ngẫu nhiên riêng tối thiểu 32 ký tự. `.env` local đã được tạo khóa an toàn; sao chép giá trị đó sang cấu hình API Key của webhook. Đây **không phải** API token dùng gọi API SePay. Không gửi khóa qua chat hoặc commit lên Git. `.env.example` cố ý để trống.
- Khi triển khai HTTPS, đặt `COOKIE_SECURE=true` và `CORS_ORIGINS=https://ten-mien-cua-ban`.

Sau khi điền, chạy `docker compose up -d --build app`. Không cần đặt API token SePay vì luồng này dùng VietQR và webhook ngân hàng.

### 2. Tạo webhook trong SePay

Trong **Webhooks → Thêm webhook**:

1. Chọn sự kiện **Có tiền vào**.
2. URL: `https://ten-mien-cua-ban/api/billing/sepay/webhook`. SePay phải truy cập được URL HTTPS này; `localhost:8000` chỉ chạy trên máy bạn và không nhận được webhook từ SePay.
3. Chọn đúng tài khoản ngân hàng trùng với `.env`; nếu lọc theo tiền tố thì dùng `ASO`. Không thay đổi/lược bỏ nội dung giao dịch.
4. Chọn xác thực **API Key**. Điền khóa giống `SEPAY_WEBHOOK_API_KEY`. SePay gửi header `Authorization: Apikey <khóa>`.
5. Bật cảnh báo webhook lỗi và lưu cấu hình.

### 3. Người dùng thanh toán

Quản trị viên vào **Cấu hình → Gói dịch vụ & thanh toán → Gia hạn 1 tháng**. App tạo yêu cầu cố định số tiền, tài khoản, nội dung duy nhất và hiển thị VietQR. Giao diện tự cập nhật trạng thái mỗi 5 giây trong khi chờ. Chỉ webhook đã xác thực mới đánh dấu đã trả và gia hạn workspace; không có nút tự xác nhận đã trả.

Mã có thời hạn hiển thị 30 phút. Khoản đến muộn vẫn được ghi nhận nếu đúng tài khoản, đủ số tiền và đúng mã; không chuyển lại chỉ vì chưa thấy xác nhận. Các order giữ nguyên số tiền/tài khoản lúc tạo, kể cả cấu hình thay đổi sau đó. Giữ webhook cho tài khoản cũ đến khi xử lý hết yêu cầu còn tồn.

Backend lưu `payment_receipts.transaction_id` duy nhất, khóa order/subscription khi cập nhật để chống retry/concurrent delivery cộng trùng. Giao dịch sai số tiền/tài khoản, không có mã, hoặc chuyển lần hai vào order đã trả không tự gia hạn. Các trường hợp đó được giữ trong `payment_receipts` với outcome `mismatch`, `unmatched`, `ignored`, `duplicate_payment` để đơn vị vận hành đối soát và xử lý/hoàn tiền thủ công. Chưa có giao diện đối soát hoặc hoàn tiền tự động. Không chia nhỏ hay cộng nhiều khoản chuyển thiếu thành một lần thanh toán.

### Trạng thái triển khai

Build frontend và biên dịch Python không xác nhận luồng tiền thật. Chỉ kích hoạt nhận tiền cho khách sau khi bạn đã cấu hình tài khoản, webhook công khai và xác nhận một giao dịch thực tế trong nhật ký SePay cũng như lịch sử app. Không dùng chức năng gửi thử payload để đánh dấu order thật đã trả; endpoint tin cậy các webhook mang API Key hợp lệ.

Tài liệu chính thức: [Webhook SePay](https://docs.sepay.vn/tich-hop-webhooks.html), [VietQR](https://docs.sepay.vn/tao-qr-code-vietqr-dong.html).


## Email mời thành viên (Gmail SMTP)

Ứng dụng dùng một địa chỉ email của đơn vị cung cấp để gửi lời mời cho tất cả workspace, hỗ trợ người nhận Gmail hoặc các dịch vụ email khác. Quản trị viên/quản lý vẫn bị giới hạn nhóm/vai trò như trước. Mỗi workspace có tối đa 20 lần tạo lời mời trong 5 phút trên mỗi tiến trình; triển khai nhiều worker cần bộ giới hạn dùng chung.

Điền các biến sau trong `.env` (không gửi mật khẩu lên chat):

```dotenv
APP_PUBLIC_URL=https://ten-mien-cua-ban
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=AI Support Operations
```

- `SMTP_USERNAME`: Gmail dùng để gửi lời mời.
- `SMTP_FROM_EMAIL`: dùng cùng địa chỉ với `SMTP_USERNAME` khi gửi qua Gmail.
- `SMTP_PASSWORD`: **Mật khẩu ứng dụng** của Google, không phải mật khẩu đăng nhập Gmail. Bật Xác minh 2 bước trong tài khoản Google, vào [Mật khẩu ứng dụng](https://myaccount.google.com/apppasswords), tạo mật khẩu riêng cho app này rồi điền giá trị 16 ký tự, bỏ khoảng trắng. Nếu Google không cung cấp mục đó do chính sách tài khoản, dùng SMTP của nhà cung cấp email giao dịch thay thế.
- `APP_PUBLIC_URL`: địa chỉ HTTPS mà người nhận truy cập được, chỉ gồm origin, không có đường dẫn/query/hash. Có thể dùng URL tunnel HTTPS khi phát triển; link `localhost` không mở được từ máy người nhận, nên app không gửi email chứa link đó.
- SMTP hỗ trợ STARTTLS (587) hoặc TLS trực tiếp (`SMTP_SECURITY=ssl`, port 465), luôn xác minh chứng chỉ. Không hỗ trợ gửi mật khẩu qua SMTP không mã hóa.

Sau khi điền, chạy `docker compose up -d app`. Không cần deploy riêng dịch vụ email; Gmail SMTP có thể gửi từ backend local khi URL tham gia là URL HTTPS công khai trỏ tới app của bạn.

Trong **Nhóm & thành viên → Mời thành viên**, bấm **Gửi lời mời** để lưu lời mời, gửi email gồm tên workspace, nhóm, vai trò, ngày hết hạn và nút tham gia. Giao diện giữ link sao chép, hiển thị kết quả SMTP và lưu kết quả trong danh sách lời mời. Nếu SMTP chưa cấu hình hoặc gửi lỗi, lời mời vẫn tồn tại và link vẫn dùng được. Không tự gửi lại khi lỗi mạng để tránh email trùng. Muốn thử lại có thể tạo lời mời mới cho cùng email/nhóm; lời mời mới sẽ thay thế link cũ.

Trạng thái `sent` chỉ xác nhận máy chủ SMTP đã nhận thư, không chứng minh thư đã vào Gmail Inbox. Người nhận cần kiểm tra cả Spam. Nếu request bị ngắt ngay sau lúc tạo lời mời, trạng thái có thể còn `pending`; kiểm tra hộp thư trước khi tạo lại. Token chỉ được lưu dạng hash trong DB, không được ghi vào log; email chứa link riêng của người nhận. Thu hồi/thay thế lời mời khiến link trong email cũ không còn hiệu lực. Không gửi email thực tế khi build/khởi động server.


## Dữ liệu VinStay và kiểm thử

Workspace test VinStay AI chứa dữ liệu lưu trú giả lập có nhãn `[TEST]`, không phải chính sách thật: 12 ticket, 12 tài liệu, 3 nhóm nghiệp vụ mới và nhóm hỗ trợ mặc định. Có 8 tài liệu đã duyệt, 3 chờ duyệt và 1 lưu trữ. Không có liên hệ khách hàng thật trong các fixture.

- `scripts/populate_vinstay.py --email <email-test>`: tạo/reuse dữ liệu qua API local, yêu cầu mật khẩu qua prompt không lưu ra file. Thực hiện gọi Gemini/embedding thật để tạo và kiểm tra gợi ý; có thể phát sinh sử dụng API. Chỉ chạy với workspace VinStay AI và vai trò admin. Không gửi lời mời hoặc thanh toán.
- Chạy `./.venv/bin/python scripts/run_checks.py` để thực hiện unit/integration checks. Các test PostgreSQL tạo schema riêng ngẫu nhiên `test_operations_*`, `test_startup_*` rồi xóa schema đó sau kiểm thử; không thay đổi workspace thật. SMTP và Gemini trong suite này là provider giả lập, không gửi email hoặc chuyển tiền.
- Kết quả và giới hạn đợt kiểm thử thực tế: `artifacts/VINSTAY_TEST_REPORT.md`. Không coi kiểm thử webhook giả lập là bằng chứng đã nhận tiền thật.

## Sinh nội dung qua 9router (tùy chọn)

Adapter backend dùng **Responses API** (`POST /v1/responses`), Bearer key và JSON Schema;
đầu ra vẫn được kiểm tra bằng Pydantic trước khi sử dụng. Không gửi key xuống trình duyệt.
Embedding tiếp tục dùng Gemini 768 chiều nên không cần tạo lại dữ liệu kiến thức.

Trong `.env`, điền key tạo ở trang **Endpoint & Key** của 9router và bật:

```dotenv
AI_PROVIDER=9router
NINEROUTER_BASE_URL=http://localhost:20128/v1
NINEROUTER_DOCKER_BASE_URL=http://host.docker.internal:20128/v1
NINEROUTER_API_KEY=<key riêng cho ứng dụng>
NINEROUTER_MODEL=codexlite/gpt-6-luna
NINEROUTER_FALLBACK_MODELS=codexlite/gpt-6-sol
NINEROUTER_GEMINI_FALLBACK=true
```

- Python chạy trực tiếp dùng `NINEROUTER_BASE_URL`; Docker Compose dùng `NINEROUTER_DOCKER_BASE_URL` để kết nối tới 9router trên Mac. Khi deploy, đổi URL Docker thành địa chỉ router mà server truy cập được.
- Khởi động lại bằng `docker compose up -d --build app`. 9router phải đang chạy và cho phép kết nối từ Docker. Đổi `AI_PROVIDER=gemini` rồi khởi động lại để quay về Gemini.
- Thứ tự mặc định: `codexlite/gpt-6-luna` → `codexlite/gpt-6-sol` → danh sách Gemini hiện có. Chỉ thử model tiếp theo khi lỗi/quá tải/timeout; không tự xác định độ khó của ticket để nâng model.
- Router dùng tối đa 25 giây/model; cả chuỗi sinh nội dung (bao gồm Gemini dự phòng) tối đa 90 giây. Embedding có ngân sách retry riêng như phần trên.
- JSON không hợp lệ, đầu ra bị cắt hoặc rỗng được xem là lỗi 502 để thử model tiếp theo. Các lỗi 403/404/429/5xx và timeout dùng cooldown của model pool. Lỗi cấu hình/key router (400/401/422...) chuyển sang Gemini khi cho phép; không thử lặp lại cùng key trên model tiếp theo.
- Khi router không phục vụ được, tạm bỏ qua router 60 giây; sau đó ưu tiên lại router. `NINEROUTER_GEMINI_FALLBACK=false` tắt chuyển nhà cung cấp; danh sách model router vẫn có hiệu lực.
- Startup kiểm tra key router qua `GET /v1/models`; nếu router lỗi và có bật dự phòng, kiểm tra Gemini. Kiểm tra này chưa xác nhận model sẽ sinh nội dung thành công. Gemini embedding luôn được kiểm tra.
- Router phải hỗ trợ Responses API và `text.format` JSON Schema. Tên model trong dashboard là cấu hình của dịch vụ trung gian, không bảo đảm quyền truy cập, giá, quota hoặc tính năng API.
- Giữ `GEMINI_API_KEY` vì embeddings vẫn cần key này. Nội dung ticket và các đoạn kiến thức truy xuất sẽ đi qua nhà cung cấp được chọn.

Các biến 9router được chuẩn bị trong `.env` với `AI_PROVIDER=gemini` cho đến khi bạn điền key.

## Bảo mật và production

Xem [SECURITY.md](SECURITY.md) cho MFA, xác minh/khôi phục tài khoản, hạn mức API/AI, backup mã hóa và triển khai HTTPS.

Sau khi tạo .env, chạy `.venv/bin/python scripts/init_security.py` để tạo khóa mã hóa còn thiếu. Không xoay APP_ENCRYPTION_KEY khi đã có tài khoản bật MFA.

## Vận hành, migration và R2

Xem [OPERATIONS.md](OPERATIONS.md) để tạo bucket R2, bật sao lưu ngoài máy, vận hành cảnh báo và nâng cấp schema bằng Alembic. Database phải được migrate trước khi khởi động app.

## CI/CD và Railway

Xem [RAILWAY_DEPLOY.md](RAILWAY_DEPLOY.md) để thiết lập GitHub Actions, Railway pgvector,
runtime role, migration riêng, volume, R2 backup, uptime và release/rollback.
Railway dùng `railway.json` và `deploy/railway/Dockerfile`; Docker Compose local giữ nguyên.
