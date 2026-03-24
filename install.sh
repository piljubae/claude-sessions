#!/usr/bin/env bash
# Claude Sessions Organizer — 설치 스크립트
# 실행: bash install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$HOME"
CLAUDE_DIR="$HOME_DIR/.claude"

# ─── 색상 출력 ────────────────────────────────────────────────────────────────
green()  { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }
red()    { echo -e "\033[31m$*\033[0m"; }
bold()   { echo -e "\033[1m$*\033[0m"; }

bold "===== Claude Sessions Organizer 설치 ====="
echo ""

# ─── 설정 ────────────────────────────────────────────────────────────────────
yellow "출력 디렉토리 설정 (기본값: ~/Documents/Claude Cowork/claude-sessions)"
read -r -p "Enter 또는 원하는 경로 입력: " OUTPUT_DIR_INPUT
OUTPUT_DIR="${OUTPUT_DIR_INPUT:-$HOME_DIR/Documents/Claude Cowork/claude-sessions}"
OUTPUT_DIR="${OUTPUT_DIR/#\~/$HOME_DIR}"  # ~ 치환

yellow "Claude 바이너리 경로 (기본값: /opt/homebrew/bin/claude)"
read -r -p "Enter 또는 원하는 경로 입력: " CLAUDE_BIN_INPUT
CLAUDE_BIN="${CLAUDE_BIN_INPUT:-/opt/homebrew/bin/claude}"

echo ""
green "설정:"
echo "  출력 디렉토리: $OUTPUT_DIR"
echo "  Claude 바이너리: $CLAUDE_BIN"
echo ""
read -r -p "계속할까요? (y/N) " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "취소됨"; exit 0; }

# ─── 1. 디렉토리 생성 ────────────────────────────────────────────────────────
echo ""
yellow "[1/6] 디렉토리 생성..."
mkdir -p "$HOME_DIR/scripts"
mkdir -p "$CLAUDE_DIR/scripts"
mkdir -p "$CLAUDE_DIR/skills/organize-sessions"
mkdir -p "$CLAUDE_DIR/session-continuations"
mkdir -p "$CLAUDE_DIR/session-context-shown"
mkdir -p "$OUTPUT_DIR"
green "  완료"

# ─── 2. Python 스크립트 설치 ─────────────────────────────────────────────────
echo ""
yellow "[2/6] 스크립트 설치..."

# organize-sessions.py 경로 수정 후 복사
sed \
  -e "s|HOME / \"Documents/Claude Cowork/claude-sessions\"|Path(\"${OUTPUT_DIR}\")|g" \
  -e "s|CLAUDE_BIN = \"/opt/homebrew/bin/claude\"|CLAUDE_BIN = \"${CLAUDE_BIN}\"|g" \
  "$SCRIPT_DIR/organize-sessions.py" > "$HOME_DIR/scripts/organize-sessions.py"

chmod +x "$HOME_DIR/scripts/organize-sessions.py"

# suggest-context.py 경로 수정 후 복사
sed \
  -e "s|HOME / \"Documents/Claude Cowork/claude-sessions\"|Path(\"${OUTPUT_DIR}\")|g" \
  "$SCRIPT_DIR/suggest-context.py" > "$CLAUDE_DIR/scripts/suggest-context.py"

green "  완료"

# ─── 3. 스킬 설치 ────────────────────────────────────────────────────────────
echo ""
yellow "[3/6] 글로벌 스킬 설치..."
cp "$SCRIPT_DIR/skill/SKILL.md" "$CLAUDE_DIR/skills/organize-sessions/SKILL.md"
green "  완료"

# ─── 4. anthropic 패키지 설치 ────────────────────────────────────────────────
echo ""
yellow "[4/6] anthropic 패키지 확인..."
if python3 -c "import anthropic" 2>/dev/null; then
  green "  이미 설치됨"
else
  pip3 install anthropic --break-system-packages -q && green "  설치 완료"
fi

# ─── 5. LaunchAgent 등록 ─────────────────────────────────────────────────────
echo ""
yellow "[5/6] LaunchAgent 등록 (매일 09:00 자동 실행)..."

PLIST_PATH="$HOME_DIR/Library/LaunchAgents/com.claudesessions.organize.plist"
ESCAPED_OUTPUT="${OUTPUT_DIR//&/\\&}"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claudesessions.organize</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>${HOME_DIR}/scripts/organize-sessions.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>${HOME_DIR}</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${OUTPUT_DIR}/organize-sessions.log</string>
    <key>StandardErrorPath</key>
    <string>${OUTPUT_DIR}/organize-sessions.err</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
green "  완료"

# ─── 6. settings.json 훅 등록 ────────────────────────────────────────────────
echo ""
yellow "[6/6] Claude Code 훅 등록..."

SETTINGS_FILE="$CLAUDE_DIR/settings.json"

if [ ! -f "$SETTINGS_FILE" ]; then
  echo '{}' > "$SETTINGS_FILE"
fi

# hooks 블록이 이미 있는지 확인
if python3 -c "
import json
with open('$SETTINGS_FILE') as f:
    s = json.load(f)
assert 'hooks' in s and 'UserPromptSubmit' in s.get('hooks', {})
" 2>/dev/null; then
  yellow "  훅이 이미 등록되어 있습니다. 건너뜀."
else
  python3 << PYEOF
import json
with open('$SETTINGS_FILE') as f:
    settings = json.load(f)

settings.setdefault('hooks', {}).setdefault('UserPromptSubmit', [])

# 중복 방지
hook_cmd = "python3 ${CLAUDE_DIR}/scripts/suggest-context.py"
existing = [h.get('command') for entry in settings['hooks']['UserPromptSubmit'] for h in entry.get('hooks', [])]
if hook_cmd not in existing:
    settings['hooks']['UserPromptSubmit'].append({
        "hooks": [{"type": "command", "command": hook_cmd}]
    })

with open('$SETTINGS_FILE', 'w') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write('\n')
print("  훅 등록 완료")
PYEOF
fi

# ─── 완료 ────────────────────────────────────────────────────────────────────
echo ""
bold "===== 설치 완료 ====="
echo ""
echo "📁 세션 출력: $OUTPUT_DIR"
echo ""
echo "사용법:"
echo "  python3 ~/scripts/organize-sessions.py          # 전체 처리"
echo "  python3 ~/scripts/organize-sessions.py --recent # 최근 7일"
echo "  python3 ~/scripts/organize-sessions.py --regen  # AI 요약 재생성"
echo ""
echo "새 Claude 세션 시작 시 관련 이전 세션을 자동으로 제안합니다."
