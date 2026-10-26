"""Check the C# QR encoder (mod/src/Qr.cs). Test-only tools: segno (reference encoder) and OpenCV (decoder), never shipped.
Usage: check.py <cases.txt>   with o0.txt .. o7.txt (every mask forced) next to it, written by Program.cs.
 1. Strict: for every mask 0..7 and every case whose length equals the version's capacity (no padding bytes), the matrix is
    identical, module for module, to segno's (same version, level M, byte mode). This covers Reed-Solomon, interleaving,
    placement, timing/finder/alignment, format and version information.
 2. Every case (also the shorter ones, which have padding) decodes with OpenCV to the original text under at least 6 of the 8 masks
    (OpenCV's detector alone misses an occasional valid symbol, so all-8 is not required; segno pads with an extra 00 byte, so
    shorter cases cannot be compared module for module).
 3. The mask the encoder picks (o-1 = out.txt) is one of the valid masks: its matrix equals the forced-mask matrix for some mask."""
import sys, segno
import numpy as np, cv2
CAPS = {1:14,2:26,3:42,4:62,5:84,6:106,7:122,8:152,9:180,10:213,11:251,12:287,13:331,14:362,15:412}
cases = open(sys.argv[1], encoding="utf-8").read().split("\n")[:-1]
def load(path):
    out = open(path).read().split("\n"); i = 0; res = []
    for idx, _ in enumerate(cases):
        head = out[i]; assert head.startswith("#%d " % idx), head
        if head.endswith("none"): res.append((0, None)); i += 1; continue
        v = int(head.split("v")[1]); n = 17 + 4 * v
        res.append((v, ["".join(r) for r in (list(x) for x in out[i+1:i+1+n])])); i += 1 + n
    return res
forced = [load("o%d.txt" % k) for k in range(8)]; auto = load("out.txt")
def dec(rows, text):
    m = np.array([[int(c) for c in r] for r in rows], dtype=np.uint8)
    img = np.pad((1 - m) * 255, 4, constant_values=255).astype(np.uint8)
    img = cv2.resize(img, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    return cv2.QRCodeDetector().detectAndDecode(img)[0] == text
problems = []; strict = 0
for idx, text in enumerate(cases):
    n_bytes = len(text.encode("utf-8"))
    v = auto[idx][0]
    if v == 0: problems.append((idx, "does not fit")); continue
    if CAPS[v] == n_bytes:
        for k in range(8):
            q = segno.make(text, error="m", mode="byte", micro=False, mask=k)
            ref = ["".join(str(b) for b in r) for r in q.matrix]
            if q.version != v or ref != forced[k][idx][1]: problems.append((idx, "mask %d differs from segno" % k))
            else: strict += 1
    good = sum(dec(forced[k][idx][1], text) for k in range(8))
    if good < 6: problems.append((idx, "decoded under only %d of 8 masks" % good))
    if auto[idx][1] not in [forced[k][idx][1] for k in range(8)]: problems.append((idx, "auto mask is no valid mask"))
print("cases", len(cases), "strict module-identical (case x mask)", strict, "problems", problems)
sys.exit(1 if problems else 0)
