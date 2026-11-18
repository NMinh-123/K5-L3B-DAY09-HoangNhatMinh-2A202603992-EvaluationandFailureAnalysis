# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape swarm --claim C-002 --seed 55               # trial fail duy nhất của baseline
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11   # cùng lỗi, bật trên mọi seed
python -m lab9.trace_case --shape fixed --claim C-002 --seed 55               # đối chứng
```

## Case: `swarm C-002@55`

| Trường | Nội dung |
|---|---|
| Trial | `swarm C-002@55`, run `E-swarm-20261118-69f5` (`reports/baseline_v1.json`, row `E-002@55`) — trial fail duy nhất trong 70 trial của baseline |
| Triệu chứng | `pass_rate`, `refund_amount_correct`, `db_fact_kept` đều fail. Grader Lab 8: `status resolved != denied`. Ledger ghi **20.000đ** (refund_count 1), nhãn là `denied`, 0đ. |
| Bước sai đầu tiên | Event **3** `model_override` — `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng (tool chỉ đọc, scope `owner_order_only`). Event 2 `investigator` đọc đúng DB: `O-202 delay_days = 2`, phí ship 20.000đ. Đến event 3 agent thay số ngày trễ của DB bằng "trễ 5 ngày" khách tự khai trong ticket. Event 4 `quote` chỉ là hệ quả (tính tiền trên `delay_days = 5` → clause `SHIP-LATE-03` → 20.000đ). |
| Failure mode | **FM-03** ticket_trust (layer model/prompt) |
| Đối chứng | `fixed C-002@55`: không có `model_override`; event 3 là `quote {"amount_vnd": 0, "reason": "no_entitlement"}`; status `denied`, ledger 0đ — khớp nhãn. |
| Nguyên nhân gốc | `swarm_reference` tin ticket khi `seed % 5 == 0` (seed 55) — lỗi chập chờn 1/5 seed, nên `pass_5` (0.9286) thấp hơn `pass_rate` (0.9857). |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_ticket_override_caught[swarm-55]` và `[seeded_regression-11]` khẳng định có `model_override` trước `quote`, và `DbFactKept`, `RefundAmountCorrect` đều fail; `test_lab9_trace_case_fixed_is_clean` khẳng định `fixed` pass cả hai. Đã chạy: fail trên variant lỗi, pass trên `fixed` (3/3 test xanh). Item `E-002` mang `provenance.from_trace` trỏ về trial này. |
| Chưa chắc chắn | Trace chỉ cho thấy MockLLM đè số ngày ở seed chia hết cho 5; không chứng minh LLM thật sẽ đè với tần suất nào. Trace cũng không ghi lý do (prompt) khiến model tin ticket. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
