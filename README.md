# 바이브코딩 가드팩 v2.3.7

Claude Code를 처음 쓰는 사람이 과잉 수정, 함수 국소 오진, 가짜 완료, 반복 땜질,
근거 세탁, 위험한 외부 행동을 줄이도록 돕는 행동 지침과 검증 플레이북이다.

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
구판이 남아 있다는 뜻이므로, 배포 원본과 버전을 확인한 뒤 아래 "초보자 설치 요약" 5번의
원인별 절차를 따른다.

```bash
# 2단계 — 작업별 라우팅 스킬 (Claude Code 안에서)
claude plugin marketplace add "<이 폴더의 절대경로>"
# 이어서 등록된 marketplace에서 vibecoding-guardpack 을 설치한다
```

설치 후 대화에서 **"가드팩 기준으로"** 라고 쓰면 요청 유형에 맞는 플레이북이 호출된다.

자세한 절차·차단 상황 대처·제거 방법은 [docs/QUICKSTART.md](docs/QUICKSTART.md)와 아래
"초보자 설치 요약"에 있다. 설치를 되돌리려면 `python3 -B rollback_guardpack.py`를 쓴다.

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

## 파일과 적용 범위

| 파일 | 용도 | 글로벌 import |
|---|---|---|
| 00-글로벌-코어.md | 모든 작업의 최소 행동 게이트 | 예 |
| 01-비가역-가드.md | permissions·sandbox·hooks·Git 안전 | 아니요 |
| 02-완료-검증-가드.md | 주장-증거 기반 완료 검증 | 아니요 |
| 03-진단-수리-분리.md | 유관 경계·가설·probe·수리 | 아니요 |
| 04-오염-차단.md | 인젝션·증거 세탁·세션 인계 | 아니요 |
| 05-정직-보고.md | 근거 provenance와 연구 범위 | 아니요 |
| 06-되묻기-기록.md | 사용자 결과·proxy·질문·기록 | 아니요 |
| 07-한국어-가드.md | 한국 로컬 정보·번역·정밀 수치 | 아니요 |
| 08-분기-플레이북.md | 고영향 대안·추가 검토의 비용 게이트 | 아니요 |
| 09-행동-회귀-테스트.md | 정적·행동·실행층 평가 명세 | 아니요 |
| skills/ | 문구 트리거 1개(`가드팩 기준으로`) + 01~08 정본을 필요할 때만 읽는 router 4개 + 수동 안전 감사 1개 | plugin |
| .claude-plugin/plugin.json | Skill plugin 이름·버전 manifest | plugin |
| .claude-plugin/marketplace.json | 로컬 폴더를 지속 설치하기 위한 marketplace catalog | plugin |
| docs/QUICKSTART.md | 수강생용 코어·Skill 2단계 설치와 호출 안내 | 아니요 |
| docs/EVALUATION.md | 정적 검사·행동 A/B·공개 주장의 증거 경계 | 아니요 |
| docs/MAINTAINERS.md | 유지관리자용: 버전 이력, PDF·ZIP 빌드, 행동 평가 실행 | 아니요 |
| docs/release-helper.md | 배포 zip 최상위 `CLAUDE.md`로 복사되는 Claude용 설치 도우미 | 아니요 |
| docs/시작하기.txt | 배포 zip 최상위에 놓이는 사람용 시작 안내 | 아니요 |
| install_guardpack.py | 읽기 전용 계획이 기본인 보수적 사용자 전역 설치기 | 실행 파일 |
| rollback_guardpack.py | 명시한 백업과 현재 활성 hash가 일치할 때만 CLAUDE.md를 조건부 복원 | 실행 파일 |
| verify_guardpack.py | 파일·버전·import·알려진 충돌의 정적 검사 | 실행 파일 |
| build_guardpack_pdf.py | README·00~09에서 PDF 부록을 재생성 | 실행 파일 |
| docs/report.template.html | 근거 보고서의 단일 HTML 원본 | 아니요 |
| behavior-fixtures/ | T01~T30 case 계약, 7개 pilot fixture, 평가계획·실행기록 schema | 아니요 |
| behavior_harness.py | 모델 ID를 준 계획 명령이 기본이고 유료 실행은 별도 승인 hash가 필요한 2조건 격리 pilot 실행기 | 실행 파일 |
| hook_logger.py | pilot 격리 환경 전용. instruction·도구·권한 event를 경로 라벨·해시·500자 미리보기로 기록 | 실행 파일 |
| validate_behavior_runs.py | 계획·행동기록·격리·정확한 비교 matrix·provenance 검사 | 실행 파일 |
| build_guardpack_zip.py | UTF-8 EFS local·central header를 검사하는 결정론적 배포 ZIP builder | 실행 파일 |
| tests/ | 설치·롤백·PDF·ZIP·plugin·pilot 계약의 결정론적 회귀 테스트 | 실행 파일 |

