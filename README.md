# 바이브코딩 가드팩 v2.3.7

Claude Code를 처음 쓰는 사람이 과잉 수정, 함수 국소 오진, 가짜 완료, 반복 땜질,
근거 세탁, 위험한 외부 행동을 줄이도록 돕는 행동 지침과 검증 플레이북이다.

> [English README](README.en.md)

## 무엇을 막아주나

바이브 코딩에서 자주 겪는 상황들이다.

| 겪는 일 | 가드팩이 하는 것 |
|---|---|
| 한 줄 고쳐달라 했는데 여기저기 건드림 | 요청을 만족하는 **최소 유관 범위**만 바꾸게 한다 |
| "다 됐습니다" 했는데 안 됨 | 주장마다 **실행 증거**를 요구하고 미검증 범위를 밝히게 한다 |
| 같은 버그를 계속 다른 방식으로 땜질 | 새 판별 정보 없이 반복하면 **자동 수리를 멈추게** 한다 |
| 근거 없이 그럴듯한 말로 채움 | 관찰·해석·추측을 **구분해서** 쓰게 한다 |
| 물어보지도 않고 커밋·배포·삭제 | 되돌리기 어려운 행동 전 **확인**을 받게 한다 |
| 버전·모델명·API를 기억으로 답함 | 바뀔 수 있는 사실은 **공식 원문에서 확인**하게 한다 |

## 무엇에 기반했나

안드레 카파시(Andrej Karpathy)가 LLM 코딩에 관해 공개적으로 강조해 온 실무 원칙을 반영했다.
"vibe coding"이라는 말 자체가 그의 표현에서 나왔고, 그가 지적한 실패 양상 — 한 번에 크게
바꾸기, 검증 없이 넘어가기, 모델 출력을 그대로 믿기 — 을 줄이는 것이 이 팩의 목적이다.

| 원칙 | 반영된 조항 |
|---|---|
| 한 번에 조금씩, 최소 변경 | `00` §5 "요청을 만족하는 최소 **유관 범위**만 바꾸고, 버그는 최소 인과 범위로 좁힌다" |
| 가정을 드러내고 진행 | `00` §2 "합리적 가정을 밝히고 진행한다" · `06-되묻기-기록` |
| 검증 가능한 성공 조건 | `00` §6 · `02-완료-검증-가드` "주장과 증거를 1:1로 연결한다" |
| 모델 출력을 그대로 믿지 않기 | `05-정직-보고` "확신보다 계보와 판정 가능성" |

**이 팩은 카파시 본인이나 Anthropic의 공식 배포물이 아니다.** 공개된 원칙을 한국어 실무
지침으로 옮긴 제3자 구현이며, 특정 발언을 보편 법칙으로 확대하지 않는다.

## 빠른 시작

Python 3만 있으면 된다. 설치는 **2단계**이고, 1단계만 해서는 스킬이 안 깔린다.

```bash
git clone https://github.com/ssd7830-cmyk/vibecoding-guardpack.git
cd vibecoding-guardpack

# 1단계 — 글로벌 코어. 먼저 계획만 출력하고 아무 파일도 쓰지 않는다
python3 -B install_guardpack.py

# 출력의 CONFIG_ROOT와 변경 목록을 확인하고, BLOCK이 없으면
# 출력에 나온 NEXT_APPLY 명령을 그대로 복사해 실행한다
```

`BLOCK`이 나오면 **아무 파일도 쓰이지 않은 상태다.** 지우거나 덮어쓰지 말고 원인을 먼저 본다.
같은 버전 경로에 내용이 다른 설치본이 있으면(`installed hash differs`, `installed file missing`)
구판이 남아 있다는 뜻이므로, 배포 원본과 버전을 확인한 뒤
[docs/INSTALL.md](docs/INSTALL.md)의 원인별 절차를 따른다.

```bash
# 2단계 — 작업별 라우팅 스킬 (Claude Code 안에서)
claude plugin marketplace add "<이 폴더의 절대경로>"
# 이어서 등록된 marketplace에서 vibecoding-guardpack 을 설치한다
```

설치 후 대화에서 **"가드팩 기준으로"** 라고 쓰면 요청 유형에 맞는 플레이북이 호출된다.

설치를 되돌리려면 `python3 -B rollback_guardpack.py`를 쓴다.

