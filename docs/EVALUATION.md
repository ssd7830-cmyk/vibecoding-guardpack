# 가드팩 평가·주장 규칙

이 문서는 가드팩의 문구가 그럴듯한지가 아니라, **무엇을 실제로 검증했고 어디까지
말할 수 있는지**를 고정한다. 정적 검사, 배포 도구 테스트, LLM 행동 평가는 서로 다른
증거이며 대신할 수 없다.

## 현재 증거 상태

| 층 | 확인하는 것 | 이 배포본에 포함된 것 | 현재 말할 수 있는 범위 |
|---|---|---|---|
| 문서 자기감사 | 규칙 사이의 충돌·누락·과잉 요구 | 09의 T01~T30 oracle, 검토 기록에 쓸 기준 | 결함 후보를 찾았다는 것. 통과 증거는 아님 |
| 결정론적 구조 검사 | 파일·버전·import·manifest·설치·롤백·routing metadata·PDF·ZIP·pilot 계약 | 검사기, 합성 matrix 생성·검증 경로와 단위 테스트 | 검사한 입력과 코드 경로가 계약을 만족했다는 것. routing WARN은 실제 호출·충돌 증거가 아니며 행동 실행은 0회 |
| LLM 행동 평가 | 실제 모델이 조건별로 어떤 선택을 하는지 | 30개 case 계약, 선택한 7개 실행 fixture, 2조건 harness·plan·기록 schema | 채점된 실제 반복 기록이 없으면 효과를 주장할 수 없음 |
| 실제 사용 결과 | 초보자의 성공률·오진·중단·비용 변화 | 수집 도구나 사용자 연구 결과 없음 | 아직 미검증 |

T01은 과거 대화에서 관찰된 읽기 전용 준수 사례일 수 있으나, 재현 가능한 원본 session,
시작 상태, 전체 도구·write log, 모델 식별자와 고정 oracle가 함께 보존되지 않았다면 이
배포본의 독립 검증 결과로 세지 않는다. T02~T30도 테스트 **정의**이지 통과 기록이 아니다.

## 행동 A/B의 최소 계약

1. 비교 전에 모델·정확한 버전, 권한 모드, 도구, 설정, fixture, 프롬프트, oracle와
   합격 기준을 고정한다.
2. 물질적으로 다른 treatment만 둔다. 이 릴리스의 고정 pilot(09·harness 해시로 식별)은 `no_pack`과 `full_pack` 2조건,
   T01·T02·T04·T11·T18·T20·T26, 각 3회로 정확히 42개 cell이다. 이름만 다르고 해당 행동
   artifact가 같은 이전판은 독립 arm으로 세지 않는다.
   `full_pack`은 00~08·6개 Skill·plugin manifest만 제공하는 최소 runtime treatment이며,
   09·case/oracle·fixture README·평가 도구는 모델 가시 범위에서 제외한다. `no_pack`에는
   추가 CLAUDE.md·가드팩·plugin load를 허용하지 않는다.
3. 각 조건을 격리된 config root와 fresh session에서 시작한다. 시작 상태, configured
   treatment와 실제 로드된 instruction·plugin·Skill 관찰을 서로 다른 hash로 남긴다.
4. 조건 순서는 무작위화하거나 균형 교대한다. 같은 case를 충분히 반복하고 표본 수와
   중단 규칙을 결과를 보기 전에 정한다.
5. 자기평가 문장은 통과 증거로 쓰지 않는다. 파일 write audit, 명령·도구 log, 승인·거부,
   시작/종료 상태와 사용자 결과를 우선한다.
6. 결정론적으로 판정할 수 없는 의미 항목은 condition·model·config 식별자를 뺀 packet으로
   사람이 고정 rubric을 적용한다. 원 응답이 treatment를 스스로 언급할 수 있으므로 이는
   완전한 이중맹검이 아니라 **조건 metadata masking**이다. 개입 시점과 내용을 기록한다.
7. 안전 억제뿐 아니라 정상 작업 성공률, 불필요한 질문·중단·승인·재시도,
   시간과 비용도 함께 비교한다.
8. 누락·실패·중단 표본을 버리지 않는다. 변경된 oracle나 instruction으로 과거 기록을
   재채점할 때는 별도 분석으로 표시한다.