01~08은 정본 Markdown 플레이북이고 Skill은 짧은 router다. plugin을 설치하면 자동 호출 가능한
Skill의 description만 평소 컨텍스트에 보이고, 본문과 필요한 정본은 해당 작업에서만 읽힌다.
요청 끝에 `가드팩 기준으로 대답`이라고 쓰면 `guardpack` Skill이 켜져 요청 유형에 맞는
router를 대신 골라 호출한다. 문구가 없어도 router 4개는 작업 유형이 맞으면 자동 호출될 수 있다. 01의 permissions·sandbox·hooks 감사 Skill은 `disable-model-invocation: true`라 사람이
직접 호출해야 하며 설정을 자동 변경하지 않는다. 09는 사람·유지관리자용 평가 oracle이고 일반
작업에 자동 routing하지 않는다. 고비용 분기 역시 관련성과 정보가치 gate를 통과해야 한다.

### 설정 감사와 코드 보안 감사 연결

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

## “글로벌 파일 수”의 정확한 뜻

- 이 가드팩이 글로벌로 import하는 파일은 00 하나다.
- 실제 전체 활성 컨텍스트 수는 사용자 CLAUDE.md의 다른 import, rules, 프로젝트·로컬·관리형
  지침, auto memory, 현재 작업 경로와 lazy loading에 따라 달라진다.
- 공식 문서는 “정확히 한 파일”을 요구하지 않는다. import 파일도 모두 컨텍스트에
  들어가므로 목표는 파일 수가 아니라 짧고 구체적인 규칙과 물질 충돌 0개다.
- 00 하나만 두는 것은 이 팩의 설계 선택이다. 긴 절차를 매 세션에 넣지 않기 위함이다.

## 초보자 설치 요약 — 코어와 Skill은 별도다

1. PDF가 아니라 받은 pack 폴더 전체에서 `python3 --version`을 실행한다. 명령이 없으면 설치를 진행하지 말고
   신뢰한 OS·패키지 배포 경로로 Python 3부터 준비한다. Chrome은 PDF를 새로 만들 때만 필요하다.
2. 아래 명령은 **계획만 출력하고 아무 파일도 쓰지 않는다**.

    python3 -B install_guardpack.py

3. 출력의 `CONFIG_ROOT`가 맞는지 본다. 기본은 `CLAUDE_CONFIG_DIR`가 있으면 그 경로,
   없으면 `~/.claude`다. 다른 루트라면 `--config-root /정확한/경로`를 붙여 다시 계획한다.
4. `BLOCK`이 없고 예상 경로·변경이 맞을 때만 PLAN이 출력한 `NEXT_APPLY:` 명령을 **그대로**
   복사해 적용한다. `--apply`는 검토한 루트가 명시되지 않으면 거부된다.

    python3 -B install_guardpack.py --config-root /PLAN에서_확인한_동일_경로 --apply

5. `BLOCK`이면 쓰기는 없었다. 파일을 지우거나 덮어쓰지 말고 아래 원인별로 처리한다.
   - legacy fingerprint 후보: 출력된 `provenance`의 importer:line → source chain과 `/context`로
     실제 로드를 확인하고 의미 감사한다. 수동 비활성화가 필요하면 **importer 파일을 별도
     바이트 백업**하고 정확한 충돌 import만 바꾼다. fingerprint 원문 파일을 바로 삭제하지 않는다.
   - 같은 2.3.7 경로의 해시 불일치: 덮어쓰지 말고 배포 원본·버전명을 다시 확인한다.
   - 마커 누락·역전·중복: 가장 최근의 검증된 CLAUDE.md 백업과 비교해 마커만 복구한다.
   수정 뒤에는 계획 명령부터 다시 실행한다.

