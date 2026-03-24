# Claude Sessions Organizer

Claude Code 세션 대화 내역을 자동으로 분류·요약하고, 새 세션 시작 시 관련 이전 세션을 제안해주는 도구입니다.

## 기능

- **자동 분류**: Jira 티켓(KMA-1234 등) 또는 프로젝트명 기준으로 세션 분류
- **AI 요약**: 각 세션의 제목과 내용을 Haiku 모델로 요약
- **컨텍스트 제안**: 새 세션 시작 시 관련 이전 세션을 자동으로 찾아 제안
- **이어쓰기**: 이전 세션을 선택해 이어서 작업하면 요약 파일에 내용 추가
- **매일 자동 실행**: LaunchAgent로 매일 09:00에 새 세션 처리

## 출력 구조

```
~/Documents/Claude Cowork/claude-sessions/
├── index.md
├── .processed
├── KMA-7033/
│   └── 2026-02-25_review-jira-ticket.md
├── kurly-android/
│   └── 2026-03-20_compose-migration.md
└── misc/
    └── 2026-03-23_general-question.md
```

## 설치

```bash
git clone https://github.com/piljubae/claude-sessions.git
cd claude-sessions
bash install.sh
```

설치 중 두 가지를 물어봅니다:
1. 세션 저장 경로 (기본값: `~/Documents/Claude Cowork/claude-sessions`)
2. Claude 바이너리 경로 (기본값: `/opt/homebrew/bin/claude`)

그 외 모든 설정은 자동으로 처리됩니다.

## 수동 실행

```bash
python3 ~/scripts/organize-sessions.py           # 전체 처리
python3 ~/scripts/organize-sessions.py --recent  # 최근 7일만
python3 ~/scripts/organize-sessions.py --regen   # AI 요약 전체 재생성
```

## 이어서 작업하기

```bash
claude "$(cat ~/Documents/Claude\ Cowork/claude-sessions/KMA-7033/2026-02-25_xxx.md) 여기서 이어서 작업해줘"
```

또는 세션 ID로 직접 재개:

```bash
claude --resume <session-id>
```

## 요구사항

- macOS
- Python 3.10+
- [Claude Code CLI](https://claude.ai/code)
- `pip3 install anthropic` (install.sh가 자동 설치)
