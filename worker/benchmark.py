"""Sequential comparison on a supplied real video; never infers fidelity from test passes.

Run inside an environment containing the unchanged pinned engines plus CV dependencies.
Example: python -m worker.benchmark --video dish.mov --output /private/comparison --counts 24 32 48 64
"""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
from .colmap_artifacts import sparse_metrics
from .frame_selection.models import SelectionConfig
from .reconstruct import digest, execute_stage, task_lock, memory_available, MIB, HERE


def mesh_metrics(path):
    if not path.exists(): return None
    with path.open("rb") as stream:
        magic,version,length=struct.unpack("<4sII",stream.read(12))
        size,kind=struct.unpack("<I4s",stream.read(8))
        if magic!=b"glTF" or version!=2 or kind!=b"JSON" or size>32*MIB: raise ValueError("Invalid GLB")
        doc=json.loads(stream.read(size))
    vertex_accessors=set();faces=0
    for mesh in doc.get("meshes",[]):
        for primitive in mesh["primitives"]:
            if primitive.get("mode",4)!=4: raise ValueError("Metrics support triangle primitives only")
            vertex_accessors.add(primitive["attributes"]["POSITION"])
            accessor=primitive.get("indices",primitive["attributes"]["POSITION"])
            faces+=doc["accessors"][accessor]["count"]//3
    return {"vertices":sum(doc["accessors"][i]["count"] for i in vertex_accessors),"faces":faces,
            "bytes":path.stat().st_size,"note":"Unique POSITION accessor counts; not welded topology"}


def collect(path):
    manifest=json.loads((path/"manifest.json").read_text()) if (path/"manifest.json").exists() else {}
    capture=json.loads((path/"capture_report.json").read_text()) if (path/"capture_report.json").exists() else {}
    sparse=sparse_metrics(path/"sparse"/"0")
    count=len(manifest.get("inputs",[]))
    stages={s["name"]:s for s in manifest.get("stages",[])}
    return {"state":manifest.get("state","NOT_RUN"),"error":manifest.get("error"),"errorCode":manifest.get("error_code"),
            "selectedFrameCount":count,"selectedFrameIndices":[f.get("frameIndex") for f in manifest.get("inputs",[])],
            **sparse,"registeredRatio":sparse["registeredImages"]/count if sparse["registeredImages"] is not None and count else None,
            "openMVSSuccess":all(stages.get(s,{}).get("state")=="completed" for s in ["densification","mesh","refinement","texture"]),
            "runtimeSeconds":manifest.get("elapsed_seconds"),"childPeakRssKiB":manifest.get("child_peak_rss_kib"),
            "preprocessingResources":capture.get("resources"),"stageTimings":capture.get("timingsSeconds"),
            "glb":mesh_metrics(path/"model.glb"),"usdzBytes":(path/"model.usdz").stat().st_size if (path/"model.usdz").exists() else None,
            "engineBinaries":manifest.get("engine_binaries"),"engineVersions":manifest.get("engine_versions"),
            "captureReport":str(path/"capture_report.json"),"visualReview":"PENDING_HUMAN_REVIEW"}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--config",type=Path)
    parser.add_argument("--capture-manifest",type=Path)
    parser.add_argument("--counts",nargs="+",type=int,default=[24,32,48,64])
    parser.add_argument("--long-edge",type=int,default=800)
    parser.add_argument("--memory-mib",type=int,default=1536)
    parser.add_argument("--prepare-only",action="store_true")
    args=parser.parse_args()
    if args.output.exists(): parser.error("Use a fresh private output directory")
    if any(not 3<=c<=80 for c in args.counts): parser.error("Counts must be 3..80")
    if not 320<=args.long_edge<=1600 or not 512<=args.memory_mib<=2048: parser.error("Resource budget out of range")
    if memory_available() is None or memory_available()<(args.memory_mib+1024)*MIB:
        parser.error("Insufficient free RAM for the selected cap plus 1024 MiB headroom")
    output=args.output.resolve();output.mkdir(parents=True,mode=0o700)
    base=json.loads(args.config.read_text()) if args.config else {}
    result={"sourceSha256":digest(args.video),"source":str(args.video.resolve()),"runs":[],
            "conclusion":"UNDETERMINED: requires completed same-source reconstructions and visual review",
            "longEdge":args.long_edge,"prepareOnly":args.prepare_only}
    for count in args.counts:
        pair=[]
        for method in ["TEMPORAL_BASELINE","SMART_SELECTION_V1"]:
            config=SelectionConfig(**{**base,"method":method,"final_count":count,"minimum_count":min(count,base.get("minimum_count",8))})
            name=f"{method}-{count}";path=output/name
            config_path=output/(name+".json");config_path.write_text(json.dumps(config.document(),indent=2))
            command=[sys.executable,str(HERE/"reconstruct.py"),"--prepare-video" if args.prepare_only else "--run",
                     "--video",str(args.video.resolve()),"--output",str(path),"--selection-config",str(config_path),
                     "--long-edge",str(args.long_edge),"--memory-mib",str(args.memory_mib)]
            if args.capture_manifest: command.extend(["--capture-manifest",str(args.capture_manifest.resolve())])
            with (output/(name+".log")).open("w") as log:
                # reconstruct.py provides one-task lock, per-stage limits and pressure checks.
                completed=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
            metrics={"method":method,"targetCount":count,"exitCode":completed.returncode,**collect(path)}
            if (path/"model.glb").exists():
                with task_lock():
                    settings={"memory_mib":args.memory_mib,"disk_mib":4096,"stage_seconds":120}
                    try:
                        execute_stage({"name":"benchmark-render","command":["blender","--background","--factory-startup","--threads","1",
                            "--python-exit-code","1","--python",str(HERE/"render_benchmark.py"),"--",str(path/"model.glb"),str(path/"render.png")]},path,settings)
                        metrics["render"]=str(path/"render.png")
                    except ValueError as error: metrics["renderError"]=str(error)
            result["runs"].append(metrics);pair.append(metrics)
            (output/"comparison.json").write_text(json.dumps(result,indent=2))
        a,b=pair
        if a.get("engineBinaries") and b.get("engineBinaries") and a["engineBinaries"]!=b["engineBinaries"]:
            raise ValueError("Engine binary mismatch; comparison invalid")
        if a.get("render") and b.get("render"):
            from PIL import Image,ImageDraw
            sheet=Image.new("RGB",(1024,552),"white")
            for i,run in enumerate(pair):
                with Image.open(run["render"]) as image: sheet.paste(image.convert("RGB"),(512*i,40))
                ImageDraw.Draw(sheet).text((512*i+8,10),run["method"],fill="black")
            sheet.save(output/f"comparison-{count}.jpg")
    return 0 if all(r["exitCode"]==0 for r in result["runs"]) else 1


if __name__=="__main__": raise SystemExit(main())