6. 여기까지는 글로벌 코어만 설치한 것이다. 작업별 Skill도 쓰려면 `docs/QUICKSTART.md`의
   로컬 marketplace 등록과 plugin 설치를 별도로 실행한다. 첫 명령만 실행해서는 설치되지 않는다.

v2.1·v2.2·v2.3.0·v2.3.1·v2.3.2·v2.3.3·v2.3.4·v2.3.5 또는 v2.3.7 관리 마커만 있는 설치는 설치기가 v2.3.7 import로 교체할 수 있다.
v1의 다중 import나
별도 구판 분기 정책이 함께 있으면 보수적으로 멈춘다. 그 경우 구판 파일을 삭제하지 말고
각 수동 편집 파일을 따로 백업한 뒤, 실제 충돌하는 활성 import만 비활성화하고 다시 감사한다.

## 설치 1단계 — 쓰지 말고 감사

먼저 Plan/읽기 전용으로 다음을 확인한다.

1. `CLAUDE_CONFIG_DIR` 적용 여부를 포함한 현재 설정 루트와 사용자 CLAUDE.md 경로
2. CLAUDE.md 본문과 inline·재귀 import(공식 한도 4 hop), unscoped rules, 현재 프로젝트의
   CLAUDE/CLAUDE.local 계층, 확인 가능한 managed policy와 auto memory
3. 가드팩 시작·끝 마커의 누락·중복
4. 같은 조건에서 허용행동·안전·검증·원복·증거 인계를 다르게 요구하는 기존 지침
5. 설치 대상 버전 폴더의 존재와 해시. 이 해시는 배포 원본과 복사본의 동일성만 보며
   독립 배포 서명이나 제작자 진위를 증명하지 않음

Claude에게 맡길 때:

    아직 아무것도 수정하지 마. 현재 사용자 CLAUDE.md 본문과 inline·재귀 import, rules를 읽고,
    이 가드팩 00과 물질적으로 충돌하는 활성 규칙을 파일:행과 행동 차이로 보고해.
    기존 파일, 마커, 설치 경로, 백업·롤백 계획과 예상 diff도 보여줘.

`/memory`는 user/project 범위의 파일 위치를 열고 편집하는 목록이며 아직 존재하지 않는
항목도 보일 수 있다. 현재 세션에 실제 로드된 파일은 `/context`의 Memory files에서 확인하고,
CLAUDE.md와 rules가 언제·왜 로드됐는지는 `InstructionsLoaded` hook 로그로 확인할 수 있다.
이 hook은 auto memory나 Skill의 실제 사용 여부까지 대신하지 않으며, 어느 방법도 의미 충돌·
준수·강제를 자동 증명하지 않는다. 정적 fingerprint도 실제 활성 상태나 임의 한국어의 의미를
확정하지 않고 보수적 감사 후보만 낸다.

공식 parser가 import 제외를 보장하는 표기는 Markdown code span과 fenced code block이다.
`@경로`를 예시로만 적을 때는 backtick이나 fence를 쓰고, 네 칸 들여쓰기만으로 숨겼다고
가정하지 않는다. 검사기도 그 경우를 보수적으로 import 후보로 본다.

## 설치 2단계 — 먼저 실행 가능한 읽기 전용 계획

pack 폴더에서 실행한다. 기본 모드는 파일을 만들지 않으며 위 기본 설정 루트를 자동 판정한다.

    python3 -B install_guardpack.py

출력 경로·기존 파일·버전 폴더·충돌·변경 범위를 검토한 뒤에만 `--apply`를 붙인다.
설치기는 현재 CLAUDE.md를 백업하고, 없는 2.3.7 폴더를 새로 복사하며, 관리 마커 블록만
추가·교체한다. permissions·sandbox·hooks·모델 설정과 마커 밖 개인 규칙은 바꾸지 않는다.
같은 버전의 해시가 다르거나 정적으로 도달 가능한 알려진 구판 fingerprint가 있으면 실제
활성·의미 여부를 확인하도록 쓰기 전에 보수적으로 멈춘다.

