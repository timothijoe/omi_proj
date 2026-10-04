"""Render auditable candidate contact sheets without changing source pixels/files."""
from pathlib import Path
import json
from PIL import Image, ImageDraw
from .app import summary
from .storage import image_path, atomic_json, NAMES


def render_report(store, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    doc = store.read()
    tiles, rows = [], []
    for record in doc['images']:
        run = record['proposals'][-1] if record['proposals'] else None
        tile = Image.new('RGB', (440, 490), '#131b26')
        raw = Image.open(image_path(store.root, record)).convert('RGB')
        tile.paste(raw.resize((384, 384), Image.Resampling.NEAREST), (24, 42))
        draw = ImageDraw.Draw(tile)
        draw.text((16, 12), record['image_id'] + ' / ' + record['split'], fill='white')
        if run:
            for i, candidate in enumerate(run['candidates']):
                vertices = [(24+(x+.5)*3,42+(y+.5)*3) for x,y in candidate['vertices']]
                draw.line(vertices+[vertices[0]], fill='#ffe27b', width=2)
                draw.text(vertices[0], str(i+1), fill='#ff738a', stroke_width=1, stroke_fill='black')
            for i, point in enumerate(run['points']):
                if point['status'] != 'visible':
                    continue
                x,y = 24+(point['x']+.5)*3,42+(point['y']+.5)*3
                draw.ellipse((x-3,y-3,x+3,y+3), outline='#73edbf',width=2)
                draw.text((x+4,y),NAMES[i],fill='#73edbf',stroke_width=1,stroke_fill='black')
        count = len(run['candidates']) if run else 0
        visible = sum(p['status']=='visible' for p in run['points']) if run else 0
        draw.text((16, 438), f'{count} geometric candidates; {visible}/6 named suggestions', fill='#ffe27b')
        draw.text((16, 458), 'NOT HUMAN TRUTH / physical target unconfirmed' if not record['target_definition_confirmed'] else 'Human review required for model suggestions', fill='#b1c2d5')
        tile.save(destination / (record['image_id'] + '.png'))
        tiles.append(tile)
        rows.append({'image_id':record['image_id'],'view':record['view'],'split':record['split'],
                     'candidate_count':count,'named_suggestions':visible,
                     'elapsed_ms':run['elapsed_ms'] if run else None,
                     'reasons':[p['reason'] for p in run['points']] if run else []})
    sheet = Image.new('RGB', (440*4,490*((len(tiles)+3)//4)), '#131b26')
    for i,tile in enumerate(tiles):
        sheet.paste(tile, ((i%4)*440,(i//4)*490))
    sheet.save(destination / 'candidate_contact_sheet.png')
    atomic_json(destination / 'report.json', {'summary':summary(doc),'images':rows,
                'no_truth_metrics':'No reviewed real labels yet; PCK/error/false visibility/correction savings are unavailable.'})
