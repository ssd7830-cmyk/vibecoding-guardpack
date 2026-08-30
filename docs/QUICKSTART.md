# 가드팩 v2.3.7 라우팅 스킬 빠른 시작

## 먼저 확인할 것

- PDF에서 파일을 다시 만들지 말고 **완성된 가드팩 폴더 전체**를 사용한다.
- `00-글로벌-코어.md` 하나만 기존 설치 방식으로 글로벌 import한다.
- `01`~`08`은 정본 플레이북이다. 글로벌에 추가하지 않고 이 폴더의 plugin skill이 필요한
  정본만 읽게 한다.
- 스킬 호출은 현재 요청의 쓰기 권한이나 외부 행동 권한을 넓히지 않는다.
- 지원 환경은 macOS·Linux(WSL 포함)다. Windows 네이티브 Python에서는 설치기가 `dir_fd`
  미지원으로 BLOCK한다. 우회하지 말고 WSL 또는 macOS/Linux에서 설치한다.
- plugin은 이 폴더의 절대경로에 등록된다. 설치 뒤 폴더를 옮기거나 지우면 새 세션에서 Skill이
  로드되지 않는다(`claude plugin list`에 cache-miss). 옮겼다면 3절의 두 명령을 새 경로로 다시
  실행한다.

## 글로벌 코어와 라우팅 스킬은 별도 설치다

| 설치 | 하는 일 | 하지 않는 일 |
|---|---|---|
| 글로벌 코어 | 설치기의 PLAN을 검토하고 APPLY하면 사용자 `CLAUDE.md`가 `00-글로벌-코어.md` 하나를 매 세션 import한다. | `01`~`08` 스킬을 등록하거나 permissions·sandbox·hooks를 바꾸지 않는다. |
| 라우팅 스킬 plugin | 로컬 marketplace에서 plugin을 설치해 문구 트리거 1개와 상황별 스킬 5개를 등록한다. 호출된 스킬만 정본 `01`~`08` 중 필요한 파일을 읽는다. | 사용자 `CLAUDE.md`와 보안 설정을 바꾸거나 `00`을 글로벌로 import하지 않는다. |

두 설치는 서로를 대신하지 않는다. 글로벌 코어를 설치하지 않고 스킬만 시험할 수 있고, 글로벌
코어만 설치한 상태에서는 `01`~`08`이 자동으로 라우팅되지 않는다.

여기서 “글로벌 1개”는 물리적으로 설치되는 파일 수가 아니라 매 세션 자동 load되는 import
수다. 설치기는 무결성·rollback·도구 사용을 위해 전체 version tree를 보관하지만 나머지 파일을
자동 컨텍스트에 넣지 않는다.

## 1. 폴더 계약 검사

가드팩 폴더로 이동한 뒤 신규 라우팅 계약을 검사한다.

```bash
python3 -B -m unittest tests/test_skills_contract.py -v
```

전체 배포 회귀도 함께 확인하려면 다음을 실행한다.

```bash
python3 -B -m unittest discover -s tests -v
```

## 2. 글로벌 코어 설치

먼저 쓰지 않는 PLAN을 실행한다.

```bash
python3 -B install_guardpack.py
```

출력의 `CONFIG_ROOT`, 대상 파일, 충돌과 예상 변경이 맞고 `BLOCK`이 없을 때만 출력된
`NEXT_APPLY:` 명령을 그대로 검토해 실행한다. 이 단계는 plugin을 설치하지 않는다.

PLAN은 같은 설정 루트의 개인 Skill·legacy command와 설치 plugin에서 정적으로 확인 가능한
자동 라우팅·workflow 충돌 후보도 `WARN`으로 보여준다. `ROUTING-POLICY`는 알려진 정책 후보,
`ROUTING-OVERLAP`은 description 어휘 후보, `ROUTING-SCAN-INCOMPLETE`는 읽지 못한 범위다.
`GUARDPACK-PLUGIN-VERSION-MISMATCH`·`GUARDPACK-PLUGIN-CONTENT-MISMATCH`는 별도 plugin의
버전·참조 byte 또는 활성 라우팅 표면이 현재 배포본과 다른 경고다.
WARN은 자동 삭제·비활성화나 설치 차단을 뜻하지 않으며 실제 호출 충돌의 증거도 아니다.

## 3. 라우팅 스킬을 지속 설치

다음 두 명령은 서로 다른 단계다. `<가드팩-절대경로>`는 이 폴더의 실제 절대경로로 바꾸고,
공백이나 한글이 있으므로 따옴표를 유지한다.

1. 로컬 marketplace를 Claude Code에 등록한다.

```bash
claude plugin marketplace add "<가드팩-절대경로>"
```

2. 등록된 marketplace에서 plugin을 설치한다.

```bash
claude plugin install vibecoding-guardpack@vibecoding-guardpack-local
```

