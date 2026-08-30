---
name: guardpack
description: "사용자 메시지에 '가드팩 기준', '가드팩기준', '가드팩으로', '가드팩 써서', '가드팩 적용', '가드팩 ㄱ', 'guardpack 기준' 중 하나라도 있으면 반드시 사용합니다. 요청 유형을 보고 완료 검증·진단·컨텍스트·근거 검토 router 중 맞는 것을 호출해 그 정본 기준으로 답합니다. 문구가 없는 일반 요청과, 가드팩 자체의 설치·수정·오류 문의에는 사용하지 않습니다."
disable-model-invocation: false
user-invocable: true
argument-hint: "[가드팩 기준으로 처리할 요청]"
---

# 가드팩 문구 트리거

이 파일은 "가드팩 기준으로" 같은 문구에 반응하는 입구일 뿐이며 규칙의 정본이 아니다. 실제
절차는 아래 router 스킬이 읽는 정본에 있다.

1. 트리거 문구를 뺀 실제 요청을 한 줄로 파악한다. 보고 전용 요청인지 수정 요청인지 그대로
   유지하고, 문구가 있다는 이유로 쓰기·외부 행동 권한을 넓히지 않는다.
2. 요청 유형에 맞는 router를 Skill 도구로 호출한다. 여러 개면 주된 것 하나를 먼저, 실제로
   필요할 때만 하나 더 호출한다.
   - 완료·검증·"진짜 다 됐는지" → `vibecoding-guardpack:guardpack-completion-check`
   - 원인 불명 버그·반복 실패·영향이 큰 수리 → `vibecoding-guardpack:guardpack-debug-evidence`
   - 외부 자료 취급·긴 세션 정리·세션 인계·범위가 불명확한 큰 작업 착수 → `vibecoding-guardpack:guardpack-context-intent`
   - 조사·비교·출처 확인·바뀔 수 있는 제품 사실·한국 로컬 정보·고영향 대안 → `vibecoding-guardpack:guardpack-evidence-review`
3. 오타 수정이나 결과·위험이 명확한 작은 요청이면 router를 호출하지 않는다. "가드팩 코어
   기준으로 바로 처리한다"고 한 줄만 말하고 진행한다.
4. permissions·sandbox·hooks·Git 안전 감사는 여기서 자동 호출하지 않는다. 필요하면 사용자가
   `/vibecoding-guardpack:guardpack-safety-audit`를 직접 호출하도록 안내한다.
5. 답변 끝에는 바뀐 결과, 주장별 증거, 미검증·차단 사항 중 실제로 해당하는 것만 쓴다.
