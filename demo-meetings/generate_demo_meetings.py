from __future__ import annotations

import subprocess
import wave
from pathlib import Path
import re
import tempfile
import asyncio


OUT_DIR = Path(__file__).resolve().parent
PRODUCT = "ZenoPay Merchant Portal"
TARGET_SECONDS = 30 * 60
VOICE = "vi-VN-HoaiMyNeural"
RATE = "+0%"
SAMPLE_RATE = 44100
CHANNELS = 1
SAMPLE_WIDTH = 2


def minute_block(
    minute: int,
    title: str,
    lin: str,
    minh: str,
    an: str,
    decision: str | None = None,
) -> str:
    lines = [
        f"[{minute:02d}:00] {title}",
        f"Linh: {lin}",
        f"Minh: {minh}",
        f"An: {an}",
    ]
    if decision:
        lines.append(f"Quyết định ghi nhận: {decision}")
    lines.append("")
    return "\n".join(lines)


def meeting_1() -> str:
    blocks = [
        minute_block(
            0,
            "Mở đầu và mục tiêu deploy",
            "Hôm nay là ngày 1 tháng 5 năm 2026. Mục tiêu cuộc họp là chốt hướng deploy tính năng Auto Settlement cho ZenoPay Merchant Portal.",
            "Về kỹ thuật, backend settlement đã qua kiểm thử tích hợp nội bộ, nhưng dashboard reconciliation vẫn cần thêm kiểm tra tải.",
            "QA ghi nhận build hiện tại là RC zero point nine, còn 12 test case regression chưa chạy xong.",
        ),
        minute_block(
            2,
            "Mốc thời gian tổng quan",
            "Timeline đang đi theo ba giai đoạn: hoàn tất UAT ngày 20 tháng 5, pilot merchant ngày 1 tháng 6, go live canary ngày 15 tháng 6.",
            "Nếu giữ canary 20 phần trăm vào ngày 15 tháng 6, đội kỹ thuật có đủ thời gian theo dõi lỗi settlement lệch số.",
            "Em đề xuất giữ ngày 15 tháng 6 cho canary, không nên đẩy lên sớm hơn vì bộ test đối soát chưa đủ dữ liệu.",
            "Go live đầu tiên là canary 20 phần trăm ngày 15 tháng 6, không phải full rollout.",
        ),
        minute_block(
            4,
            "Phạm vi release",
            "Release lần này chỉ gồm Auto Settlement, bảng đối soát mới, và cảnh báo lệch tiền theo merchant.",
            "Không đưa bulk refund vào release này vì API refund chưa ổn định trong sandbox.",
            "QA đồng ý loại bulk refund khỏi phạm vi, để tránh tăng rủi ro rollback.",
        ),
        minute_block(
            6,
            "Tiến độ backend",
            "Minh cập nhật giúp chị phần backend theo thời gian, từ tuần này đến cuối tháng 5.",
            "Ngày 3 tháng 5 sẽ khóa schema settlement, ngày 10 tháng 5 hoàn tất worker retry, ngày 17 tháng 5 hoàn tất idempotency key.",
            "QA sẽ test idempotency từ ngày 18 đến ngày 20 tháng 5, ưu tiên case merchant gửi duplicate callback.",
        ),
        minute_block(
            8,
            "Tiến độ frontend",
            "Về frontend portal, tuần đầu tháng 5 sẽ xong màn hình settlement summary, tuần thứ hai xong chi tiết giao dịch.",
            "Cần thêm một API summary theo ngày, nhưng nếu chậm thì frontend vẫn fallback bằng endpoint list giao dịch.",
            "QA cần design freeze trước ngày 12 tháng 5 để viết test script ổn định.",
        ),
        minute_block(
            10,
            "Quyết định về OTP và bảo mật",
            "Có đề xuất bắt OTP cho lần đầu vào tính năng Auto Settlement, nhưng chị muốn nghe rủi ro vận hành.",
            "Nếu bật OTP ngay phase 1, merchant pilot có thể bị tăng friction. Em đề xuất hoãn mandatory OTP sang sau canary.",
            "QA đồng ý. Trong phase 1 chỉ cảnh báo bảo mật và audit log, chưa bắt OTP bắt buộc.",
            "Mandatory OTP bị hoãn khỏi phase 1; chỉ bật audit log và cảnh báo bảo mật.",
        ),
        minute_block(
            12,
            "Tiến độ dữ liệu pilot",
            "Từ ngày 15 tháng 5, đội vận hành sẽ chọn 30 merchant pilot có volume vừa phải.",
            "Backend cần seed dữ liệu mapping merchant vào ngày 18 tháng 5 để có đủ thời gian dry run.",
            "QA sẽ so sánh dữ liệu settlement cũ và mới trong ba ngày 21, 22, 23 tháng 5.",
        ),
        minute_block(
            14,
            "Rủi ro đối soát lệch số",
            "Rủi ro lớn nhất là lệch số giữa transaction ledger và settlement summary.",
            "Em sẽ thêm reconciliation job chạy mỗi giờ trong pilot, nếu lệch quá 0.1 phần trăm thì alert.",
            "QA cần alert đi vào Slack và email, vì đội vận hành không theo dashboard liên tục.",
        ),
        minute_block(
            16,
            "Rollback và monitoring",
            "Rollback window của canary cần rõ. Nếu merchant bị ảnh hưởng, đội mình phản ứng trong bao lâu?",
            "Em đề xuất rollback trong 2 giờ sau khi phát hiện lỗi nghiêm trọng, bằng feature flag per merchant.",
            "QA cần checklist rollback trước ngày 25 tháng 5, bao gồm tắt feature flag và restore settlement view cũ.",
            "Rollback window mục tiêu là 2 giờ sau khi xác nhận lỗi nghiêm trọng.",
        ),
        minute_block(
            18,
            "Tiến độ tài liệu",
            "User guide cho merchant phải sẵn sàng trước pilot ngày 1 tháng 6.",
            "Tech sẽ cung cấp ảnh màn hình và mô tả API trạng thái settlement trước ngày 24 tháng 5.",
            "QA sẽ review user guide cùng Support ngày 26 tháng 5.",
        ),
        minute_block(
            20,
            "Go no-go criteria",
            "Điều kiện go no-go cho ngày 15 tháng 6 là gì?",
            "Không có bug severity cao, lệch settlement dưới 0.1 phần trăm, latency summary dưới 2 giây p95.",
            "Thêm điều kiện Support phải xác nhận đã training cho nhóm trực pilot.",
        ),
        minute_block(
            22,
            "Chủ sở hữu hành động",
            "Minh owner backend timeline, An owner QA và rollback checklist, chị owner merchant pilot và communication.",
            "Em nhận deadline 17 tháng 5 cho idempotency, 24 tháng 5 cho tài liệu kỹ thuật.",
            "Em nhận deadline 20 tháng 5 regression, 25 tháng 5 rollback checklist, 26 tháng 5 review user guide.",
        ),
        minute_block(
            24,
            "Tóm tắt tiến độ theo thời gian",
            "Đến ngày 1 tháng 5, chúng ta đang ở giai đoạn build gần xong, chưa vào UAT chính thức.",
            "Đến ngày 20 tháng 5 phải xong UAT, ngày 1 tháng 6 pilot, ngày 15 tháng 6 canary 20 phần trăm.",
            "QA sẽ cập nhật tiến độ hằng tuần, nếu regression trễ hơn ngày 20 tháng 5 thì phải báo go no-go sớm.",
        ),
        minute_block(
            26,
            "Kết luận",
            "Chốt lại: giữ canary 20 phần trăm ngày 15 tháng 6, chưa bật mandatory OTP phase 1, không đưa bulk refund vào scope.",
            "Tech sẽ không đổi timeline nếu không có bug nghiêm trọng trong UAT.",
            "QA ghi nhận ba quyết định này để so sánh trong các cuộc họp sau.",
        ),
        minute_block(
            28,
            "Nhắc lại cam kết",
            "Cuộc họp kết thúc với cam kết theo dõi tiến độ hằng tuần đến ngày go live.",
            "Nếu đến ngày 1 tháng 6 pilot không ổn, team sẽ không chuyển sang canary ngày 15 tháng 6.",
            "Em sẽ dùng các mốc thời gian hôm nay làm baseline cho test plan.",
        ),
    ]
    return "\n".join(blocks)


