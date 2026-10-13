# Hướng dẫn tiếng Việt — Hoạt ảnh bảng trắng từ SRT

Biến phụ đề SRT thành video bảng trắng được vẽ theo trình tự câu chuyện. Từng đối tượng xuất hiện theo phụ đề; đầu bút di chuyển liên tục để vẽ nét (`ink`) rồi tô màu (`color`), cuối cùng xuất MP4.

## Cài đặt

```powershell
python scripts/prepare_env.py --check
python scripts/prepare_env.py
```

Khi hoàn tất, lệnh in `ENV_PY=<đường-dẫn-python>`. Dùng Python này để dựng video. Nếu Windows không hiển thị Unicode trong terminal, chạy:

```powershell
$env:PYTHONUTF8='1'; python scripts/prepare_env.py
```

## Quy trình

1. Nhập SRT/TXT hoặc dán lời thoại vào Studio. SRT giữ mốc thời gian từng đoạn.
2. Mở thư mục có ảnh. Studio tự ghép các đoạn SRT theo thứ tự: nếu số ảnh bằng hoặc nhiều hơn số đoạn thì mỗi ảnh nhận một đoạn; nếu ảnh ít hơn số đoạn thì mỗi ảnh nhận một nhóm đoạn SRT liên tiếp, được chia cân đối.
3. Với một ảnh và ba đoạn SRT, Studio tự tạo ba vùng lời thoại trong ảnh đó; mỗi vùng mang đúng nội dung và thời lượng của đoạn SRT tương ứng. Có thể bấm **Tự ghép SRT vào ảnh / vùng** để áp lại quy tắc này sau khi thêm ảnh hoặc sửa SRT.
4. Sửa nội dung trong ô **Phụ đề** của một vùng được tạo từ SRT sẽ tự cập nhật đoạn SRT tương ứng và tự ghi lại file `.srt` gốc trong thư mục dự án (khi mở thư mục bằng Chrome/Edge và cấp quyền ghi). Bạn cũng có thể sửa ô **Kịch bản & phụ đề**; khi rời ô, timeline và SRT được cập nhật.
5. Mốc SRT xác định nội dung và thời lượng mặc định. Các trường Bắt đầu/Kết thúc ở mô-đun là mốc **nội bộ của cảnh** (`reveal.startMs`), nên có thể tinh chỉnh mà không đổi mốc thời gian SRT.
   Renderer tự nới nhẹ mép các vùng khi dựng và vá phần ảnh chưa thuộc vùng nào ở cuối lượt vẽ. Vì vậy các khe hở nhỏ do kéo khung chưa sát sẽ không tạo đường trắng hoặc ô trống trong video xuất.
6. Tạo lời đọc tiếng Việt bằng Kokoro-Vietnamese hoặc nạp MP3/WAV/M4A cho từng ảnh. Studio tự đọc thời lượng audio, chia lại thời gian vẽ các mô-đun theo tỷ lệ và đặt thời lượng cảnh bằng audio cộng 0,5 giây giữ hình cuối. Nút **Khớp lại thời lượng vẽ theo audio** cho phép chạy lại thao tác này khi cần; audio được lưu cạnh ảnh và ghép vào cảnh tương ứng.
7. Chọn chất lượng rồi bấm **Xuất MP4 toàn dự án** để dựng từng cảnh và ghép theo thứ tự ảnh thành một tệp MP4. Studio mở trình phát xem trước sau khi dựng xong; kiểm tra bản ghép rồi chọn **Tải MP4 này** khi bạn đồng ý. **Xuất MP4 cảnh này** cũng dùng cùng bước xem trước.

### Thiết lập giọng đọc Kokoro-Vietnamese

