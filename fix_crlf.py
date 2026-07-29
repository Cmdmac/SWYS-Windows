import os

HERE = os.path.abspath(os.path.dirname(__file__))
targets = ["run.bat", "debug_start.bat"]

for fn in targets:
    p = os.path.join(HERE, fn)
    if not os.path.exists(p):
        print("skip (missing):", fn)
        continue
    with open(p, "rb") as f:
        data = f.read()
    # normalize: any \r\n or \r -> \n, then all \n -> \r\n
    normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")
    # ensure pure ASCII (strip any BOM)
    if normalized[:3] == b"\xef\xbb\xbf":
        normalized = normalized[3:]
    with open(p, "wb") as f:
        f.write(normalized)
    # verify
    d = open(p, "rb").read()
    has_crlf = b"\r\n" in d
    lf_only = (b"\n" in d) and (b"\r\n" not in d)
    non = sum(1 for b in d if b > 127)
    print(f"{fn}: CRLF={has_crlf} LFonly={lf_only} non_ascii={non} BOM={d[:3]==b'\\xef\\xbb\\xbf'}")
print("done")
