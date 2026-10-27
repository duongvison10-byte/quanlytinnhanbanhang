# Quản lý tin nhắn bán hàng

Backend Flask cho một fanpage Facebook: xác minh webhook, nhận sự kiện tin nhắn/bình luận, lưu SQLite hoặc MySQL và chống ghi trùng. Chưa có giao diện hộp thư, quản lý đơn hàng hoặc AI.

## Chạy thử nhanh không cần Docker

Trong terminal Codespace của kho này, chạy một lệnh:

```sh
git pull --ff-only && ./scripts/quickstart.sh
```

Lệnh cài phụ thuộc, chỉ hỏi App Secret qua lời nhắc ẩn nếu chưa có, rồi khởi động lại SQLite và đăng ký callback ứng dụng với Meta. Giữ cổng **8000 → Port Visibility → Public** trong tab **Ports**. Helper lấy tên máy từ `CODESPACE_NAME`, không cần sao chép URL hoặc mã xác minh. Nó không yêu cầu Page Access Token, không tự gửi tin, và chỉ báo đăng ký thành công khi Meta chấp nhận. Đăng ký các sự kiện của fanpage vẫn là bước riêng sau đó.

Chế độ SQLite chạy trực tiếp bằng Python 3.12+, phù hợp để thử một máy chủ nhận tin nhắn và bình luận. Dùng cách này nếu Codespace chưa có Docker hoặc đang cần khôi phục cấu hình container:

```sh
./scripts/setup.sh
./scripts/start.sh --sqlite
./scripts/start.sh status
```

Lựa chọn SQLite được lưu trong `.local/storage-engine`; các lần chạy `start.sh`, `start.sh status` và `start.sh stop` tiếp theo giữ chế độ này. Dữ liệu nằm trong `.local/webhooks.sqlite3` và không được đưa lên GitHub. `SQLITE_PATH` có thể chỉ định một file khác. Chuyển giữa hai chế độ sẽ khởi động lại Flask do script quản lý; script không dừng MySQL khi chạy ở chế độ SQLite. Đây là bản thử trên một máy, không tự chuyển dữ liệu giữa SQLite và MySQL. Muốn quay lại MySQL, dùng `./scripts/start.sh --mysql` khi Docker Compose đã sẵn sàng.

Để nhận webhook thật, vẫn cần App Secret đúng, URL HTTPS công khai và mã xác minh khớp với Meta. Có thể nhập App Secret qua lời nhắc ẩn bằng `python3 scripts/generate-local-env.py --set-app-secret`, rồi chạy `./scripts/start.sh stop` và `./scripts/start.sh`. **Nhận sự kiện không cần Page Access Token**; token chỉ cần cho các thao tác gọi Meta như đăng ký qua script hoặc gửi trả lời. Không chuyển token sang Codespaces chỉ để nhận tin.

Nếu muốn dùng Docker feature đã khai báo, mở **Ctrl+Shift+P → Codespaces: Rebuild Container → Rebuild**. Nếu rebuild thất bại, xem lỗi đầu tiên trong `creation.log`; không cài thêm Docker thủ công vào container khôi phục.

## Bản thử bằng GitHub Codespaces

Đã chuẩn bị `.devcontainer/devcontainer.json` cho Python 3.12 và Docker. Cấu hình này chưa được chạy trong một Codespace thật. Khi dùng Codespaces, kiểm tra hạn mức miễn phí trong tài khoản GitHub trước khi tạo máy; thời gian và dung lượng vượt hạn mức có thể bị tính phí.

Các bí mật của môi trường Codex không tự chuyển sang Codespaces. Đặt `META_APP_SECRET` qua cài đặt Codespaces secrets của tài khoản GitHub hoặc lời nhắc ẩn ở trên. Chỉ thêm `META_PAGE_ACCESS_TOKEN` nếu cần gọi Meta từ Codespace. Với Codespaces secrets, cho phép kho này sử dụng rồi khởi động lại Codespace. Không ghi giá trị vào mã nguồn. `META_PAGE_ID` đã có giá trị mặc định cho fanpage; mã xác minh và mật khẩu MySQL được tạo riêng trong `.env` bị Git bỏ qua.

Nên đặt Codespaces secrets cần dùng trước khi tạo máy để tránh phải khởi động lại. Sau khi mã đã được đưa lên GitHub, mở **Code → Codespaces → Create codespace on main**. Setup và khởi động backend sẽ chạy tự động ở chế độ đã lưu, mặc định MySQL với máy mới. Có thể chuyển sang SQLite bằng lệnh ở trên. Trong tab **Ports**, bấm chuột phải cổng **8000 → Port Visibility → Public**, rồi lấy địa chỉ HTTPS được GitHub cấp và thêm `/webhook`. Tổ chức có thể giới hạn quyền mở cổng Public.