def meeting_2() -> str:
    blocks = [
        minute_block(
            0,
            "Mở đầu cập nhật pilot",
            "Hôm nay là ngày 1 tháng 6 năm 2026. Cuộc họp tập trung vào pilot Auto Settlement và quyết định deploy tiếp theo.",
            "Backend đã hoàn tất worker retry và idempotency, nhưng reconciliation job còn một lỗi timezone khi merchant ở múi giờ khác.",
            "QA hoàn tất 86 phần trăm regression, còn lỗi timezone và hai case callback duplicate.",
        ),
        minute_block(
            2,
            "Tiến độ từ tháng 5 đến nay",
            "So với baseline ngày 1 tháng 5, UAT đáng ra xong ngày 20 tháng 5 nhưng thực tế kéo đến ngày 28 tháng 5.",
            "Pilot bắt đầu hôm nay với 18 merchant, thấp hơn kế hoạch 30 merchant vì Support chưa training xong.",
            "QA vẫn coi đây là pilot hạn chế, chưa đủ dữ liệu để gọi là go-live ready.",
        ),
        minute_block(
            4,
            "Conflict về ngày deploy",
            "Marketing muốn công bố Auto Settlement sớm hơn vào ngày 12 tháng 6 để kịp chiến dịch merchant.",
            "Nếu bỏ canary 20 phần trăm ngày 15 tháng 6 và chuyển thành full rollout ngày 12 tháng 6, kỹ thuật vẫn có thể bật feature flag toàn bộ.",
            "Em không đồng ý. Cuộc họp ngày 1 tháng 5 đã chốt canary 20 phần trăm ngày 15 tháng 6, không phải full rollout ngày 12 tháng 6.",
            "Có mâu thuẫn: đề xuất mới là full rollout ngày 12 tháng 6, khác baseline canary 20 phần trăm ngày 15 tháng 6.",
        ),
        minute_block(
            6,
            "Conflict về OTP",
            "Một điểm nữa là Compliance vừa yêu cầu bật mandatory OTP ngay khi merchant vào Auto Settlement.",
            "Điều này trái với quyết định tháng 5 là hoãn mandatory OTP khỏi phase 1.",
            "QA ghi nhận đây là conflict thứ hai: phase 1 trước đó chỉ audit log, nay lại yêu cầu OTP bắt buộc.",
            "Yêu cầu mới bật mandatory OTP phase 1 đang mâu thuẫn với quyết định hoãn OTP ở cuộc họp ngày 1 tháng 5.",
        ),
        minute_block(
            8,
            "Đánh giá rủi ro rollout sớm",
            "Nếu full rollout ngày 12 tháng 6, rủi ro lớn nhất là lỗi timezone chưa đủ dữ liệu production.",
            "Em cũng lo latency summary p95 đang 2.4 giây, vượt tiêu chí 2 giây đã đặt trước.",
            "QA đề xuất không dùng chữ full rollout cho ngày 12 tháng 6; chỉ có thể mở rộng pilot lên 50 merchant.",
        ),
        minute_block(
            10,
            "Tiến độ kỹ thuật",
            "Minh cập nhật tiến độ từ hôm nay đến ngày 10 tháng 6.",
            "Ngày 3 tháng 6 fix timezone, ngày 5 tháng 6 chạy lại duplicate callback, ngày 7 tháng 6 optimize query summary.",
            "QA cần build mới trước sáng ngày 6 tháng 6 để retest cuối tuần.",
        ),
        minute_block(
            12,
            "Tiến độ vận hành",
            "Support chưa training xong vì tài liệu merchant vẫn thiếu phần xử lý lệch tiền.",
            "Tech sẽ thêm mô tả trạng thái settlement failed và retry before ngày 4 tháng 6.",
            "QA và Support sẽ dry run kịch bản merchant gọi hotline ngày 8 tháng 6.",
        ),
        minute_block(
            14,
            "Quyết định tạm thời",
            "Chị không muốn bỏ qua cảnh báo QA, nhưng cũng cần phản hồi Marketing.",
            "Đề xuất tạm thời: ngày 12 tháng 6 chỉ mở rộng pilot, không full rollout, còn canary production giữ sau đó.",
            "QA đồng ý với điều kiện phải ghi rõ đây là mở rộng pilot, không thay thế quyết định canary chính thức.",
        ),
        minute_block(
            16,
            "OTP và trải nghiệm merchant",
            "Về OTP, nếu bật mandatory ngay thì merchant pilot có thể gặp lỗi đăng nhập lần đầu.",
            "Có thể bật OTP optional kèm audit log trong pilot mở rộng, sau đó mới quyết định mandatory.",
            "QA cần test cả hai nhánh optional OTP và no OTP để tránh đổi phút chót.",
        ),
        minute_block(
            18,
            "Rollback",
            "Rollback window 2 giờ vẫn còn phù hợp không?",
            "Nếu full rollout thì 2 giờ không đủ, nhưng nếu pilot hoặc canary thì feature flag per merchant vẫn xử lý được trong 2 giờ.",
            "QA giữ rollback window 2 giờ cho pilot/canary, nhưng không chấp nhận cho full rollout.",
        ),
        minute_block(
            20,
            "Tiến độ đo lường",
            "Từ ngày 1 đến ngày 7 tháng 6, team sẽ đo latency summary, lệch settlement, và tỷ lệ retry callback.",
            "Nếu đến ngày 7 tháng 6 p95 vẫn trên 2 giây, không mở rộng pilot ngày 12 tháng 6.",
            "QA cần dashboard số liệu hằng ngày từ ngày 2 tháng 6.",
        ),
        minute_block(
            22,
            "Trạng thái go no-go",
            "Theo tiêu chí tháng 5, hiện tại chưa đạt go no-go vì regression chưa xong, latency vượt ngưỡng, Support chưa training.",
            "Tech cần thêm bốn ngày để fix và đo lại.",
            "QA sẽ gửi báo cáo go no-go sơ bộ ngày 8 tháng 6.",
        ),
        minute_block(
            24,
            "Chủ sở hữu hành động",
            "Minh owner fix timezone và latency, An owner retest và báo cáo go no-go, chị owner phản hồi Marketing.",
            "Em nhận deadline ngày 3 tháng 6 timezone, ngày 7 tháng 6 latency.",
            "Em nhận deadline ngày 8 tháng 6 báo cáo go no-go và training checklist.",
        ),
        minute_block(
            26,
            "Tóm tắt conflict",
            "Ghi rõ vào biên bản: có conflict với cuộc họp 1 về ngày deploy và phạm vi rollout.",
            "Ghi thêm conflict về OTP: trước đó hoãn mandatory OTP khỏi phase 1, hôm nay Compliance yêu cầu bật ngay.",
            "QA sẽ đánh dấu hai conflict này để meeting ngày 10 tháng 6 phải resolve.",
        ),
        minute_block(
            28,
            "Kết luận",
            "Kết luận tạm thời: không full rollout ngày 12 tháng 6, chỉ xem xét mở rộng pilot nếu đạt điều kiện ngày 8 tháng 6.",
            "Canary 20 phần trăm ngày 15 tháng 6 chưa bị hủy, nhưng đang có nguy cơ trễ nếu latency không giảm.",
            "Cuộc họp ngày 10 tháng 6 sẽ chốt quyết định cuối cùng.",
        ),
    ]
    return "\n".join(blocks)


