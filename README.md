# AI Scientist — Hệ thống tự động nghiên cứu & viết báo khoa học

Hệ thống đa tác tử (multi-agent) tự động: khảo sát tài liệu trên arXiv → sinh giả thuyết
nghiên cứu → viết từng phần bài báo → **vẽ hình & bảng từ dữ liệu thật** → **xuất PDF hoàn chỉnh
(chèn hình, bảng, trích dẫn đánh số, danh mục tham khảo) bằng ReportLab — thuần Python, không cần
cài LaTeX** → tự bình duyệt (self-review). Có cả giao diện web (FastAPI, streaming real-time)
lẫn CLI.

```
Topic ──▶ LiteratureAgent (arXiv) ──▶ HypothesisAgent ──▶ WriterAgent (6 phần)
                                                                │
                           ┌────────────────────────────────────┤
                           ▼                                    ▼
              Figures (matplotlib, dữ liệu thật)      Tables (dữ liệu thật)   
                           │                                    │
                           └─────────────────┬──────────────────┘
                                              ▼
                      Citation sanitizer ──▶ PDF Service (ReportLab) ──▶ paper.pdf  (luôn có)
                                              │
                                              └─▶ LaTeX source (tuỳ chọn) ──▶ paper.tex, paper_bundle.zip,
                                                                               paper_latex.pdf (nếu có LaTeX)
                                              ▼
                                         ReviewerAgent
```

## Nguyên tắc trung thực khoa học (quan trọng, đọc trước khi dùng)

Hệ thống này **không tự chạy thí nghiệm thật**, nên nó **không được phép bịa ra số liệu kết
quả**. Thiết kế tuân thủ nghiêm 2 quy tắc:

1. **Hình & bảng chỉ vẽ từ dữ liệu THẬT đã có**: số bài báo theo năm, thuật ngữ xuất hiện
   nhiều trong abstract (đếm thật từ kết quả arXiv), bảng so sánh công trình liên quan (tóm
   tắt từ chính các bài đã tìm được) — không có biểu đồ "kết quả thí nghiệm" nào được vẽ.
