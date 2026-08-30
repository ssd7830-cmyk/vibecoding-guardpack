from feature import status_message


if status_message("cafe") != "cafe: ready":
    raise SystemExit("FEATURE_FAIL")
raise SystemExit("MOCK_RUNTIME_UNAVAILABLE")
