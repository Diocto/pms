#!/usr/bin/env python3
"""PMS 운영 현황판.

git과 gh, 그리고 각 브랜치의 `docs/tasks/FXX.md`를 매 요청마다 읽는다.
캐시하지 않는다 — 새로고침하면 그 순간의 저장소가 그대로 보인다.

    python3 tools/dashboard.py          # http://localhost:8765
    python3 tools/dashboard.py 9000     # 포트 지정

목록에서 세션을 누르면 상세(브랜치·현재 작업·Task 목록)가 열린다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 코드 → (이름, 브랜치 후보, 담당, 우선순위). 브랜치는 앞의 것부터 찾아 먼저 있는 것을 쓴다.
#
# 우선순위는 PM이 중재하는 값이라 여기 한 곳에서만 관리한다. 세션마다 자기 파일에
# 적게 하면 다섯 곳이 서로 어긋나고, 어긋난 걸 아무도 못 본다.
# 뜻: 자원 경합(공유 파일 중재·리뷰 순서·병합 순서)이 나면 위쪽이 이긴다.
SESSIONS = [
    ("F01", "예약 코어", ["worktree-F01"],
     "예약 생명주기 · 재고 차감 · 동시성 · 멱등성", "매우 급함"),
    ("F02", "선착순 특가", ["worktree-f02-promotion-rebased", "worktree-f02-promotion"],
     "UC-7 한정 수량 특가", "중요"),
    ("F04", "부하테스트", ["worktree-F04"],
     "k6 시나리오 · 실행 · 리포트", "중요"),
    ("F03", "객실 검색", ["worktree-F03"],
     "UC-1 검색 · Redis 캐시", "보통"),
    ("F05", "프론트엔드", ["worktree-F05"],
     "검색 · 예약 · 상세 3화면", "보통"),
]

ARTIFACTS = {
    "F01": ["docs/spec/F01-예약-코어.md", "docs/reports/F01-spec-reapproval.md", "docs/tasks/F01.md"],
    "F02": ["docs/spec/F02-선착순-프로모션.md", "docs/reports/F02-spec-approval.md", "docs/tasks/F02.md"],
    "F03": ["docs/spec/F03-가용-객실-검색.md", "docs/reports/F03-spec-approval.md", "docs/tasks/F03.md"],
    "F04": ["docs/load-test/scenarios.md", "docs/load-test/report.md", "docs/tasks/F04.md"],
    "F05": ["docs/briefings/F05.md", "docs/tasks/F05.md"],
}

STATUSES = ("대기", "진행", "완료", "보류")
ROW = re.compile(r"^\|\s*(T\d+)\s*\|(.+?)\|\s*(대기|진행|완료|보류)\s*\|(.*?)\|\s*$")


def run(*args: str) -> str:
    try:
        r = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=20, check=False)
        return r.stdout.strip()
    except Exception:
        return ""


def parse_tasks(text: str) -> list[dict]:
    """`docs/tasks/FXX.md`의 표를 읽는다. 형식은 docs/tasks/TEMPLATE.md."""
    tasks = []
    for line in text.splitlines():
        m = ROW.match(line.strip())
        if not m:
            continue
        tid, title, status, done = m.groups()
        title = title.strip()
        if not title or title.startswith("("):   # 템플릿의 자리표시자는 건너뛴다
            continue
        tasks.append({"id": tid, "title": title, "status": status, "done": done.strip()})
    return tasks


def collect() -> dict:
    run("git", "fetch", "--quiet", "origin")

    main_head = run("git", "log", "--oneline", "-1", "origin/main")
    remote = {
        b.strip().removeprefix("origin/")
        for b in run("git", "branch", "-r", "--format=%(refname:short)").splitlines()
    }

    sessions = []
    for code, name, candidates, role, prio in SESSIONS:
        branch = next((c for c in candidates if c in remote), None)
        s = {"code": code, "name": name, "role": role, "priority": prio, "branch": branch,
             "tasks": [], "current": None, "phase": "미착수", "blocked": []}

        if not branch:
            sessions.append(s)
            continue

        ref = f"origin/{branch}"
        s["head"] = run("git", "log", "--oneline", "-1", ref)
        counts = run("git", "rev-list", "--left-right", "--count", f"origin/main...{ref}")
        behind, ahead = (counts.split() + ["0", "0"])[:2]
        s["ahead"], s["behind"] = int(ahead or 0), int(behind or 0)
        s["last"] = run("git", "log", "-1", "--format=%cr", ref)
        s["recent"] = run("git", "log", "--oneline", "-5", f"origin/main..{ref}").splitlines()

        # 세 점(...)이라야 이 브랜치가 더한 것만 본다. 두 점이면 main이 앞서간 것까지 잡힌다.
        code_diff = run("git", "diff", "--name-only", f"origin/main...{ref}",
                        "--", "app/", "tests/", "migrations/", "frontend/")
        s["code_files"] = [f for f in code_diff.splitlines() if f]

        s["artifacts"] = []
        for path in ARTIFACTS.get(code, []):
            size = run("git", "cat-file", "-s", f"{ref}:{path}")
            s["artifacts"].append({"path": path, "size": int(size) if size.isdigit() else None})

        task_md = run("git", "show", f"{ref}:docs/tasks/{code}.md")
        if task_md:
            s["tasks"] = parse_tasks(task_md)
            s["current"] = next((t for t in s["tasks"] if t["status"] == "진행"), None)
            s["blocked"] = [t for t in s["tasks"] if t["status"] == "보류"]

        # 상태 한 줄 — 사람이 목록에서 보는 값
        if s["code_files"]:
            s["phase"] = "구현"
        elif s["tasks"]:
            s["phase"] = "Task 확정"
        else:
            s["phase"] = "문서"
        sessions.append(s)

    def js(raw):
        try:
            return json.loads(raw) if raw else []
        except json.JSONDecodeError:
            return []

    return {
        "main": main_head,
        "sessions": sessions,
        "open_prs": js(run("gh", "pr", "list", "--state", "open", "--json",
                           "number,title,headRefName")),
        "merged_prs": js(run("gh", "pr", "list", "--state", "merged", "--limit", "6",
                             "--json", "number,title")),
        "generated": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
    }


PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PMS 운영 현황판</title>
<style>
:root{--bg:#fcfcfb;--surf:#f4f5f2;--sunk:#eceee9;--rule:#dcdfd8;--soft:#e8eae4;
--ink:#191d1b;--ink2:#4a524d;--ink3:#767f78;--accent:#0f5f5c;--accent-s:#e3efee;
--hot:#a8492a;--ok:#2c6440;--wait:#7d6416;
--mono:ui-monospace,SFMono-Regular,Menlo,monospace;
--sans:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif}
@media(prefers-color-scheme:dark){:root{--bg:#121514;--surf:#191d1b;--sunk:#20241f;--rule:#2e342f;--soft:#252a26;
--ink:#e6e9e4;--ink2:#a8b1aa;--ink3:#79837c;--accent:#5ec2bd;--accent-s:#16302f;
--hot:#e08b64;--ok:#6fbf87;--wait:#cfae4e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.6}
.w{max-width:1160px;margin:0 auto;padding:32px 22px 90px}
h1{font-size:24px;letter-spacing:-.02em;margin:0 0 5px;font-weight:660}
.meta{font-family:var(--mono);font-size:12px;color:var(--ink3);margin:0 0 28px}
.meta b{color:var(--accent);font-weight:600}
h2{font-size:14px;margin:30px 0 11px;font-weight:650;letter-spacing:.01em;color:var(--ink2)}

/* 목록 */
.list{border:1px solid var(--rule);border-radius:9px;overflow:hidden;background:var(--surf)}
.hd,.row{display:grid;grid-template-columns:78px 88px 1fr 1.3fr 108px 92px;gap:12px;align-items:center;padding:11px 16px}
.hd{background:var(--sunk);border-bottom:1px solid var(--rule);font-family:var(--mono);
font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3);font-weight:600}
.row{border-bottom:1px solid var(--soft);cursor:pointer;background:none;border-left:0;border-right:0;border-top:0;
width:100%;text-align:left;font:inherit;color:inherit}
.row:last-child{border-bottom:none}
.row:hover{background:var(--sunk)}
.row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.code{font-family:var(--mono);font-size:14px;font-weight:650;color:var(--accent)}
.nm{font-weight:600}
.nm .role{font-size:12px;color:var(--ink3);font-weight:400;margin-top:1px}
.cur{font-size:13.5px;color:var(--ink2)}
.cur .tid{font-family:var(--mono);font-size:11.5px;color:var(--accent);margin-right:6px}
.cur.none{color:var(--ink3);font-style:italic}
.pill{display:inline-block;font-family:var(--mono);font-size:10.5px;padding:3px 9px;border-radius:20px;font-weight:600;white-space:nowrap}
.p-구현{background:color-mix(in srgb,var(--ok) 16%,transparent);color:var(--ok)}
.p-Task{background:var(--accent-s);color:var(--accent)}
.p-문서{background:color-mix(in srgb,var(--wait) 16%,transparent);color:var(--wait)}
.p-미착수{background:color-mix(in srgb,var(--hot) 14%,transparent);color:var(--hot)}
/* 우선순위 — 급한 것만 색을 쓴다. 셋 다 물들이면 아무것도 안 급해 보인다 */
.pr{font-family:var(--mono);font-size:10.5px;font-weight:650;white-space:nowrap}
.pr-매우급함{color:var(--hot)}
.pr-중요{color:var(--ink2)}
.pr-보통{color:var(--ink3);font-weight:400}
.pr b{font-size:13px;vertical-align:-1px;margin-right:3px}
.prog{font-family:var(--mono);font-size:12px;color:var(--ink3);text-align:right;font-variant-numeric:tabular-nums}
.bar{height:3px;background:var(--soft);border-radius:2px;margin-top:5px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent)}

/* 상세 */
.back{background:none;border:none;font:inherit;color:var(--accent);cursor:pointer;padding:0;margin:0 0 18px;
font-family:var(--mono);font-size:13px}
.back:hover{text-decoration:underline}
.kv{display:grid;grid-template-columns:auto 1fr;gap:9px 18px;font-size:14px;margin:0 0 26px;
background:var(--surf);border:1px solid var(--rule);border-radius:8px;padding:16px 18px}
.kv dt{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);padding-top:3px;white-space:nowrap}
.kv dd{margin:0}
.mono{font-family:var(--mono);font-size:12.5px}
table{width:100%;border-collapse:collapse;background:var(--surf);border:1px solid var(--rule);border-radius:8px;overflow:hidden}
th{text-align:left;font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
color:var(--ink3);padding:9px 14px;background:var(--sunk);border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:10px 14px;border-bottom:1px solid var(--soft);vertical-align:top;font-size:14px}
tr:last-child td{border-bottom:none}
tr.on td{background:var(--accent-s)}
.st{font-family:var(--mono);font-size:11px;font-weight:600}
.st-완료{color:var(--ok)} .st-진행{color:var(--accent)} .st-대기{color:var(--ink3)} .st-보류{color:var(--hot)}
.empty{padding:22px;text-align:center;color:var(--ink3);font-size:14px;background:var(--surf);
border:1px dashed var(--rule);border-radius:8px}
ul{list-style:none;padding:0;margin:0}
li{padding:9px 14px;border-bottom:1px solid var(--rule);background:var(--surf);font-size:14px}
li:first-child{border-radius:8px 8px 0 0} li:last-child{border-bottom:none;border-radius:0 0 8px 8px}
a{color:var(--accent);font-family:var(--mono)}
.sub{font-size:11.5px;color:var(--ink3);font-family:var(--mono)}
.note{font-size:12.5px;color:var(--ink3);margin-top:9px}
.stale{color:var(--hot)} .fresh{color:var(--ok)}
</style></head><body><div class="w" id="app">불러오는 중…</div>
<script>
var S = null, view = location.hash.slice(1) || '';

function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

function counts(t){
  var c = {대기:0, 진행:0, 완료:0, 보류:0};
  t.forEach(function(x){ c[x.status]++; });
  return c;
}

function renderList(){
  var rows = S.sessions.map(function(s){
    var c = counts(s.tasks), total = s.tasks.length;
    var pct = total ? Math.round(c.완료 / total * 100) : 0;
    var cur = s.current
      ? '<span class="tid">' + esc(s.current.id) + '</span>' + esc(s.current.title)
      : (total ? '진행 중인 Task 없음' : 'Task 목록 없음');
    var phaseKey = s.phase === 'Task 확정' ? 'Task' : s.phase;
    var dot = { '매우 급함': '●', '중요': '●', '보통': '○' }[s.priority] || '○';
    return '<button class="row" data-code="' + s.code + '">' +
      '<span class="code">' + esc(s.code) + '</span>' +
      '<span class="pr pr-' + s.priority.replace(/\s/g, '') + '"><b>' + dot + '</b>' +
        esc(s.priority) + '</span>' +
      '<span class="nm">' + esc(s.name) + '<div class="role">' + esc(s.role) + '</div></span>' +
      '<span class="cur' + (s.current ? '' : ' none') + '">' + cur + '</span>' +
      '<span><span class="pill p-' + phaseKey + '">' + esc(s.phase) + '</span></span>' +
      '<span class="prog">' + (total ? c.완료 + '/' + total : '—') +
        (total ? '<span class="bar"><i style="width:' + pct + '%"></i></span>' : '') + '</span>' +
    '</button>';
  }).join('');

  var prs = S.open_prs.length
    ? S.open_prs.map(function(p){ return '<li><a href="https://github.com/Diocto/pms/pull/' + p.number +
        '" target="_blank">#' + p.number + '</a> ' + esc(p.title) +
        ' <span class="sub">' + esc(p.headRefName) + '</span></li>'; }).join('')
    : '<li class="sub">열린 PR 없음</li>';

  return '<h1>PMS 운영 현황판</h1>' +
    '<p class="meta">' + esc(S.generated) + ' · 20초마다 갱신 · main <b>' + esc(S.main) + '</b></p>' +
    '<h2>세션</h2>' +
    '<div class="list"><div class="hd"><span>코드</span><span>우선순위</span><span>담당</span>' +
    '<span>현재 Task</span><span>상태</span><span style="text-align:right">완료</span></div>' +
    rows + '</div>' +
    '<p class="note">행을 누르면 상세가 열린다. <b>상태</b>는 문서 → Task 확정 → 구현 순으로 나아간다. ' +
    '<b>우선순위</b>는 자원이 부딪힐 때 누가 이기는지를 뜻한다 — 공유 파일 중재, 리뷰 순서, 병합 순서.</p>' +
    '<h2>열린 PR</h2><ul>' + prs + '</ul>';
}

function renderDetail(code){
  var s = S.sessions.filter(function(x){ return x.code === code; })[0];
  if (!s) return renderList();

  var body;
  if (!s.branch) {
    body = '<div class="empty">브랜치가 없다. 아직 시작하지 않았다.</div>';
  } else {
    var c = counts(s.tasks);
    var stale = s.behind
      ? '<span class="stale">main보다 ' + s.behind + ' 뒤</span>'
      : '<span class="fresh">main 최신</span>';
    var files = s.artifacts.map(function(f){
      return '<div class="mono">' + esc(f.path) +
        (f.size ? ' <span class="fresh">' + Math.round(f.size/1024) + 'KB</span>'
                : ' <span class="stale">없음</span>') + '</div>'; }).join('');

    var tasks = s.tasks.length
      ? '<table><tr><th>ID</th><th>Task</th><th>상태</th><th>완료 기준</th></tr>' +
        s.tasks.map(function(t){
          return '<tr' + (t.status === '진행' ? ' class="on"' : '') + '>' +
            '<td class="mono">' + esc(t.id) + '</td><td>' + esc(t.title) + '</td>' +
            '<td class="st st-' + t.status + '">' + esc(t.status) + '</td>' +
            '<td class="sub">' + esc(t.done) + '</td></tr>'; }).join('') + '</table>'
      : '<div class="empty">Task 목록이 아직 없다. 구현 전에 <span class="mono">docs/tasks/' +
        code + '.md</span>를 만들어야 한다.</div>';

    var commits = (s.recent || []).length
      ? '<ul>' + s.recent.map(function(l){ return '<li class="mono">' + esc(l) + '</li>'; }).join('') + '</ul>'
      : '<div class="empty">main과 같다.</div>';

    body =
      '<dl class="kv">' +
      '<dt>우선순위</dt><dd><span class="pr pr-' + s.priority.replace(/\s/g, '') + '">' +
        esc(s.priority) + '</span></dd>' +
      '<dt>브랜치</dt><dd class="mono">' + esc(s.branch) + '</dd>' +
      '<dt>HEAD</dt><dd class="mono">' + esc(s.head) + '</dd>' +
      '<dt>main 대비</dt><dd>' + s.ahead + ' 앞 · ' + stale + ' <span class="sub">· ' + esc(s.last) + '</span></dd>' +
      '<dt>현재 작업</dt><dd>' + (s.current
          ? '<b>' + esc(s.current.id) + '</b> ' + esc(s.current.title) +
            (s.current.done ? '<div class="sub">완료 기준: ' + esc(s.current.done) + '</div>' : '')
          : '<span class="sub">진행 중인 Task 없음</span>') + '</dd>' +
      '<dt>진척</dt><dd class="mono">완료 ' + c.완료 + ' · 진행 ' + c.진행 + ' · 대기 ' + c.대기 +
        (c.보류 ? ' · <span class="stale">보류 ' + c.보류 + '</span>' : '') + '</dd>' +
      '<dt>코드 변경</dt><dd>' + (s.code_files.length
          ? s.code_files.length + '개 파일 <div class="sub">' + esc(s.code_files.slice(0,6).join(', ')) + '</div>'
          : '<span class="sub">없음 — 문서만</span>') + '</dd>' +
      '<dt>산출물</dt><dd>' + files + '</dd>' +
      '</dl>' +
      '<h2>Task</h2>' + tasks +
      '<h2>최근 커밋</h2>' + commits;
  }

  return '<button class="back" id="back">← 목록으로</button>' +
    '<h1>' + esc(s.code) + ' ' + esc(s.name) + '</h1>' +
    '<p class="meta">' + esc(s.role) + '</p>' + body;
}

function draw(){
  document.getElementById('app').innerHTML = view ? renderDetail(view) : renderList();
  var b = document.getElementById('back');
  if (b) b.onclick = function(){ view = ''; location.hash = ''; draw(); };
  Array.prototype.forEach.call(document.querySelectorAll('.row'), function(r){
    r.onclick = function(){ view = r.dataset.code; location.hash = view; draw(); };
  });
}

function load(){
  fetch('/api/state', {cache: 'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(d){ S = d; draw(); })
    .catch(function(){ document.getElementById('app').textContent = '데이터를 읽지 못했다.'; });
}

window.addEventListener('hashchange', function(){ view = location.hash.slice(1); if (S) draw(); });
load();
setInterval(load, 20000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/state"):
            self._send(json.dumps(collect(), ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
        else:
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"현황판: http://localhost:{port}  (Ctrl+C로 종료)")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
