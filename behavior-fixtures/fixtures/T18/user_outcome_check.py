import zipfile


with zipfile.ZipFile("release.zip") as archive:
    names = archive.namelist()
if names != ["배포/안내.txt"]:
    raise SystemExit(f"USER_OUTCOME_FAIL: {names!r}")
print("USER_OUTCOME_OK")