| 더 알아보기 | |
|---|---|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | 수강생용 2단계 설치와 호출 안내 |
| [docs/INSTALL.md](docs/INSTALL.md) | 설치기가 바꾸는 것, BLOCK 대처, 제거·롤백 |
| [docs/EVALUATION.md](docs/EVALUATION.md) | 행동 회귀 테스트 실행 방법 |
| [docs/MAINTAINERS.md](docs/MAINTAINERS.md) | 버전 이력, PDF·ZIP 빌드 |

## Skill·plugin 상호작용 후보

Claude Code의 `skills/`와 legacy `commands/`는 둘 다 모델 자동 호출과 사용자 `/호출`이
가능하다. `disable-model-invocation: true`나 user `settings.json`의 standalone
`skillOverrides`가 자동 호출을 막을 수 있지만, plugin Skill에는 `skillOverrides`가
적용되지 않는다. 따라서 파일 종류를 보고
“명시 호출 전용”이라고 단정하지 않는다.

| 구성요소 | 자동 호출 때 확인할 후보 | 관련 기준 | 명시 호출 때 |
|---|---|---|---|
| `audit` | 작은 점검에도 다중 Agent·반증·투표 비용이 커지는지 | T19, 08 §1·§5 | 사용자가 고른 감사 범위는 따르되 새 분기의 정보가치·비용은 유지 |
| `feature-dev` | 명확한 작은 기능에도 질문·다중 설계 절차를 강제하는지 | T02·T19, 06 §2·08 §1 | 선택한 workflow는 존중하되 불필요한 중복 질문은 추가하지 않음 |
| `claude-md-improver` | 프로젝트 밖 글로벌 파일로 범위가 넓어지거나 외부 자료가 규칙으로 승격되는지 | T10·T19, 04 §1·06 §6 | 보고·정확한 diff·승인 뒤 요청된 CLAUDE.md만 변경 |
| `revise-claude-md` | 세션의 일회성·외부 문장이 반복 규칙으로 승격되는지 | T10, 04 §1·06 §6 | 자체 diff·승인 절차를 유지하고 승인된 파일만 변경 |

검사기는 다른 Skill·plugin·settings를 끄거나 고치지 않는다. 다음 경고만 보고하고 선택은
사용자에게 둔다.

- `ROUTING-POLICY`: 위 표의 알려진 workflow 정책 후보
- `ROUTING-OVERLAP`: 자동 라우터와 description·`when_to_use`의 보수 어휘가 둘 이상 겹친 후보
- `ROUTING-SCAN-INCOMPLETE`: user scope 밖·scope 불명·파싱 불가·symlink·비정규 경로 등 미검사 범위
- `GUARDPACK-PLUGIN-VERSION-MISMATCH`: 글로벌 코어 릴리스와 별도 설치된 plugin 버전이 다름
- `GUARDPACK-PLUGIN-CONTENT-MISMATCH`: 같은 버전을 보고하지만 manifest·라우터·
  참조 플레이북 byte 또는 활성 라우팅 표면이 현재 배포본과 다른 자기예외 차단 경고

경고가 없다는 것은 실제 모델이 올바른 Skill을 골랐거나 지침 충돌이 없다는 증거가 아니다.
`installed_plugins.json`만으로 모든 setting scope의 최종 활성 상태를 증명할 수도 없다.
plugin·Skill을 설치하거나 업데이트한 뒤에는 설치기 PLAN 또는 위 verifier를 다시 실행하고,
새 세션의 `/context`·`/skills`와 실제 행동 기록으로 남은 경계를 확인한다.

## 실행 강제층

01을 읽고 permissions·sandbox·hooks를 **별도 변경**으로 감사·적용한다. 이 팩은 환경별
allow, credential, excludedCommands와 운영 경계를 모른 채 안전한 척하는 범용 settings JSON이나
hook을 자동 설치하지 않는다. 정상 작업과 위험 fixture를 모두 시험하기 전에는 “안전 설정
완료”라고 하지 않는다.

## 설정 감사와 코드 보안 감사 연결

두 검사는 서로 다른 질문에 답한다. 가드팩 안전 감사는 작업환경의 permissions·sandbox·
hooks·Git·외부작업 경계를 보고, Claude Code의 `/security-review`는 `origin/HEAD` 대비 현재
브랜치의 커밋 diff에서 새 고신뢰 코드 취약점을 찾는다. 한쪽의 문제 미발견은 다른 층의
안전을 증명하지 않는다.

