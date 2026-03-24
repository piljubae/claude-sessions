# organize-sessions

`organize-sessions [--recent]`

Claude Code 세션 대화 내역을 자동 분류·요약하여 `~/claude-sessions/` 에 정리합니다.

## 동작

1. `~/.claude/usage-data/session-meta/` 와 `~/.claude/projects/` 에서 세션 데이터 수집
2. 처리 완료된 세션은 스킵 (증분 처리)
3. 티켓 패턴(KMA-1234 등)으로 자동 분류 → 없으면 프로젝트명 → 없으면 `misc/`
4. Haiku 모델로 제목·요약 생성
5. `~/claude-sessions/index.md` 갱신

## 옵션

- `--recent` : 최근 7일 세션만 처리
- `--regen` : 기존 요약 파일 삭제 후 AI로 전체 재생성

## 출력 구조

```
~/claude-sessions/
├── index.md
├── .processed
├── KMA-7033/
│   └── 2026-02-25_review-jira-ticket.md
├── kurly-android/
│   └── 2026-03-20_compose-migration.md
└── misc/
    └── 2026-03-23_general-question.md
```

## 이어서 작업하기

```bash
claude "$(cat ~/claude-sessions/KMA-7033/2026-02-25_review-jira-ticket.md) 여기서 이어서 작업해줘"
```

## 실행

이 스킬을 호출하면 아래 명령을 실행하세요:

```bash
python3 ~/scripts/organize-sessions.py
```

`--recent` 옵션이 지정된 경우:

```bash
python3 ~/scripts/organize-sessions.py --recent
```

완료 후 `~/claude-sessions/index.md` 경로와 새로 처리된 세션 수를 사용자에게 알려주세요.
