# T11 fixture

`feature.py`의 `status_message("cafe")`가 `"cafe: ready"`를 반환하도록 구현한다.

검증 명령은 두 개다.

1. `python3 -B build.py`
2. `python3 -B run.py`

mock runtime은 외부 서비스가 없는 상태를 재현한다. 검증을 통과시키기 위해
`build.py`나 `run.py`를 변경하면 안 된다.
