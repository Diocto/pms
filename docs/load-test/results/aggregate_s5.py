# S5 회차 집계 (일회용). results/ 안에서 실행: python3 aggregate_s5.py
import json
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def val(m, name, key):
    x = m.get(name)
    return x.get(key) if x else None


rows = {}
for cond in ["on", "off"]:
    for r in [1, 2, 3]:
        tag = f"s5{cond}-r{r}"
        m = json.load(open(f"{tag}-k6-summary.json"))["metrics"]
        main = m.get("http_req_duration{phase:main}", {})
        reqs = m.get("http_reqs{phase:main}", {})
        row = {
            "created": val(m, "rsv_created", "count"),
            "lock_failed": val(m, "lock_failed", "count") or 0,
            "rej_inv": val(m, "rej_inventory", "count"),
            "rej_dup": val(m, "rej_duplicate", "count") or 0,
            "server_err": val(m, "server_error", "count"),
            "main_reqs": reqs.get("count"),
            "rps": round(reqs.get("count", 0) / 20, 1),
            "med": round(main.get("med", 0), 1),
            "p90": round(main.get("p(90)", 0), 1),
            "p95": round(main.get("p(95)", 0), 1),
            "p99": round(main.get("p(99)", 0), 1),
            "max": round(main.get("max", 0), 1),
            "d_created_p99": round(val(m, "dur_created", "p(99)") or 0, 1),
            "d_rejinv_p99": round(val(m, "dur_rej_inventory", "p(99)") or 0, 1),
            "d_created_med": round(val(m, "dur_created", "med") or 0, 1),
            "d_created_p95": round(val(m, "dur_created", "p(95)") or 0, 1),
            "d_rejinv_med": round(val(m, "dur_rej_inventory", "med") or 0, 1),
            "d_rejinv_p95": round(val(m, "dur_rej_inventory", "p(95)") or 0, 1),
            "d_lockf_med": round(val(m, "dur_lock_failed", "med") or 0, 1),
            "d_lockf_p95": round(val(m, "dur_lock_failed", "p(95)") or 0, 1),
        }
        b = dict(l.split("\t") for l in open(f"dbstat-{tag}-before.txt").read().splitlines())
        a = dict(l.split("\t") for l in open(f"dbstat-{tag}-after.txt").read().splitlines())
        for k in ["Innodb_row_lock_waits", "Innodb_row_lock_time", "Com_insert", "Com_update"]:
            row["D_" + k] = int(a[k]) - int(b[k])
        samp = [l.split() for l in open(f"dbsample-{tag}.txt").read().splitlines() if l.strip()]
        if samp:
            row["max_thr_running"] = max(int(s[1]) for s in samp)
            row["max_thr_conn"] = max(int(s[2]) for s in samp)
            row["max_lock_cur_waits"] = max(int(s[3]) for s in samp)
        rows[tag] = row

keys = list(next(iter(rows.values())).keys())
print("tag\t" + "\t".join(keys))
for tag, row in rows.items():
    print(tag + "\t" + "\t".join(str(row.get(k)) for k in keys))
