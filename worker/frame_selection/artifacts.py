"""Small offline contact sheets; never loaded by a public UI."""
import math
from PIL import Image, ImageDraw


def contact_sheet(records, source, target, masks=None):
    tile_w, tile_h, columns = 192, 174, 5
    sheet = Image.new("RGB", (columns*tile_w, max(1, math.ceil(len(records)/columns))*tile_h), "#171b20")
    draw = ImageDraw.Draw(sheet)
    for position, record in enumerate(records):
        x, y = position % columns*tile_w, position//columns*tile_h
        with Image.open(source/record["name"]) as raw:
            thumb = raw.convert("RGB")
            if masks and record.get("mask"):
                with Image.open(masks/record["mask"]) as mask:
                    overlay = Image.new("RGB", thumb.size, "#36bf83")
                    thumb = Image.composite(Image.blend(thumb, overlay, .45), thumb, mask.convert("L"))
            thumb.thumbnail((tile_w, 112))
            sheet.paste(thumb, (x, y))
        quality = record.get("metrics", {}).get("qualityScore")
        title = f'#{record["frameIndex"]} {record["timestampMs"]:.0f}ms Q={quality:.2f}' if quality is not None else str(record["frameIndex"])
        text = "SELECTED" if record.get("selected") else ",".join(record.get("reasons", [])) or "not selected"
        draw.text((x+3, y+114), title, fill="white")
        draw.text((x+3, y+130), text[:28], fill="#8de8b5" if record.get("selected") else "#efb078")
        if masks and not record.get("mask"):
            draw.text((x+3, y+146), "MASK UNAVAILABLE", fill="#ffb0a0")
    sheet.save(target, quality=85)


def coverage_svg(coverage, path):
    if not coverage.get("directions"):
        return
    points = []
    for d in coverage["directions"]:
        angle = math.radians(d["azimuth"])
        points.append(f'<circle cx="{150+100*math.sin(angle):.2f}" cy="{150-100*math.cos(angle):.2f}" r="5" fill="#087f5b"/>')
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="330"><rect width="300" height="330" fill="white"/>'
                    '<circle cx="150" cy="150" r="100" fill="none" stroke="#555"/>'+''.join(points)
                    +'<text x="10" y="310">Supplied pose coverage (approximate)</text></svg>')
