# Giảm lỗi Groq 413 / 429

- `config.yaml`: giảm `llm.max_tokens` từ 4000 xuống 1600.
- `src/llm.py`: ước lượng token, rút gọn phần giữa của prompt quá dài, dự trữ tối đa 80% TPM, tự xếp hàng các request trong **cùng tiến trình**, thử lại tối đa 3 lần khi gặp 413/429/lỗi mạng.
- `.env`: có thể thêm `LLM_TPM_LIMIT=8000` và `LLM_MAX_OUTPUT_TOKENS=1600`. Nếu vẫn gặp giới hạn, thử `LLM_TPM_LIMIT=6000` và `LLM_MAX_OUTPUT_TOKENS=1200`.

**Lưu ý:** Groq có thể tính token khác ước lượng, và giới hạn có thể chia sẻ với ứng dụng khác dùng cùng API key. Bộ điều tiết này chỉ dùng trong một tiến trình Python; nhiều worker/server khác nhau không dùng chung ngân sách. 413/429 vẫn có thể xảy ra, nhưng sẽ được thử lại có giới hạn. Khi prompt bị rút gọn, một phần tài liệu ở giữa có thể mất; hãy kiểm tra chất lượng nội dung nghiên cứu. Đừng chạy nhiều phiên nghiên cứu đồng thời bằng cùng API key nếu cần tránh TPM.