2. **Phần "Experimental Design" viết ở thì tương lai/đề xuất** ("we will evaluate...", "we
   plan to compare...") và **cấm LLM nêu bất kỳ con số kết quả nào** — đây là kế hoạch đánh
   giá đề xuất, không phải kết quả đã có.
3. **Trích dẫn (`\cite{}`) chỉ được dùng với khoá thật**, lấy từ chính các bài báo đã tải từ
   arXiv. Một bộ lọc (`src/tools/latex_utils.py`) tự động xoá mọi `\cite{khoá-lạ}` mà model
   lỡ bịa ra trước khi đưa vào bản PDF cuối — xem log giai đoạn "Citation Check".

Nếu bạn cần báo cáo kết quả thực nghiệm thật, hãy tự chạy thí nghiệm và **thay nội dung mục
Experimental Design bằng kết quả thật của bạn** trước khi dùng bài báo cho mục đích học thuật
chính thức. Bài do hệ thống này tạo ra là **một bản đề xuất/khảo sát** (research proposal),
không phải báo cáo kết quả.

---

## 1. Cài đặt

```bash
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Xuất PDF — KHÔNG cần cài LaTeX

`paper.pdf` được tạo bởi **PDF Service** (`src/tools/pdf_writer.py`, dùng thư viện **ReportLab**
— thuần Python, cài cùng `pip install -r requirements.txt`). Vì vậy **bạn không cần cài
MiKTeX/TeX Live/tectonic** để có file PDF tải về. PDF Service tự động:

- ghép 6 phần bài báo (Abstract → Conclusion) với tiêu đề, định dạng chuyên nghiệp, số trang;
- chèn **hình** (xu hướng công bố, thuật ngữ phổ biến, sơ đồ pipeline) kèm chú thích "Figure N";
- chèn **bảng** (so sánh công trình liên quan, kế hoạch đánh giá) kèm chú thích "Table N";
- đánh số **trích dẫn [1], [2]...** theo thứ tự xuất hiện, bấm vào số nhảy tới mục tham khảo,
  kèm danh mục **References** đầy đủ (tác giả, tiêu đề, năm, link arXiv);
- hiển thị đúng **tiếng Việt có dấu** và ký hiệu toán (ℝ, Δ, ≥, ≪, d²...) nhờ nhúng font Unicode
  DejaVu Sans (có sẵn trong matplotlib, không cần cài thêm).

**LaTeX giờ chỉ là tuỳ chọn** — dành cho ai cần mã nguồn `.tex` để nộp tạp chí/hội nghị hoặc
chỉnh sửa trên [Overleaf](https://www.overleaf.com). Hệ thống luôn xuất `paper.tex` +
`references.bib` + `paper_bundle.zip` (upload thẳng lên Overleaf). Nếu máy có sẵn
tectonic/latexmk/pdflatex (MiKTeX, TeX Live...), sẽ tạo thêm `paper_latex.pdf` — nếu không thì
bỏ qua, **không ảnh hưởng `paper.pdf`**.

Kiểm tra môi trường:
```bash
python main.py doctor
```
(Nếu nghi ngờ do API key, chạy `python debug.py` — script chẩn đoán cấp thấp gọi thẳng API.)

## 3. Cấu hình

```bash
cp .env.example .env
```

Mở `.env`, điền API key. Mặc định dùng **Groq** (xem mục 4 bên dưới để đổi sang nhà cung cấp khác).

## 4. Chọn nhà cung cấp LLM

Hệ thống dùng `openai` SDK trỏ tới **bất kỳ API nào tương thích chuẩn OpenAI** — chỉ cần đổi
`OPENAI_BASE_URL` + `OPENAI_API_KEY` trong `.env`, không cần sửa 1 dòng code nào.

| Nhà cung cấp | Free tier | Model mạnh đề xuất | `OPENAI_BASE_URL` |
|---|---|---|---|
| **Groq** (mặc định) | Hào phóng, tốc độ rất nhanh | `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` | `https://api.groq.com/openai/v1` |
| **Cerebras** | Free tier tốt, nhanh nhất thị trường | `llama-3.3-70b` | `https://api.cerebras.ai/v1` |
| **Google Gemini** | Free tier rất rộng (qua lớp tương thích OpenAI) | `gemini-2.0-flash` / bản mới hơn nếu có | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| **OpenRouter** | Tổng hợp nhiều model free (`:free` suffix) | tuỳ model đang free tại thời điểm dùng | `https://openrouter.ai/api/v1` |

**Khuyến nghị:** giữ Groq hoặc thử Cerebras trước — cả hai đều có model ≥70B tham số, đủ mạnh
để viết văn phong học thuật mạch lạc và tuân theo chỉ dẫn JSON (cần cho việc sinh bảng/hình có
cấu trúc). Vì các gói free tier thay đổi thường xuyên, hãy kiểm tra trang pricing/limits chính
thức của từng nhà cung cấp tại thời điểm bạn dùng.

### Vì sao không "tự huấn luyện một LLM riêng"?

Đây là lựa chọn **không khả thi** trong phạm vi đồ án vì 3 lý do:

1. **Chi phí tính toán**: huấn luyện một LLM từ đầu đủ mạnh để viết văn bản học thuật mạch
   lạc cần hàng trăm nghìn đến hàng triệu USD tiền GPU và hàng tỷ token dữ liệu — không có
   cách nào làm được trên máy cá nhân hay trong khuôn khổ một đồ án.
2. **Fine-tune một model nhỏ có sẵn** (VD: Llama-3.2-3B) bằng LoRA trên vài nghìn abstract
   arXiv là *khả thi về mặt kỹ thuật*, nhưng kết quả **gần như chắc chắn kém hơn** việc gọi
   thẳng một model 70B+ miễn phí qua Groq/Cerebras — vừa tốn công, vừa tốn GPU, vừa cho ra
   chất lượng thấp hơn.
3. **Không cần thiết**: vấn đề cốt lõi của hệ thống (bịa trích dẫn, bịa số liệu) **không nằm
   ở việc model "chưa đủ mạnh"**, mà nằm ở *kiến trúc* (có dùng RAG/dữ liệu thật không, có lọc
   output không). Bản cập nhật này giải quyết đúng chỗ đó — ở tầng kiến trúc, không phải tầng
   model.

→ Lựa chọn đúng cho phạm vi đồ án là **Option 1 (đổi API)**, và đã được tích hợp sẵn.

## 5. Chạy

### CLI
```bash
python main.py run                        # dùng topic trong config.yaml
python main.py topic "Your research topic here"   # ghi đè topic
python main.py doctor                      # kiểm tra môi trường
```
Kết quả lưu vào `outputs/`: **`paper.pdf`** (bài báo hoàn chỉnh), `paper.tex`, `references.bib`,
`fig_*.png`, `paper_bundle.zip` (cho Overleaf), `paper_latex.pdf` (nếu có LaTeX), `review.md`,
`literature.md`, `hypotheses.md`.

### Web (FastAPI)
Cần MongoDB chạy sẵn (`docker run -p 27017:27017 mongo` hoặc cài local).
```bash
uvicorn backend.main:app --reload --port 8000
```
Mở **http://localhost:8000** — nhập chủ đề, theo dõi tiến trình real-time (SSE) qua 14 giai
đoạn, xem hình/bảng/PDF ngay trên trang, tải `paper_bundle.zip`, xem lại lịch sử các lần chạy.

### Dry-run không tốn API (khuyên chạy trước khi dùng thật)
```bash
python -m unittest tests.test_pipeline_offline -v
```
```bash
python -m unittest tests.test_backend_offline -v     # test luồng FastAPI với DB giả (không cần MongoDB)
```
Các test dùng LLM giả (không gọi mạng, không tốn phí) + dữ liệu arXiv giả để chạy toàn bộ
pipeline và kiểm tra `paper.pdf` được tạo hợp lệ — kể cả tình huống **máy không có LaTeX**.
Cách nhanh nhất để biết môi trường đã sẵn sàng trước khi tốn credit API thật.

---

## 6. Kiến trúc & những gì mới trong bản cập nhật này

| Thành phần | Trước | Sau |
|---|---|---|
| LLM call | Sync (`asyncio.to_thread` bọc ngoài) | **Async thật** (`AsyncOpenAI`), đúng tinh thần FastAPI |
| FastAPI lifecycle | `@app.on_event` (đã deprecated) | **`lifespan` context manager** (chuẩn FastAPI hiện tại) |
| Trích dẫn | `\cite{ref1}` — placeholder không trỏ tới bài nào | **BibTeX key thật** từ metadata arXiv, có bộ lọc xoá key bịa |
| Hình ảnh | Không có | **matplotlib**, vẽ từ dữ liệu arXiv thật (xu hướng công bố, thuật ngữ phổ biến) + sơ đồ pipeline khái niệm |
| Bảng | Không có | Bảng so sánh công trình liên quan + bảng kế hoạch đánh giá (LaTeX `booktabs`) |
| PDF | **Không xuất được** (chỉ có `.tex` string) | **PDF Service (ReportLab)**: `paper.pdf` luôn có, chèn hình/bảng/trích dẫn, hỗ trợ tiếng Việt; LaTeX là tuỳ chọn |
| "Experiments" | Đoạn text hard-code "planned but not yet executed" | Sinh động theo từng giả thuyết, viết đúng thì đề xuất, cấm bịa số liệu |
| Làm sạch LaTeX | Không có — ký tự đặc biệt từ LLM dễ làm vỡ biên dịch | `src/tools/latex_utils.py`: escape, chuyển markdown→LaTeX, cân bằng ngoặc |
| Test | Không có | `tests/test_pipeline_offline.py` — dry-run full pipeline không cần API/mạng |

### Các module mới
- `src/tools/latex_utils.py` — escape ký tự đặc biệt, chuyển markdown→LaTeX, chuẩn hoá Unicode, chống vỡ biên dịch
- `src/tools/bibliography.py` — sinh BibTeX key/entry thật, lọc `\cite{}` không hợp lệ
- `src/tools/visuals.py` — vẽ hình bằng matplotlib (chỉ từ dữ liệu thật)
- `src/tools/tables.py` — sinh bảng LaTeX (`booktabs`/`tabularx`)
- `src/tools/pdf_writer.py` — **PDF Service**: ghép nội dung + hình + bảng + trích dẫn → PDF (ReportLab, font Unicode)
- `src/tools/pdf_compiler.py` — (tuỳ chọn) biên dịch `.tex` → `.pdf` nếu có LaTeX, đóng gói bundle cho Overleaf
- `src/tools/jsonutil.py` — parse JSON "lỏng" từ output LLM (chịu được markdown fence, lời dẫn thừa)

## 7. API endpoints (backend)

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/api/health` | Kiểm tra server + model đang cấu hình |
| POST | `/api/runs` | Tạo 1 lượt chạy mới `{topic, num_papers, max_hypotheses, model}` |
| GET | `/api/runs` | Danh sách lịch sử |
| GET | `/api/runs/{id}` | Chi tiết đầy đủ (papers, sections, bảng, review) |
| GET | `/api/runs/{id}/status` | Trạng thái hiện tại (cho polling) |
| GET | `/api/runs/{id}/stream` | SSE — theo dõi tiến trình real-time |
| GET | `/api/runs/{id}/files` | Danh sách file (tex/bib/png/pdf/zip) |
| GET | `/api/runs/{id}/files/{name}` | Tải/xem file (PDF & ảnh hiển thị inline trên trình duyệt) |

## 8. Xử lý lỗi thường gặp

| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Thiếu OPENAI_API_KEY trong file .env` | Chưa tạo `.env` | `cp .env.example .env` rồi điền key |
| `API key bị từ chối (401)` | Sai key hoặc hết hạn | Kiểm tra lại key đúng nhà cung cấp |
| `Vượt giới hạn miễn phí (429)` | Free tier hết hạn mức | Đợi vài phút, giảm `num_papers`, hoặc đổi provider |
| Không có `paper_latex.pdf` | Máy chưa cài LaTeX (không phải lỗi) | Bỏ qua — dùng `paper.pdf`; cần bản LaTeX thì upload `paper_bundle.zip` lên Overleaf |
| `ModuleNotFoundError: reportlab` | Chưa cài đủ thư viện | `pip install -r requirements.txt` |
| `pymongo.errors.ServerSelectionTimeoutError` | MongoDB chưa chạy | `docker run -p 27017:27017 mongo` hoặc cài local |
| Hình bị thiếu trong PDF | Quá ít bài báo (< 3) để vẽ biểu đồ xu hướng/thuật ngữ có ý nghĩa | Tăng `num_papers`, hoặc chấp nhận bỏ qua hình đó (template tự ẩn nếu thiếu dữ liệu) |

## 9. Giới hạn đã biết

- Không chạy thí nghiệm thật — xem mục "Nguyên tắc trung thực khoa học" ở đầu file.
- `ReviewerAgent` dùng chính LLM để tự chấm — không thay thế được phản biện của con người.
- Trích xuất arXiv chỉ lấy `title/authors/abstract/year` — không phân tích được bảng/hình bên
  trong các bài báo gốc.
- Bảng "so sánh công trình liên quan" rút gọn mỗi ô còn ~90 ký tự để vừa trang A4 — xem chi
  tiết đầy đủ trong phần Related Work (văn xuôi).
