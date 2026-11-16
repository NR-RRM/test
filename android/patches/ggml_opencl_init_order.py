"""ggml OpenCL 백엔드 버그 수정 (whisper.cpp v1.9.5에 포함된 ggml).

buffer type 함수(get_alignment / get_max_size / get_alloc_size)가 백엔드 초기화
(ggml_cl_init) 전에 불리면 dev_ctx->backend_ctx 가 NULL이라 충돌한다.
llama.cpp는 장치를 먼저 초기화해서 문제가 없지만, whisper.cpp는 모델 가중치 버퍼를
먼저 만들기 때문에 Adreno에서 시작하자마자 SIGSEGV가 난다.
각 함수가 ggml_cl_init()으로 컨텍스트를 받도록 바꾼다 (이미 초기화돼 있으면 그대로 반환).

사용: python ggml_opencl_init_order.py <whisper.cpp 소스 폴더>
"""
import sys
from pathlib import Path

f = Path(sys.argv[1]) / "ggml/src/ggml-opencl/ggml-opencl.cpp"
s = f.read_text(encoding="utf-8")
MARK = "// autosub: ggml_cl_init before buffer type queries"
if MARK in s:
    print("  패치: 이미 적용됨")
    sys.exit(0)

reps = [
    ("    ggml_backend_opencl_device_context * dev_ctx = (ggml_backend_opencl_device_context *) buffer_type->device->context;\n"
     "    return dev_ctx->backend_ctx->alignment;",
     "    " + MARK + "\n    return ggml_cl_init(buffer_type->device)->alignment;"),
    ("        max_size = dev_ctx->backend_ctx->max_alloc_size;",
     "        max_size = ggml_cl_init(buffer_type->device)->max_alloc_size;"),
    ("        size += 4 * dev_ctx->backend_ctx->alignment;",
     "        size += 4 * ggml_cl_init(buft->device)->alignment;"),
]
n = 0
for old, new in reps:
    c = s.count(old)
    if c == 1:
        s = s.replace(old, new)
        n += 1
    else:
        print(f"  패치: 대상 코드를 찾지 못함({c}회) — 건너뜀: {old.strip()[:60]}")
if n == 0:
    print("  패치: 적용할 곳 없음 (이미 고쳐진 버전일 수 있음)")
    sys.exit(0)
if MARK not in s:  # 첫 번째 교체가 빠졌어도 표시는 남긴다
    s = MARK + "\n" + s
f.write_text(s, encoding="utf-8")
print(f"  패치: {n}곳 수정")