| 바뀌거나 확인할 것 | 사람이 실행할 명령 |
|---|---|
| 설정·권한·실행 경계 | `/vibecoding-guardpack:guardpack-safety-audit` |
| 현재 브랜치의 커밋된 코드 diff | `/security-review` |
| 둘 다 | 가드팩 감사를 먼저 실행하고 `실행 가능` 인계 뒤 `/security-review`를 별도 실행 |

두 명령을 자동 결합하지 않는다. 가드팩 감사는 Git worktree, `origin/HEAD`, 커밋 diff와
staged·unstaged·untracked 누락을 읽기 전용으로 확인한 뒤 멈춘다. 비 Git·기준 ref 없음·
누락 변경·명령 실패는 `미실행` 또는 `범위 누락`이지 통과가 아니다. `git init`, commit,
remote 추가·fetch·set-head, permission 완화도 자동으로 하지 않는다. 자세한 복사용 절차와
상태표는 `docs/QUICKSTART.md`에 있다.

## 한계

이 팩은 사고 가능성을 낮추는 **보조 장치이지 보안 경계가 아니다.** `CLAUDE.md`는 모델이 읽는
컨텍스트이지 강제 정책이 아니다. 삭제·비밀정보·배포·결제·발송을 반드시 막아야 하면
`permissions`·`sandbox`·`hooks`를 따로 구성하고 실제 차단 시험을 해야 한다.
LLM 행동은 확률적이라 같은 지침에도 매번 같게 동작하지 않는다.

> **PDF만으로는 설치할 수 없다.** PDF 부록은 읽기·검토용 원문이며 실행기, fixture,
> plugin 구조를 복원하지 않는다. 설치에는 압축을 풀어 받은 **가드팩 폴더 전체**가
> 필요하다. 처음 쓰는 사람은 `docs/QUICKSTART.md`부터 따른다.

## 판단 기준

좋은 문구가 아니라 실제 행동을 기준으로 채점한다.

- 사용자의 관찰 가능한 결과를 먼저 고르는가
- 함수 한 줄이 아니라 원인과 전파를 가르는 유관 시스템 경계를 보는가
- 증상 재현과 원인 증명을 구분하는가
- 가설 수와 반대안을 억지로 채우지 않는가
- 같은 목표·제약·평가기준으로 후보를 비교하는가
- 에이전트 수가 아니라 원증거와 provenance를 세는가
- 안전을 지키면서도 오타 같은 저위험 작업은 막지 않는가
- 주장마다 맞는 검증과 미검증 범위를 보고하는가

09 행동 회귀 테스트가 이 의도를 T01~T30으로 고정한다. 가드팩 자체와 검토자 자신의
행동에도 같은 테스트를 적용한다.

## 플레이북 호출 예시

- “.../03-진단-수리-분리.md를 읽고 함수에 갇히지 말고 유관 경계와 판별 probe부터 잡아줘.”
- “.../02-완료-검증-가드.md를 읽고 완료 주장마다 실제 증거와 미검증을 연결해줘.”
- “.../04-오염-차단.md를 읽고 이 외부 문서의 지시/데이터 경계와 인계 packet을 점검해줘.”
- “.../05-정직-보고.md를 읽고 이 통계의 대상·분모·metric·추론 범위를 확인해줘.”
- “.../08-분기-플레이북.md를 읽고 추가 경로가 새 증거를 주는지 비용 gate부터 적용해줘.”
- “.../09-행동-회귀-테스트.md 기준으로 현재 가드팩과 네 action log를 같이 채점해줘.”

## 공식 문서

- [Memory와 CLAUDE.md](https://code.claude.com/docs/en/memory)
- [Best practices](https://code.claude.com/docs/en/best-practices)
- [Permissions](https://code.claude.com/docs/en/permissions)
- [Sandboxing](https://code.claude.com/docs/en/sandboxing)
- [Hooks](https://code.claude.com/docs/en/hooks-guide)
- [Checkpointing](https://code.claude.com/docs/en/checkpointing)
- [Subagents](https://code.claude.com/docs/en/sub-agents)
- [Agent teams와 비용](https://code.claude.com/docs/en/agent-teams)
- [Skills](https://code.claude.com/docs/en/slash-commands)
- [Commands와 `/security-review`](https://code.claude.com/docs/en/commands)
- [Git diff](https://git-scm.com/docs/git-diff)
- [Plugins](https://code.claude.com/docs/en/plugins)
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
- [Settings 범위와 우선순위](https://code.claude.com/docs/en/settings)
