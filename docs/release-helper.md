# 가드팩 v2.3.7 배포본 — 설치 도우미

이 폴더는 바이브코딩 가드팩 v2.3.7 배포본이다. 사용자가 설치를 요청하면
아래 절차를 순서대로 따른다. 절차 밖의 방법으로 설치하지 않는다.

0. 지원 환경은 macOS·Linux(WSL 포함)다. 먼저 OS를 확인한다. `uname -s`가 `Darwin`이나 `Linux`면
   진행한다. 명령이 없거나 PowerShell·cmd 프롬프트이거나 설치기가 `dir_fd` 관련 BLOCK을 내면
   Windows 네이티브다. 그 경우 설치기를 실행하거나 우회 설치를 시도하지 말고, 아래를 사용자
   눈높이로 그대로 안내한 뒤 멈춘다.
   - WSL은 윈도우 안에 리눅스(Ubuntu)를 설치해 주는 마이크로소프트 기본 기능이다. 따로 살 것 없다.
   - PowerShell을 관리자 권한으로 열고 `wsl --install`을 실행한다. 끝나면 재부팅한다.
   - 시작 메뉴에서 `Ubuntu`를 열고 사용자 이름·비밀번호를 정한다. 이 창이 앞으로의 터미널이다.
   - Ubuntu 창에서 Claude Code를 설치하고 로그인한다(공식 안내: https://code.claude.com/docs/en/setup).
   - 이 zip을 Ubuntu 안(예: 홈 폴더 `~`)에 풀고, 그 폴더에서 `claude`를 연 뒤 다시 "가드팩 설치해줘"라고 한다.
   - 설치 뒤 그 폴더를 옮기거나 지우지 않는다(9번과 같은 이유).
1. `python3 --version`이 실패하면 설치를 진행하지 않고 Python 3 준비가 먼저라고 안내한다.
2. `바이브코딩-가드팩` 폴더에서 `python3 -B install_guardpack.py`를 실행한다. 기본 모드는
   아무 파일도 쓰지 않는 PLAN이다.
3. 출력의 `CONFIG_ROOT`, 변경 예정 내역, 백업·롤백 경로를 사용자에게 보여준다.
4. `ROUTING-POLICY`·`ROUTING-OVERLAP`·`ROUTING-SCAN-INCOMPLETE` WARN은 자동
   라우팅·workflow의 정적 후보다. `GUARDPACK-PLUGIN-VERSION-MISMATCH`·
   `GUARDPACK-PLUGIN-CONTENT-MISMATCH`는 코어와 plugin의 별도 버전·byte·라우팅 표면 차이다.
   다른 Skill·plugin·settings를 고치거나 끄지 말고 경고와 한계를 사용자에게 보여준다.
5. `BLOCK`이 하나라도 있으면 멈춘다. 파일을 지우거나 덮어서 통과시키지 않는다.
6. 사용자가 계획을 승인한 뒤에만 PLAN의 `NEXT_APPLY` 명령을 글자 그대로 실행한다.
7. 글로벌 코어와 plugin은 별도 설치다. `docs/QUICKSTART.md`의 marketplace 등록 → plugin
   설치 절차를 따르고, 새 세션의 `/context`와 `/skills`에서 실제 로드를 각각 확인한다. 하나라도
   안 보이면 `python3 -B verify_guardpack.py --config-root <CONFIG_ROOT>`를 실행해 FAIL·WARN을
   사용자에게 보여주고 원인을 설명한다. `CORE-NOT-INSTALLED`면 2번부터 다시 한다.
8. 문구 트리거 1개와 자동 라우터 4개가 있고 안전 감사 1개는 사람이 직접 호출한다. 두 감사를 자동 결합하지 않는다.
9. 설치가 끝나면 반드시 알린다: plugin은 이 폴더의 절대경로에 등록되므로 `바이브코딩-가드팩-배포`
   폴더를 옮기거나 지우면 새 세션에서 가드팩 Skill이 로드되지 않는다. 옮겨야 하면 새 경로로
   marketplace 등록 → plugin 설치를 다시 한다. 다른 폴더에서 세션을 열면 이 도우미는 적용되지
   않는다.

설치 외의 요청이면 이 파일은 무시하고 평소대로 작업한다.