Lưu URL HTTPS đầy đủ kết thúc bằng `/webhook` vào `.local/public-webhook-url`, rồi chạy `.venv/bin/python scripts/connect-meta-webhook.py`. Lệnh này kiểm tra readiness và xác minh công khai trước khi đăng ký callback với Meta; nó giữ nguyên callback khác đã tồn tại. `.venv/bin/python scripts/connect-meta-webhook.py --status` chỉ đọc trạng thái.

Các đường tunnel trực tiếp trong môi trường Codex hiện tại đã được thử nhưng chưa hoạt động: Cloudflare bị từ chối kết nối trực tiếp, còn Dev Tunnels không xác minh được chứng thư qua proxy dù đã dùng CA bundle của máy. Chưa tạo được URL công khai và chưa đăng ký webhook trên Meta bằng các đường này. Hướng dẫn tunnel dưới đây chỉ dùng ở môi trường có kết nối tương thích; không tắt xác minh TLS để khắc phục.

## Chạy trong môi trường phát triển

Cần Python 3.12+; chế độ MySQL cần thêm Docker và Docker Compose. Mỗi tác vụ cloud đã có môi trường riêng; dùng checkout hiện có, không cần tạo Git worktree.

```sh
./scripts/setup.sh
./scripts/start.sh
./scripts/start.sh status
```

Setup tạo `.env` riêng tư với quyền đọc/ghi chỉ cho chủ file. Mật khẩu MySQL và mã xác minh webhook được tạo tự động, giữ nguyên khi chạy lại. `META_PAGE_ACCESS_TOKEN` đã được nền tảng cung cấp qua biến môi trường sẽ được dùng trực tiếp, không sao chép vào file.

Ở chế độ MySQL, MySQL chỉ mở cổng nội bộ 3307; Flask chỉ lắng nghe cổng nội bộ 8000 trong cả hai chế độ. Dữ liệu MySQL nằm tại `MYSQL_DATA_DIR` trong `.env` (mặc định `.local/mysql`). Tất cả cấu hình bí mật, dữ liệu và log cục bộ đã được Git bỏ qua. Khi đổi mật khẩu của một MySQL đã khởi tạo, cần đổi cả tài khoản trong MySQL; thay `.env` riêng lẻ không đổi mật khẩu trong dữ liệu cũ.

```sh
./scripts/start.sh stop
```

Lệnh dừng giữ nguyên dữ liệu. Các tiến trình cần khởi động lại sau khi khôi phục một môi trường cloud: chạy lại `./scripts/start.sh`.

## App Secret và webhook Meta

App Secret thật phải lấy từ **Meta Developers → Cài đặt ứng dụng → Thông tin cơ bản**. Có thể nhập từ terminal tương tác bằng:

```sh
python3 scripts/generate-local-env.py --set-app-secret
```

Hoặc cung cấp `META_APP_SECRET` như biến môi trường trực tiếp của máy chủ. Đây phải là giá trị thật vì ứng dụng dùng nó tính HMAC cục bộ, không phải mã đại diện được proxy thay thế khi gọi API. Không gửi App Secret, token hay file `.env` lên GitHub hoặc chat. Sau khi cập nhật cấu hình, dừng rồi khởi động lại Flask.

`GET /healthz` kiểm tra tiến trình. `GET /readyz` kiểm tra các điều kiện nhận webhook; nếu chưa có App Secret thì ứng dụng chưa sẵn sàng. Endpoint Meta là `/webhook`: GET kiểm tra mã xác minh; POST chỉ nhận sự kiện có chữ ký Meta hợp lệ. Mã xác minh đặt trong `META_VERIFY_TOKEN` phải khớp giá trị nhập trong Meta Developers.

Các sự kiện cần cấu hình sau khi máy chủ công khai hoạt động: `messages`, `messaging_postbacks` và `feed` cho bình luận. Tài khoản, quyền Trang và trạng thái xét duyệt Meta quyết định phạm vi chạy với khách thật. Ứng dụng không tự gửi tin nhắn thật khi khởi động hoặc kiểm tra sức khỏe.

Nhân viên có thể chủ động gửi một câu trả lời bằng lệnh sau, với ID khách theo phạm vi Trang lấy từ sự kiện tin nhắn:

