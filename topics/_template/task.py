"""Thí nghiệm của MỘT đề tài. Điền các chỗ có dấu TODO rồi chạy thử bằng --quick.

Chạy thử trên máy:   python experiments/run_experiments.py --task topics/<slug>/task.py --quick --out /tmp/t.json --topic "..."
Chạy thật (Kaggle):  python experiments/run_on_kaggle.py push --task topics/<slug>/task.py --topic "..." --slug <slug>

QUY TẮC: số liệu chỉ do code này chạy ra; siêu tham số chọn trên tập VALIDATION; không chọn seed; không dán khoá API vào đây.
"""


def get_task(quick: bool) -> dict:
    raise SystemExit("topics/_template/task.py chưa được điền: hãy sao chép thư mục này thành topics/<slug>/ và viết task.")

    # --- Khung tham khảo (bỏ comment sau khi điền) -----------------------------------------------------
    # def load_dataset_a(seed):                  # trả về dữ liệu tuỳ ý; nên chia train/valid/test theo seed
    #     ...                                    # quick=True -> lấy tập con nhỏ
    #
    # def baseline_1(data, seed):                # fn(data, seed) -> {metric: value}
    #     ...
    #     return {"Accuracy": acc, "Macro-F1": f1}
    #
    # return {
    #     "datasets": {"DatasetA": load_dataset_a, "DatasetB": load_dataset_b},
    #     "metrics": ["Accuracy", "Macro-F1"],
    #     "methods": [
    #         {"name": "Baseline 1", "run": baseline_1},            # >= 4 baseline đã công bố
    #         {"name": "Proposed", "proposed": True, "run": proposed},
    #     ],
    #     "ablation": {"dataset": "DatasetA", "variants": [{"name": "Full", "run": proposed}, {"name": "w/o X", "run": proposed_wo_x}]},
    #     "sensitivity": {"parameter": "...", "dataset": "DatasetA", "metric": "Accuracy",
    #                     "values": [..], "series": [{"name": "Proposed", "run": proposed_with_value}]},  # fn(data, seed, value)
    #     "dataset_stats": {"DatasetA": {"Train": ..., "Test": ...}},
    #     "setup": {"hardware": "Kaggle GPU", "dataset_urls": {"DatasetA": "https://..."}},   # chỉ ghi sự thật
    # }
