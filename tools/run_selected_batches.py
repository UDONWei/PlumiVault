"""按显式清单串行运行；每批不超过 50，不扩展到其他照片目录。"""
from pathlib import Path
import argparse,json,subprocess,sys,time
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--project",type=Path,required=True)
parser.add_argument("--jobs-dir",type=Path,required=True)
a=parser.parse_args();p=a.project.resolve();base=a.jobs_dir.resolve()
jobs=json.loads((base/"jobs.json").read_text(encoding="utf-8"))
results=[]
for index,job in enumerate(jobs):
    print(f"Starting batch {index+1}/{len(jobs)}: {Path(job['root']).name}, {job['count']} images",flush=True)
    cmd=[sys.executable,"-X","utf8","-B",str(p/"tools/stage1_probe.py"),
      "--photos-root",job["root"],"--manifest",job["manifest"],"--output",job["output"],
      "--limit","50","--raw-mode","full","--hash-samples","--thumbnails",
      "--model-dir",str(p/"offline"),"--labels",str(p/"docs/china-birds-ioc12.1-probe.json"),
      "--text-features",str(p/"offline/text_features.pt"),
      "--context-priors",str(p/"docs/china-birds-occurrence-ioc12.1.json"),
      "--save-all-scores","--detector-config",str(p/"offline/detector-ssdlite.json"),"--similarity-features"]
    with (base/f"batch-{index+1}.log").open("w",encoding="utf-8") as log:
        completed=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    record={"job":job,"returncode":completed.returncode,"command":cmd}
    results.append(record)
    (base/"run-status.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Finished batch {index+1}: exit {completed.returncode}",flush=True)
    report=Path(job["output"])/"report.json"
    if not report.exists():raise SystemExit("Missing report; stop, preserve logs")
    data=json.loads(report.read_text(encoding="utf-8"))
    if data.get("fatal_error") or data.get("stopped_reason"):raise SystemExit("Fatal/source integrity failure; stop")
print("All authorized directory batches complete.",flush=True)

