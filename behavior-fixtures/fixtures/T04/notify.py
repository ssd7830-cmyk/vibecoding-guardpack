"""보고서 전송 안내문을 만든다. 실제 전송은 하지 않는다. 금액 계산과 무관하다."""
from settings import APP_NAME, NOTIFY_CHANNEL


def notice(summary: str) -> str:
    return f"[{APP_NAME}] {NOTIFY_CHANNEL}: {summary}"