설치 요약에 재로드 안내가 나오면 Claude Code 안에서 `/reload-plugins`를 실행한다. 새 세션의
`/skills`에서 `vibecoding-guardpack` namespace의 스킬 6개를 확인하고, `/context`의 Skills 행에서
`vibecoding-guardpack:guardpack` description이 잘리지 않았는지 본다. 스킬이 많은 환경에서는
스킬 목록 예산(컨텍스트의 1%)을 넘기면 덜 쓴 스킬의 description부터 조용히 빠지고, 그러면
`가드팩 기준으로` 문구를 붙여도 아무 반응이 없다. 잘렸으면 settings의
`skillListingBudgetFraction`을 올리거나 안 쓰는 스킬을 줄인다.

설치 직후, 그리고 다른 plugin·Skill을 새로 설치하거나 업데이트한 뒤에는 읽기 전용으로 확인한다.

```bash
python3 -B verify_guardpack.py --config-root "/실제/Claude/설정루트" --cwd "/검사할/프로젝트"
```

`--config-root`만 줘도 그 루트의 `CLAUDE.md`와 설치본을 함께 검사한다. `RESULT: FAIL`이면
FAIL 줄을 그대로 Claude에게 붙여넣는다. `CORE-NOT-INSTALLED`와 `RESULT: PASS (partial; …)`가
보이면 코어가 그 루트에 없다는 뜻이므로 2절부터 다시 한다. 검사기는 후보만 보고하며 다른
plugin·Skill·settings를 수정하거나 끄지 않는다.

- `ROUTING-POLICY`·`ROUTING-OVERLAP`은 자동 호출 정책·어휘 후보이지 실제 충돌 증거가 아니다.
- `ROUTING-SCAN-INCOMPLETE`는 안전하게 읽지 못했거나 user scope 밖이라 남은 범위다.
- `GUARDPACK-PLUGIN-VERSION-MISMATCH`는 글로벌 코어와 plugin이 별도 업데이트라는 뜻이다.
- `GUARDPACK-PLUGIN-CONTENT-MISMATCH`는 같은 버전 표시와 실제 라우팅 파일·표면이 다른 경고다.

두 mismatch를 봐도 plugin을 자동 삭제·비활성화하지 않는다. 프로젝트별 활성 상태는
해당 프로젝트의 `/status`·`/skills`·`/plugin`에서 따로 확인한다.

marketplace 등록은 설치 가능한 목록을 추가하고, plugin 설치는 그 목록에서 실제 스킬을 사용자
환경에 활성화한다. 첫 단계만 실행해서는 스킬이 설치되지 않는다.

## 4. 설치 전 임시 plugin으로 시험

현재 Claude Code 세션에만 이 폴더를 plugin으로 로드한다. 경로에는 실제 가드팩 폴더의
절대경로를 넣고, 공백이나 한글이 있으므로 따옴표를 유지한다.

```bash
claude --plugin-dir "/절대경로/바이브코딩-가드팩"
```

이 방식은 현재 실행에만 plugin을 로드한다. 지속 설치를 대신하지 않는다. Claude Code가
시작되면 `/skills`에서 `vibecoding-guardpack` namespace의 스킬을 확인한다. 개발 중 파일을
고친 뒤에는 `/reload-plugins`로 다시 읽을 수 있다.

## 5. 상황별 호출

가장 쉬운 방법은 요청 끝에 문구를 붙이는 것이다. 어떤 스킬을 골라야 할지 몰라도 된다.

    나 이런 거 만들려고 하는데 조사 좀 하자. 가드팩 기준으로 대답.

`가드팩 기준`, `가드팩으로`, `가드팩 써서` 같은 문구가 있으면 `guardpack` Skill이 켜져 아래 표의
router 중 맞는 것을 대신 호출한다. 안전 감사만은 문구로 켜지지 않고 직접 호출해야 한다.

| 상황 | 호출 | 자동 호출 |
|---|---|---|
| 요청 유형을 모를 때 — 문구로 위임 | 요청 끝에 `가드팩 기준으로 대답` 또는 `/vibecoding-guardpack:guardpack` | 가능(문구) |
| permissions·sandbox·hooks·Git 안전 설정 감사 | `/vibecoding-guardpack:guardpack-safety-audit` | 불가 — 사람이 직접 호출 |
| 중요한 완료 주장과 실제 증거 확인 | `/vibecoding-guardpack:guardpack-completion-check` | 가능 |
| 원인 불명 버그·반복 실패 진단 | `/vibecoding-guardpack:guardpack-debug-evidence` | 가능 |
| 외부 자료 오염·긴 세션 인계·불명확한 큰 요구 | `/vibecoding-guardpack:guardpack-context-intent` | 가능 |
| 출처·연구·한국 로컬 정보·고영향 대안 검토 | `/vibecoding-guardpack:guardpack-evidence-review` | 가능 |

### 설정 감사와 코드 보안 감사 — 한 흐름, 두 명령

두 검사는 서로 다른 질문에 답한다. 가드팩 감사는 작업환경의 permissions·sandbox·hooks·
Git·외부작업 경계를 보고, Claude Code의 `/security-review`는 `origin/HEAD` 대비 현재
브랜치의 커밋 diff에서 새 고신뢰 코드 취약점을 찾는다. 한쪽의 문제 미발견은 다른 층의
안전을 증명하지 않는다.

