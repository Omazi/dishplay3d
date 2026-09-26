"""Read local pinned COLMAP binary output; no reconstruction dependency or mutation."""
import struct


def read(stream, fmt):
    size=struct.calcsize(fmt)
    data=stream.read(size)
    if len(data)!=size: raise ValueError("Truncated COLMAP artifact")
    return struct.unpack(fmt,data)


def cameras(path):
    result={}
    counts={0:3,1:4,2:4}  # SIMPLE_PINHOLE, PINHOLE, SIMPLE_RADIAL only
    with path.open("rb") as stream:
        count,=read(stream,"<Q")
        if count>10000: raise ValueError("Camera artifact exceeds budget")
        for _ in range(count):
            cid,model,width,height=read(stream,"<iiQQ")
            if model not in counts: raise ValueError("Unsupported camera model for mask undistortion")
            params=read(stream,"<"+"d"*counts[model])
            result[cid]={"model":model,"width":width,"height":height,"params":params}
    return result


def images(path):
    result={}
    with path.open("rb") as stream:
        count,=read(stream,"<Q")
        if count>10000: raise ValueError("Image artifact exceeds budget")
        for _ in range(count):
            values=read(stream,"<i7di")
            name=bytearray()
            while True:
                byte=stream.read(1)
                if byte==b"\x00": break
                if not byte or len(name)>4096: raise ValueError("Invalid image name")
                name.extend(byte)
            points,=read(stream,"<Q")
            if points>10_000_000: raise ValueError("Point count exceeds budget")
            stream.seek(points*24,1)
            result[values[0]]={"name":name.decode("utf8"),"cameraId":values[-1]}
    return result


def sparse_metrics(path):
    result={"registeredImages":None,"sparsePoints":None,"meanReprojectionErrorPixels":None}
    if (path/"images.bin").exists(): result["registeredImages"]=len(images(path/"images.bin"))
    if (path/"points3D.bin").exists():
        with (path/"points3D.bin").open("rb") as stream:
            count,=read(stream,"<Q")
            if count>10_000_000: raise ValueError("Sparse artifact exceeds budget")
            error=0.0
            for _ in range(count):
                values=read(stream,"<QdddBBBdQ")
                error+=values[-2]
                stream.seek(values[-1]*8,1)
            result.update(sparsePoints=count,meanReprojectionErrorPixels=error/count if count else None)
    return result
