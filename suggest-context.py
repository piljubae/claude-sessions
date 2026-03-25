#!/usr/bin/env python3
"""
UserPromptSubmit 훅: 새 세션 첫 메시지에서 유사 세션 찾아 컨텍스트 주입
"""

import json
import os
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

HOME = Path.home()
SESSIONS_DIR = HOME / "Documents/Claude Cowork/claude-sessions"
SHOWN_DIR = HOME / ".claude/session-context-shown"
TICKET_PATTERN = re.compile(r"\b([A-Za-z]+-\d+)\b")

# 동의어 그룹 (한국어 ↔ 영어 상호 확장)
SYNONYM_GROUPS: list[set[str]] = [
    {"코드리뷰", "코드 리뷰", "리뷰", "review", "code review", "pr review", "pull request"},
    {"버그", "bug", "fix", "수정", "hotfix", "오류", "에러", "error", "crash", "크래시"},
    {"리팩터링", "리팩토링", "refactor", "refactoring", "개선", "cleanup", "정리"},
    {"테스트", "test", "testing", "unit test", "테스팅"},
    {"배포", "deploy", "deployment", "release", "릴리즈", "cd"},
    {"기능", "feature", "기능개발", "신규", "구현"},
    {"성능", "performance", "최적화", "optimization", "perf", "속도"},
    {"디버그", "debug", "debugging", "트러블슈팅", "troubleshooting"},
    {"인증", "auth", "authentication", "login", "로그인"},
    {"api", "endpoint", "서버", "server", "백엔드", "backend"},
    {"컴포즈", "compose", "jetpack compose", "jetpack", "composable"},
    {"안드로이드", "android"},
    {"스킬", "skill", "skills", "command"},
    {"훅", "hook", "hooks"},
    {"worktree", "워크트리"},
    {"플랜", "plan", "planning", "계획"},
    {"빌드", "build", "gradle", "compile", "컴파일"},
    {"마이그레이션", "migration", "migrate", "이전"},
]

_SYNONYM_LOOKUP: dict[str, set[str]] = {}
for _group in SYNONYM_GROUPS:
    for _term in _group:
        _SYNONYM_LOOKUP[_term] = _group


def expand_keywords(keywords: set[str]) -> set[str]:
    """동의어로 키워드 확장"""
    expanded = set()
    for kw in keywords:
        expanded.add(kw)
        if kw in _SYNONYM_LOOKUP:
            expanded |= _SYNONYM_LOOKUP[kw]
    return expanded


def is_first_message(session_id: str) -> bool:
    """이 세션에서 처음 호출인지 확인"""
    SHOWN_DIR.mkdir(parents=True, exist_ok=True)
    marker = SHOWN_DIR / session_id
    if marker.exists():
        return False
    marker.touch()
    # 24시간 지난 마커 정리
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for f in SHOWN_DIR.iterdir():
        try:
            if datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc) < cutoff:
                f.unlink()
        except Exception:
            pass
    return True