| 바뀌거나 확인할 것 | 실행 |
|---|---|
| permissions·sandbox·hooks·Git 경계 | 가드팩 안전 감사 |
| 현재 브랜치의 커밋된 코드 diff | `/security-review` |
| 둘 다 | 가드팩 안전 감사 → 사람이 `/security-review`를 별도 실행 |
| 둘 다 아님 | 두 감사 모두 불필요 |

둘 다 필요하면 첫 메시지로 다음 문장을 복사한다.

```text
/vibecoding-guardpack:guardpack-safety-audit 현재 프로젝트의 permissions·sandbox·hooks·Git 경계를 읽기 전용으로 감사하고, /security-review의 Git 준비 상태와 검토에서 빠질 변경도 보고해. 아무것도 바꾸지 마.
```

감사는 아래 인계 카드를 남기고 멈춰야 한다.

- 상태: `실행 가능 / 검토 대상 없음 / 범위 누락 / 미실행 / 미지원` 중 하나
- 대상 경로
- `origin/HEAD`와 `HEAD`
- `git diff --name-only origin/HEAD...`의 커밋 diff 파일 수
- staged·unstaged·untracked 중 내장 감사에서 빠지는 변경
- 정확한 다음 명령

상태가 `실행 가능`일 때만 **다음 메시지에서** 사람이 직접 실행한다.

```text
/security-review
```

한 메시지에 두 Skill을 합치거나 가드팩이 내장 감사를 자동 호출하게 하지 않는다. 현재 검증
기준인 Claude Code 2.1.220의 내장 감사는 `git diff origin/HEAD...`를 사용하므로 staged·
unstaged·untracked 파일은 diff 본문에서 빠진다. 제품 동작은 바뀔 수 있으므로 실제 버전의
공식 문서와 명령 지원 여부를 다시 확인한다.

| 관찰 | 인계 상태와 의미 |
|---|---|
| Git worktree가 아님 | `미실행` — 자동 `git init` 금지 |
| `origin/HEAD` 또는 `HEAD`를 해석할 수 없음 | `미실행` — remote 추가·fetch·set-head 자동 실행 금지 |
| staged·unstaged·untracked가 하나라도 있음 | `범위 누락` — 내장 감사가 그 변경을 봤다고 주장 금지 |
| 커밋 diff 0, working tree도 깨끗함 | `검토 대상 없음` |
| 명령 미지원 | `미지원` |
| permission·API·명령 실행 실패 | `미실행` — 문제 없음으로 바꾸지 않음 |

내장 감사가 발견을 보고하지 않아도 “검토 범위에서 보고 기준을 넘은 고신뢰 새 취약점이
보고되지 않음”까지만 말한다. `안전`, `통과`, `보안 완료`로 확대하지 않는다. 두 감사 모두
설정이나 코드를 고치지 않는다. 실제 변경은 정확한 대상·예상 diff·시험·복구법을 확인한 뒤
별도 요청으로 승인한다.

## 6. 무엇이 컨텍스트에 들어가나

- 자동 호출 가능한 다섯 스킬(문구 트리거 1 + 라우터 4)은 짧은 `description`만 평소 컨텍스트에
  보인다. 스킬 목록 예산을 넘으면 그 description도 빠질 수 있다(3절).
- 스킬 본문은 호출될 때만 들어가며, 본문이 가리키는 정본도 필요한 것만 읽는다.
- 사람 전용 안전 감사 스킬은 `disable-model-invocation: true`라 사용자가 직접 호출하기 전에는
  설명과 본문이 모델 컨텍스트에 들어가지 않는다.
- 스킬은 `01`~`08`을 복사하지 않는다. 내용 수정은 루트의 정본 MD에서만 한다.

## 7. 경계

- plugin은 글로벌 `CLAUDE.md`, permissions, sandbox, hooks를 설치하거나 바꾸지 않는다.
- `09-행동-회귀-테스트.md`는 평가 기준이며 일반 작업 라우터가 아니다.
- 행동 pilot 실행기는 pack 루트의 유지관리자 도구 `behavior_harness.py`다. 라우팅 Skill이
  자동 실행하거나 모델 비용을 발생시키지 않는다. 모델 ID를 준 계획 명령도 계획만 출력하고,
  유료 실행은 별도 승인 hash가 있어야 한다.
- plugin이 보이지 않으면 `skills/<이름>/SKILL.md`가 plugin 루트 바로 아래에 있는지 확인하고,
  새 세션에서 정확한 `--plugin-dir` 절대경로로 다시 시작한다.

공식 규격: [Claude Code Skills](https://code.claude.com/docs/en/skills) ·
[Claude Code Commands](https://code.claude.com/docs/en/commands) ·
[Git diff](https://git-scm.com/docs/git-diff) ·
[Claude Code Plugins](https://code.claude.com/docs/en/plugins)
