from PIL import Image, ImageDraw, ImageFont

w, h = 1200, 630
img = Image.new('RGB', (w, h), (15, 15, 26))
draw = ImageDraw.Draw(img)

# Gradient background
for i in range(h):
    r = int(15 + (i/h)*20)
    g = int(15 + (i/h)*10)
    b = int(26 + (i/h)*60)
    draw.line([(0,i),(w,i)], fill=(r,g,b))

# Accent circles
draw.ellipse([800,50,1150,350], fill=(26,26,78))
draw.ellipse([50,300,400,620], fill=(15,32,64))

# Load fonts
try:
    font_xl  = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 80)
    font_lg  = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 40)
    font_md  = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 28)
    font_sm  = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 22)
except Exception:
    font_xl = font_lg = font_md = font_sm = ImageFont.load_default()

# Purple circle logo
draw.ellipse([80, 55, 185, 160], fill=(99, 102, 241))
draw.text((133, 107), 'P', fill='white', font=font_lg, anchor='mm')

# Brand name
draw.text((205, 70), 'PixelDocs', fill=(241, 245, 249), font=font_xl)

# Tagline
draw.text((82, 200), 'Free Image & PDF Tools Online', fill=(129, 140, 248), font=font_lg)

# Sub tagline
draw.text((82, 255), 'Convert  |  Compress  |  Resize  |  Edit PDF  |  Sign PDF  |  Passport Photo', fill=(100, 116, 139), font=font_sm)

# Feature pills row 1
pills1 = ['Convert', 'Compress', 'Resize', 'Crop']
pills2 = ['PDF Editor', 'Merge PDF', 'AI Tools', 'OCR']

def draw_pill(draw, x, y, text, font):
    bb = draw.textbbox((0,0), text, font=font)
    tw = bb[2] - bb[0]
    pw = tw + 28
    draw.rounded_rectangle([x, y, x+pw, y+38], radius=19, fill=(30,30,58), outline=(99,102,241), width=1)
    draw.text((x+14, y+19), text, fill=(165,180,252), font=font, anchor='lm')
    return pw + 12

px, py = 82, 320
for pill in pills1:
    pw = draw_pill(draw, px, py, pill, font_sm)
    px += pw

px = 82
for pill in pills2:
    pw = draw_pill(draw, px, py+50, pill, font_sm)
    px += pw

# Trust badge
draw.rounded_rectangle([82, 430, 440, 475], radius=22, fill=(16,46,30))
draw.text((262, 452), 'No Sign-up   100% Free   Private', fill=(52, 211, 153), font=font_sm, anchor='mm')

# Right panel
draw.rounded_rectangle([810, 120, 1140, 510], radius=16, fill=(26,26,46), outline=(45,45,74), width=1)
draw.text((975, 148), 'What you can do', fill=(148,163,184), font=font_sm, anchor='mm')

items = [
    ('Images', 'Convert, Compress, Resize, Edit'),
    ('PDF',    'Merge, Split, Compress, Protect'),
    ('Editor', 'Fill forms, Sign, Tick boxes'),
    ('AI',     'Remove BG, Upscale, OCR'),
    ('India',  'Passport Photo, Govt Forms'),
]
iy = 195
for title, desc in items:
    draw.text((840, iy), title, fill=(165,180,252), font=font_md)
    draw.text((840, iy+30), desc, fill=(100,116,139), font=font_sm)
    draw.line([(840, iy+60),(1120, iy+60)], fill=(45,45,74), width=1)
    iy += 70

img.save('static/og-image.png', 'PNG', optimize=True)
print('og-image.png saved')

