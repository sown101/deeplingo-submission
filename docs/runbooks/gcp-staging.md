# Hướng dẫn đưa DeepLingo backend và web lên GCP

Ngày soạn: 2026-10-07, cập nhật 2026-10-08. Image và compose trong
`backend/deploy/` đã được build và chạy thử cục bộ (không Supabase, key AI giả);
chưa chạy trên GCP. Việc đọc tài liệu này không tạo tài nguyên hay thay đổi database.

Mục tiêu: có một môi trường dùng thử có HTTPS, có thể cập nhật và quay lại bản
code trước. Giữ FastAPI, Celery Linux prefork, Beat riêng, Redis và Supabase;
không đổi API, schema, chính sách AI, retry hay giới hạn worker.

## 1. Chuẩn bị trước khi tạo tài nguyên

- Một GCP project dành cho thử nghiệm, có billing và credit còn hiệu lực.
- Quyền lấy source từ repository và một commit đã chọn để triển khai.
- Một hostname cho API, ví dụ `api-staging.tenmiencuaban.com`, và quyền sửa DNS.
- Một Supabase project **không phải production**, đã có schema/RPC tương thích
  với commit đó. Backend và web phải dùng cùng project.
- Cấu hình Gemini đang sử dụng: model, endpoint, cách xác thực và quota.
  Không gửi secrets vào chat.

Nếu dùng project development hiện tại, dữ liệu trên máy và trên GCP sẽ dùng
chung. Trước lần chuyển đầu tiên, dừng nhận import mới, chờ các công việc đang
chạy kết thúc, xác nhận không còn running intents, rồi dừng API/worker/Beat cũ.
Không để hai topology cũ/mới và hai Redis broker độc lập cùng xử lý project đó.
Không purge queue hoặc reset trạng thái trong database để ép chuyển.

Nếu tạo Supabase project mới, dừng ở bước chuẩn bị database: cần kế hoạch migration
và kiểm tra grants/RLS/RPC riêng. **Không replay toàn bộ baseline lịch sử.**

Theo thông tin bạn cung cấp, AI hiện dùng **Gemini**. Giữ model và endpoint
Gemini thực tế đang hoạt động khi chuẩn bị triển khai. `ENVIRONMENT=staging`
yêu cầu cấu hình đầy đủ, provider có funding/quota phù hợp và được phân loại
`production_eligible`. Gemini không tự được chứng nhận chỉ vì startup thành công;
vẫn cần kiểm tra structured output, grounding/leakage và injection theo workload.
Nếu cấu hình hiện mới đủ điều kiện development, triển khai môi trường
**cloud development** với `ENVIRONMENT=development` trong phạm vi nhóm thử nghiệm
trước. Xem chính sách AI.

## 2. Tạo project, cảnh báo chi phí và VM

Trong Google Cloud Console:

1. Tạo/chọn project thử nghiệm, ví dụ tên `deeplingo-staging`.
2. Vào Billing, kiểm tra số credit và ngày hết hạn. Credit Free Trial tiêu chuẩn
   là $300 trong 90 ngày từ lúc đăng ký; loại credit khác có thể có điều kiện khác.
3. Tạo budget cảnh báo với mức bạn chấp nhận, ví dụ $60/tháng, và ngưỡng
   50%, 80%, 100%. Đây là **mức ngân sách mục tiêu, không phải báo giá**.
   Budget dạng alerts-only không tự chặn chi tiêu.
4. Bật Compute Engine API, mở Compute Engine → VM instances → Create instance.
5. Cấu hình khởi đầu để thử nghiệm:
   - Tên: `deeplingo-staging-vm`.
   - Region: chọn gần Supabase và nhóm dùng thử; Singapore
     (`asia-southeast1`) là một ứng viên nếu dữ liệu ở khu vực đó.
   - Ubuntu 24.04 LTS.
   - `e2-medium`, 4 GiB RAM, là ứng viên bắt đầu cho tải nhỏ; CPU là shared-core.
     Chưa có load test chứng minh cấu hình này đủ. Theo dõi RAM/CPU và nâng máy
     nếu cần, giữ nguyên concurrency worker.
   - Boot disk 30 GB.
   - VM thường, không dùng Spot cho lần triển khai đầu.