def meeting_3() -> str:
    blocks = [
        minute_block(
            0,
            "Mở đầu go no-go cuối",
            "Hôm nay là ngày 10 tháng 6 năm 2026. Mục tiêu là chốt quyết định deploy Auto Settlement cho ZenoPay Merchant Portal.",
            "Backend đã fix timezone ngày 3 tháng 6, optimize summary ngày 7 tháng 6, và latency p95 hiện còn 1.7 giây.",
            "QA hoàn tất regression 100 phần trăm, còn một bug severity thấp về wording.",
        ),
        minute_block(
            2,
            "Tiến độ timeline",
            "So với baseline ngày 1 tháng 5, UAT trễ tám ngày nhưng pilot đã có dữ liệu đủ từ ngày 1 đến ngày 9 tháng 6.",
            "Pilot hiện có 24 merchant, tỷ lệ retry callback giảm từ 1.8 phần trăm xuống 0.3 phần trăm.",
            "QA xác nhận tiêu chí lệch settlement dưới 0.1 phần trăm đã đạt trong ba ngày liên tiếp.",
        ),
        minute_block(
            4,
            "Resolve conflict ngày deploy",
            "Cuộc họp ngày 1 tháng 6 có conflict giữa full rollout ngày 12 tháng 6 và canary 20 phần trăm ngày 15 tháng 6.",
            "Sau dữ liệu pilot, em đề xuất không full rollout ngày 12 tháng 6. Chuyển sang canary 20 phần trăm ngày 18 tháng 6 để có thêm ba ngày monitoring.",
            "QA đồng ý. Quyết định cuối là canary 20 phần trăm ngày 18 tháng 6, không full rollout ngày 12 tháng 6.",
            "Conflict được resolve: bỏ full rollout ngày 12 tháng 6; chọn canary 20 phần trăm ngày 18 tháng 6.",
        ),
        minute_block(
            6,
            "Resolve conflict OTP",
            "Về OTP, cuộc họp 1 hoãn mandatory OTP khỏi phase 1, cuộc họp 2 có yêu cầu bật ngay.",
            "Compliance đã đồng ý tạm thời: phase 1 dùng audit log và OTP optional, mandatory OTP chuyển sang phase 2 sau canary.",
            "QA ghi nhận conflict OTP đã resolve theo hướng không bắt buộc trong phase 1.",
            "OTP mandatory không bật ở phase 1; chỉ bật optional OTP và audit log.",
        ),
        minute_block(
            8,
            "Quy trình deploy theo ngày",
            "Ngày 10 tháng 6 chốt go no-go, ngày 11 tháng 6 freeze code, ngày 12 tháng 6 mở rộng pilot lên 50 merchant.",
            "Ngày 14 tháng 6 hoàn tất training Support, ngày 17 tháng 6 chạy dry run rollback, ngày 18 tháng 6 canary.",
            "QA sẽ chạy smoke test mỗi sáng từ ngày 12 đến ngày 18 tháng 6.",
        ),
        minute_block(
            10,
            "Điều kiện canary",
            "Điều kiện canary gồm latency p95 dưới 2 giây, lệch settlement dưới 0.1 phần trăm, không bug severity cao.",
            "Tech thêm điều kiện queue retry không vượt 500 message trong 30 phút.",
            "QA thêm điều kiện Support xác nhận trực ca trong hai giờ đầu canary.",
        ),
        minute_block(
            12,
            "Kế hoạch rollback",
            "Rollback window 2 giờ được giữ cho canary 20 phần trăm.",
            "Feature flag sẽ tắt theo merchant group, không tắt toàn bộ portal.",
            "QA đã có checklist rollback gồm tắt flag, restore view cũ, kiểm tra settlement summary và gửi thông báo cho Support.",
        ),
        minute_block(
            14,
            "Trạng thái tài liệu",
            "User guide đã cập nhật phần settlement failed, retry, và trạng thái chờ đối soát.",
            "Tech đã bổ sung ảnh màn hình và mô tả lỗi timezone.",
            "QA đã review cùng Support ngày 9 tháng 6, chỉ còn sửa wording.",
        ),
        minute_block(
            16,
            "Theo dõi sau canary",
            "Trong 24 giờ đầu sau ngày 18 tháng 6, team cần theo dõi dashboard mỗi giờ.",
            "Tech sẽ trực latency, queue retry, và reconciliation job.",
            "QA sẽ trực test smoke trên ba merchant mẫu lúc 10 giờ, 14 giờ, và 18 giờ.",
        ),
        minute_block(
            18,
            "Plan sau canary",
            "Nếu canary ổn 48 giờ, ngày 20 tháng 6 mở lên 50 phần trăm merchant.",
            "Nếu 50 phần trăm ổn đến ngày 23 tháng 6, ngày 24 tháng 6 full rollout.",
            "QA yêu cầu full rollout chỉ khi không phát sinh bug severity cao trong giai đoạn 50 phần trăm.",
        ),
        minute_block(
            20,
            "Rủi ro còn lại",
            "Rủi ro còn lại là merchant hiểu nhầm trạng thái pending settlement là lỗi.",
            "Support sẽ dùng script giải thích mới, và portal thêm tooltip ở màn hình summary.",
            "QA sẽ kiểm tra tooltip trong build freeze ngày 11 tháng 6.",
        ),
        minute_block(
            22,
            "Chủ sở hữu hành động",
            "Minh owner freeze code ngày 11, dry run rollback ngày 17, và monitoring ngày 18.",
            "An owner smoke test, wording user guide, và go-live checklist.",
            "Linh owner communication với Marketing, Support, và nhóm merchant pilot.",
        ),
        minute_block(
            24,
            "Tóm tắt tiến độ liên tục",
            "Từ ngày 1 tháng 5 đến 10 tháng 6, dự án đi từ build gần xong, sang pilot trễ, rồi đạt điều kiện canary sau khi fix latency.",
            "Quy trình không còn theo full rollout sớm. Quy trình mới là pilot mở rộng, canary 20 phần trăm, 50 phần trăm, rồi full rollout.",
            "QA ghi nhận đây là trạng thái mới nhất để các cuộc họp sau dùng làm baseline.",
        ),
        minute_block(
            26,
            "Quyết định cuối",
            "Chốt quyết định: canary Auto Settlement ngày 18 tháng 6, 20 phần trăm merchant, OTP optional, rollback window 2 giờ.",
            "Tech đồng ý và sẽ không nhận thêm scope mới trước canary.",
            "QA đồng ý go nếu build freeze ngày 11 tháng 6 không phát sinh bug severity cao.",
            "Quyết định mới thay thế đề xuất full rollout ngày 12 tháng 6.",
        ),
        minute_block(
            28,
            "Kết thúc",
            "Cảm ơn mọi người. Meeting này đóng các conflict từ ngày 1 tháng 6 và cập nhật baseline deploy mới.",
            "Em sẽ gửi release checklist trong hôm nay.",
            "QA sẽ đánh dấu completed cho các action đã xong và pending cho smoke test sau freeze.",
        ),
    ]
    return "\n".join(blocks)


