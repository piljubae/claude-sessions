#!/usr/bin/env python3
"""
Claude Sessions Organizer
CLI 세션 대화 내역을 자동 분류 + 요약하여 ~/claude-sessions/ 에 저장
"""

import json
import os
import re
import glob
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
HOME = Path.home()
META_DIR = HOME / ".claude/usage-data/session-meta"
PROJECTS_DIR = HOME / ".claude/projects"
OUTPUT_DIR = HOME / "Documents/Claude Cowork/claude-sessions"
PROCESSED_FILE = OUTPUT_DIR / ".processed"
INDEX_FILE = OUTPUT_DIR / "index.md"
CLAUDE_BIN = "/opt/homebrew/bin/claude"
TAG_RULES_FILE = HOME / ".claude/session-tag-rules.json"
SYNONYMS_FILE = HOME / ".claude/session-synonyms.json"

TICKET_PATTERN = re.compile(r"\b([A-Za-z]+-\d+)\b")
CONTINUATIONS_DIR = HOME / ".claude/session-continuations"

# ─── 유틸 함수 ─────────────────────────────────────────────────────────────────

def load_processed() -> set:
    if not PROCESSED_FILE.exists():
        return set()
    return set(PROCESSED_FILE.read_text().splitlines())


def save_processed(processed: set):
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text("\n".join(sorted(processed)) + "\n")