def get_git_branch(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd, capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return ""


def extract_keywords(text: str) -> set[str]:
    """한국어/영어 키워드 추출 (짧은 단어 제외)"""
    words = re.findall(r"[A-Za-z가-힣][A-Za-z가-힣0-9_-]*", text)
    stop = {"있어", "해줘", "해서", "하고", "이야", "인데", "이거", "그거", "the", "and", "for", "with", "this", "that"}
    return {w.lower() for w in words if len(w) >= 3 and w.lower() not in stop}


def score_session(md_path: Path, ticket: str, project: str, keywords: set[str]) -> float:
    """세션 유사도 점수 계산"""
    try:
        content = md_path.read_text()
    except Exception:
        return 0.0

    score = 0.0
    folder = md_path.parent.name.upper()

    # 티켓 일치 (최고 우선순위)
    if ticket and folder == ticket.upper():
        score += 10.0
    elif ticket and ticket.upper() in content.upper():
        score += 5.0

    # 프로젝트 일치
    if project and project.lower() in folder.lower():
        score += 3.0

    # 태그 매칭 (가중치 높음)
    content_lower = content.lower()
    tags_m = re.search(r"\*\*tags\*\*:\s*(.+)$", content_lower, re.MULTILINE)
    if tags_m:
        tags = {t.strip() for t in tags_m.group(1).split(",")}
        matched_tags = sum(1 for kw in keywords if kw in tags)
        score += matched_tags * 3.0

    # 키워드 매칭 (동의어 포함)
    matched = sum(1 for kw in keywords if kw in content_lower)
    score += matched * 0.5

    return score


def find_similar_sessions(cwd: str, branch: str, prompt: str, top_n: int = 3) -> list[dict]:
    if not SESSIONS_DIR.exists():
        return []

    ticket = ""
    m = TICKET_PATTERN.search(branch) or TICKET_PATTERN.search(cwd) or TICKET_PATTERN.search(prompt)
    if m:
        ticket = m.group(1).upper()

    # 프로젝트명 추출
    project = ""
    wt_match = re.search(r"/([^/]+)/\.claude/worktrees/", cwd)
    if wt_match:
        project = wt_match.group(1)
    elif cwd:
        p = Path(cwd)
        if p != HOME and len(p.parts) > 3:
            project = p.name

    keywords = expand_keywords(extract_keywords(prompt))

    results = []
    for md in SESSIONS_DIR.rglob("*.md"):
        if md.name == "index.md":
            continue
        score = score_session(md, ticket, project, keywords)
        if score > 0:
            try:
                content = md.read_text()
                title_m = re.search(r"^# (.+)$", content, re.MULTILINE)
                date_m = re.search(r"\*\*Date\*\*: (\d{4}-\d{2}-\d{2})", content)
                dur_m = re.search(r"\*\*Duration\*\*: (\d+)분", content)
                title = title_m.group(1) if title_m else md.stem
                date = date_m.group(1) if date_m else ""
                duration = dur_m.group(1) if dur_m else ""
                results.append({
                    "score": score,
                    "title": title[:50],
                    "date": date,
                    "duration": duration,
                    "folder": md.parent.name,
                    "path": str(md),
                })
            except Exception:
                pass

    results.sort(key=lambda x: (-x["score"], x["date"]), reverse=False)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    session_id = data.get("session_id", "")
    if not session_id or not is_first_message(session_id):
        sys.exit(0)

    # 첫 번째 유저 메시지 텍스트 추출
    prompt = ""
    for block in data.get("message", {}).get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            prompt += block.get("text", "")
        elif isinstance(block, str):
            prompt += block

    cwd = data.get("cwd", os.getcwd())
    branch = get_git_branch(cwd)

    similar = find_similar_sessions(cwd, branch, prompt)
    if not similar:
        sys.exit(0)

    # 후보 목록을 마커 디렉토리에 저장 (사용자가 선택 시 Claude가 참조)
    CONTINUATIONS_DIR = HOME / ".claude/session-continuations"
    CONTINUATIONS_DIR.mkdir(parents=True, exist_ok=True)
    candidates_file = CONTINUATIONS_DIR / f"{session_id}.candidates.json"
    candidates_file.write_text(json.dumps([s["path"] for s in similar]))

    # 컨텍스트 출력 (Claude가 읽음)
    lines = ["[관련 이전 세션 발견]"]
    for i, s in enumerate(similar):
        dur_str = f" ({s['duration']}분)" if s["duration"] else ""
        lines.append(f"{i+1}. {s['date']} [{s['folder']}] {s['title']}{dur_str}")
        lines.append(f"   파일: {s['path']}")

    lines += [
        "",
        "위 세션과 관련된 작업이면, 사용자에게 번호와 함께 간단히 소개하고 이어서 할지 물어보세요.",
        "사용자가 이어서 하겠다고 하면, 반드시 아래 Bash 명령을 실행해서 마커를 남기세요:",
        f"  echo '<선택한 파일 경로>' > ~/.claude/session-continuations/{session_id}.chosen",
        "(선택한 파일 경로는 위 '파일:' 줄의 경로로 대체)",
    ]

    print("\n".join(lines))


if __name__ == "__main__":
    main()