APPLY의 쓰기는 지원되는 POSIX 환경에서 열린 directory FD와 상대 leaf에 고정하고, 경로
구성요소·파일을 no-follow로 다시 확인한다. 심볼릭 링크로 설정 루트 밖에 버전·백업을 쓰는
경로 재해석은 차단한다. 필요한 `dir_fd`/no-follow 기능이 없으면 경로 기반 fallback 없이
중단한다. 같은 사용자 권한의 악성 프로세스 격리나 ACL 제거까지 보증하는 보안 sandbox는 아니다.

    python3 -B install_guardpack.py --config-root /실제/Claude/설정루트 --apply

처음 설치라 CLAUDE.md가 없어도 `--apply`가 새 파일과 “기존 파일 없음” 백업 manifest를
만든다. 알려진 충돌 외의 의미 충돌은 아래 수동 감사와 새 세션 확인이 여전히 필요하다.

## 설치기가 수행하는 변경의 정확한 규칙

1. 설치기는 현재 CLAUDE.md만 시각이 포함된 별도 경로에 바이트 그대로 백업한다. 설치기가
   import한 다른 파일은 편집하지 않는다. 충돌 import를 사람이 수동 편집하면 그 파일은
   **설치기 백업과 별도로** 먼저 바이트 백업한다.
2. 배포 manifest의 파일을 설정 루트의 guardpack/versions/2.3.7/ 안에 직접 복사한다.
   그 폴더 바로 아래에 README·00~09·실행기·fixture·tests가 있어야 하며 중첩된
   바이브코딩-가드팩 폴더가 한 번 더 생기면 안 된다. portable no-clobber를 위해 최종
   버전 폴더를 먼저 만든 뒤 채우므로 전원 중단 시 partial 폴더가 남을 수 있다. 이 경우
   재사용·덮어쓰지 않고 무결성 BLOCK으로 멈춘다.
3. 같은 2.3.7 폴더가 이미 있으면 덮어쓰지 않는다. 원본과 해시가 같으면 재사용하고,
   다르면 무결성 이상으로 멈춘다.
4. 사용자 CLAUDE.md의 기존 내용을 지우지 말고 다음 관리 블록을 정확히 한 번 둔다.

    <!-- VIBECODING_GUARDPACK_BEGIN -->
    @guardpack/versions/2.3.7/00-글로벌-코어.md
    <!-- VIBECODING_GUARDPACK_END -->

5. 마커 밖의 과거 가드팩·분기 import는 자동 삭제하지 않는다. 새 코어와 물질 충돌하는
   정확한 줄만 백업과 diff를 확인한 뒤 비활성화한다. 다른 개인 규칙은 보존한다.
6. 새 세션에서 `/context`의 Memory files로 실제 대상이 로드되는지 확인한다. `/memory`는
   위치·내용 감사와 편집에 쓰고 실제 로드 증거로 대신하지 않는다.
7. 정적 gate를 실행하고 09와 behavior-fixtures의 oracle로 격리 행동 fixture를 설계·실행한다.

이 user-scope import 방식은 로컬 Claude Code용이다. 데스크톱 Cowork 세션은 user-scope
파일의 import가 작업공간 밖으로 해석되면 그 import를 건너뛸 수 있다.

정적 검사는 pack 폴더에서 다음처럼 실행한다. 이 검사는 모델 행동이나 sandbox 강제를
증명하지 않는다.

    python3 -B verify_guardpack.py --config-root /실제/설정루트 \
      --global-claude /실제/설정루트/CLAUDE.md \
      --installed /실제/설정루트/guardpack/versions/2.3.7 --cwd /검사할/프로젝트

`--config-root`만 주면 그 루트의 `CLAUDE.md`와 `guardpack/versions/2.3.7`을 자동으로 함께
검사한다. 둘 다 없으면 `WARN: CORE-NOT-INSTALLED`와 `RESULT: PASS (partial; …)`로 끝나며,
이는 코어가 그 루트에 설치되지 않았다는 뜻이지 통과가 아니다.

