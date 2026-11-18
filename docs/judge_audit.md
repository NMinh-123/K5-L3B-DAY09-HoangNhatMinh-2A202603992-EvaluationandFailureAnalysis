# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, FAIL là lớp dương).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** — tp 24, fp 4, fn 6, tn 66 | **dùng** (non-blocking, chỉ cho giọng văn) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (κ, R) — tp 9, fp 0, fn 21, tn 70 | **loại** |

Tỉ lệ fail sau hiệu chỉnh Rogan-Gladen: tone 0.28 → 0.30; helpful 0.09 → 0.30. Judge helpful báo chỉ 9% reply có vấn đề trong khi tỉ lệ thật ~30%: nó bỏ sót 21/30 reply hỏng.

## Vì sao không dùng judge `helpful` làm gate
- Recall 0.3: 21/30 reply người chấm FAIL bị judge cho PASS. Precision 1.0 chỉ có nghĩa "khi nó kêu thì đúng" — một gate im lặng 70% thời gian vẫn cho bản tệ merge.
- 18/21 lần bỏ sót có `human_failure = sai tiền` (reply nói 55.000đ, ledger ghi 40.000đ…). Judge chỉ đọc reply, **không thấy ledger**, nên về nguyên tắc không thể chấm đúng tiêu chí này. Reply càng dài, nhiều lời xin lỗi thì judge càng cho PASS.
- Tiền luôn chấm bằng code: tiêu chí "reply nói đúng số tiền" đã chuyển sang grader `ReplyAmountMatchesLedger` (metric `reply_amount_matches_ledger`, FM-08).

## Case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em", "nha" quá suồng sã với khách khiếu nại. Rubric: thêm quy tắc xưng hô bắt buộc "LogiX — anh/chị", cấm "em/bạn/nha/nhé". |
| 2 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge bị đánh lừa bởi "Dạ, vui lòng". Rubric: chấm cả câu, liệt kê giọng ra lệnh ("không cần…", "phải…") là FAIL dù có kính ngữ. |
| 3 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì thiếu xin lỗi. Rubric: ghi rõ "ngắn, đủ ý, lịch sự là PASS; xin lỗi không bắt buộc". |
| 4 | H-051 "…đã refund 90.000đ…" | FAIL | PASS | Người | CS LogiX cho phép từ "refund". Rubric: thêm whitelist thuật ngữ được phép (refund, ship, COD). |
| 5 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống — thực chất là lỗi nội dung, không phải giọng. Rubric tone: không chấm; chuyển sang grader code (reply chỉ được nêu số = ledger, cấm hứa "sẽ hoàn thêm"). |
| 6 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Rubric: emoji trong ngữ cảnh khiếu nại là FAIL. |
| 7 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Người đọc nhầm ticket. Hành động: sửa nhãn người trong tập calibration (không sửa CSV replay công khai; ghi vào bảng nhãn v2), rồi tính lại κ. |
| 8 | H-094 "Da, LogiX da hoan 40.000đ…" | PASS | FAIL | Người | Mất dấu tiếng Việt (dịch máy). Rubric: reply không dấu là FAIL. |
| 9 | HL-015 (helpful) "…đã hoàn 55.000đ cho đơn O-112 ạ." | PASS | FAIL | Người | Ledger ghi 40.000đ. Judge không có ledger → không thể đúng. Hành động: bỏ tiêu chí tiền khỏi rubric judge, giao cho code grader. |
| 10 | HL-047 (helpful) "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Vừa sai xưng hô vừa không nói kết quả cụ thể. Rubric helpful: phải nêu trạng thái + số tiền/bước tiếp theo. |

Tổng: trong 10 case tone bất đồng, người đúng 9, judge đúng 1 (H-081). Lỗi judge nghiêng về **bỏ sót** (6 FN) hơn **báo nhầm** (4 FP).

## Kết luận
- `tone_ok` dùng được (κ 0.757 ≥ 0.6, P 0.857 ≥ 0.8, R 0.8 ≥ 0.7) nhưng để **non-blocking**: vẫn bỏ sót 6/30 reply sai giọng.
- `helpful` bị loại: recall 0.3, κ 0.375; nó chấm tiền mà không có ledger. Phần "đúng tiền" chuyển sang code (FM-08).
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (có thể đã bị "học"); cần nhãn người mới, held-out, ≥2 người gán nhãn để tách lỗi người (như H-081) khỏi lỗi judge.
