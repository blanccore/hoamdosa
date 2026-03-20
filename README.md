# 호암도사 영상 편집 자동화 v2

대본 → ElevenLabs TTS → 무음 삭제 → 영상 처리 파이프라인

## 필요 환경

- Python 3.9+
- FFmpeg (`brew install ffmpeg`)

## 설치

```bash
pip install -r requirements.txt
cp .env.example .env        # API 키 설정
cp project_example.json project.json  # 프로젝트 설정
```

## 사용법

### 1. `.env` 설정
```
ELEVENLABS_API_KEY=your_key_here
```

### 2. `project.json` 설정
```bash
cp project_example.json project.json
# 각 파일 경로를 실제 경로로 수정
```

### 3. 사전 검사
```bash
python3 hoamdosa_editor.py --config project.json --dry-run
```

### 4. 실행
```bash
python3 hoamdosa_editor.py --config project.json
```

## 파이프라인

| 단계 | 작업 | 설명 |
|:---:|:---:|:---|
| 1 | TTS 생성 | 대본 → ElevenLabs 호암도사 음성 |
| 2 | 무음 컷 | TTS 오디오의 무음 구간 감지 & 제거 |
| 3 | 영상 합성 | HeyGen 영상 + 무음 제거 오디오 (선택) |
| 4 | PIP 오버레이 | 이미지 균등 배치 (선택) |
| 5 | 자막 처리 | SRT 교정 + ASS 번인 (선택) |
| 6 | BGM 믹싱 | 배경 음악 낮은 볼륨으로 깔기 (선택) |

## 설정 파라미터

| 파라미터 | 기본값 | 설명 |
|:---|:---:|:---|
| silence_threshold | -35 | 무음 감지 임계값 (dB) |
| silence_min_duration | 0.5 | 최소 무음 길이 (초) |
| bgm_volume | 0.15 | BGM 기본 볼륨 |
| subtitle_fontsize | 48 | 자막 폰트 크기 |
| tts_speed | 0.85 | TTS 속도 (기본 느리게) |
| pip_position | top-left | PIP 위치 |
| pip_scale | 0.30 | PIP 크기 비율 |

## 팁

- `silence_threshold`를 -30으로 올리면 더 공격적으로 컷
- `silence_threshold`를 -40으로 내리면 보수적으로 컷
- BGM/PIP/자막 파일 없으면 자동 스킵
