"""
Downloads the DWM training images and writes the rule-based labels.

Usage: python collect_dwm_images.py <images_dir> <auto_labels_csv>

Sources (file name prefix -> source):
  taco_   TACO litter dataset (pedropro/TACO). Labels derived from its human object annotations.
  wvbio_  steveharianto/waste-garbage-management-dataset, class "biological" -> wet, domestic
  wvbat_  same dataset, class "battery" -> hazardous, domestic
  ginin_  SpotGarbage GINI non-garbage-queried images -> none, none
  ginig_  SpotGarbage GINI garbage-queried images annotated as garbage (label 1)  -> labelled by hand
  dc_     Dataclusterlabspvtltd/Domestic-Trash-Garbage-Dataset (India)           -> labelled by hand
  bin_    Akhila-9849/Garbage_Bin_overflow_images                                -> labelled by hand
  ew_     GIZ/e-waste-dataset-yolo-labels                                        -> labelled by hand
Only taco_, wvbio_, wvbat_ and ginin_ rows are written to <auto_labels_csv>.
"""
import csv, io, json, os, random, sys, urllib.parse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageOps

TACO_ANN = "https://raw.githubusercontent.com/pedropro/TACO/master/data/annotations.json"
GINI = "https://raw.githubusercontent.com/spotgarbage/spotgarbage-GINI/master/spotgarbage"
HF = "https://huggingface.co"
MAX_SIDE = 1280
SEED = 0

TACO_WET = {"Food waste"}
TACO_HAZARDOUS = {"Battery", "Aerosol"}
TACO_IGNORE = {"Unlabeled litter"}
TACO_OPEN_GROUND = {"Pavement", "Sand, Dirt, Pebbles", "Vegetation", "Water"}
DOMINANT_SHARE = 0.7      # a waste type is dominant if it covers >= 70% of the annotated litter area
DOMESTIC_MAX_OBJECTS = 3  # <= 3 annotated objects -> domestic, more -> moderate

GINI_NONE_QUERIES = ["clean+road", "city+street", "suburb", "Indian+roads", "rural+area", "buildings",
                     "countryside", "indian+railway+tracks", "crowd", "vehicles", "people", "objects"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def save(url, path):
    if os.path.exists(path):
        return True
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(fetch(url)))).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        img.save(path, "JPEG", quality=92)
        return True
    except Exception as e:
        print(f"  failed {os.path.basename(path)}: {e}")
        return False


def hf_files(repo, prefix=""):
    info = json.loads(fetch(f"{HF}/api/datasets/{repo}"))
    return sorted(s["rfilename"] for s in info["siblings"]
                  if s["rfilename"].startswith(prefix) and s["rfilename"].lower().endswith((".jpg", ".jpeg", ".png")))


def hf_url(repo, path):
    return f"{HF}/datasets/{repo}/resolve/main/{urllib.parse.quote(path)}"


def taco_jobs():
    d = json.loads(fetch(TACO_ANN))
    cats = {c["id"]: c["name"] for c in d["categories"]}
    scenes = {c["id"]: c["name"] for c in d["scene_categories"]}
    bg = {s["image_id"]: {scenes.get(b, "unknown") for b in s["background_ids"]} for s in d["scene_annotations"]}
    anns = defaultdict(list)
    for a in d["annotations"]:
        anns[a["image_id"]].append(a)
    jobs = []
    for im in d["images"]:
        area = defaultdict(float)
        for a in anns[im["id"]]:
            name = cats[a["category_id"]]
            if name in TACO_IGNORE:
                continue
            group = "wet" if name in TACO_WET else "hazardous" if name in TACO_HAZARDOUS else "dry"
            area[group] += a["area"]
        if not area:
            continue
        top = max(area, key=area.get)
        waste = top if area[top] / sum(area.values()) >= DOMINANT_SHARE else "mixed"
        severity = "domestic" if len(anns[im["id"]]) <= DOMESTIC_MAX_OBJECTS else "moderate"
        backgrounds = bg.get(im["id"], set())
        env = "open_ground" if backgrounds and backgrounds <= TACO_OPEN_GROUND else ""
        name = f"taco_{im['id']:04d}.jpg"
        jobs.append((im["flickr_640_url"] or im["flickr_url"], name, (waste, severity, env)))
    return jobs


def class_folder_jobs(repo, folder, prefix, n, labels):
    files = hf_files(repo, folder + "/" if folder else "")
    random.Random(SEED).shuffle(files)
    return [(hf_url(repo, f), f"{prefix}{os.path.splitext(os.path.basename(f))[0]}.jpg", labels) for f in files[:n]]


def gini_jobs():
    rows = list(csv.DictReader(io.StringIO(fetch(f"{GINI}/garbage-queried-images.csv").decode())))
    jobs = [(f"{GINI}/garbage-queried-images/{urllib.parse.quote(r['query'])}/{r['image']}",
             f"ginig_{os.path.splitext(r['image'])[0]}.jpg", None) for r in rows if r["label"] == "1"]
    rows = list(csv.DictReader(io.StringIO(fetch(f"{GINI}/non-garbage-queried-images.csv").decode())))
    jobs += [(f"{GINI}/non-garbage-queried-images/{urllib.parse.quote(r['query'])}/{r['image']}",
              f"ginin_{os.path.splitext(r['image'])[0]}.jpg", ("none", "none", ""))
             for r in rows if r["query"] in GINI_NONE_QUERIES]
    return jobs


def main(images_dir, auto_labels_csv):
    os.makedirs(images_dir, exist_ok=True)
    jobs = taco_jobs()
    jobs += class_folder_jobs("steveharianto/waste-garbage-management-dataset", "biological", "wvbio_", 150,
                              ("wet", "domestic", ""))
    jobs += class_folder_jobs("steveharianto/waste-garbage-management-dataset", "battery", "wvbat_", 150,
                              ("hazardous", "domestic", ""))
    jobs += gini_jobs()
    jobs += class_folder_jobs("Dataclusterlabspvtltd/Domestic-Trash-Garbage-Dataset", "images", "dc_", 250, None)
    jobs += class_folder_jobs("Akhila-9849/Garbage_Bin_overflow_images", "", "bin_", 200, None)
    jobs += class_folder_jobs("GIZ/e-waste-dataset-yolo-labels", "YOLO with Pictures/images", "ew_", 150, None)

    with ThreadPoolExecutor(16) as pool:
        ok = list(pool.map(lambda j: save(j[0], os.path.join(images_dir, j[1])), jobs))

    with open(auto_labels_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_file", "label_waste_type", "label_severity", "label_environment"])
        for (url, name, labels), good in zip(jobs, ok):
            if good and labels:
                w.writerow([name, *labels])
    print(f"Downloaded {sum(ok)}/{len(jobs)} images to {images_dir}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
