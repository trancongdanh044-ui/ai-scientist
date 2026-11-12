# Mỗi đề tài một thư mục

```
topics/
  ten-de-tai/          # slug: chữ thường, số, gạch ngang
    config.yaml        # topic, tác giả, tuỳ chọn trình bày
    task.py            # thí nghiệm của đề tài (get_task)
    results.json       # kết quả THẬT (do run_experiments.py tạo, mang tên đề tài + hash task.py)
    outputs/           # paper.pdf, paper.tex, TODO.md ... (sinh khi chạy main.py)
```

Tạo đề tài mới: sao chép `_template/` thành `topics/<slug>/`, sửa `config.yaml`, viết `task.py`.
Sinh bài: `python main.py run --config topics/<slug>/config.yaml` — `results.json` và `outputs/` được hiểu là nằm
CẠNH file config đó, nên kết quả của đề tài này không bao giờ lẫn sang đề tài khác. Nếu `results.json` ghi tên đề tài khác
với `research.topic`, hệ thống từ chối.
