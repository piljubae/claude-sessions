# load-context

`load-context <query>`

과거 Claude 세션 요약에서 맥락을 검색하여 현재 대화에 로드합니다.

## 실행 순서

1. **검색**: 아래 명령으로 매칭 파일 목록 조회

```bash
grep -ril "<query>" "CLAUDE_SESSIONS_DIR" --include="*.md" | grep -v "index\.md" | sort -r | head -10
```

2. **읽기**: 매칭된 파일을 최대 5개까지 Read 툴로 읽기
   - 파일 수가 많으면 날짜 최신순으로 선택

3. **요약 제시**: 읽은 내용을 다음 형식으로 정리하여 현재 대화에 로드

```
## 로드된 세션 맥락

### [날짜] 제목
- **브랜치**: ...
- **요약**: ...
- **미결 사항**: (있는 경우만)
  - [ ] ...
- **원본 세션**: `<UUID>` → 재개 시 `claude --resume <UUID>`
```

## 옵션

- `load-context KMA-7277` — 티켓 번호로 검색
- `load-context benchmark` — 키워드로 검색
- `load-context 2026-03-12` — 날짜로 검색
- `load-context code-review --recent` — 최근 7일로 제한

`--recent` 옵션이 있으면 grep 결과에서 최근 7일 날짜 패턴만 필터링.

## 주의

- 매칭 결과가 없으면 "관련 세션을 찾지 못했습니다" 안내
- 미결 사항이 있는 세션은 상단에 배치
- 세션 원본 재개가 필요하면 `원본 세션` 경로에서 UUID 추출하여 안내
