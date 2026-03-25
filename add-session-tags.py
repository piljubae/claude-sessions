#!/usr/bin/env python3
"""
세션 파일에 **Tags**: 메타데이터 일괄 추가
내용 분석 → 카테고리 태그 자동 부여

태그 룰: ~/.claude/session-tag-rules.json (없으면 기본값으로 자동 생성)
"""

import json
import re
import sys
from pathlib import Path

SESSIONS_DIR = Path.home() / "Documents/Claude Cowork/claude-sessions"
TAG_RULES_FILE = Path.home() / ".claude/session-tag-rules.json"

DEFAULT_TAG_RULES: dict[str, list[str]] = {
    "code-review":  ["코드리뷰", "코드 리뷰", "code review", "pr 리뷰", "pr리뷰", "리뷰 반영", "리뷰 준비", "review"],
    "compose":      ["compose", "composable", "컴포즈", "jetpack"],
    "android":      ["android", "안드로이드", "activity", "fragment", "viewmodel", "kotlin"],
    "tdd":          ["tdd", " 테스트 케이스", "unit test", "테스팅"],
    "debugging":    ["디버깅", "debug", "crash", "크래시", "오류 수정", "에러 해결", "컴파일 오류", "컴파일 에러"],
    "refactoring":  ["리팩터링", "리팩토링", "refactor", "stepprofile", "리펙토링"],
    "planning":     ["플랜", "planning", "브레인스토밍", "brainstorm", "설계", "계획"],
    "build":        ["빌드", "gradle", "컴파일", "compile"],
    "skill":        ["스킬", "skill", "command"],
    "hook":         ["훅", "hook"],
    "worktree":     ["워크트리", "worktree"],
    "git":          ["커밋", "commit", "branch", "push", "pull request"],
    "claude-code":  ["claude code", "claude-code", "claude 설정", "mcp"],
    "jira":         ["jira", "티켓 작업"],
    "slack":        ["slack"],
    "deploy":       ["배포", "deploy", "release", "릴리즈"],
    "performance":  ["성능", "performance", "최적화", "optimization"],
    "weekly":       ["주간", "weekly", "weekly summary"],
    "daily":        ["daily", "데일리"],
    "pr":           ["pr #", "pull request", "pr 리뷰", "pr리뷰", "코드 리뷰"],
}


def load_tag_rules() -> dict[str, list[str]]:
    """TAG_RULES_FILE 로드. 없으면 기본값으로 파일 생성."""
    if TAG_RULES_FILE.exists():
        try:
            data = json.loads(TAG_RULES_FILE.read_text())
            if isinstance(data, dict):
                return {k: v for k, v in data.items()
                        if isinstance(v, list) and not k.startswith("_")}
        except Exception as e:
            print(f"[WARN] {TAG_RULES_FILE} 로드 실패, 기본값 사용: {e}", file=sys.stderr)
            return DEFAULT_TAG_RULES.copy()
    # 파일 없음 → 기본값으로 생성
    TAG_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    TAG_RULES_FILE.write_text(
        json.dumps(DEFAULT_TAG_RULES, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"[INFO] 태그 룰 파일 생성: {TAG_RULES_FILE}")
    return DEFAULT_TAG_RULES.copy()


TAG_RULES = load_tag_rules()


def determine_tags(folder: str, filename: str, content: str) -> list[str]:
    haystack = (folder + " " + filename + " " + content).lower()
    tags = []

    # 폴더명이 티켓이면 티켓 태그
    ticket_m = re.match(r"^([a-z]+-\d+)$", folder.lower())
    if ticket_m:
        tags.append(ticket_m.group(1).upper())

    for tag, keywords in TAG_RULES.items():
        if any(kw in haystack for kw in keywords):
            tags.append(tag)

    # 중복 제거, 티켓 먼저
    seen = set()
    result = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def insert_tags(content: str, tags: list[str]) -> str:
    """**Duration** 또는 **Model** 줄 다음에 Tags 삽입"""
    tag_line = f"- **Tags**: {', '.join(tags)}"

    m = re.search(r"(- \*\*Duration\*\*: .+)", content)
    if m:
        return content.replace(m.group(1), m.group(1) + "\n" + tag_line, 1)

    m = re.search(r"(- \*\*Model\*\*: .+)", content)
    if m:
        return content.replace(m.group(1), m.group(1) + "\n" + tag_line, 1)

    m = re.search(r"(\n\n)", content)
    if m:
        return content[:m.start()] + "\n" + tag_line + content[m.start():]

    return content + "\n" + tag_line


def replace_tags(content: str, tags: list[str]) -> str:
    """기존 Tags 줄을 새 값으로 교체"""
    tag_line = f"- **Tags**: {', '.join(tags)}"
    return re.sub(r"- \*\*Tags\*\*: .+", tag_line, content, flags=re.IGNORECASE)


def main():
    dry_run = "--dry-run" in sys.argv
    update = "--update" in sys.argv

    files = sorted(SESSIONS_DIR.rglob("*.md"))
    files = [f for f in files if f.name != "index.md"]

    added = 0
    updated = 0
    skipped = 0

    for path in files:
        try:
            content = path.read_text()
        except Exception as e:
            print(f"[ERROR] {path}: {e}")
            continue

        folder = path.parent.name
        has_tags = bool(re.search(r"\*\*Tags\*\*:", content, re.IGNORECASE))

        if has_tags and not update:
            skipped += 1
            continue

        tags = determine_tags(folder, path.stem, content)
        if not tags:
            skipped += 1
            continue

        tag_str = ", ".join(tags)

        if has_tags:
            existing_m = re.search(r"\*\*Tags\*\*: (.+)", content, re.IGNORECASE)
            if existing_m and existing_m.group(1).strip() == tag_str:
                skipped += 1
                continue
            new_content = replace_tags(content, tags)
            label = "UPD"
            updated += 1
        else:
            new_content = insert_tags(content, tags)
            label = "OK "
            added += 1

        if dry_run:
            print(f"[DRY/{label}] {path.relative_to(SESSIONS_DIR)}  →  {tag_str}")
        else:
            path.write_text(new_content)
            print(f"[{label}]  {path.relative_to(SESSIONS_DIR)}  →  {tag_str}")

    print(f"\n총 {len(files)}개 중 신규: {added}개, 업데이트: {updated}개, 스킵: {skipped}개")


if __name__ == "__main__":
    main()
