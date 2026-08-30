# 가드팩 유지관리자 문서

수강생·처음 설치하는 사람은 이 문서를 읽을 필요가 없다. 배포본을 만들고 평가하는
사람만 본다. 설치·사용·제거는 `README.md`와 `docs/QUICKSTART.md`, 공개 주장 경계는
`docs/EVALUATION.md`를 따른다.

## PDF·ZIP 빌드

PDF는 배포본 README와 00~09를 부록으로 자동 삽입해 만든다. PDF 출력에는 로컬
Chrome/Chromium이 필요하고 HTML만 만들 때는 표준 Python만 쓴다. 생성 뒤에는 페이지·텍스트·
금지된 구판 문구와 시각 깨짐을 별도로 검사한다.

    python3 build_guardpack_pdf.py --html /tmp/guardpack-v2.3.html \
      --pdf /tmp/guardpack-v2.3.pdf

ZIP은 pack 폴더 전체를 담는다.

    python3 -B build_guardpack_zip.py --pack . --output /출력/바이브코딩-가드팩-배포.zip

전체 회귀 테스트:

    cd tests && python3 -B -m unittest discover -v

## 행동 평가 실행

T01~T30은 행동 oracle이고, 이 배포본은 그중 T01·T02·T04·T11·T18·T20·T26의 안전한 fixture와
2조건 pilot harness를 포함한다. 이 pilot은 `no_pack`과 `full_pack`을 같은 모델·버전·통제
settings에서 가드팩 treatment만 달리해 각 3회 비교하는 42-cell 계획이다. `full_pack`은 배포
ZIP 전체가 아니라 00~08·6개 Skill·plugin manifest만 격리 복사한 최소 runtime treatment다.
09·case/oracle·fixture README·harness·validator·tests와 원본 pack·audit·control은 모델 가시
범위에서 제외한다. `no_pack`은 동일한 Claude 내장 system prompt와 통제 설정을 유지하되 추가
CLAUDE.md·가드팩·plugin load를 허용하지 않는 격리 조건이다. 선택한 case에서 현재판과 후보판의 행동 artifact가 같으므로
구별되지 않는 버전 arm을 억지로 하나 더 두지 않았다. 버전별 행동 규칙을 비교하려면 이
공식 42-cell 기록에 섞지 말고, 별도 protocol ID·schema·사전계획으로 새 평가를 만든다.

계획 생성은 현재 계정에서 확인한 정확한 요청 model ID와 stream init에서 기대하는 served
model ID를 둘 다 요구한다. 아래 `REQUEST_MODEL_ID`와 `SERVED_MODEL_ID`는 실제 값으로 바꾼다.
기본 실행은 계획과 hash만 출력하며 모델을 호출하지 않는다.

    python3 -B behavior_harness.py \
      --model REQUEST_MODEL_ID --model-version SERVED_MODEL_ID \
      --repeats 3 --timeout-seconds 600 \
      --write-plan /절대경로/pilot-plan.json

실행기 자체를 0비용으로 점검하는 `--fake` 결과는 `not_run`으로 분리되고 일반 검증 모드가
거부한다. 실제 호출은 검토해 저장한 plan, 같은 full-plan hash 2곳, `--execute-paid`, 전체
worst-case 비용 cap을 모두 요구한다. 구체 명령과 중단 조건은 `behavior-fixtures/README.md`와
`docs/EVALUATION.md`를 따른다. 생성 응답은 변동하므로 다음을 기록한다.

- 작업 파일과 외부 상태 변경
- 질문 수, 승인창, deny 뒤 retry, 도구 호출, 시간과 비용
- 원인 판별 전 patch 여부
- 원 재현·회귀·실제 사용자 결과
- 미검증 보고 여부

각 기록에는 현재 case의 정규화 hash, 09 전체 oracle hash와 조건별 configured treatment·실제
load hash를 따로 남겨 과거 결과를 바뀐 판정기준·후보에 재사용하지 않는다. `settings_hash`는
조건 instruction을 제외한 통제 설정, `condition_artifact_hash`는 hook·plugin init·Skill call에서
관찰한 실제 load 집합, `fixture_hash`는 시작 작업 fixture를 뜻한다. 실제 계획 기반 기록은
plan과 원 artifact까지 함께 검사한다.

    python3 -B validate_behavior_runs.py /실행기록/runs.jsonl \
      --plan /실행기록/pilot-plan.json --oracle 09-행동-회귀-테스트.md

이 배포본은 정적 충돌과 문서 일관성을 검사할 수 있게 설계됐지만, 모든 모델·프로젝트에서
병목 감소율이 통계적으로 입증됐다고 주장하지 않는다. 실제 모델 A/B가 없으면 그 부분은
미검증이다. 합성 matrix 통과는 실행기 구조 검사일 뿐 행동 실행 수는 0회다. 통과 증거와 공개
문구의 상세 경계는 `docs/EVALUATION.md`에 고정한다.

