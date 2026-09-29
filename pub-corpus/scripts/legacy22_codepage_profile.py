#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, struct
from collections import Counter
from pathlib import Path
import olefile

CFB=bytes.fromhex("d0cf11e0a1b11ae1")
SUMMARY="\x05SummaryInformation"
DOCSUMMARY="\x05DocumentSummaryInformation"

def sha(b): return hashlib.sha256(b).hexdigest()
def u32(b,o):
    if o+4>len(b): raise ValueError("u32_oob")
    return struct.unpack_from("<I",b,o)[0]

def cp(ole,name):
    if not ole.exists(name): return None
    try: p=ole.getproperties(name,convert_time=False)
    except Exception as e: return {"status":"parse_error","error":type(e).__name__}
    v=p.get(1)
    if v is None:return {"status":"missing"}
    try:v=int(v)
    except Exception:return {"status":"non_integer"}
    if v<0:v+=65536
    return {"status":"present","value":v}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--corpus",type=Path,required=True);ap.add_argument("--out",type=Path,required=True);a=ap.parse_args()
    rows=[]; errs=[]
    for p in sorted(a.corpus.glob("*.pub")):
        data=p.read_bytes()
        try:
            if not data.startswith(CFB):continue
            with olefile.OleFileIO(p) as ole:
                if not ole.exists("Contents"):continue
                c=ole.openstream("Contents").read()
                if len(c)<4 or c[2]!=0x22:continue
                streams=["/".join(x) for x in ole.listdir(streams=True,storages=False)]
                if any(s=="Quill" or s.startswith("Quill/") for s in streams):continue
                hp=u32(c,0x12); d=hp+14; st=u32(c,d); en=u32(c,d+4)
                if st>en or en>len(c):raise ValueError(f"bad_text_range:{st}:{en}:{len(c)}")
                body=c[st:en]; hi=bytes(x for x in body if x>=0x80)
                rows.append({
                    "sha256":sha(data),"text_byte_len":len(body),"high_byte_count":len(hi),
                    "high_byte_distinct":sorted(set(hi)),
                    "high_byte_sha256":sha(hi) if hi else None,
                    "summary_codepage":cp(ole,SUMMARY),
                    "document_summary_codepage":cp(ole,DOCSUMMARY),
                })
        except Exception as e: errs.append({"sha256":sha(data),"error":f"{type(e).__name__}:{e}"})
    non=[r for r in rows if r["high_byte_count"]]
    def dist(field):
        c=Counter()
        for r in non:
            x=r[field] or {}
            c[str(x.get("value")) if x.get("status")=="present" else x.get("status","absent")]+=1
        return dict(sorted(c.items()))
    pairs=Counter()
    for r in non:
        def val(field):
            x=r[field] or {}
            return str(x.get("value")) if x.get("status")=="present" else x.get("status","absent")
        pairs[f"{val('summary_codepage')}/{val('document_summary_codepage')}"]+=1
    s={"schema":"chaptera.legacy22-codepage-signal-profile.v1","legacy22_noquill_file_count":len(rows),
       "non_ascii_text_file_count":len(non),"ascii_only_text_file_count":len(rows)-len(non),
       "summary_codepage_counts_on_non_ascii":dist("summary_codepage"),
       "document_summary_codepage_counts_on_non_ascii":dist("document_summary_codepage"),
       "codepage_pair_counts_on_non_ascii":dict(sorted(pairs.items())),
       "profile_error_count":len(errs),
       "evidence_boundary":"OLEPS PID_CODEPAGE is a persisted property-set string encoding signal only; no Publisher body-text authority is inferred."}
    a.out.mkdir(parents=True,exist_ok=True)
    for n,v in [("summary.json",s),("rows.json",rows),("errors.json",errs)]:(a.out/n).write_text(json.dumps(v,indent=2)+"\n")
    print(json.dumps(s,indent=2))
if __name__=="__main__":main()