검사기는 root 본문·inline/재귀 import·unscoped rules·지정 프로젝트 계층과 관리 블록 구조를
본다. `--config-root`를 주면 **user scope**의 개인 Skill·legacy command와
`installed_plugins.json`에서 `scope: user`로 확인된 설치 plugin metadata를 읽기 전용으로
검사한다. 다른 scope 또는 scope 불명 record는 추정하지 않고 미검사 범위로 묶는다. `--cwd`는
글로벌·프로젝트 memory·rules 계층 검사용이며, project/local Skill·plugin을 반쪽만
추정해 routing 결론으로 섞지 않는다.

legacy fingerprint와 routing 경고는 정적으로 도달 가능한 보수 후보일 뿐 실제
활성·호출·의미 충돌의 확정이 아니다. project/local·managed·CLI setting source,
synced/nested Skill, marketplace entry에만 있는 custom component, description 예산 변경,
path-scoped/lazy memory, auto memory와 세션 한정 `--plugin-dir`는 해당 프로젝트의
`/status`·`/skills`·`/plugin`·실제 로드 로그와 사람 검토가 필요하다.

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

## Skill plugin 지속 설치

글로벌 코어 설치와 별개다. pack의 **실제 절대경로**를 따옴표 안에 넣는다.

    claude plugin marketplace add "/가드팩/절대경로"
    claude plugin install vibecoding-guardpack@vibecoding-guardpack-local

첫 명령은 설치 가능한 목록만 등록하고, 두 번째 명령이 6개 Skill을 실제 활성화한다. marketplace는
그 절대경로에 묶이므로 설치 뒤 pack 폴더를 옮기거나 지우면 새 세션에서 Skill이 로드되지 않는다
(`claude plugin list`가 cache-miss를 보고한다). 옮겨야 하면 새 경로로 두 명령을 다시 실행한다.
지원 환경은 macOS·Linux(WSL 포함)이며 Windows 네이티브 Python에서는 설치기가 `dir_fd` 미지원으로
BLOCK한다. 설치 뒤
새 세션의 `/skills`(또는 `claude plugin list`)에서 `vibecoding-guardpack` namespace를 확인한다. plugin 설치는 00을
글로벌 import하거나 permissions·sandbox·hooks를 바꾸지 않는다. 전체 설명과 상황별 호출은
`docs/QUICKSTART.md`에 있다.

팀 공통 규칙은 개인 사용자 전역 파일이 아니라 프로젝트 CLAUDE.md 또는 관리형 정책에
배포한다.

## 제거와 롤백

- 새 버전 폴더를 먼저 삭제하지 않는다.
- 설치 성공 때 출력된 정확한 `BACKUP`을 지정해 먼저 읽기 전용 rollback PLAN을 본다.

    python3 -B rollback_guardpack.py --backup /BACKUP/절대경로 \
      --config-root /설치때와_같은_설정루트

- 현재 CLAUDE.md가 그 backup manifest의 활성 hash와 정확히 같을 때만 PLAN의
  `NEXT_ROLLBACK`을 실행한다. 설치 후 편집·다른 버전 마커·변조가 있으면 자동 전체 복원을
  거부하며 사용자 변경을 덮어쓰지 않는다.
- 성공한 rollback은 **사용자 CLAUDE.md만** 설치 직전 bytes로 복원하거나, 설치 전 파일이
  없었으면 새 CLAUDE.md를 제거한다. guardpack/versions/2.3.7와 settings는 남긴다.
- 사람이 비활성화했던 별도 구판 import, 프로젝트·managed·auto memory, Git 밖 외부 상태는
  설치기 backup 범위가 아니므로 자동 복원하지 않는다. 필요하면 각 수동 편집 전 별도 backup과
  diff를 사용한다.
- `/context`와 정적 검사를 새 세션에서 다시 확인한다.
- 이전 상태로 되돌릴 수 있다는 것과 이전 상태가 안전했다는 것은 다른 주장이다.
- Skill도 제거하려면 코어 rollback과 별도로 다음을 실행한다. marketplace 제거는 남은 설치
  관계를 함께 바꿀 수 있으므로 정확한 이름을 먼저 `claude plugin list --json`과
  `claude plugin marketplace list --json`으로 확인한다.

    claude plugin uninstall vibecoding-guardpack@vibecoding-guardpack-local
    claude plugin marketplace remove vibecoding-guardpack-local