```sh
.venv/bin/python -m flask --app app send-message --recipient-id PAGE_SCOPED_ID --text 'Nội dung trả lời'
```

Chỉ chạy khi thực sự muốn gửi tin và đang trong cửa sổ nhắn tin Meta cho phép. Lệnh này gọi Meta thật; các lệnh setup, khởi động và kiểm thử không tự gọi lệnh gửi.

## Kiểm thử

```sh
.venv/bin/python -m pip install --requirement requirements-dev.txt
.venv/bin/python -m pytest
```

Các kiểm thử dùng sự kiện và kết nối giả lập, không gửi tin hoặc gọi Meta thật.

## Chạy bằng container và đưa lên máy chủ

Có thể chạy thêm app container bằng:

```sh
docker compose --profile app build app
docker compose --profile app run --rm app flask --app app init-db
docker compose --profile app up --detach --wait
```

Dừng Flask chạy bằng script trước khi dùng app container để tránh trùng cổng. Cung cấp token Trang, App Secret và mã xác minh bằng cài đặt bảo mật của máy chủ. MySQL được truy cập qua mạng riêng giữa các container.

Trong môi trường cloud hiện tại có proxy TLS, thay lệnh build ở trên bằng lệnh sau để dùng bundle CA đã được máy chủ tin cậy:

```sh
BUILDX_CONFIG=/tmp/quanlytinnhanbanhang-buildx docker build \
  --secret id=build_ca,src=/etc/ssl/certs/ca-certificates.crt \
  --tag quanlytinnhanbanhang-app .
```

CA chỉ được gắn vào bước build, không được lưu trong image; xác minh TLS vẫn bật. Tag này khớp image mặc định của Compose. Các lệnh init-db và khởi động ở trên dùng image đã build. Trên hosting thông thường, `docker compose --profile app build app` dùng trust store của image. Nếu chọn chạy app container qua proxy TLS, cần cung cấp CA tin cậy cho container lúc chạy; quy trình `scripts/start.sh` mặc định chạy Gunicorn trên host và dùng trust store sẵn có của môi trường.

URL webhook công khai chưa được tạo bởi các lệnh trên. Cần một VPS hoặc dịch vụ hosting có HTTPS, tên miền phù hợp và reverse proxy chuyển tiếp `/webhook` vào app. Sau khi có URL thực, nhập URL đó và mã xác minh vào Meta Developers, đăng ký sự kiện cho fanpage, rồi kiểm tra nhận/lưu sự kiện trước khi bật trả lời khách.

## URL HTTPS tạm thời để chạy thử

Khi backend trả `HTTP 200` ở `/readyz`, có thể dùng Cloudflare Quick Tunnel để thử webhook mà chưa cần tài khoản hosting hay tên miền:

```sh
python3 scripts/install-cloudflared.py
./scripts/tunnel.sh start
./scripts/tunnel.sh status
```

Installer tải bản Linux amd64 chính thức `2026.10.4` từ GitHub của Cloudflare và kiểm tra SHA-256 trước khi cho phép thực thi. Xác minh TLS vẫn bật. Mã xác minh webhook và App Secret không được đưa vào lệnh hoặc log tunnel. Script chỉ báo thành công sau khi Cloudflare đăng ký kết nối, đồng thời ghi URL callback có đuôi `/webhook` vào `.local/public-webhook-url`; vẫn cần kiểm tra HTTP từ bên ngoài. Đăng ký callback và các sự kiện trong Meta là bước riêng, không tự xảy ra khi mở tunnel.

```sh
./scripts/tunnel.sh stop
```

URL này công khai, tạm thời và đổi khi tạo tunnel mới; nó ngừng hoạt động khi tiến trình dừng hoặc môi trường cloud không còn chạy. Không có cam kết thời gian hoạt động; Quick Tunnel giới hạn 200 yêu cầu đồng thời và không hỗ trợ SSE. Khi khởi động lại môi trường, chạy lại backend rồi tạo tunnel mới, kiểm tra URL mới và cập nhật callback Meta. Đây là cách thử nghiệm, không phải hosting ổn định cho khách thật.

Cloudflared dùng kết nối `http2` ra Cloudflare trên TCP cổng 7844. Nếu môi trường chỉ cho phép HTTPS qua proxy, kết nối có thể bị chặn dù tải binary thành công; script sẽ dừng tunnel chưa kết nối và giữ thông báo lỗi trong `.local/cloudflared.log`. Không tắt xác minh TLS để xử lý lỗi mạng. Tham khảo [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) và [mã nguồn phát hành chính thức](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.4).
