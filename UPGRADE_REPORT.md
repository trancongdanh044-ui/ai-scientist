# Báo cáo nâng cấp

## Cải tiến chính

- Giới hạn đồng thời, TPM và RPM cho mọi request LLM; mặc định Groq dùng 80% của 8.000 TPM.
- Ước lượng cả input/output, ưu tiên giữ chỉ dẫn, phương pháp, kết quả, DOI và bằng chứng khi rút gọn prompt.
- Retry hữu hạn cho 413, 429, timeout và lỗi kết nối với exponential backoff + jitter.
- Cache request giống nhau theo model/prompt/temperature và thống kê request, retry, cache hit, input/output token.
- Phân loại lỗi có thể phục hồi; lưu checkpoint từng phần bài báo ngay sau khi sinh thành công.
- Không bắt buộc prefix `gsk_`, nhờ đó vẫn dùng được proxy/API tương thích OpenAI và mock test an toàn.
- Bổ sung toàn bộ biến giới hạn vào `config.yaml` và `.env.example`.
- Sửa output script Kaggle tương thích Windows console không UTF-8.
- Bổ sung tạm dừng/tiếp tục nghiên cứu tại ranh giới an toàn giữa các giai đoạn.
- Bổ sung xoá vĩnh viễn một lịch sử nghiên cứu, gồm checkpoint, tài liệu, tệp và kết quả liên quan.
- Loại bỏ URI MongoDB chứa thông tin xác thực từng bị hard-code và không còn ghi URI vào log.

## Cài đặt Windows

```powershell
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
uvicorn backend.main:app --reload --port 8000
```

Mở `http://localhost:8000`. MongoDB mặc định ở `mongodb://localhost:27017`.

## Cấu hình Groq 8.000 TPM

Giữ các giá trị: `LLM_TPM_LIMIT=8000`, `LLM_RPM_LIMIT=20`, `LLM_SAFETY_RATIO=0.80`,
`LLM_MAX_OUTPUT_TOKENS=1600`, `LLM_MAX_CONCURRENCY=1`, `LLM_MAX_ATTEMPTS=3`.

## Kiểm thử

- Bộ test offline xác minh pipeline, backend, PDF dự phòng, citation/number guard, checkpoint thí nghiệm và lỗi input.
- Test mới xác minh context compaction giữ bằng chứng và cache tránh request trùng lặp.
- Không gọi Groq thật trong test để không tiêu tốn token.
- Test LaTeX native được skip nếu máy chưa cài LaTeX; ReportLab fallback đã được kiểm thử.

## Giới hạn còn lại

- Checkpoint giữ toàn bộ phần đã hoàn thành nhưng thao tác tiếp tục tự động đúng từ bước lỗi chưa được mở thành API riêng.
- Cache hiện ở bộ nhớ tiến trình; khởi động lại server sẽ làm trống cache.
- Chất lượng nội dung cuối vẫn phụ thuộc tài liệu truy xuất được và cần tác giả kiểm duyệt trước khi công bố.
