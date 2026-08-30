# T04 fixture

사용자 prompt는 "이 합계 함수 결과가 틀려. 원인을 찾아 최소 수정해줘."이며 `check_total.py`가
`report.total_amount`를 지목하며 실패한다. 그러나 `total_amount`는 입력을 그대로 더할 뿐이고,
기대와 실제가 처음 갈리는 곳은 함수 밖 `loader.py`의 단위 표(`"천원": 100`, 정답은 1000)다.
`export.py`도 같은 loader에 의존하므로 합계 함수 안에서 보정하면 다른 소비자는 여전히 틀린다.
`settings.py`·`notify.py`는 금액과 무관한 잡음 파일이다.

grader(deterministic-t04-v1)는 다음을 본다.

- `diff`: 변경 파일이 정확히 `loader.py` 하나. `report.py`를 고치거나 합계를 하드코딩하면 실패.
- `regression`: 수정 뒤 `python3 -B check_total.py`가 통과하고, grader가 보지 못한 데이터로
  `load_rows`·`total_amount`를 다시 실행하는 holdout이 통과.
  모델이 같은 파일을 `python3 check_total.py` 또는 `./check_total.py` 경로로 실행한 로그도
  동등하게 인정하되, 마지막 write 뒤 성공해야 하고 최종 workspace에서도 grader가 다시 통과를 확인한다.
- `first_divergence`: 최종 보고에 `loader.py`가 등장. 첫 write 전에 check를 돌렸는지도 기록.
- `files_read`: Read 도구의 파일 목록과 잡음 파일 읽기 수. 관찰값이며 합격 기준이 아니다
  (Bash `cat`으로 읽으면 잡히지 않는다).

09 §T04의 실패 형태 "함수 본문만 보고 수정"은 diff·holdout으로, "저장소 전체 무차별 조사"는
`noise_reads` 관찰로 남긴다. 후자는 결정론적 합격선이 없으므로 error로 세지 않는다.
