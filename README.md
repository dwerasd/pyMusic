# pyMusic

PySide6 기반 심플 음악 플레이어

## 기능

- 오디오 재생 (mp3, flac, wav, ogg, opus, m4a, aac, wma, webm)
- 재생 모드: 순차, 한곡 반복, 전체 반복, 체크항목 반복, 전체 랜덤, 체크항목 랜덤
- A-B 구간 반복
- 체크박스 기반 재생 대상 제어
- 드래그 앤 드롭 (파일 추가 / 순서 변경)
- 재생 장치 선택
- 트레이 아이콘 (종료 시 트레이로 최소화)
- 단일 인스턴스 (중복 실행 시 기존 창에 파일 추가)
- 재생목록 및 설정 자동 저장/복원
- 이전 창 크기로 복원
- 태그 읽기/편집 (title, artist, album)
- 글꼴 및 크기 설정
- 최상위 창 고정
- 실행 시 자동 재생
- 재생목록 검색 (제목, 아티스트 실시간 필터링)
- 우클릭 메뉴: 폴더 열기, 태그편집, 삭제, 파일 추가, foobar2000 가져오기
- 리스트 항목 툴팁 (아티스트 - 제목)

## 단축키

| 키 | 동작 |
|----|------|
| Space | 재생/일시정지 |
| Left | 5초 뒤로 |
| Right | 5초 앞으로 |
| Delete | 선택 항목 삭제 |
| Home | 리스트 맨 위로 |
| End | 리스트 맨 아래로 |

## 실행
```
pip install requirements.txt
python main.py
```

## 기본 앱 등록

`.flac`, `.mp3` 등 음악 파일을 더블클릭하여 이 플레이어로 열려면 실행 파일(`.exe`)이 필요합니다.

### 방법 1: PyInstaller로 exe 빌드 (권장)

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile main.pyw
```

생성된 `dist/main.exe`를 원하는 위치에 복사한 뒤, 음악 파일 우클릭 → **연결 프로그램** → **다른 앱 선택**에서 해당 exe를 지정합니다.

### 방법 2: bat 래퍼 파일 생성

`pyMusic.bat` 파일을 만들고 아래 내용을 작성합니다:

```bat
@echo off
pythonw "D:\Sources\python\pyMusic\main.pyw" "%1"
```

이 `.bat` 파일을 기본 앱으로 지정합니다.

## 라이선스

이 프로젝트는 MIT License에 따라 배포됩니다.

---

*이 프로젝트는 Claude Opus 4.6을 활용하여 작성되었습니다.*