def slugify(text: str) -> str:
    """제목을 파일명 슬러그로 변환"""
    text = re.sub(r"[^\w\s가-힣-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:60].lower()


def find_jsonl(session_id: str) -> Optional[Path]:
    """session_id로 JSONL 파일 찾기"""
    candidates = list(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
    return candidates[0] if candidates else None


def extract_session_details(jsonl_path: Path) -> dict:
    """JSONL에서 gitBranch, cwd, model, user messages 추출"""
    git_branch = ""
    cwd = ""
    model = ""
    user_msgs = []

    with open(jsonl_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            t = d.get("type")

            if t == "user" and not git_branch:
                git_branch = d.get("gitBranch", "")
                cwd = d.get("cwd", "")

            if t == "user" and len(user_msgs) < 12:
                msg = d.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item["text"].strip()
                            if text:
                                user_msgs.append(text)
                elif isinstance(content, str) and content.strip():
                    user_msgs.append(content.strip())

            if t == "assistant" and not model:
                model = d.get("message", {}).get("model", "")

    return {
        "git_branch": git_branch,
        "cwd": cwd,
        "model": model,
        "user_msgs": user_msgs,
    }


def extract_ticket(branch: str, cwd: str) -> str:
    """브랜치명/CWD에서 티켓 패턴 추출"""
    for text in [branch, cwd]:
        m = TICKET_PATTERN.search(text)
        if m:
            return m.group(1).upper()
    return ""


def extract_project_name(project_path: str, cwd: str) -> str:
    """project_path/cwd에서 프로젝트명 추출"""
    # 워크트리 경로 처리: .../project-name/.claude/worktrees/xxx
    for path in [project_path, cwd]:
        if not path:
            continue
        # 워크트리 패턴
        wt_match = re.search(r"/([^/]+)/\.claude/worktrees/", path)
        if wt_match:
            return wt_match.group(1)
        # 일반 프로젝트
        p = Path(path)
        # home이나 빈 경로 제외
        if p != HOME and len(p.parts) > 3:
            return p.name

    return "misc"


def normalize_project_folder(project_name: str) -> str:
    """프로젝트명 → 폴더명 정규화"""
    # daily-summary-env → daily-summary
    name = project_name.lower()
    name = re.sub(r"[-_]env$", "", name)
    name = re.sub(r"[-_]worktrees?$", "", name)
    return name or "misc"


def generate_summary(first_prompt: str, user_msgs: list[str], session_info: dict) -> dict:
    """Claude CLI로 제목 + 요약 생성"""
    conversation = "\n\n".join([f"[사용자]: {m}" for m in user_msgs[:10]])
    # 너무 길면 자르기
    if len(conversation) > 6000:
        conversation = conversation[:6000] + "\n...(이하 생략)"

    prompt = f"""다음은 Claude Code 세션의 사용자 메시지들입니다.

{conversation}

위 대화를 분석하여 다음 JSON 형식으로 응답하세요:
{{
  "title": "세션 제목 (20자 이내, 한국어, 무엇을 했는지 구체적으로)",
  "summary": "3~5줄 요약 (무엇을 했고, 어떤 결정을 내렸는지)",
  "changed_files": ["변경된 주요 파일 목록 (대화에서 언급된 것만, 없으면 빈 배열)"],
  "todos": ["미결 사항 (대화에서 언급된 것만, 없으면 빈 배열)"]
}}

JSON만 응답하고 다른 텍스트는 포함하지 마세요."""

    try:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--no-session-persistence", "--model", "haiku"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        output = result.stdout.strip()
        # JSON 블록 추출
        json_match = re.search(r"\{.*\}", output, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        pass

    # 실패 시 기본값
    return {
        "title": first_prompt[:40] if first_prompt else "제목 없음",
        "summary": first_prompt[:200] if first_prompt else "",
        "changed_files": [],
        "todos": [],
    }


def suggest_new_mappings(new_sessions: list[dict]) -> None:
    """새 세션 배치 분석 → 신규 태그 룰/동의어 제안 → JSON 파일 병합"""
    if not new_sessions:
        return

    tag_rules: dict = {}
    if TAG_RULES_FILE.exists():
        try:
            tag_rules = json.loads(TAG_RULES_FILE.read_text())
        except Exception:
            pass

    synonyms: list = []
    if SYNONYMS_FILE.exists():
        try:
            synonyms = json.loads(SYNONYMS_FILE.read_text())
        except Exception:
            pass

    session_texts = "\n".join(
        f"- 제목: {s['title']}\n  요약: {s['summary'][:200]}"
        for s in new_sessions[:20]
    )
    existing_tags = ", ".join(tag_rules.keys())
    sample_synonyms = [g[:3] for g in synonyms[:8]]

    prompt = f"""세션 태그 시스템에 새 세션들이 추가됐습니다. 기존 룰에 없거나 부족한 태그/동의어를 제안해주세요.

현재 태그 목록: {existing_tags}
현재 동의어 샘플: {sample_synonyms}

새 세션 목록:
{session_texts}

규칙:
- 기존 태그에 빠진 키워드 추가 (extend_tag_rules)
- 완전히 새 카테고리 추가 (new_tag_rules)
- 새 동의어 그룹 추가 (new_synonym_groups)
- 추가할 게 없으면 빈 값으로

JSON만 응답:
{{
  "new_tag_rules": {{"태그명": ["키워드1", "키워드2"]}},
  "extend_tag_rules": {{"기존태그명": ["추가키워드"]}},
  "new_synonym_groups": [["유사어1", "유사어2"]]
}}"""

    try:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--no-session-persistence", "--model", "haiku"],
            input=prompt, capture_output=True, text=True, timeout=60, env=env,
        )
        json_match = re.search(r"\{.*\}", result.stdout.strip(), re.DOTALL)
        if not json_match:
            print("  응답 파싱 실패")
            return
        suggestions = json.loads(json_match.group())
    except Exception as e:
        print(f"  [WARN] 매핑 제안 실패: {e}")
        return

    tag_changed = False
    for tag, kws in suggestions.get("new_tag_rules", {}).items():
        if tag not in tag_rules and isinstance(kws, list) and kws:
            tag_rules[tag] = kws
            print(f"  [태그 신규] {tag}: {kws}")
            tag_changed = True

    for tag, kws in suggestions.get("extend_tag_rules", {}).items():
        if tag in tag_rules and isinstance(kws, list):
            existing = set(tag_rules[tag])
            additions = [k for k in kws if k not in existing]
            if additions:
                tag_rules[tag] = tag_rules[tag] + additions
                print(f"  [태그 확장] {tag}: +{additions}")
                tag_changed = True

    if tag_changed:
        TAG_RULES_FILE.write_text(json.dumps(tag_rules, ensure_ascii=False, indent=2) + "\n")

    syn_changed = False
    existing_terms = {term for group in synonyms for term in group}
    for group in suggestions.get("new_synonym_groups", []):
        if isinstance(group, list) and not any(t in existing_terms for t in group):
            synonyms.append(group)
            existing_terms.update(group)
            print(f"  [동의어 추가] {group}")
            syn_changed = True

    if syn_changed:
        SYNONYMS_FILE.write_text(json.dumps(synonyms, ensure_ascii=False, indent=2) + "\n")

    if not tag_changed and not syn_changed:
        print("  신규 매핑 없음")


def extract_meta_from_jsonl(jsonl_path: Path) -> Optional[dict]:
    """JSONL 파일에서 session-meta 구조로 메타데이터 추출 (session-meta 없는 신규 세션용)"""
    session_id = None
    start_time = None
    end_time = None
    first_prompt = None
    cwd = None

    with open(jsonl_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not session_id:
                session_id = d.get("sessionId")

            if not cwd and d.get("cwd"):
                cwd = d.get("cwd")

            ts = d.get("timestamp")
            if ts:
                if not start_time:
                    start_time = ts
                end_time = ts

            if not first_prompt and d.get("type") == "user" and not d.get("isMeta"):
                msg = d.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    first_prompt = content.strip()
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item["text"].strip()
                            if text:
                                first_prompt = text
                                break

    if not session_id or not start_time:
        return None

    duration = 0.0
    if start_time and end_time:
        try:
            from datetime import datetime as _dt
            dt_s = _dt.fromisoformat(start_time.replace("Z", "+00:00"))
            dt_e = _dt.fromisoformat(end_time.replace("Z", "+00:00"))
            duration = (dt_e - dt_s).total_seconds() / 60
        except Exception:
            pass

    return {
        "session_id": session_id,
        "start_time": start_time,
        "first_prompt": first_prompt or "",
        "project_path": cwd or "",
        "duration_minutes": duration,
    }


def get_chosen_file(session_id: str) -> Optional[Path]:
    """이 세션이 이어쓰기로 선택된 파일 경로 반환"""
    marker = CONTINUATIONS_DIR / f"{session_id}.chosen"
    if not marker.exists():
        return None
    path_str = marker.read_text().strip()
    path = Path(path_str)
    return path if path.exists() else None


def append_to_session_file(target_path: Path, meta: dict, details: dict, summary_data: dict):
    """기존 세션 파일에 새 세션 내용 추가"""
    date_str = meta["start_time"][:10]
    duration = meta.get("duration_minutes", 0)
    dur_str = f" ({int(duration)}분)" if duration else ""

    jsonl = find_jsonl(meta["session_id"])

    lines = [
        "",
        "---",
        "",
        f"## 이어진 세션 — {date_str}{dur_str}",
        "",
        summary_data["summary"] or "(요약 없음)",
    ]

    if summary_data.get("changed_files"):
        lines += ["", "**변경된 파일**", ""]
        for f in summary_data["changed_files"]:
            lines.append(f"- `{f}`")

    if summary_data.get("todos"):
        lines += ["", "**미결 사항**", ""]
        for t in summary_data["todos"]:
            lines.append(f"- [ ] {t}")

    if jsonl:
        lines += ["", f"원본: `{jsonl}`"]

    existing = target_path.read_text().rstrip("\n")
    target_path.write_text(existing + "\n" + "\n".join(lines) + "\n")

    # 마커 정리
    marker = CONTINUATIONS_DIR / f"{meta['session_id']}.chosen"
    if marker.exists():
        marker.unlink()


def write_session_file(output_path: Path, meta: dict, details: dict, summary_data: dict):
    """세션 요약 마크다운 파일 작성"""
    date_str = meta["start_time"][:10]
    project_path = meta.get("project_path", "")
    worktree_name = ""

    wt_match = re.search(r"/worktrees/([^/]+)$", project_path)
    if wt_match:
        worktree_name = wt_match.group(1)

    base_project = re.sub(r"/\.claude/worktrees/.*$", "", project_path)

    lines = [
        f"# {summary_data['title']}",
        "",
        f"- **Date**: {date_str}",
        f"- **Project**: {Path(base_project).name if base_project else 'unknown'}",
        f"- **Branch**: {details['git_branch'] or '(없음)'}",
    ]

    ticket = extract_ticket(details["git_branch"], details["cwd"])
    if ticket:
        lines.append(f"- **Ticket**: {ticket}")

    if details["model"]:
        lines.append(f"- **Model**: {details['model']}")
    if worktree_name:
        lines.append(f"- **Worktree**: {worktree_name}")

    duration = meta.get("duration_minutes", 0)
    if duration:
        lines.append(f"- **Duration**: {int(duration)}분")

    lines += [
        "",
        "## 대화 요약",
        "",
        summary_data["summary"] or "(요약 없음)",
    ]

    if summary_data.get("changed_files"):
        lines += ["", "## 변경된 파일", ""]
        for f in summary_data["changed_files"]:
            lines.append(f"- `{f}`")

    if summary_data.get("todos"):
        lines += ["", "## 미결 사항", ""]
        for t in summary_data["todos"]:
            lines.append(f"- [ ] {t}")

    # 원본 세션 경로
    jsonl = find_jsonl(meta["session_id"])
    if jsonl:
        lines += [
            "",
            "## 원본 세션",
            "",
            f"`{jsonl}`",
        ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")


def update_index(entries: list[dict]):
    """index.md 갱신 (날짜순 내림차순)"""
    entries.sort(key=lambda x: x["date"], reverse=True)

    lines = [
        "# Claude Sessions Index",
        "",
        f"_마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
        "| 날짜 | 제목 | 프로젝트/티켓 | 파일 |",
        "|------|------|---------------|------|",
    ]

    for e in entries:
        rel_path = e["path"].relative_to(OUTPUT_DIR)
        lines.append(
            f"| {e['date']} | {e['title']} | {e['folder']} | [{rel_path}]({rel_path}) |"
        )

    INDEX_FILE.write_text("\n".join(lines) + "\n")


# ─── 메인 ──────────────────────────────────────────────────────────────────────

def process_sessions(recent_only: bool = False, regen: bool = False):
    processed = load_processed()
    if regen:
        # 기존 세션 파일 전부 삭제 후 재처리
        for md in OUTPUT_DIR.rglob("*.md"):
            if md == INDEX_FILE:
                continue
            md.unlink()
        processed.clear()
        save_processed(processed)
        print("기존 요약 파일 삭제 완료 → 재생성 시작")

    new_count = 0
    index_entries = []
    new_sessions_data: list[dict] = []

    from datetime import timedelta
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=7) if recent_only else None
    cutoff_str = cutoff_dt.isoformat() if cutoff_dt else None

    # session-meta 기반 세션 수집
    meta_files = sorted(META_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if cutoff_str:
        meta_files_filtered = []
        for mf in meta_files:
            try:
                with open(mf) as f:
                    meta = json.load(f)
                if meta.get("start_time", "") >= cutoff_str:
                    meta_files_filtered.append(mf)
            except Exception:
                pass
        meta_files = meta_files_filtered

    # JSONL 직접 스캔 (session-meta 없는 신규 세션)
    jsonl_files = sorted(PROJECTS_DIR.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if cutoff_dt:
        jsonl_files = [
            jf for jf in jsonl_files
            if datetime.fromtimestamp(jf.stat().st_mtime, tz=timezone.utc) >= cutoff_dt
        ]

    # session-meta에 없는 JSONL 세션을 meta 구조로 변환
    meta_session_ids = set()
    for mf in meta_files:
        try:
            with open(mf) as f:
                meta_session_ids.add(json.load(f)["session_id"])
        except Exception:
            pass

    jsonl_metas = []
    for jf in jsonl_files:
        sid = jf.stem
        if sid in meta_session_ids or sid in processed:
            continue
        m = extract_meta_from_jsonl(jf)
        if m:
            jsonl_metas.append(m)

    all_metas = []
    for mf in meta_files:
        try:
            with open(mf) as f:
                all_metas.append(json.load(f))
        except Exception:
            pass
    all_metas.extend(jsonl_metas)
    all_metas.sort(key=lambda m: m.get("start_time", ""), reverse=True)

    total = len(all_metas)
    print(f"총 {total}개 세션 발견 (처리 완료: {len(processed)}개)")

    for i, meta in enumerate(all_metas, 1):
        sid = meta["session_id"]

        if sid in processed:
            continue

        jsonl = find_jsonl(sid)
        if not jsonl:
            print(f"[{i}/{total}] {sid[:8]}... JSONL 없음, 스킵")
            processed.add(sid)
            continue

        print(f"[{i}/{total}] {sid[:8]}... 처리 중", end="", flush=True)

        details = extract_session_details(jsonl)
        date_str = meta["start_time"][:10]
        first_prompt = meta.get("first_prompt", "")

        print(" → AI 요약 생성 중...", end="", flush=True)
        summary_data = generate_summary(first_prompt, details["user_msgs"], meta)

        # 이어쓰기 마커 확인
        chosen_file = get_chosen_file(sid)
        if chosen_file:
            append_to_session_file(chosen_file, meta, details, summary_data)
            processed.add(sid)
            new_count += 1
            print(f" → (이어쓰기) {chosen_file.relative_to(OUTPUT_DIR)}")
            index_entries.append({
                "date": date_str,
                "title": summary_data["title"],
                "folder": chosen_file.parent.name,
                "path": chosen_file,
            })
            continue

        ticket = extract_ticket(details["git_branch"], details["cwd"])
        project_name = extract_project_name(meta.get("project_path", ""), details["cwd"])
        folder = ticket if ticket else normalize_project_folder(project_name)

        title = summary_data["title"]
        slug = slugify(title)
        filename = f"{date_str}_{slug}.md"

        output_path = OUTPUT_DIR / folder / filename
        counter = 1
        while output_path.exists():
            output_path = OUTPUT_DIR / folder / f"{date_str}_{slug}_{counter}.md"
            counter += 1

        write_session_file(output_path, meta, details, summary_data)
        processed.add(sid)
        new_count += 1
        new_sessions_data.append({
            "title": summary_data["title"],
            "summary": summary_data.get("summary", ""),
        })

        print(f" → {folder}/{filename}")

        index_entries.append({
            "date": date_str,
            "title": title,
            "folder": folder,
            "path": output_path,
        })

    save_processed(processed)

    # index.md 전체 재빌드 (기존 파일들도 포함)
    all_entries = []
    for md in OUTPUT_DIR.rglob("*.md"):
        if md == INDEX_FILE:
            continue
        try:
            content = md.read_text()
            title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
            date_match = re.search(r"\*\*Date\*\*: (\d{4}-\d{2}-\d{2})", content)
            if title_match and date_match:
                folder = md.parent.name
                all_entries.append({
                    "date": date_match.group(1),
                    "title": title_match.group(1),
                    "folder": folder,
                    "path": md,
                })
        except Exception:
            pass

    if all_entries:
        update_index(all_entries)

    print(f"\n완료: {new_count}개 신규 처리, 총 {len(all_entries)}개 항목")
    print(f"출력 디렉토리: {OUTPUT_DIR}")

    if new_sessions_data:
        print("\n[매핑 분석] 신규 태그 룰/동의어 탐색 중...")
        suggest_new_mappings(new_sessions_data)


def main():
    recent_only = "--recent" in sys.argv
    regen = "--regen" in sys.argv
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    process_sessions(recent_only=recent_only, regen=regen)

    # 신규 세션 요약 후 태그 자동 추가
    tagger = Path.home() / ".claude/scripts/add-session-tags.py"
    if tagger.exists():
        subprocess.run([sys.executable, str(tagger)], check=False)


if __name__ == "__main__":
    main()
