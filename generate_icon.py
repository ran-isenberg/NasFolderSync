"""Generate FolderSync app icon: a folder with sync arrows inside."""

import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw


def draw_icon(size: int) -> Image.Image:
    """Draw a folder icon with circular sync arrows inside."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    s = size
    pad = s * 0.08

    # ── Folder back ──────────────────────────────────────────────
    folder_left = pad
    folder_right = s - pad
    folder_top = s * 0.28
    folder_bottom = s - pad
    folder_radius = s * 0.06

    # Tab on top-left of folder
    tab_width = s * 0.38
    tab_top = folder_top - s * 0.10

    draw.rounded_rectangle(
        [folder_left, tab_top, folder_left + tab_width, folder_top + folder_radius],
        radius=folder_radius,
        fill=(66, 133, 244),
    )

    draw.rounded_rectangle(
        [folder_left, folder_top, folder_right, folder_bottom],
        radius=folder_radius,
        fill=(66, 133, 244),
    )

    # Lighter front panel
    front_top = folder_top + s * 0.08
    draw.rounded_rectangle(
        [folder_left, front_top, folder_right, folder_bottom],
        radius=folder_radius,
        fill=(100, 160, 255),
    )

    # ── Sync arrows (circular) ───────────────────────────────────
    cx = s * 0.50
    cy = s * 0.58
    radius = s * 0.17
    arrow_color = (255, 255, 255)
    stroke = max(2, int(s * 0.045))

    # Draw two arcs (~240 degrees each, offset by 180)
    # Arc 1: top-right going clockwise
    # Arc 2: bottom-left going clockwise
    arc_extent = 220
    gap = (360 - arc_extent) // 2

    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]

    # Arc 1
    start1 = -30
    draw.arc(bbox, start1, start1 + arc_extent, fill=arrow_color, width=stroke)

    # Arc 2
    start2 = start1 + 180
    draw.arc(bbox, start2, start2 + arc_extent, fill=arrow_color, width=stroke)

    # Arrowheads at the end of each arc
    arrow_size = s * 0.07

    def arrowhead_at_angle(angle_deg, direction):
        """Draw a triangular arrowhead at the given angle on the circle."""
        angle_rad = math.radians(angle_deg)
        # Point on the circle
        px = cx + radius * math.cos(angle_rad)
        py = cy + radius * math.sin(angle_rad)

        # Tangent direction (perpendicular to radius)
        # direction: 1 = clockwise, -1 = counter-clockwise
        tx = -math.sin(angle_rad) * direction
        ty = math.cos(angle_rad) * direction

        # Arrow tip is ahead along the tangent
        tip_x = px + tx * arrow_size * 0.9
        tip_y = py + ty * arrow_size * 0.9

        # Two base points perpendicular to tangent
        nx = math.cos(angle_rad)
        ny = math.sin(angle_rad)

        base1_x = px + nx * arrow_size * 0.5
        base1_y = py + ny * arrow_size * 0.5
        base2_x = px - nx * arrow_size * 0.5
        base2_y = py - ny * arrow_size * 0.5

        draw.polygon([(tip_x, tip_y), (base1_x, base1_y), (base2_x, base2_y)], fill=arrow_color)

    # Arrowhead at end of arc 1
    arrowhead_at_angle(start1 + arc_extent, 1)
    # Arrowhead at end of arc 2
    arrowhead_at_angle(start2 + arc_extent, 1)

    return img


def main():
    iconset_dir = 'icon.iconset'
    os.makedirs(iconset_dir, exist_ok=True)

    icon_sizes = [16, 32, 64, 128, 256, 512, 1024]

    for sz in icon_sizes:
        img = draw_icon(sz)
        img.save(os.path.join(iconset_dir, f'icon_{sz}x{sz}.png'))
        if sz <= 512:
            img2x = draw_icon(sz * 2)
            img2x.save(os.path.join(iconset_dir, f'icon_{sz}x{sz}@2x.png'))

    print('  PNG frames written')

    result = subprocess.run(
        ['iconutil', '-c', 'icns', iconset_dir, '-o', 'FolderSync.icns'],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print('  FolderSync.icns created')
    else:
        print(f'  iconutil warning: {result.stderr}', file=sys.stderr)


if __name__ == '__main__':
    main()