모델 ID를 준 계획 명령은 계획과 full-plan hash만 출력하고 모델을 호출하지 않는다. 모델 ID가
없으면 `BLOCK: an exact requested model ID is required`로 멈춘다.

    python3 -B behavior_harness.py \
      --model REQUEST_MODEL_ID --model-version SERVED_MODEL_ID \
      --write-plan /절대경로/pilot-plan.json

`--fake`는 42-cell 산출 경로와 grader를 점검하지만 모든 record가 `not_run`이며 실측으로
검증할 수 없다. 실제 호출은 저장·검토한 plan, 일치하는 hash 2곳, 명시 실행 flag와 전체
worst-case 비용 cap 없이는 차단된다. 실행 기록은 `behavior-fixtures/run-record.schema.json`을
만족해야 하며 plan·oracle·원 artifact와 함께 구조를 확인한다.

    python3 -B validate_behavior_runs.py /실행기록/runs.jsonl \
      --plan /실행기록/pilot-plan.json --oracle 09-행동-회귀-테스트.md

schema 통과는 기록 형식의 검증일 뿐, 관찰값의 진실성·채점의 타당성·효과 크기를 증명하지
않는다.

## Skill·plugin 공존 검사의 증거 경계

v2.3.3의 detector는 명시한 config root의 user scope에서 개인 Skill·legacy command와
`scope: user`로 확인된 설치 plugin의 frontmatter·component identity를 정적으로 읽는다. 다른
scope 또는 scope 불명 record는 추정하지 않는다. 알려진 workflow 후보와 두 개
이상의 보수 어휘 겹침을 WARN으로 분리하며 다른 구성요소를 수정하거나 비활성화하지 않는다.
이는 설치·업데이트 뒤 사람이 볼 감사 후보를 만드는 구조 검사다.

`installed_plugins.json`과 user `settings.json`만으로는 project/local/managed/CLI scope의 최종
활성 상태, synced/nested Skill, marketplace entry에만 있는 custom component, 세션 한정
`--plugin-dir`, managed·cloud 환경을 완전히 재현하지 않는다. description 겹침도 실제 모델
라우팅이나 호출 뒤 정책 충돌을 증명하지 않는다. 외부 Skill과의 효과를 주장하려면 같은
외부 Skill을 둔 `외부 Skill만` 대 `가드팩+외부 Skill` 조건을 별도 protocol로 사전등록하고
실제 Skill 호출·Agent·질문·쓰기 log를 반복 채점해야 한다. 이 릴리스에는 그 행동 결과가 없다.

## 릴리스 때 남겨야 할 증거

- 배포본 전체 hash와 정확한 버전
- 실행한 명령, 종료 코드, 테스트 수와 전체 출력 보관 위치
- 정적 검사가 읽은 글로벌·프로젝트 범위와 읽지 못한 범위
- 행동 평가를 실행했다면 원본 run record, fixture/oracle/instruction hash, 표본 수와 탈락 사유
- 발견된 P0/P1/P2, 수정과 연결된 T-ID, 남은 미검증
- PDF가 어느 배포본에서 생성됐는지와 본문·부록 동기화 검사 결과

## 공개 문구의 경계

행동 A/B와 사용자 연구 기록이 없는 현재 배포본에는 다음처럼 말할 수 있다.

> 독립 조사와 반증 기준을 바탕으로 설계했고, 설치·롤백·구조 검사는 자동화했다.
> T01~T30 행동 평가 규격과 7개 case pilot 도구를 제공하지만, 실제 모델별 효과는 채점된
> 반복 실행 기록으로 별도 확인해야 한다.

다음 표현은 그에 맞는 원자료가 생기기 전에는 쓰지 않는다.

- “실제 행동 테스트로 작동을 확인했다”
- “서로 다른 AI 3개가 독립적으로 검증했다”
- “수십 건/21건의 연구가 이 설정 전체를 입증했다”
- “병목을 제거한다”, “성공률을 보장한다”, “가장 잘 쓰는 방법이다”

여러 모델이나 에이전트가 같은 원자료·실행·평가기준을 반복한 것은 관점 교차검토일 수는
있어도 독립 증거 수를 늘리지 않는다. 강한 표현은 에이전트 수가 아니라 공개 가능한
provenance와 재현 기록으로 정한다.
