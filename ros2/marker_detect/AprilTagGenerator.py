import numpy as np
from PIL import Image
from moms_apriltag.generator2 import TagGenerator2
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4

# ========= 参数 =========
TAG_FAMILY = "tag36h11"
# 每个marker：(外框边长mm, tag位图边长mm, 该marker使用的tag ID列表)
MARKERS = [
    (45, 20, [0,1,2,3]),
    (50, 20, [4,5,6,7]),
]
GAP_MM = 30                      # 一行内两个marker之间的水平间距
COPIES = 3                       # marker组复制的份数，从上到下排列
ROW_GAP_MM = 20                  # 行与行之间的垂直间距
LABEL_OFFSET_MM = 6              # 尺寸标注距marker下边缘的距离
PAGE_W, PAGE_H = A4

# 高分辨率渲染tag PNG（所有marker用到的ID，一次生成共用）
SCALE = 400
ALL_TAG_IDS = sorted({tid for _, _, ids in MARKERS for tid in ids})
tag_generator = TagGenerator2(TAG_FAMILY)
tag_pngs = {}
for tag_id in ALL_TAG_IDS:
    tag_bits = tag_generator.generate(tag_id)
    img = Image.fromarray(tag_bits).convert("L")
    img = img.resize((8*SCALE, 8*SCALE), Image.NEAREST)  # 最近邻插值，保持锐利边缘
    tmp_name = f"tag_{TAG_FAMILY}_{tag_id}.png"
    img.save(tmp_name)
    tag_pngs[tag_id] = tmp_name

# 每行两个marker横向排开，整组复制COPIES份，从上到下排列在A4页面上
out_name = "apriltag_45_50mm_A4.pdf"
c = canvas.Canvas(out_name, pagesize=A4)

ROW_W_MM = sum(m[0] for m in MARKERS) + GAP_MM * (len(MARKERS) - 1)   # 45+30+50 = 125mm
ROW_H_MM = max(m[0] for m in MARKERS)                                 # 50mm
total_h = COPIES * ROW_H_MM + (COPIES - 1) * (ROW_GAP_MM + LABEL_OFFSET_MM)

def draw_row(center_y_mm):
    """在页面垂直位置center_y_mm（行中心）处画一行marker"""
    cursor_x = (PAGE_W/mm - ROW_W_MM) / 2   # 该行起始x（mm）
    for region_mm, tag_mm, marker_tag_ids in MARKERS:
        REGION_MM = region_mm * mm
        TAG_SIZE_MM = tag_mm * mm
        x0 = cursor_x * mm
        y0 = center_y_mm * mm - REGION_MM / 2

        # 4个tag贴到该marker的4个角
        CORNER_POSITIONS = [
            (x0, y0),
            (x0 + REGION_MM - TAG_SIZE_MM, y0),
            (x0, y0 + REGION_MM - TAG_SIZE_MM),
            (x0 + REGION_MM - TAG_SIZE_MM, y0 + REGION_MM - TAG_SIZE_MM),
        ]
        for (bx, by), tag_id in zip(CORNER_POSITIONS, marker_tag_ids):
            c.drawImage(tag_pngs[tag_id], bx, by, width=TAG_SIZE_MM, height=TAG_SIZE_MM)

        # 每个marker下方标注尺寸
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0, 0, 0)
        c.drawCentredString(x0 + REGION_MM/2, y0 - LABEL_OFFSET_MM*mm, f"{region_mm} mm")

        cursor_x += region_mm + GAP_MM   # 移动到下一个marker的槽位起点

# 从上到下依次画各行（整体在页面上垂直居中）
block_h_mm = ROW_H_MM + LABEL_OFFSET_MM
top_center_y = PAGE_H/mm/2 + total_h/2 - ROW_H_MM/2
for i in range(COPIES):
    draw_row(top_center_y - i * (block_h_mm + ROW_GAP_MM))

c.save()
print(f"已生成 {out_name}，45mm/50mm两个marker一组（间距{GAP_MM}mm），共{COPIES}组从上到下排列，直接A4 1:1打印，不要缩放！")