Trên Windows, chạy `scripts\\install_kokoro.ps1` một lần để cài [Kokoro-Vietnamese](https://github.com/iamdinhthuan/Kokoro-Vietnamese) vào môi trường Python riêng `.venv-kokoro` (không thay đổi môi trường dựng video). Bộ cài ghim mã nguồn Kokoro-Vietnamese vào bản đã kiểm tra. Khởi động lại `Mo-Preview-Desk.cmd`, chọn cảnh, chọn một trong 14 giọng và nhịp đọc rồi bấm **Tạo lời đọc WAV cho cảnh**. Lần tạo đầu cần Internet để tải checkpoint, voicepack và cấu hình từ Hugging Face; các lần sau chạy inference cục bộ, không gửi lời thoại tới dịch vụ TTS bên ngoài. Mặc định ứng dụng thử CUDA nếu PyTorch hỗ trợ và tự chuyển về CPU nếu không; đặt `KOKORO_DEVICE=cpu` để buộc dùng CPU, hoặc `KOKORO_PYTHON` để dùng một môi trường đã có.

**Giấy phép:** mã nguồn Kokoro-Vietnamese được phát hành theo Apache-2.0. Hãy kiểm tra riêng giấy phép/các điều khoản của checkpoint trên Hugging Face trước khi phát hành hoặc thương mại hóa video.

### Thiết lập VieNeu-TTS (khuyến nghị cho laptop này)

Chạy `scripts\\install_vieneu.ps1` một lần để tạo môi trường `.venv-vtts` độc lập và cài VieNeu-TTS ở chế độ CPU/ONNX. Preview Desk sẽ có lựa chọn **VieNeu-TTS** cùng các giọng 48 kHz dựng sẵn; lần đầu tạo audio sẽ tải model, những lần sau suy luận hoàn toàn cục bộ. Máy cần Python 3.10–3.13 x64 (không dùng Python 3.14 hiện có); không cần NVIDIA/CUDA. Tốc độ đọc của VieNeu phụ thuộc vào giọng chọn và hiện không có thanh chỉnh nhịp như Kokoro.

#### Clone giọng của bạn

Trong bảng **Giọng đọc tiếng Việt**, chọn **VieNeu-TTS**, rồi ở phần **Tạo giọng mẫu riêng** chọn file WAV/MP3/M4A/OGG/FLAC có một người nói tiếng Việt rõ ràng trong khoảng 3–8 giây. Đặt tên, xác nhận bạn có quyền dùng giọng đó và bấm **Tạo & thêm vào danh sách giọng**. Preview Desk tự chuyển file về WAV mono tạm thời trước khi VieNeu khử nhiễu, vì vậy M4A/MP3 cũng hoạt động trên Windows; file thu âm gốc không được giữ lại. Sau khi hoàn thành, giọng xuất hiện trong nhóm **Giọng mẫu của bạn** và dùng được để tạo WAV cho mọi cảnh như giọng dựng sẵn.

Tệp thu âm gốc chỉ được dùng tạm trong lúc tạo. Ứng dụng lưu hồ sơ giọng đã trích xuất tại `data/vieneu-custom-voices/` để dùng lại sau khi khởi động; thư mục này đã được bỏ qua khỏi Git vì chứa dữ liệu giọng cá nhân. Chất lượng phụ thuộc trực tiếp vào mẫu: hãy dùng mic rõ, không nhạc nền, không nhiều người nói và tránh đoạn quá ngắn/dài.

#### Chạy hoàn toàn tại chỗ / offline

Clone giọng và tạo WAV không gọi VieNeu API: Preview Desk chỉ gửi dữ liệu giữa trình duyệt và máy chủ Python `127.0.0.1` trên chính laptop. Lần **đầu tiên** VieNeu cần tải model nguồn mở từ Hugging Face về máy; sau khi chạy thành công một lần, bật **Chỉ chạy offline** trong Preview Desk để chặn mọi lần tải model qua Internet. Nếu model chưa có trong cache, chế độ này sẽ báo lỗi thay vì kết nối mạng.

Để vẫn dùng được nếu trang VieNeu hoặc kho tải xuống không còn hoạt động, hãy hoàn tất cài đặt và lần chạy đầu khi còn mạng, rồi sao lưu cả thư mục dự án (đặc biệt `data/vieneu-custom-voices/`) và môi trường `.venv-vtts` cùng cache Hugging Face của tài khoản Windows. Các hồ sơ giọng tự tạo không phụ thuộc API VieNeu; chúng được dùng trực tiếp bởi bộ suy luận VieNeu đã cài trên máy.

VieNeu-TTS v3 Turbo là bản mã nguồn mở theo Apache-2.0; hãy chỉ dùng tính năng nhân bản giọng nói khi bạn có quyền hoặc được sự đồng ý của chủ giọng và kiểm tra giấy phép model trước khi phát hành thương mại.

## Tài nguyên của một dự án

```text
assets/whiteboard/<ten-du-an>/
├── scene-01-<ten>.png
├── scene-01-<ten>.annotation.json
├── scene-01-<ten>-whiteboard.mp4
└── scene-01-<ten>-preview.mp4
```

Tệp PNG và JSON phải cùng tên gốc. Các trường `sequence`, `subtitle`, `narrativeRole`, `region` và `reveal` xác định thứ tự câu chuyện, phụ đề, vùng pixel và thời điểm xuất hiện. `protectedRegions` ngăn nội dung chồng lấp bị lộ sớm.

## Các lệnh chính

Phân tích phụ đề:

```powershell
python scripts/parse_srt.py <phu-de.srt> --target-sec 30 --min-sec 25 --max-sec 35
```

Tạo ảnh kiểm tra vùng:

```powershell
python scripts/render_annotation_preview.py <anh.png> <chu-thich.json> <anh-kiem-tra.png>
```

Nhấp đúp `Mo-Preview-Desk.cmd` để mở Preview Desk đầy đủ. Bấm **Mở thư mục…** rồi chọn thư mục cảnh. Bạn có thể kéo vùng, sắp thứ tự, sửa thời lượng/phụ đề và lưu lại JSON. Bấm **Xuất MP4 cảnh này** để dựng video H.264 và tải video về trình duyệt. Trình duyệt khác sẽ tải bản JSON đã sửa thay vì ghi trực tiếp.

Dựng một cảnh:

```powershell
<ENV_PY> scripts/render_stream_whiteboard.py <anh.png> <chu-thich.json> <dau-ra.mp4> assets/drawing-hand.png --ink-path grid --color-fill contour-wipe
```

Ghép nhiều cảnh:

```powershell
<ENV_PY> scripts/merge_scenes.py --inputs canh-1.mp4 canh-2.mp4 --output video-hoan-chinh.mp4
```

## Kiểm tra trước khi xuất

- Khung đầu là nền giấy kem sạch, không lộ nét vẽ trước thời điểm.
- `canvas` khớp kích thước ảnh; mọi `region` dùng pixel nguyên và nằm trong ảnh.
- `sequence` và `startMs` khớp diễn biến phụ đề.
- Cảnh kết giữ ảnh hoàn chỉnh tối thiểu 0,5 giây.

Thư mục `examples/` có sẵn ảnh, tệp chú thích và video mẫu để thử trong Preview Desk.
