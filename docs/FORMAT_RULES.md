# Quy tắc trình bày rút ra từ bài mẫu (Neural Collaborative Filtering, WWW 2017) và đối chiếu

Nguồn: `1708_05031v2.pdf`. "Trang" là trang trong PDF mẫu. Cột cuối cho biết hệ thống hiện thực hóa thế nào.

| # | Quy tắc quan sát được | Trang | Hiện thực trong hệ thống |
|---|---|---|---|
| 1 | Hai cột; tiêu đề và khối tác giả trải rộng toàn trang | 1 | `\twocolumn` + `\@maketitle` tự định nghĩa (template) / frame tiêu đề riêng (ReportLab) |
| 2 | Tiêu đề: sans-serif **đậm**, căn giữa, ~15pt; có dấu `*` trỏ chú thích tài trợ | 1 | `\sffamily\bfseries`, `paper.funding_note` → `\thanks` / chú thích cuối cột trái |
| 3 | Tác giả xếp **3 người/hàng**, căn giữa: tên (sans lớn), đơn vị, quốc gia, email | 1 | `_authors_tex()` (3 `\parbox` mỗi hàng); `paper.authors[]` có `name, affiliation, country, email` |
| 4 | Thân bài Times ~9pt, justify, thụt đầu dòng ~9pt | 1–8 | `\usepackage{times}`, `\normalsize = 9/11pt` |
| 5 | `ABSTRACT` (viết hoa, đậm) và `Keywords` (đậm, KHÔNG viết hoa) nằm ở **cột trái**, ngay dưới tiêu đề | 1 | `\section*{Abstract}` (tự viết hoa) + `\subsection*{Keywords}` |
| 6 | Đề mục cấp 1: `1.  INTRODUCTION` — số Ả Rập, VIẾT HOA, đậm, căn trái (không căn giữa) | 1 | `\section` định nghĩa lại (`\MakeUppercase`) |
| 7 | Cấp 2: `3.1 General Framework` — đậm, chữ thường; cấp 3: `3.1.1 Learning NCF` — **đậm nghiêng** | 3 | `\subsection`, `\subsubsection` định nghĩa lại; LLM viết `## Title` / `### Title`, số mục tự động |
| 8 | Thứ tự: Introduction → Preliminaries → (Method) → Experiments → **Related Work** → Conclusion and Future Work → Acknowledgement → References | 1–8 | `paper.related_work_position: after` (mặc định); đổi `before` nếu muốn Related Work sau Introduction |
| 9 | Introduction: 4 phần, kết thúc bằng "The main contributions of this work are as follows." + danh sách **đánh số** | 1–2 | `WriterAgent.write_introduction` |
| 10 | Công thức đánh số `(3)` căn lề phải; ký hiệu được giải thích ngay sau công thức (`where P ∈ ... denotes ...`) | 3 | `equation`/`align` + quy tắc trong STYLE của WriterAgent |
| 11 | Hình: chú thích **dưới**, dạng `Figure 2: …` (đậm, sans, ~8.5pt); ngắn thì căn giữa, dài thì justify; hình nhiều ô có nhãn (a)(b)(c)(d) | 2–3, 5–6 | `caption` package `font={bf,sf}, labelsep=colon, singlelinecheck`; ReportLab: `CapC`/`Cap` |
| 12 | Bảng: chú thích **trên**, dạng `Table 1: …` (đậm, sans); kẻ ngang kiểu booktabs; giá trị tốt nhất **in đậm** | 4–6 | `grid_table_tex()` (booktabs, caption trên, best in đậm) |
| 13 | URL dataset/code để ở **footnote** | 2, 4 | LLM dùng `\footnote{\url{…}}` chỉ với URL do bạn cung cấp (`results.json: setup.dataset_urls`) |
| 14 | Trích dẫn dạng `[31, 46]` | 1 | `\usepackage{cite}` |
| 15 | REFERENCES đánh số, **sắp theo họ tác giả đầu**, dạng `[n] A. B. Author, C. Author. Title. In VENUE, year.`, chữ nhỏ | 8–9 | `\bibliographystyle{abbrv}` (cùng cách xếp/định dạng); ReportLab tự sắp theo họ |
| 16 | Experiments: mở đầu bằng câu hỏi **RQ1–RQ3**; `4.1 Experimental Settings` có chú thích đậm chạy liền *Datasets. / Evaluation Protocols. / Baselines. / Parameter Settings.*; `4.2 Performance Comparison (RQ1)`; các mục sau trả lời RQ2, RQ3 | 5–7 | `write_experiments_intro/setup`, `write_exp_comparison/ablation/sensitivity` |
| 17 | Không có số trang; không có dòng "Draft/TBD" | 1–9 | `\pagestyle{empty}`; cảnh báo chỉ nằm ở `TODO.md` và log |

## Đối chiếu bản cũ (IEEE) với bản hiện tại

| Điểm | Bản cũ | Bản mới | Giống mẫu? |
|---|---|---|---|
| Lớp tài liệu | IEEEtran | article hai cột mô phỏng bài mẫu | ✔ |
| Đề mục | `I. INTRODUCTION`, `A.` | `1. INTRODUCTION`, `2.1`, `3.1.1` | ✔ |
| Caption | `Fig. 1.` / `TABLE III` | `Figure 1:` / `Table 1:` đậm sans | ✔ |
| Thứ tự mục | Related Work sớm | Related Work sau Experiments | ✔ |
| Tham khảo | thứ tự xuất hiện, IEEEtran | thứ tự chữ cái, `abbrv` | ✔ |
| Dòng "Draft … TBD" in lên PDF | có | **không có** (chỉ ở TODO.md) | ✔ |
| Experiments | Setup + Results chung | 4.1 Settings / 4.2 RQ1 / 4.3 RQ2 / 4.4 RQ3 | ✔ |

## Chỗ còn khác bài mẫu (cố ý hoặc chưa làm)

- **Khổ giấy**: bài mẫu là US Letter, hệ thống dùng A4 theo yêu cầu của bạn.
- **Lớp `acmart`**: không dùng. `acmart sigconf` (font Libertine, tiêu đề/đề mục kiểu khác) trông KHÔNG giống bài mẫu, còn bài mẫu dùng mẫu ACM cũ với Times. Template tự chứa chạy được trên mọi máy và Overleaf. Nếu nơi nộp bài bắt buộc `acmart`, cần chuyển nội dung sang lớp đó (nội dung `.tex` giữ nguyên, chỉ đổi preamble/tiêu đề).
- Khối bản quyền ACM / logo CC ở cuối cột trái trang 1, ô viền màu quanh liên kết trích dẫn (do bản arXiv), watermark arXiv: **không** có.
- Font: Times (`times`) và Helvetica (`times` kéo theo) — gần với Nimbus của bản mẫu nhưng chưa trùng từng chi tiết kerning/khoảng cách.
- Đường PDF dự phòng ReportLab dùng font DejaVu Serif (rộng hơn Times) và không có chú thích cuối trang thật: `\footnote{..}` hiện thành "(...)" trong dòng.