MEETINGS = [
    ("2026-05-01 deploy ZenoPay Merchant Portal", meeting_1),
    ("2026-06-01 deploy ZenoPay Merchant Portal", meeting_2),
    ("2026-06-10 deploy ZenoPay Merchant Portal", meeting_3),
]


def read_wav_frames(input_wav_path: Path) -> tuple[bytes, int, int, int]:
    with wave.open(str(input_wav_path), "rb") as src:
        channels = src.getnchannels()
        sample_width = src.getsampwidth()
        framerate = src.getframerate()
        frames = src.readframes(src.getnframes())
    return frames, channels, sample_width, framerate


def write_wav(path: Path, frames: bytes, channels: int = CHANNELS,
              sample_width: int = SAMPLE_WIDTH, framerate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(sample_width)
        dst.setframerate(framerate)
        dst.writeframes(frames)


def normalize_wav_to_30_minutes(input_wav_path: Path, output_wav_path: Path) -> None:
    frames, channels, sample_width, framerate = read_wav_frames(input_wav_path)
    target_frame_count = TARGET_SECONDS * framerate
    target_bytes = target_frame_count * channels * sample_width
    if len(frames) < target_bytes:
        frames = frames + (b"\x00" * (target_bytes - len(frames)))
    else:
        frames = frames[:target_bytes]

    write_wav(output_wav_path, frames, channels, sample_width, framerate)


def render_speech_segment(text: str, tmpdir: Path, index: int) -> bytes:
    text = spoken_text(text)
    from gtts import gTTS

    def chunks(raw: str, limit: int = 260) -> list[str]:
        pieces = [p.strip() for p in re.split(r"(?<=[.!?。])\s+|\n+", raw) if p.strip()]
        out: list[str] = []
        current = ""
        for piece in pieces:
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > limit:
                out.append(current)
                current = piece
            else:
                current = candidate
        if current:
            out.append(current)
        return out

    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        ffmpeg = "ffmpeg"

    output = bytearray()
    short_pause = b"\x00" * int(0.25 * SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    for chunk_index, chunk_text in enumerate(chunks(text)):
        mp3_path = tmpdir / f"segment-{index:02d}-{chunk_index:02d}.mp3"
        wav_path = tmpdir / f"segment-{index:02d}-{chunk_index:02d}.wav"
        gTTS(chunk_text, lang="vi", slow=False).save(str(mp3_path))
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(mp3_path),
                "-vn",
                "-ac",
                str(CHANNELS),
                "-ar",
                str(SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                str(wav_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        frames, channels, sample_width, framerate = read_wav_frames(wav_path)
        if (channels, sample_width, framerate) != (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE):
            raise ValueError(f"Unexpected WAV format for {wav_path}")
        output.extend(frames)
        output.extend(short_pause)
    return bytes(output)


def spoken_text(content: str) -> str:
    """Make transcript safer for TTS while keeping the .txt transcript unchanged."""
    text = re.sub(r"^\[(\d{2}):00\]\s*", r"Phút \1. ", content, flags=re.MULTILINE)
    text = re.sub(r"^(Linh|Minh|An):\s*", r"\1 nói: ", text, flags=re.MULTILINE)
    text = text.replace("ZenoPay", "Zeno Pay")
    text = text.replace("Auto Settlement", "auto settlement")
    text = text.replace("go-live", "go live")
    text = text.replace("go no-go", "go no go")
    text = text.replace("RC zero point nine", "R C zero point nine")
    return text


async def save_tts(text: str, output_path: Path) -> None:
    from gtts import gTTS

    tts = gTTS(spoken_text(text), lang="vi", slow=False)
    tts.save(str(output_path))


def short_audio_script(base_name: str, content: str) -> str:
    """Short spoken intro for stable demo MP3 generation.

    Full meeting content remains in the .txt transcript next to the audio.
    """
    highlights = []
    for pattern in [
        r"Quyết định ghi nhận: ([^\n]+)",
        r"có conflict[^\n.]*[.]?",
        r"Conflict được resolve[^\n.]*[.]?",
    ]:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            highlights.append(match.group(0).replace("Quyết định ghi nhận: ", ""))
    highlight_text = " ".join(highlights[:3])
    return (
        f"Đây là file demo cho cuộc họp {base_name}. "
        "Chủ đề là deploy tính năng auto settlement của sản phẩm Zeno Pay Merchant Portal. "
        "Cuộc họp có ba người tham gia: Linh, Minh và An. "
        f"{highlight_text} "
        "Transcript đầy đủ nằm trong file văn bản cùng tên để kiểm tra decision memory, contradiction radar và evidence Q and A."
    )


def render_short_tts_to_wav(base_name: str, content: str, wav_path: Path) -> bool:
    """Generate a short spoken intro, then pad to 30 minutes."""
    with tempfile.TemporaryDirectory(prefix="memoir-demo-full-tts-") as tmp:
        tmpdir = Path(tmp)
        speech_mp3 = tmpdir / "speech.mp3"
        raw_wav = tmpdir / "speech.wav"
        try:
            asyncio.run(save_tts(short_audio_script(base_name, content), speech_mp3))
            try:
                import imageio_ffmpeg

                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:  # noqa: BLE001
                ffmpeg = "ffmpeg"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(speech_mp3),
                    "-vn",
                    "-ac",
                    str(CHANNELS),
                    "-ar",
                    str(SAMPLE_RATE),
                    "-c:a",
                    "pcm_s16le",
                    str(raw_wav),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            normalize_wav_to_30_minutes(raw_wav, wav_path)
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"warning: full TTS failed, using timeline fallback: {type(exc).__name__}: {exc}")
            return False


def split_timed_blocks(content: str) -> list[tuple[int, str]]:
    matches = list(re.finditer(r"^\[(\d{2}):00\] ", content, flags=re.MULTILINE))
    blocks: list[tuple[int, str]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        minute = int(match.group(1))
        blocks.append((minute * 60, content[start:end].strip()))
    if not blocks:
        blocks.append((0, content))
    return blocks


def render_timeline_wav(content: str, wav_path: Path) -> None:
    bytes_per_second = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH
    target_len = TARGET_SECONDS * bytes_per_second
    output = bytearray()

    with tempfile.TemporaryDirectory(prefix="memoir-demo-audio-") as tmp:
        tmpdir = Path(tmp)
        for index, (start_second, block_text) in enumerate(split_timed_blocks(content)):
            target_offset = start_second * bytes_per_second
            if len(output) < target_offset:
                output.extend(b"\x00" * (target_offset - len(output)))
            output.extend(render_speech_segment(block_text, tmpdir, index))

    if len(output) < target_len:
        output.extend(b"\x00" * (target_len - len(output)))
    else:
        del output[target_len:]
    write_wav(wav_path, bytes(output))


def wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        ffmpeg = "ffmpeg"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(wav_path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-id3v2_version",
            "3",
            str(mp3_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def build_meeting(base_name: str, content: str) -> None:
    txt_path = OUT_DIR / f"{base_name}.txt"
    wav_path = OUT_DIR / f"{base_name}.30min.wav"
    mp3_path = OUT_DIR / f"{base_name}.mp3"

    txt_path.write_text(content, encoding="utf-8")
    render_timeline_wav(content, wav_path)
    wav_to_mp3(wav_path, mp3_path)
    wav_path.unlink(missing_ok=True)


def main() -> None:
    for base_name, factory in MEETINGS:
        build_meeting(base_name, factory())
        print(f"created {base_name}.mp3")


if __name__ == "__main__":
    main()