6. Xem dự toán trong Console trước khi tạo. Tính thêm disk, IPv4, egress và logs;
   dịch vụ Supabase/AI ngoài GCP tính riêng.
7. Gắn external IPv4 tĩnh và trỏ DNS bản ghi A của hostname API tới IP này.
8. Tạo firewall rule áp dụng riêng cho VM: cổng 80 cho cấp chứng chỉ HTTPS;
   cổng 443 giới hạn IP công khai của nhóm thử nghiệm trong lần đầu. Truy cập SSH
   qua cơ chế quản trị GCP; không mở SSH cho toàn Internet.
   Không mở 8000 hoặc 6379 ra Internet.

Hướng dẫn chính thức:
[tạo VM](https://docs.cloud.google.com/compute/docs/instances/create-start-instance),
[credit](https://docs.cloud.google.com/free/docs/free-cloud-features),
[budget](https://docs.cloud.google.com/billing/docs/how-to/budgets).

## 3. Chuẩn bị Linux và source

Nhấn SSH trên VM. Những lệnh trong bước này chạy **trên Ubuntu**, không phải
PowerShell trên máy Windows.

Cài Docker Engine và Compose plugin theo phần “Install using the apt repository”
trong [hướng dẫn Docker cho Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
Sau đó kiểm tra:

```bash
sudo docker version
sudo docker compose version
sudo systemctl enable --now docker
sudo apt-get update
sudo apt-get install -y git
```

Clone repository vào `~/DeepLingo` bằng quyền đọc repository. Với repo private,
dùng deploy key riêng; không nhúng access token vào URL clone.

```bash
git clone <REPO_URL> ~/DeepLingo
cd ~/DeepLingo
git checkout --detach <COMMIT_SHA_DA_CHON>
cd backend
```

Thay các giá trị trong dấu `<...>` trước khi chạy. Không copy venv Windows lên
Linux; image sẽ cài dependencies từ requirements hiện có.

Dockerfile và các file compose đã nằm trong repo; không sửa chúng trực tiếp trên VM.
Thay đổi topology đi qua commit được review.

## 4. Tạo image backend

`backend/Dockerfile` và `backend/.dockerignore` đã có trong repo. Image dùng
Python 3.13 (khớp venv đã chạy test) và cài từ `requirements.lock` với
`--no-deps` rồi `pip check`, nên phiên bản trên VM giống bản đã test.
Khi đổi `requirements.txt`, tạo lại `requirements.lock` và chạy lại full suite.

Build và ghi nhận dependencies đã resolve:

```bash
sudo docker build -t deeplingo-backend:rev1 .
sudo docker run --rm --entrypoint python deeplingo-backend:rev1 -m pip freeze
```

`rev1` là nhãn của bản triển khai đầu tiên; dùng nhãn mới cho mỗi bản sau.
Dependencies đã được khóa trong `requirements.lock`, nhưng base image chưa cố
định digest. Giữ image đã build để rollback thay vì dựa vào rebuild.
Image tối thiểu này không cài optional tokenizer hay công cụ media bổ sung;
kiểm tra pipeline/ngôn ngữ thực tế trước khi tuyên bố hỗ trợ.

## 5. Cấu hình backend và các tiến trình

Tạo thư mục runtime **ngoài source checkout**, hạn chế quyền đọc:

```bash
mkdir -p ~/deeplingo-runtime
chmod 700 ~/deeplingo-runtime
cd ~/deeplingo-runtime
```

Tạo file env backend tại đây (ví dụ `backend.env`). Điền đúng project non-production và cấu hình Gemini
hiện tại. Mẫu dưới dành cho Gemini dùng API key; nếu Gemini đang chạy qua Vertex,
dùng biến thể Vertex được mô tả bên dưới. Đây là mẫu cần thay, không phải
credentials sử dụng được:

```dotenv
ENVIRONMENT=staging
PORT=8000
REDIS_URL=redis://redis:6379/0
BACKEND_CORS_ORIGINS=https://FIREBASE_PROJECT_ID.web.app
SUPABASE_URL=https://SUPABASE_PROJECT_REF.supabase.co
SUPABASE_KEY=SUPABASE_ANON_KEY_CUA_PROJECT
SUPABASE_SERVICE_ROLE_KEY=SERVICE_ROLE_KEY_CHI_O_SERVER
SUPABASE_JWT_VERIFICATION_MODE=jwks
SUPABASE_JWT_AUDIENCE=authenticated
AI_PROVIDER=gemini
AI_PROVIDER_DEPLOYMENT_CLASS=production_eligible
AI_PROVIDER_MODE=openai_compatible
AI_STRUCTURED_OUTPUT_MODE=json_schema
AI_BASE_URL=HTTPS_ENDPOINT_GEMINI_DANG_SU_DUNG
AI_API_KEY=GEMINI_API_KEY_CHI_O_SERVER
AI_MODEL_NAME=MODEL_GEMINI_DANG_SU_DUNG
```

Các tên env này lấy từ [Settings hiện tại](../../backend/app/platform/config.py).
`SUPABASE_KEY` dùng anon key phù hợp SDK backend hiện có; browser chỉ dùng
publishable/anon key. Service-role key và AI key chỉ ở server.
Giữ auth verification mode tương thích với signing key thực tế; `jwks` ở trên
áp dụng cho project dùng asymmetric signing keys, không tự đổi auth mode nếu
project hiện dùng legacy HS256.

Nếu Gemini hiện dùng qua Vertex, dùng service account gắn với VM và quyền Vertex tối thiểu cần
thiết; đặt `AI_PROVIDER=vertex`, `VERTEX_PROJECT_ID`, `VERTEX_LOCATION` và model
Vertex cụ thể. **Bỏ** `AI_BASE_URL` và `AI_API_KEY`; không tạo key JSON để copy
vào container. Vertex adapter hiện chưa live-qualified; cần gate riêng theo
chính sách AI trước khi sử dụng learner state thật.

Các file topology không chứa secret đã có trong repo ở `backend/deploy/`:
`compose.yaml` (api, worker, Beat, Redis nội bộ, Caddy), `Caddyfile` và
`deploy.env.example`. Compose luôn đặt `REDIS_URL=redis://redis:6379/0`,
nên dòng `REDIS_URL` trong file env bên trên bị bỏ qua. Đổi tên file env bên trên
thành `~/deeplingo-runtime/backend.env`, rồi tạo `deploy.env` từ mẫu:

```bash
cp ~/DeepLingo/backend/deploy/deploy.env.example ~/deeplingo-runtime/deploy.env
nano ~/deeplingo-runtime/deploy.env   # BACKEND_IMAGE, DEEPLINGO_ENV_FILE (đường dẫn tuyệt đối), API_HOSTNAME
dc() { sudo docker compose -f ~/DeepLingo/backend/deploy/compose.yaml --env-file ~/deeplingo-runtime/deploy.env "$@"; }
```

Hàm `dc` dùng cho mọi lệnh compose bên dưới; thêm nó vào `~/.bashrc` nếu muốn giữ.

DNS phải trỏ đúng VM, cổng cấp chứng chỉ phải truy cập được. Caddy quản lý HTTPS
và lưu chứng chỉ trong volume theo [hướng dẫn chính thức](https://caddyserver.com/docs/running#docker-compose).
Web build của dự án yêu cầu API HTTPS; URL HTTP bằng IP VM sẽ không đáp ứng.

```bash
chmod 600 backend.env deploy.env
dc config --quiet
dc up -d
dc ps
```

Chỉ dùng `config --quiet`: output `config` đầy đủ có thể in secrets đã resolve.
Chưa commit các file secrets; không gửi nguyên logs hoặc error bodies ra ngoài.
Xem logs tại VM khi cần:

```bash
dc logs --tail=80 api worker beat
```

Kiểm tra HTTPS từ máy thử nghiệm có IP đã được firewall cho phép, chẳng hạn
PowerShell trên Windows:

```powershell
curl.exe --fail https://api-staging.tenmiencuaban.com/health
```

`/health` hiện không kiểm tra một DB query thực, broker hay worker readiness.
Một response 200 chưa chứng minh pipeline hoạt động. Lỗi không xử lý luôn trả
thông báo chung "Lỗi hệ thống"; chi tiết chỉ có trong log server (`dc logs api`).

Trước khi mở cổng 443 cho mọi IP: tắt đăng ký tự do trong Supabase
(Authentication → Sign In / Providers → "Allow new users to sign up") để người lạ
không thể import video làm tốn chi phí AI, và đặt budget alert cho billing của
Gemini. Chưa có giới hạn số video mới cho mỗi người dùng.

### Nguồn transcript khi chạy trên cloud

YouTube chặn việc lấy caption từ IP cloud (`RequestBlocked`), nên trên VM dùng nguồn
Gemini YouTube-URL: Gemini tự lấy video phía Google. Chỉ cho các ngôn ngữ đã qua
benchmark (hiện là tiếng Anh `en` và tiếng Trung `zh`) và `ENVIRONMENT=development`.
Mặc định trong code là 20 phút từ 2026-10-21, nhưng môi trường dùng thật giữ **15 phút** bằng
`CONTENT_MAX_VIDEO_SECONDS=900` cho tới khi qualification worker trên dev (C-dev) đạt; độ chính xác 20 phút mới đo
với tiếng Anh. Thêm vào file env backend:

```dotenv
CONTENT_TRANSCRIPT_SOURCE=gemini_youtube
AI_TRANSCRIPTION_MODEL=gemini-3.6-flash
YOUTUBE_DATA_API_KEY=KEY_YOUTUBE_DATA_API_CHI_O_SERVER
CONTENT_TRANSCRIPTION_LANGUAGES=en,zh
CONTENT_MAX_VIDEO_SECONDS=900
```

Khi bật hơn một ngôn ngữ mà video không khai báo ngôn ngữ âm thanh trên YouTube,
backend nghe thử tối đa 3 đoạn 60 giây đầu để xác định ngôn ngữ ngay lúc thêm video
(yêu cầu thêm video chậm thêm khoảng 10–20 giây và tốn thêm khoảng một đoạn phiên âm).

`GEMINI_API_KEY` đã có được dùng lại. Tạo `YOUTUBE_DATA_API_KEY` trong Google Cloud
Console: bật **YouTube Data API v3**, tạo API key và giới hạn key chỉ cho API đó.
Thiếu một trong các biến trên thì backend từ chối khởi động. Đổi model phải chạy lại
bộ đánh giá trước. Sau khi đổi env, recreate api, worker và
beat theo quy trình ở bước 9.

## 6. Đưa web lên Firebase Hosting

Vào Firebase Console, thêm Firebase vào **GCP project đã chọn**, ghi nhận project
ID và Hosting site ID; bước này không thay Supabase Auth bằng Firebase Auth.

Trên **máy Windows**, cần Node >=22 theo package.json hiện tại. Tạo file
`.env.production.local` trong `D:\DeepLingo\deeplingo_web`:

```dotenv
VITE_API_BASE_URL=https://api-staging.tenmiencuaban.com/api/v1/v3
VITE_SUPABASE_URL=https://SUPABASE_PROJECT_REF.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_HOAC_ANON_KEY_CUA_PROJECT
```

Không thêm dấu `/` cuối API base URL. Cấu hình trên được nhúng vào bundle lúc
build; sửa env phải build và deploy lại. Không dùng service-role/AI keys trong
bất kỳ biến `VITE_` nào.

Chạy PowerShell:

```powershell
Set-Location D:\DeepLingo\deeplingo_web
npm ci
npm run typecheck
npm test
npm run build
npm run audit:build
npm run check:bundle
npm run test:e2e:deterministic
npm install -g firebase-tools
firebase login
firebase init hosting
```

Nếu browser binaries chưa có, cài bằng `npx playwright install chromium` rồi
chạy lại browser gate. Không bỏ qua failure để deploy.

Trong `firebase init hosting`:

- Chọn **Use an existing project**, chọn đúng project thử nghiệm.
- Public directory: **dist**.
- Configure as a single-page app: **Yes**.
- Automatic builds/deploys with GitHub: **No** cho lần đầu.
- Overwrite `dist/index.html`: **No** nếu được hỏi.

Kiểm tra `firebase.json` có public `dist` và rewrite `**` tới `/index.html`.
Triển khai riêng Hosting:

```powershell
firebase deploy --only hosting --project FIREBASE_PROJECT_ID
```

Mở URL Hosting mà CLI trả về. Nếu site ID khác project ID, dùng URL **thực tế**
cho CORS và Supabase redirect URLs. Firebase Hosting triển khai files build với
CDN/HTTPS theo [quickstart chính thức](https://firebase.google.com/docs/hosting/quickstart).

## 7. Nối đăng nhập và CORS

Trong Supabase project dùng thử, Authentication → URL Configuration:

- Site URL: URL web cloud của môi trường đó.
- Redirect URLs: thêm URL web và URL chính xác `/reset-password`, ví dụ
  `https://FIREBASE_SITE_ID.web.app/reset-password`.
- Nếu dùng chung project development, giữ các localhost redirect URLs cần thiết;
  lưu cấu hình cũ trước khi đổi Site URL để tránh ảnh hưởng người thử nghiệm khác.

Web hiện tạo reset-password redirect từ `window.location.origin`. Vì vậy URL
Firebase/custom domain thực tế phải được allowlist. Xem
[Supabase redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls).

Cập nhật `BACKEND_CORS_ORIGINS` trong `backend.env` thành origin web thực tế,
không kèm path. Có thể liệt kê nhiều origin bằng dấu phẩy. Không dùng wildcard.
Nếu thêm URL preview hoặc custom domain sau này, cấu hình từng origin tương ứng.

Sau khi đổi env, recreate API theo quy trình cập nhật ở bước 9; chỉ `restart`
container không nạp lại env_file mới. Đổi secrets/provider dùng chung thì phải
cập nhật cả API/worker/Beat qua quy trình drain.

## 8. Kiểm tra trước khi coi là dùng được

Chạy full backend regression trên máy Windows ở commit triển khai:

```powershell
Set-Location D:\DeepLingo\backend
.\venv\Scripts\python.exe -m pytest -q
```

Đây là lệnh cần chạy, không phải kết quả đã có. Unit tests không cần live AI.

Trong phạm vi môi trường non-production và tài khoản thử nghiệm đã cho phép:

1. Web load được; refresh trực tiếp một route vẫn hoạt động.
2. Login/logout, reload session và reset password hoạt động.
3. API thiếu/sai token và truy cập tài nguyên của learner khác bị từ chối.
4. Import một video fixture đã chọn; kiểm tra worker nhận công việc, database
   thể hiện tiến trình và kết quả chuẩn bị. Beat phải tiếp tục reconcile.
5. Practice: materialize activity, gửi câu trả lời, thấy kết quả chấm.
6. Review/Progress phản ánh state đã commit, không chỉ request trả 200.
7. Gián đoạn rồi thử lại Attempt phải dùng UUID/raw response ban đầu.
8. Kiểm tra browser bundle/network không lộ secrets hoặc hidden answers.

Dùng test learners và fixture manifest riêng. Cleanup chỉ xóa dữ liệu test thuộc
manifest; không xóa shared global content. Không gửi live provider requests hoặc
chạy fault injection trên một database chưa được cho phép dùng thử.

Các smoke trên không thay thế qualification của môi trường mới. P0/P1/P2,
worker kill/replacement, recovery, stale/duplicate fencing và finite retry cần
gate riêng theo [content worker runbook](content-worker.md).
Provider cũng cần schema, positive/negative và injection gates theo chính sách AI.
Không tuyên bố production-ready dựa trên qualification development cũ.

## 9. Cập nhật khi backend/web vẫn sửa liên tục

Mỗi lần cập nhật: chọn commit, chạy checks tương ứng, build một bản mới, kiểm tra
trên cloud rồi giữ nhãn bản cũ. Không sửa trực tiếp runtime code trên VM.

Ví dụ backend bản tiếp theo, sau khi checkout commit đã chọn trong source sạch:

```bash
cd ~/DeepLingo/backend
sudo docker build -t deeplingo-backend:rev2 .
cd ~/deeplingo-runtime
```

Đối với thay đổi chỉ ở API, giữ worker/Beat nguyên nếu image cũ vẫn tương thích;
đổi `deploy.env` sang `deeplingo-backend:rev2`, rồi:

```bash
dc up -d --no-deps api
```

Nếu thay đổi cả worker/contract/config dùng chung, tạm dừng thao tác import mới,
chờ và xác nhận không còn running intents, dừng Beat rồi worker/API. Với single
VM, có downtime; thông báo cho nhóm thử nghiệm. Không để worker cũ/mới xử lý
lẫn trong cutover đầu tiên:

```bash
dc stop beat
dc stop worker api
```

Đổi `deploy.env` sang image mới và khởi động lại **chỉ** các tiến trình backend:

```bash
dc up -d --no-deps api worker beat
```

Nếu không xác nhận được công việc đang chạy và khả năng drain, dừng cutover để
đối chiếu runbook; không kill/reset/purge để ép sang bước sau.

Web: chạy lại checks/build ở bước 6, rồi `firebase deploy --only hosting` vào đúng
project. Khi API thay đổi, giữ tương thích với browser còn cache bản web cũ.

Rollback backend: kiểm tra image cũ còn tồn tại, đổi `deploy.env` về `rev1`,
recreate các tiến trình bị ảnh hưởng với cùng quy trình drain. Rollback web dùng
release Hosting trước. **Rollback code không rollback database.** Schema changes
cần một kế hoạch migration tiến tới và tương thích riêng; không đưa migration
vào startup container hay mỗi lần deploy.

Sau lần triển khai thủ công đầu tiên thành công mới chuẩn hóa CI/CD: chạy checks,
build image gắn commit SHA, lưu registry, deploy commit được chọn và smoke.
Giữ thao tác phê duyệt khi có live schema mutation hoặc production release.

## Giới hạn và bước tiếp theo

Một VM là một điểm lỗi chung; restart/recreate có thể gây downtime. Chưa có số
liệu tải để cam kết CPU/RAM, latency hay monthly bill. Ngày 2026-10-08, image đã chạy
full backend suite trong container, và compose đã chạy cục bộ: HTTPS qua Caddy
(chứng chỉ nội bộ cho localhost), worker prefork nhận task Beat, Redis/8000 không
lộ ra ngoài, worker warm shutdown. Chưa kiểm tra chứng chỉ Let's Encrypt thật,
Supabase thật, live provider hoặc real-broker gates trên GCP.

Bước tiếp theo phù hợp là xác định project/hostname/provider và chuẩn hóa bộ
deployment files thành thay đổi được review, rồi xác nhận các gates của môi
trường dùng thử trước khi đưa người dùng thật vào.