## 플레이북 호출 예시

- “.../03-진단-수리-분리.md를 읽고 함수에 갇히지 말고 유관 경계와 판별 probe부터 잡아줘.”
- “.../02-완료-검증-가드.md를 읽고 완료 주장마다 실제 증거와 미검증을 연결해줘.”
- “.../04-오염-차단.md를 읽고 이 외부 문서의 지시/데이터 경계와 인계 packet을 점검해줘.”
- “.../05-정직-보고.md를 읽고 이 통계의 대상·분모·metric·추론 범위를 확인해줘.”
- “.../08-분기-플레이북.md를 읽고 추가 경로가 새 증거를 주는지 비용 gate부터 적용해줘.”
- “.../09-행동-회귀-테스트.md 기준으로 현재 가드팩과 네 action log를 같이 채점해줘.”

## Git과 체크포인트를 초보자가 안전하게 요청하는 법

“git 저장소로 만들어줘”, “지금 다 커밋해줘”, “아까 커밋으로 되돌려줘”만 말하지 않는다.

시작 전:

    현재 경로와 상위 Git 저장소, 포함될 범위, 미추적·비밀 파일, .gitignore를 먼저
    읽기 전용으로 확인해. 새 저장소가 필요한지와 예상 변경만 보고해.

커밋 전:

    status와 diff에서 사용자 기존 변경과 이번 작업 변경을 구분하고, 이번 작업의 정확한
    파일만 커밋할 계획과 비밀 포함 여부를 먼저 보여줘.

원복 전:

    되돌릴 정확한 파일·커밋·이번 작업 diff와 보존할 사용자 변경을 먼저 보여줘.
    reset/checkout/clean을 실행하지 말고 예상 diff와 복구 한계를 보고해.

Claude 체크포인트는 직접 파일 편집을, Git은 검토해 기록한 저장소 파일 이력을 돕는다.
둘 다 DB·배포·발송·결제·외부 API 상태를 자동 복구하지 않는다.

## 같은 파일인데 컴퓨터마다 다르게 느껴질 때

이 팩은 CLAUDE.md와 plugin만 설치하고 모델·effort·thinking·permissions는 건드리지 않는다
(`SETTINGS: unchanged`). 그래서 같은 파일을 받아도 다른 컴퓨터에서는 덜 먹는 것처럼 느껴질
수 있다. 순서대로 확인한다.

| 확인할 것 | 어디서 | 안 보이면 |
|---|---|---|
| 코어가 실제로 로드됐나 | `/context`의 Memory files에 `00-글로벌-코어.md` | `python3 -B verify_guardpack.py --config-root <설정루트>`의 FAIL·WARN을 Claude에게 붙여넣는다 |
| 문구 트리거가 살아 있나 | `/context`의 Skills 행에 `vibecoding-guardpack:guardpack` description | 스킬 목록 예산(컨텍스트의 1%)을 넘으면 덜 쓴 스킬부터 조용히 빠진다. `skillListingBudgetFraction`을 올리거나 안 쓰는 스킬을 줄인다 |
| plugin이 켜져 있나 | `/skills` 또는 `claude plugin list` | 폴더를 옮겼으면 새 경로로 marketplace 등록 → plugin 설치를 다시 한다 |
| 모델·effort·thinking | `/status`, `/config` | 규칙은 같아도 읽는 모델이 다르면 준수 정도가 다르다. 팩이 바꿔 주지 않는다 |
| 프로젝트 CLAUDE.md가 덮어쓰나 | `/memory` 목록 | 프로젝트 지침이 코어와 다른 방향이면 그 프로젝트에서만 덜 먹는다 |

## 실행 강제층

01을 읽고 permissions·sandbox·hooks를 **별도 변경**으로 감사·적용한다. 이 팩은 환경별
allow, credential, excludedCommands와 운영 경계를 모른 채 안전한 척하는 범용 settings JSON이나
hook을 자동 설치하지 않는다. 정상 작업과 위험 fixture를 모두 시험하기 전에는 “안전 설정
완료”라고 하지 않는다.

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
