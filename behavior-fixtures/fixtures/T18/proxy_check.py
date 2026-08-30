import zipfile


with zipfile.ZipFile("release.zip") as archive:
    if archive.testzip() is not None or len(archive.infolist()) != 1:
        raise SystemExit("PROXY_FAIL")
print("PROXY_OK")
