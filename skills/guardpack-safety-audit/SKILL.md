---
name: guardpack-safety-audit
description: "사용자가 Claude Code의 permissions, sandbox, hooks, Git 안전 경계를 명시적으로 감사해 달라고 요청했을 때만 쓰는 사람 승인 전용 읽기 감사입니다."
disable-model-invocation: true
user-invocable: true
argument-hint: "[감사할 설정 또는 프로젝트]"
---

# 사람 승인 전용 안전 감사

이 파일은 라우터일 뿐이며 안전 규칙의 정본이 아니다.

1. 먼저 Read 도구로 `${CLAUDE_PLUGIN_ROOT}/01-비가역-가드.md` 정본을 끝까지 읽는다.
2. 이 호출 자체는 설정 변경을 승인하지 않는다. 현재 상태, 실제 적용 범위, 위험, 예상 변경,
   검증 fixture, 백업과 복구 한계만 읽기 전용으로 감사한다.
3. `CLAUDE.md`, settings, permissions, sandbox, hooks, Git 상태와 외부 상태를 바꾸지 않는다.
4. 코드 취약점 감사도 요청됐다면 `/security-review`를 대신 실행하지 말고 다음 준비 상태만
   읽기 전용으로 확인한다.
   - 현재 대상 경로와 Git worktree 여부
   - `origin/HEAD`와 `HEAD`가 해석되는지
   - `git diff --name-only origin/HEAD...`의 커밋 diff 파일 수
   - 커밋 diff 이후의 staged·unstaged 내용과 untracked 파일 등 위 diff에서 빠지는 변경
   - 현재 Claude Code에서 `/security-review`를 사용할 수 있는지 확인된 범위
5. 인계 카드는 `상태 / 대상 경로 / origin/HEAD·HEAD / 커밋 diff 파일 수 /
   staged·unstaged·untracked 누락 / 정확한 다음 명령` 순서로 쓴다. 상태는 다음 중 하나만 쓴다.
   - `실행 가능`: Git·명령·기준 ref가 확인되고 커밋 diff가 있으며 누락 변경이 없음
   - `검토 대상 없음`: 커밋 diff가 0이고 working tree도 깨끗함
   - `범위 누락`: staged·unstaged·untracked 등 내장 감사 범위 밖 변경이 있음
   - `미실행`: 비 Git, `origin/HEAD` 없음, 권한·API 실패 등으로 실행 조건을 확인하지 못함
   - `미지원`: 현재 Claude Code에 명령이 없음
6. `실행 가능`일 때만 다음 단계로 사람이 별도 메시지에서 `/security-review`를 직접 호출하도록
   안내한다. 발견 0건도 “검토 범위에서 보고 기준을 넘은 고신뢰 새 취약점이 보고되지 않음”으로
   제한하며 전체 안전·통과·보안 완료로 확대하지 않는다.
7. 적용이 필요하면 정확한 대상과 예상 diff, 정상·차단 시험, 롤백 절차를 보고하고 멈춘다.
   사용자가 그 변경을 별도로 승인한 뒤에만 새 요청 범위에서 실행한다.

자동으로 `/security-review`, `git init`, commit, remote 추가·fetch·set-head, permission 완화,
설정·코드 수정을 실행하지 않는다. 두 감사 중 한쪽의 미발견·실패를 다른 쪽의 판정으로 쓰지 않는다.

정본과 현재 사용자 요청이 충돌하면 더 강한 권한을 추정하지 말고 충돌과 영향을 보고한다.
