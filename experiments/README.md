# Chạy thí nghiệm thật để có phần Experiments

Hệ thống sinh bài **không tự chạy thí nghiệm của bạn**. Mọi con số trong bảng/hình/lời văn chỉ lấy từ `results.json`.
Quy trình:

1. **Kiểm tra đường ống** (offline, ~1 phút, dữ liệu sklearn có sẵn — chỉ để chắc mọi thứ chạy):
   ```bash
   pip install -r experiments/requirements-exp.txt
   python experiments/run_experiments.py --demo --quick     # ghi results.demo.json (+ _raw.csv)
   ```
   File demo/`--quick` mang cờ `_demo`/`_quick` và bị hệ thống **từ chối** nạp vào bài báo thật.

2. **Viết task của bạn** (xem docstring đầu `run_experiments.py`, hàm `demo_task()` là ví dụ đầy đủ):
   một file `my_task.py` định nghĩa `get_task(quick)`: dataset (loader theo seed), baseline và phương pháp đề xuất
   (`fn(data, seed) -> {metric: value}`), ablation, độ nhạy theo siêu tham số, thống kê dữ liệu, URL dataset.
   Siêu tham số của mọi phương pháp phải được chọn trên tập **validation**, không phải tập test.

3. **Chạy thật** (≥ 3 seed, tốt nhất 5):
   ```bash
   python experiments/run_experiments.py --task my_task.py --seeds 5 --out results.json
   ```
   Runner ghi `results.json` (mean ± std, paired t-test giữa phương pháp đề xuất và từng baseline trên các seed,
   ablation, độ nhạy) và `results_raw.csv` (từng seed, để tái lập và kiểm toán).

4. **Sinh lại bài báo**: `python main.py` — bảng, hình, dấu † (p < 0.05) và lời bình được dựng từ `results.json`.
   Câu nào chứa số không có trong file bị xoá; xem `outputs/TODO.md`.

Nguyên tắc: không chọn seed, không bỏ lần chạy xấu, không sửa số bằng tay. Nếu phương pháp đề xuất không hơn
baseline, bài báo phải báo cáo đúng như vậy (và bạn nên thảo luận nguyên nhân trong 4.2).

---

## Chạy trên Kaggle (máy bạn không có GPU)

Máy bạn chỉ đóng gói và gửi đi; thí nghiệm chạy trên máy của Kaggle. Hạn mức GPU và thời gian một phiên của Kaggle thay đổi
theo thời gian — hãy xem trang hiện hành của Kaggle trước khi lên kế hoạch.
**Lưu ý: phần này CHƯA được kiểm tra với Kaggle thật** (nơi phát triển không có mạng). Lần đầu hãy chạy `--quick`.

### Cách A — qua trình duyệt (dễ nhất cho lần đầu)
1. Tạo Notebook mới trên Kaggle; trong Settings bật **Accelerator = GPU** và **Internet = On**.
2. Chạy `python experiments/run_on_kaggle.py push --task topics/<slug>/task.py --topic "..." --slug <slug> --dry-run`
   trên máy bạn: nó tạo `.kaggle_build/<slug>/kaggle_entry.py` (một file duy nhất chứa runner + task).
3. Dán nội dung file đó vào một ô của notebook, chạy ô. Khi xong, tải `results.json` (và `results_raw.csv`) ở tab Output
   về thư mục đề tài `topics/<slug>/`.

### Cách B — tự động từ dòng lệnh
```bash
pip install kaggle      # + tạo token: Kaggle -> Settings -> API -> Create New Token -> ~/.kaggle/kaggle.json
python experiments/run_on_kaggle.py push   --task topics/<slug>/task.py --topic "Tên đề tài" --slug <slug> --quick   # thử trước
python experiments/run_on_kaggle.py status --slug <slug>
python experiments/run_on_kaggle.py output --slug <slug> --dest topics/<slug> --topic "Tên đề tài"
# ổn rồi thì chạy thật: bỏ --quick (mặc định 5 seed); thư viện thêm: --pip "transformers datasets"
```
`output` tải kết quả về và tự kiểm tra (hợp lệ? đúng đề tài? đủ lần chạy?).

### Khi phiên bị ngắt hoặc hết giờ
- Mỗi lần chạy được ghi ngay vào `results.runs.jsonl`. Chạy lại cùng lệnh thì bỏ qua các lần đã xong.
- Chưa đủ thì **không tạo `results.json`**, chỉ có `results.partial.json` liệt kê lần còn thiếu (tránh dùng một phần số liệu).
- Mỗi lần Kaggle chạy một phiên mới đều bắt đầu từ thư mục trống; muốn nối tiếp phiên trước dùng
  `--resume-from <slug-lần-trước>` (gắn Output của lần trước làm đầu vào). Cơ chế này cũng chưa được thử với Kaggle thật.
- `--time-budget <phút>` dừng bắt đầu lần chạy mới khi gần hết giờ để kịp lưu.

### Khoá bí mật
Thí nghiệm không cần khoá API của mô hình ngôn ngữ nên không có khoá nào được đưa lên Kaggle. **Đừng** dán khoá vào `task.py`
hoặc notebook. Sinh bài báo (cần khoá) vẫn chạy ở máy bạn.

### Mỗi đề tài một thư mục
Xem `topics/README.md`. `results.json` mang tên đề tài (`--topic`) và hash của `task.py`; sinh bài với đề tài khác sẽ bị từ chối.