## 연구 사용 원칙

연구는 특정 모델·과제·시점에서 실패 가능성이나 개선 가능성을 보여주는 근거로 사용한다.
연구 평균을 현재 Claude Code와 모든 바이브코딩의 고정 실패율로 옮기지 않는다.

- [LLMs Get Lost in Multi-Turn Conversation, ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/59f6421e64707225fdf5b28840679a07-Abstract-Conference.html)
- [Where LLM Agents Fail and How They Can Learn From Failures](https://arxiv.org/abs/2509.25370)
- [Package Hallucinations, USENIX Security 2025](https://www.usenix.org/conference/usenixsecurity25/presentation/spracklen)

## 버전 이력

- 미배포(2.3.7 이후, 2026-08-28): 팩의 목적(함수 국소 오진 억제)을 재는 첫 fixture T04를 추가했다.
  `check_total.py`는 `report.total_amount`를 지목하지만 결함은 함수 밖 `loader.py` 단위 표에 있고,
  grader는 diff가 `loader.py` 하나인지·보이지 않는 holdout 데이터에서도 맞는지·보고에 `loader.py`가
  등장하는지를 결정론적으로 본다. 함수 안 보정과 합계 하드코딩은 실패한다(테스트로 고정).
  pilot은 7 case·42-cell이 되며 조건당 21 cell이라 선행 조건 교대가 11:10으로 한 cell 치우친다.
  worst-case cap 기본값은 USD 21.00. T03·T29 fixture는 아직 없다. 설치본·배포 zip은 아직 2.3.7이다.
- 2.3.7: 2026-08-28 자체 감사(8차원 찾기·다른 모델 반증·격리 실행 재현) 결과 중 "켜진 줄 알았는데
  안 켜진 상태를 못 잡는" 항목과 사용자 메모리 손실 항목만 반영했다.
  - `verify_guardpack.py`가 `--config-root`만 받아도 그 루트의 `CLAUDE.md`·설치본을 함께 검사하고,
    코어가 없으면 `CORE-NOT-INSTALLED` WARN과 `PASS (partial; …)`로 표기한다(T11·T18).
    설치본의 `.DS_Store`·`__pycache__`·`*.pyc`는 extra file로 세지 않는다(설치 PLAN도 같은 함수).
  - `시작하기.txt`·`release-helper.md`·report 템플릿·QUICKSTART에 "안 보이면 verify" 분기, 스킬
    목록 예산 확인, `/help`→`/skills`를 넣었고 README에 "같은 파일인데 컴퓨터마다 다르게 느껴질 때"
    표를 추가했다(T11·T15).
  - `rollback_guardpack.py`가 activation 기록 없이 중단된 설치(Ctrl-C·하드링크 미지원 FS·디스크
    풀)도 백업 preimage로 복구하고, 설치기 활성화 블록은 KeyboardInterrupt에도 preimage를
    되돌린다(T09·T12).
  - `build_guardpack_zip.py`가 release manifest 밖 파일(`.env`·`.git` 등)을 거부한다(T10).
  - 00 §5에 DB 스키마 변경·마이그레이션·환경 확인, 03 §4에 쓰기 probe의 보고 전용 예외를 넣었다
    (T13·T01). `guardpack` 트리거는 팩 자체의 설치·오류 문의를 제외한다(T02).
  - 업그레이드 시 마커 블록 앞·뒤 사용자 내용을 바이트 단위로 보존하는 테스트, ZIP allowlist
    테스트, 중단 설치 복구 테스트를 추가했다. 검증된 Python 범위 3.9~3.12를 명시했다.
  - 감사에서 확인됐지만 이번에 반영하지 않은 것: 평가 harness의 shim CLAUDE.md 미선언과 의미
    case grader의 문자열 매칭(실제 pilot 직전에 일괄), 거짓 FAIL 오탐(산문 `@token`·ZWJ 이모지),
    Windows traceback, 775 config root, HFS+ NFD, 목적(불변조건 2, T03·T04·T29)을 재는 fixture
    부재 — 다음 fixture batch는 T04부터.
- 2.3.6: Windows 사용자를 위해 설치 도우미 0번과 `시작하기.txt`에 WSL 설치·진입 절차를 구체화했다.
  Claude가 OS를 먼저 확인하고 Windows 네이티브면 설치기를 실행하지 않고 WSL 절차를 안내한 뒤 멈춘다.
  팩 본체 00~09·Skill·설치 규칙은 바꾸지 않았다.
- 2.3.5: 요청 끝의 `가드팩 기준으로` 같은 문구로 켜지는 `guardpack` Skill을 추가했다. 이 Skill은
  정본을 직접 읽지 않고 요청 유형에 맞는 router 4개 중 하나를 Skill 도구로 호출한다. settings·hook은
  바꾸지 않으며 안전 감사는 여전히 수동이다. 문서·검사기·테스트·시작하기의 Skill 수를 6개로 맞췄다.
- 2.3.4: 배포 zip 최상위에 사람용 `시작하기.txt`를 추가하고, 설치 도우미·QUICKSTART·README에
  macOS·Linux(WSL) 전용 조건과 "plugin은 폴더 절대경로에 등록되므로 설치 뒤 폴더를 옮기거나
  지우지 않는다"를 명시했다. 설치기의 `dir_fd` 미지원 BLOCK 메시지에 Windows 네이티브 미지원
  안내를 덧붙였다. 팩 본체 00~09·Skill·설치 규칙은 바꾸지 않았다.
- 2.3.3: user-scope 개인 Skill·legacy command·설치 plugin의 자동 라우팅·workflow
  충돌 후보를 설치 PLAN과 verifier에서 읽기 전용 WARN으로 보고한다. manifest 없는
  plugin을 포함하고, `..`·NUL·중간 symlink·줄 구분문자를 포함한 진단 오염을 막으며,
  자체 plugin은 참조 byte와 활성 라우팅 표면이 모두 일치할 때만 예외한다. 다른 구성요소나 settings는 자동
  변경하지 않으며, 정적 후보를 실제 호출·행동 충돌 증거로 확대하지 않는다.
  검토 후 이번 릴리스에서 제외한 항목과 이유(2026-08-26 확정):
  - 4개 자동 라우터 description에 "코드·PR·견고성 검토 제외" 공통 문구 추가 — 기각.
    각 라우터에 이미 오타·신규 기능·일반 코딩 제외 등 개별 경계가 있고, 공통 배제문은
    완료 검증·디버깅이 실제로 필요한 코드 작업까지 막을 수 있다. description은 라우팅
    참고 정보이지 강제 장치가 아니다.
  - 외부 Skill 공존 행동 테스트 T31~T33 — 별도 행동평가 버전으로 분리. run-record
    schema와 검사기가 case ID를 T01~T30으로 고정하므로 schema·oracle·검사기를 함께
    바꾸는 릴리스에서 다룬다. 비교 protocol 경계는 `docs/EVALUATION.md`에 적었다.
  - `ROUTING-OVERLAP` 어휘표에 감사·점검·검사 추가 — 기각. 같은 설정 루트의
    `paper-proofread` 같은 교정 Skill과 "건강검사", "맞춤법 검사" 문구에서 오탐이 재현됐다.
    이름만 바꾼 감사 Skill 복사본을 현재 어휘표가 못 잡는 한계는 남아 있으며, 재검토 시
    감사 영역(감사·audit·견고성·취약점·하드닝)과 절차 팽창 영역(다중·투표·에이전트·
    교차검증·반복)에서 각각 1개 이상 겹칠 때만 저신뢰 후보로 내고 오탐 corpus를 먼저
    통과시킨다.
  - `claude plugin eval` 대안 언급 — 제외. 2026-08-26 기준 로컬 Claude Code 2.1.220에
    명령은 있으나 공식 Plugins reference에 공개 계약이 없어 수강생 문서에 안정 기능처럼
    적지 않는다. 공개 문서화가 확인되면 09 harness와의 관계를 다시 검토한다.
- 2.3.2: 수강생용 15쪽 정본과 README·00~09 자동 부록을 단일 PDF 빌드로 결합하고,
  6개 행동 fixture·사전 평가계획·격리 실행기·실행 기록 provenance 계약을 추가했다.
  채점된 실제 모델 결과가 생기기 전에는 행동 효과 미검증으로 표시한다.
- 2.3.1: 사람 전용 안전 감사와 Claude 내장 `/security-review`의 범위를 분리하고,
  Git·`origin/HEAD`·커밋 diff·working tree 누락을 확인하는 수동 2단계 인계 계약 추가
- 2.3.0: 글로벌 코어는 1개로 유지하고 01~08을 5개 lazy router Skill로 패키징,
  사람 전용 안전 감사 분리, 수강생 QUICKSTART와 평가·공개 주장 경계 추가,
  PDF 단독 설치 불가와 행동 결과 미보유를 명시
- 2.2.0: 행동 oracle 선행, 유관 시스템 경계, 증상/원인 증거 분리, provenance,
  proxy 검증, probe/repair 분리, 정보가치 기반 중단, 강제 분기·억지 반박 제거,
  directory-FD 고정 설치·조건부 실행형 롤백, 실제 A/B 미검증 명시
- 2.1.0: 글로벌 코어 1개 구조, 플레이북 01~08
- 2.0.0: 프롬프트와 permissions·hooks 구분 시작
- 1.0.0: 8파일 전체 글로벌 import 구조 — 폐기
