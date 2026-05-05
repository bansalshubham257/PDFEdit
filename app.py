from flask import Flask, render_template, request, jsonify, send_file
import os, io, logging, sys, uuid, tempfile, zipfile
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageFont, ImageOps

# ── PDF libraries ──────────────────────────────────────────────────────────
try:
    from pypdf import PdfReader, PdfWriter
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    import fitz          # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.colors import Color
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except ImportError:
    PIKEPDF_AVAILABLE = False

try:
    import mammoth
    MAMMOTH_AVAILABLE = True
except ImportError:
    MAMMOTH_AVAILABLE = False

try:
    from rembg import remove as rembg_remove
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from weasyprint import HTML as WeasyprintHTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB upload limit
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'imgtools-secret')
app.config['SITE_URL']   = os.environ.get('SITE_URL', 'https://pixeldocs.io')

TMP_DIR = tempfile.gettempdir()

log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    log_handlers.append(logging.FileHandler('app.log'))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

# ---------- optional deps ----------
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not available")

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:
    HEIF_AVAILABLE = False
    logger.warning("pillow-heif not available – HEIC conversion disabled")

try:
    import cairosvg
    CAIRO_AVAILABLE = True
except ImportError:
    CAIRO_AVAILABLE = False
    logger.warning("cairosvg not available – SVG conversion disabled")

# ---------- helpers ----------

PIL_FORMAT_MAP = {
    'jpg': 'JPEG',
    'jpeg': 'JPEG',
    'png': 'PNG',
    'webp': 'WEBP',
    'bmp': 'BMP',
    'tiff': 'TIFF',
    'tif': 'TIFF',
    'gif': 'GIF',
    'heic': 'HEIF',
}

MIME_MAP = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'webp': 'image/webp',
    'bmp': 'image/bmp',
    'tiff': 'image/tiff',
    'gif': 'image/gif',
    'pdf': 'application/pdf',
}

def open_image(file_storage):
    """Open uploaded file as PIL Image, handling SVG separately."""
    filename = file_storage.filename.lower()
    data = file_storage.read()

    if filename.endswith('.svg'):
        if not CAIRO_AVAILABLE:
            raise ValueError("SVG conversion requires cairosvg. Please install it.")
        png_bytes = cairosvg.svg2png(bytestring=data)
        return Image.open(io.BytesIO(png_bytes)).convert('RGBA')

    img = Image.open(io.BytesIO(data))
    return img

def save_image(img, fmt):
    """Save PIL Image to bytes buffer in given format string (e.g. 'JPEG')."""
    buf = io.BytesIO()
    if fmt == 'JPEG' and img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGB')
    elif fmt == 'PNG' and img.mode not in ('RGBA', 'RGB', 'P', 'L'):
        img = img.convert('RGBA')
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf

def compress_to_target(img, fmt, target_bytes, quality_start=85):
    """Binary-search quality to hit target file size."""
    lo, hi = 1, 95
    best_buf = None
    for _ in range(12):
        q = (lo + hi) // 2
        buf = io.BytesIO()
        save_img = img
        if fmt == 'JPEG' and save_img.mode in ('RGBA', 'P', 'LA'):
            save_img = save_img.convert('RGB')
        if fmt in ('JPEG', 'WEBP'):
            save_img.save(buf, format=fmt, quality=q, optimize=True)
        else:
            save_img.save(buf, format=fmt, optimize=True)
        size = buf.tell()
        buf.seek(0)
        if size <= target_bytes:
            best_buf = buf
            lo = q + 1
        else:
            hi = q - 1
    if best_buf is None:
        # Can't hit target – return smallest possible
        buf = io.BytesIO()
        save_img = img.convert('RGB') if fmt == 'JPEG' else img
        save_img.save(buf, format=fmt, quality=1, optimize=True)
        buf.seek(0)
        return buf
    return best_buf

# ---------- routes ----------

@app.route('/')
def index():
    return render_template('index.html',
                           heif_available=HEIF_AVAILABLE,
                           cairo_available=CAIRO_AVAILABLE)

# ── Static pages ──────────────────────────────────────────────────
@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy.html')

@app.route('/terms-of-service')
def terms_of_service():
    return render_template('terms.html')

# ── Tool landing pages ────────────────────────────────────────────
@app.route('/jpg-to-pdf')
def tool_jpg_to_pdf():
    return render_template('tool_jpg_to_pdf.html')

@app.route('/compress-jpg-to-50kb')
def tool_compress():
    return render_template('tool_compress.html')

@app.route('/resize-image-to-200x200')
def tool_resize():
    return render_template('tool_resize.html')

@app.route('/passport-photo-maker')
def tool_passport():
    return render_template('tool_passport.html')

@app.route('/merge-pdf')
def tool_merge_pdf():
    return render_template('tool_merge_pdf.html')

@app.route('/pdf-to-jpg')
def tool_pdf_to_jpg():
    return render_template('tool_pdf_to_jpg.html')

# ── Primary PDF SEO landing pages ─────────────────────────────────
@app.route('/fill-pdf-form-online')
def tool_fill_pdf():
    return render_template('tool_fill_pdf.html')

@app.route('/edit-pdf-online')
def tool_edit_pdf():
    return render_template('tool_edit_pdf.html')

@app.route('/sign-pdf-online')
def tool_sign_pdf():
    return render_template('tool_sign_pdf.html')

# ── SEO: sitemap.xml ──────────────────────────────────────────────
@app.route('/sitemap.xml')
def sitemap():
    from flask import make_response
    site = app.config['SITE_URL']
    urls = [
        ('/', '1.0', 'daily'),
        # Primary PDF tools — highest priority
        ('/fill-pdf-form-online', '1.0', 'weekly'),
        ('/edit-pdf-online', '1.0', 'weekly'),
        ('/sign-pdf-online', '0.9', 'weekly'),
        ('/merge-pdf', '0.9', 'weekly'),
        ('/pdf-to-jpg', '0.9', 'weekly'),
        # Image tools
        ('/jpg-to-pdf', '0.8', 'weekly'),
        ('/compress-jpg-to-50kb', '0.8', 'weekly'),
        ('/resize-image-to-200x200', '0.8', 'weekly'),
        ('/passport-photo-maker', '0.8', 'weekly'),
        # Static pages
        ('/about', '0.6', 'monthly'),
        ('/contact', '0.6', 'monthly'),
        ('/privacy-policy', '0.3', 'yearly'),
        ('/terms-of-service', '0.3', 'yearly'),
    ]
    today = '2026-05-05'
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for path, priority, freq in urls:
        xml += f'  <url><loc>{site}{path}</loc><lastmod>{today}</lastmod><changefreq>{freq}</changefreq><priority>{priority}</priority></url>\n'
    xml += '</urlset>'
    resp = make_response(xml, 200)
    resp.headers['Content-Type'] = 'application/xml'
    return resp

# ── SEO: robots.txt ───────────────────────────────────────────────
@app.route('/robots.txt')
def robots():
    from flask import make_response
    site = app.config['SITE_URL']
    txt = f"""User-agent: *
Allow: /
Allow: /fill-pdf-form-online
Allow: /edit-pdf-online
Allow: /sign-pdf-online
Allow: /merge-pdf
Allow: /pdf-to-jpg
Allow: /jpg-to-pdf
Allow: /compress-jpg-to-50kb
Allow: /resize-image-to-200x200
Allow: /passport-photo-maker
Allow: /about
Allow: /contact
Allow: /privacy-policy
Allow: /terms-of-service
Disallow: /api/
Disallow: /tmp/
Disallow: /static/tmp/

# Crawl-delay for polite bots
Crawl-delay: 2

Sitemap: {site}/sitemap.xml
"""
    resp = make_response(txt, 200)
    resp.headers['Content-Type'] = 'text/plain'
    return resp

# ---- Convert ----
@app.route('/api/convert', methods=['POST'])
def api_convert():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    target_fmt = request.form.get('format', 'png').lower().strip('.')

    try:
        img = open_image(f)
    except Exception as e:
        return jsonify({'error': f'Cannot open image: {e}'}), 400

    pil_fmt = PIL_FORMAT_MAP.get(target_fmt)
    if not pil_fmt:
        return jsonify({'error': f'Unsupported output format: {target_fmt}'}), 400

    try:
        buf = save_image(img, pil_fmt)
    except Exception as e:
        return jsonify({'error': f'Conversion failed: {e}'}), 500

    mime = MIME_MAP.get(target_fmt, 'application/octet-stream')
    original_stem = os.path.splitext(f.filename)[0] if f.filename else 'image'
    download_name = f"{original_stem}.{target_fmt}"

    return send_file(buf, mimetype=mime, as_attachment=True, download_name=download_name)

# ---- Compress ----
@app.route('/api/compress', methods=['POST'])
def api_compress():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    target_kb = request.form.get('target_kb', '')
    quality = int(request.form.get('quality', 80))

    filename_lower = f.filename.lower() if f.filename else ''
    if filename_lower.endswith('.png'):
        pil_fmt = 'PNG'
        mime = 'image/png'
        ext = 'png'
    elif filename_lower.endswith('.webp'):
        pil_fmt = 'WEBP'
        mime = 'image/webp'
        ext = 'webp'
    else:
        pil_fmt = 'JPEG'
        mime = 'image/jpeg'
        ext = 'jpg'

    try:
        data = f.read()
        img = Image.open(io.BytesIO(data))
    except Exception as e:
        return jsonify({'error': f'Cannot open image: {e}'}), 400

    try:
        if target_kb:
            target_bytes = int(target_kb) * 1024
            buf = compress_to_target(img, pil_fmt, target_bytes)
        else:
            buf = io.BytesIO()
            save_img = img.convert('RGB') if pil_fmt == 'JPEG' and img.mode in ('RGBA', 'P') else img
            if pil_fmt in ('JPEG', 'WEBP'):
                save_img.save(buf, format=pil_fmt, quality=quality, optimize=True)
            else:
                save_img.save(buf, format=pil_fmt, optimize=True)
            buf.seek(0)
    except Exception as e:
        return jsonify({'error': f'Compression failed: {e}'}), 500

    original_stem = os.path.splitext(f.filename)[0] if f.filename else 'image'
    download_name = f"{original_stem}_compressed.{ext}"
    return send_file(buf, mimetype=mime, as_attachment=True, download_name=download_name)

# ---- Resize ----
@app.route('/api/resize', methods=['POST'])
def api_resize():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    mode = request.form.get('mode', 'dimensions')  # dimensions | percentage | preset

    try:
        data = f.read()
        img = Image.open(io.BytesIO(data))
    except Exception as e:
        return jsonify({'error': f'Cannot open image: {e}'}), 400

    orig_w, orig_h = img.size

    try:
        if mode == 'percentage':
            pct = float(request.form.get('percentage', 100)) / 100.0
            new_w = max(1, int(orig_w * pct))
            new_h = max(1, int(orig_h * pct))
        elif mode == 'preset':
            preset = request.form.get('preset', '1920x1080')
            new_w, new_h = map(int, preset.split('x'))
        else:  # dimensions
            new_w = int(request.form.get('width', orig_w) or orig_w)
            new_h = int(request.form.get('height', orig_h) or orig_h)
            keep_ratio = request.form.get('keep_ratio', 'true').lower() == 'true'
            if keep_ratio:
                ratio = min(new_w / orig_w, new_h / orig_h)
                new_w = max(1, int(orig_w * ratio))
                new_h = max(1, int(orig_h * ratio))

        img = img.resize((new_w, new_h), Image.LANCZOS)
    except Exception as e:
        return jsonify({'error': f'Resize failed: {e}'}), 500

    filename_lower = f.filename.lower() if f.filename else ''
    if filename_lower.endswith('.png'):
        pil_fmt, mime, ext = 'PNG', 'image/png', 'png'
    elif filename_lower.endswith('.webp'):
        pil_fmt, mime, ext = 'WEBP', 'image/webp', 'webp'
    else:
        pil_fmt, mime, ext = 'JPEG', 'image/jpeg', 'jpg'

    buf = save_image(img, pil_fmt)
    original_stem = os.path.splitext(f.filename)[0] if f.filename else 'image'
    download_name = f"{original_stem}_{new_w}x{new_h}.{ext}"
    return send_file(buf, mimetype=mime, as_attachment=True, download_name=download_name)

# ---- Image to PDF ----
@app.route('/api/to-pdf', methods=['POST'])
def api_to_pdf():
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files uploaded'}), 400

    images = []
    for f in files:
        try:
            data = f.read()
            img = Image.open(io.BytesIO(data)).convert('RGB')
            images.append(img)
        except Exception as e:
            return jsonify({'error': f'Cannot open {f.filename}: {e}'}), 400

    buf = io.BytesIO()
    try:
        images[0].save(buf, format='PDF', save_all=True, append_images=images[1:])
    except Exception as e:
        return jsonify({'error': f'PDF creation failed: {e}'}), 500

    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='images.pdf')

# ---- Metadata strip (privacy) ----
@app.route('/api/strip-metadata', methods=['POST'])
def api_strip_metadata():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']

    try:
        data = f.read()
        img = Image.open(io.BytesIO(data))
        # Re-save without metadata
        clean = Image.new(img.mode, img.size)
        clean.putdata(list(img.getdata()))
    except Exception as e:
        return jsonify({'error': f'Cannot process image: {e}'}), 400

    filename_lower = f.filename.lower() if f.filename else ''
    if filename_lower.endswith('.png'):
        pil_fmt, mime, ext = 'PNG', 'image/png', 'png'
    elif filename_lower.endswith('.webp'):
        pil_fmt, mime, ext = 'WEBP', 'image/webp', 'webp'
    else:
        pil_fmt, mime, ext = 'JPEG', 'image/jpeg', 'jpg'

    buf = save_image(clean, pil_fmt)
    original_stem = os.path.splitext(f.filename)[0] if f.filename else 'image'
    return send_file(buf, mimetype=mime, as_attachment=True, download_name=f"{original_stem}_clean.{ext}")

# ---------- helpers for new endpoints ----------
def get_fmt(filename_lower):
    if filename_lower.endswith('.png'):
        return 'PNG', 'image/png', 'png'
    elif filename_lower.endswith('.webp'):
        return 'WEBP', 'image/webp', 'webp'
    else:
        return 'JPEG', 'image/jpeg', 'jpg'

def get_font(size):
    paths = [
        '/System/Library/Fonts/Helvetica.ttc',
        '/System/Library/Fonts/Arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()

# ---- Edit / Effects ----
@app.route('/api/edit', methods=['POST'])
def api_edit():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']

    brightness  = float(request.form.get('brightness',  1.0))
    contrast    = float(request.form.get('contrast',    1.0))
    saturation  = float(request.form.get('saturation',  1.0))
    sharpness   = float(request.form.get('sharpness',   1.0))
    blur        = float(request.form.get('blur',        0.0))
    effect      = request.form.get('effect', 'none')   # single named effect

    try:
        img = Image.open(io.BytesIO(f.read())).convert('RGB')
    except Exception as e:
        return jsonify({'error': f'Cannot open image: {e}'}), 400

    # ── Named filter effects ──
    if effect == 'grayscale':
        img = ImageOps.grayscale(img).convert('RGB')
    elif effect == 'sepia':
        gray = ImageOps.grayscale(img)
        r_ch = gray.point(lambda x: min(255, int(x * 1.08)))
        g_ch = gray.point(lambda x: min(255, int(x * 0.85)))
        b_ch = gray.point(lambda x: min(255, int(x * 0.65)))
        img = Image.merge('RGB', (r_ch, g_ch, b_ch))
    elif effect == 'invert':
        img = ImageOps.invert(img)
    elif effect == 'vivid':
        img = ImageEnhance.Color(img).enhance(2.2)
        img = ImageEnhance.Contrast(img).enhance(1.2)
    elif effect == 'vintage':
        img = ImageEnhance.Color(img).enhance(0.7)
        img = ImageEnhance.Contrast(img).enhance(0.8)
        img = ImageEnhance.Brightness(img).enhance(0.95)
        gray = ImageOps.grayscale(img)
        r_ch = gray.point(lambda x: min(255, int(x * 1.08)))
        g_ch = gray.point(lambda x: min(255, int(x * 0.85)))
        b_ch = gray.point(lambda x: min(255, int(x * 0.65)))
        sepia_layer = Image.merge('RGB', (r_ch, g_ch, b_ch))
        img = Image.blend(img, sepia_layer, 0.35)
    elif effect == 'cool':
        r, g, b = img.split()
        r = r.point(lambda x: max(0, x - 20))
        b = b.point(lambda x: min(255, x + 30))
        img = Image.merge('RGB', (r, g, b))
        img = ImageEnhance.Color(img).enhance(1.3)
    elif effect == 'warm':
        r, g, b = img.split()
        r = r.point(lambda x: min(255, x + 25))
        b = b.point(lambda x: max(0, x - 20))
        img = Image.merge('RGB', (r, g, b))
        img = ImageEnhance.Color(img).enhance(1.4)
    elif effect == 'faded':
        img = ImageEnhance.Contrast(img).enhance(0.65)
        img = ImageEnhance.Brightness(img).enhance(1.2)
        img = ImageEnhance.Color(img).enhance(0.6)
    elif effect == 'highcontrast':
        img = ImageEnhance.Contrast(img).enhance(1.8)
        img = ImageEnhance.Brightness(img).enhance(1.05)
    elif effect == 'dramatic':
        img = ImageOps.grayscale(img).convert('RGB')
        img = ImageEnhance.Contrast(img).enhance(1.5)
        img = ImageEnhance.Brightness(img).enhance(0.85)
    elif effect == 'matte':
        img = ImageEnhance.Contrast(img).enhance(0.8)
        img = ImageEnhance.Brightness(img).enhance(1.1)
        img = ImageEnhance.Color(img).enhance(0.8)

    # ── Adjustments (applied on top of effect) ──
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)
    if sharpness != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(sharpness)
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))

    filename_lower = f.filename.lower() if f.filename else ''
    pil_fmt, mime, ext = get_fmt(filename_lower)
    buf = save_image(img, pil_fmt)
    stem = os.path.splitext(f.filename)[0] if f.filename else 'image'
    return send_file(buf, mimetype=mime, as_attachment=True, download_name=f"{stem}_edited.{ext}")

# ---- Watermark / Add Text ----
@app.route('/api/watermark', methods=['POST'])
def api_watermark():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']

    text       = request.form.get('text', 'Watermark')
    position   = request.form.get('position', 'bottom-right')
    font_size  = int(request.form.get('font_size', 40))
    color      = request.form.get('color', '#ffffff')
    opacity    = int(request.form.get('opacity', 70))
    repeat     = request.form.get('repeat', 'false').lower() == 'true'

    try:
        img = Image.open(io.BytesIO(f.read())).convert('RGBA')
    except Exception as e:
        return jsonify({'error': f'Cannot open image: {e}'}), 400

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)
    font    = get_font(font_size)

    try:
        rc = int(color[1:3], 16)
        gc = int(color[3:5], 16)
        bc = int(color[5:7], 16)
    except Exception:
        rc, gc, bc = 255, 255, 255
    alpha = int(opacity * 255 / 100)
    fill  = (rc, gc, bc, alpha)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    iw, ih = img.size
    pad  = max(20, int(min(iw, ih) * 0.03))

    if repeat:
        step_x = tw + 80
        step_y = th + 60
        for yp in range(-th, ih + th, step_y):
            for xp in range(-tw, iw + tw, step_x):
                draw.text((xp, yp), text, font=font, fill=fill)
    else:
        positions = {
            'top-left':       (pad, pad),
            'top-center':     ((iw - tw) // 2, pad),
            'top-right':      (iw - tw - pad, pad),
            'middle-left':    (pad, (ih - th) // 2),
            'center':         ((iw - tw) // 2, (ih - th) // 2),
            'middle-right':   (iw - tw - pad, (ih - th) // 2),
            'bottom-left':    (pad, ih - th - pad),
            'bottom-center':  ((iw - tw) // 2, ih - th - pad),
            'bottom-right':   (iw - tw - pad, ih - th - pad),
        }
        pos = positions.get(position, (iw - tw - pad, ih - th - pad))
        draw.text(pos, text, font=font, fill=fill)

    result = Image.alpha_composite(img, overlay).convert('RGB')
    filename_lower = f.filename.lower() if f.filename else ''
    pil_fmt, mime, ext = get_fmt(filename_lower)
    buf  = save_image(result, pil_fmt)
    stem = os.path.splitext(f.filename)[0] if f.filename else 'image'
    return send_file(buf, mimetype=mime, as_attachment=True, download_name=f"{stem}_watermarked.{ext}")

# ---- Add Text to Image ----
@app.route('/api/add-text', methods=['POST'])
def api_add_text():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']

    text       = request.form.get('text', 'Your Text')
    x_pct      = float(request.form.get('x_pct', 50))
    y_pct      = float(request.form.get('y_pct', 50))
    font_size  = int(request.form.get('font_size', 60))
    color      = request.form.get('color', '#ffffff')
    bold       = request.form.get('bold', 'true').lower() == 'true'
    bg_box     = request.form.get('bg_box', 'false').lower() == 'true'
    bg_color   = request.form.get('bg_color', '#000000')
    bg_opacity = int(request.form.get('bg_opacity', 60))

    try:
        img = Image.open(io.BytesIO(f.read())).convert('RGBA')
    except Exception as e:
        return jsonify({'error': f'Cannot open image: {e}'}), 400

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)
    font    = get_font(font_size)

    try:
        rc, gc, bc = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    except Exception:
        rc, gc, bc = 255, 255, 255
    fill = (rc, gc, bc, 255)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    iw, ih = img.size
    x = int(x_pct / 100 * iw - tw / 2)
    y = int(y_pct / 100 * ih - th / 2)
    x = max(0, min(x, iw - tw))
    y = max(0, min(y, ih - th))

    if bg_box:
        pad = max(6, font_size // 8)
        try:
            rb, gb, bb = int(bg_color[1:3], 16), int(bg_color[3:5], 16), int(bg_color[5:7], 16)
        except Exception:
            rb, gb, bb = 0, 0, 0
        ab = int(bg_opacity * 255 / 100)
        draw.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], fill=(rb, gb, bb, ab))

    draw.text((x, y), text, font=font, fill=fill)
    result = Image.alpha_composite(img, overlay).convert('RGB')
    filename_lower = f.filename.lower() if f.filename else ''
    pil_fmt, mime, ext = get_fmt(filename_lower)
    buf  = save_image(result, pil_fmt)
    stem = os.path.splitext(f.filename)[0] if f.filename else 'image'
    return send_file(buf, mimetype=mime, as_attachment=True, download_name=f"{stem}_text.{ext}")

# ---- Passport Photo Maker ----
PASSPORT_SIZES = {
    '35x45mm':  (413, 531),   # India Passport / Visa
    '51x51mm':  (600, 600),   # US Passport
    '40x40mm':  (472, 472),   # UAE / Gulf
    '35x35mm':  (413, 413),   # Some Indian ID
    '25x35mm':  (295, 413),   # Indian PAN card style
    '50x70mm':  (591, 827),   # A-type visa
    '45x35mm':  (531, 413),   # Landscape ID
}

@app.route('/api/passport-photo', methods=['POST'])
def api_passport_photo():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']

    size_key  = request.form.get('size', '35x45mm')
    bg_color  = request.form.get('bg_color', '#ffffff')
    sheet     = request.form.get('sheet', 'false').lower() == 'true'

    w, h = PASSPORT_SIZES.get(size_key, (413, 531))
    try:
        rr, gr, br = int(bg_color[1:3], 16), int(bg_color[3:5], 16), int(bg_color[5:7], 16)
    except Exception:
        rr, gr, br = 255, 255, 255

    try:
        img = Image.open(io.BytesIO(f.read())).convert('RGBA')
    except Exception as e:
        return jsonify({'error': f'Cannot open image: {e}'}), 400

    # Fill background
    bg  = Image.new('RGBA', (w, h), (rr, gr, br, 255))
    ratio = min(w / img.width, h / img.height)
    nw, nh = int(img.width * ratio), int(img.height * ratio)
    img_r  = img.resize((nw, nh), Image.LANCZOS)
    bg.paste(img_r, ((w - nw) // 2, (h - nh) // 2), img_r)
    result = bg.convert('RGB')

    if sheet:
        margin, gap, cols, rows = 30, 15, 4, 2
        sw = cols * w + (cols - 1) * gap + 2 * margin
        sh = rows * h + (rows - 1) * gap + 2 * margin
        s  = Image.new('RGB', (sw, sh), (255, 255, 255))
        for row in range(rows):
            for col in range(cols):
                s.paste(result, (margin + col * (w + gap), margin + row * (h + gap)))
        result = s

    buf = io.BytesIO()
    result.save(buf, format='JPEG', quality=95)
    buf.seek(0)
    stem   = os.path.splitext(f.filename)[0] if f.filename else 'photo'
    suffix = '_4up' if sheet else f'_{size_key}'
    return send_file(buf, mimetype='image/jpeg', as_attachment=True, download_name=f"{stem}_passport{suffix}.jpg")

# ---- Signature Resize ----
SIGNATURE_SIZES = {
    'ssc':       (140, 60),
    'upsc':      (150, 60),
    'ibps':      (140, 60),
    'sbi':       (160, 80),
    'railway':   (150, 70),
    'passport':  (200, 100),
    'generic':   (200, 80),
    'custom':    None,
}

@app.route('/api/signature-resize', methods=['POST'])
def api_signature_resize():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']

    preset  = request.form.get('preset', 'ssc')
    cust_w  = int(request.form.get('width',  140))
    cust_h  = int(request.form.get('height', 60))
    white_bg = request.form.get('white_bg', 'true').lower() == 'true'

    if preset == 'custom' or preset not in SIGNATURE_SIZES:
        tw, th = cust_w, cust_h
    else:
        tw, th = SIGNATURE_SIZES[preset]

    try:
        img = Image.open(io.BytesIO(f.read())).convert('RGBA')
    except Exception as e:
        return jsonify({'error': f'Cannot open image: {e}'}), 400

    if white_bg:
        bg = Image.new('RGBA', (tw, th), (255, 255, 255, 255))
        ratio = min(tw / img.width, th / img.height)
        nw, nh = max(1, int(img.width * ratio)), max(1, int(img.height * ratio))
        img_r = img.resize((nw, nh), Image.LANCZOS)
        bg.paste(img_r, ((tw - nw) // 2, (th - nh) // 2), img_r)
        result = bg.convert('RGB')
        pil_fmt, mime, ext = 'JPEG', 'image/jpeg', 'jpg'
    else:
        result = img.resize((tw, th), Image.LANCZOS)
        pil_fmt, mime, ext = 'PNG', 'image/png', 'png'

    buf = save_image(result, pil_fmt)
    stem = os.path.splitext(f.filename)[0] if f.filename else 'signature'
    return send_file(buf, mimetype=mime, as_attachment=True, download_name=f"{stem}_{preset}_{tw}x{th}.{ext}")

# ---- Merge Photo + Signature ----
@app.route('/api/merge-photo-signature', methods=['POST'])
def api_merge_photo_signature():
    photo_f = request.files.get('photo')
    sig_f   = request.files.get('signature')
    if not photo_f or not sig_f:
        return jsonify({'error': 'Both photo and signature are required'}), 400

    layout = request.form.get('layout', 'side-by-side')

    try:
        photo = Image.open(io.BytesIO(photo_f.read())).convert('RGB')
        sig   = Image.open(io.BytesIO(sig_f.read())).convert('RGBA')
    except Exception as e:
        return jsonify({'error': f'Cannot open image: {e}'}), 400

    def paste_sig(canvas, sig_img, x, y, max_w, max_h):
        r = min(max_w / sig_img.width, max_h / sig_img.height)
        nw, nh = max(1, int(sig_img.width * r)), max(1, int(sig_img.height * r))
        s = sig_img.resize((nw, nh), Image.LANCZOS)
        bg = Image.new('RGB', (nw, nh), (255, 255, 255))
        bg.paste(s, mask=s.split()[3] if s.mode == 'RGBA' else None)
        canvas.paste(bg, (x + (max_w - nw) // 2, y + (max_h - nh) // 2))

    if layout == 'side-by-side':
        target_h = max(photo.height, 200)
        r = target_h / photo.height
        ph = target_h; pw = int(photo.width * r)
        photo = photo.resize((pw, ph), Image.LANCZOS)
        sig_h = ph // 2; sig_w = pw
        gap = 20
        result = Image.new('RGB', (pw + gap + sig_w, ph), (255, 255, 255))
        result.paste(photo, (0, 0))
        paste_sig(result, sig, pw + gap, (ph - sig_h) // 2, sig_w, sig_h)

    elif layout == 'form':
        # Govt form layout — photo right, signature left on white A5 canvas
        cw, ch = 800, 260
        result = Image.new('RGB', (cw, ch), (255, 255, 255))
        draw   = ImageDraw.Draw(result)
        font_s = get_font(18)
        # Photo box (right)
        ph = 200; r = ph / photo.height; pw = int(photo.width * r)
        photo_r = photo.resize((pw, ph), Image.LANCZOS)
        px = cw - pw - 30; py = (ch - ph) // 2
        result.paste(photo_r, (px, py))
        draw.rectangle([px - 2, py - 2, px + pw + 2, py + ph + 2], outline=(180, 180, 180), width=1)
        draw.text((px, py + ph + 6), "Photograph", font=font_s, fill=(120, 120, 120))
        # Signature box (left)
        sx = 30; sy = (ch - 80) // 2; sw = 280; sh = 80
        paste_sig(result, sig, sx, sy, sw, sh)
        draw.rectangle([sx - 2, sy - 2, sx + sw + 2, sy + sh + 2], outline=(180, 180, 180), width=1)
        draw.text((sx, sy + sh + 6), "Signature", font=font_s, fill=(120, 120, 120))

    else:  # above-below
        gap = 20
        sig_h = max(60, photo.width // 4)
        sig_r_w = photo.width
        sig_r_h = max(1, int(sig.height * sig_r_w / max(sig.width, 1)))
        sig_bg = Image.new('RGB', (sig_r_w, sig_r_h), (255, 255, 255))
        s = sig.resize((sig_r_w, sig_r_h), Image.LANCZOS)
        sig_bg.paste(s, mask=s.split()[3] if s.mode == 'RGBA' else None)
        result = Image.new('RGB', (photo.width, photo.height + gap + sig_r_h), (255, 255, 255))
        result.paste(photo, (0, 0))
        result.paste(sig_bg, (0, photo.height + gap))

    buf = io.BytesIO()
    result.save(buf, format='JPEG', quality=95)
    buf.seek(0)
    stem = os.path.splitext(photo_f.filename)[0] if photo_f.filename else 'merged'
    ext = 'jpg'
    return send_file(buf, mimetype='image/jpeg', as_attachment=True, download_name=f"{stem}_merged.{ext}")

# ══════════════════════════════════════════════════════════════════
#  PDF TOOLS
# ══════════════════════════════════════════════════════════════════

def parse_page_range(s, total):
    """Parse '1,3-5,7' (1-indexed) → sorted 0-indexed list."""
    pages = set()
    for part in str(s).split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                a, b = part.split('-', 1)
                pages.update(range(max(0, int(a.strip()) - 1), min(total, int(b.strip()))))
            except Exception:
                pass
        else:
            try:
                p = int(part) - 1
                if 0 <= p < total:
                    pages.add(p)
            except Exception:
                pass
    return sorted(pages)

# ── PDF Info ──────────────────────────────────────────────────────
@app.route('/api/pdf/info', methods=['POST'])
def api_pdf_info():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    try:
        reader = PdfReader(io.BytesIO(f.read()))
        return jsonify({'pages': len(reader.pages), 'encrypted': reader.is_encrypted})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ── PDF to Images ─────────────────────────────────────────────────
@app.route('/api/pdf/to-image', methods=['POST'])
def api_pdf_to_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    fmt         = request.form.get('format', 'jpg').lower()
    pages_input = request.form.get('pages', 'all')
    dpi         = min(int(request.form.get('dpi', 150)), 300)

    if not FITZ_AVAILABLE:
        return jsonify({'error': 'PDF rendering library not installed'}), 500
    try:
        doc   = fitz.open(stream=f.read(), filetype='pdf')
        total = len(doc)
        page_nums = list(range(total)) if pages_input == 'all' else parse_page_range(pages_input, total)
        if not page_nums:
            return jsonify({'error': 'No valid pages selected'}), 400

        mat = fitz.Matrix(dpi / 72, dpi / 72)

        if len(page_nums) == 1:
            pix = doc[page_nums[0]].get_pixmap(matrix=mat)
            ext  = 'png' if fmt == 'png' else 'jpg'
            mime = 'image/png' if fmt == 'png' else 'image/jpeg'
            data = pix.tobytes('png') if fmt == 'png' else pix.tobytes('jpeg')
            return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True,
                             download_name=f'page_{page_nums[0]+1}.{ext}')

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for pn in page_nums:
                pix  = doc[pn].get_pixmap(matrix=mat)
                data = pix.tobytes('png') if fmt == 'png' else pix.tobytes('jpeg')
                zf.writestr(f'page_{pn+1}.{fmt}', data)
        zip_buf.seek(0)
        return send_file(zip_buf, mimetype='application/zip', as_attachment=True,
                         download_name='pdf_images.zip')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Merge PDFs ────────────────────────────────────────────────────
@app.route('/api/pdf/merge', methods=['POST'])
def api_pdf_merge():
    files = request.files.getlist('files')
    if len(files) < 2:
        return jsonify({'error': 'Upload at least 2 PDF files'}), 400
    try:
        writer = PdfWriter()
        for f in files:
            reader = PdfReader(io.BytesIO(f.read()))
            for page in reader.pages:
                writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name='merged.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Split PDF ─────────────────────────────────────────────────────
@app.route('/api/pdf/split', methods=['POST'])
def api_pdf_split():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f          = request.files['file']
    split_type = request.form.get('split_type', 'each')   # each | range | every_n
    ranges_str = request.form.get('ranges', '')
    every_n    = max(1, int(request.form.get('every_n', 1)))

    try:
        reader = PdfReader(io.BytesIO(f.read()))
        total  = len(reader.pages)

        if split_type == 'each':
            groups = [[i] for i in range(total)]
        elif split_type == 'every_n':
            groups = [list(range(i, min(i + every_n, total))) for i in range(0, total, every_n)]
        else:
            groups = []
            for r in ranges_str.split(','):
                r = r.strip()
                if r:
                    grp = parse_page_range(r, total)
                    if grp:
                        groups.append(grp)

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, group in enumerate(groups):
                w = PdfWriter()
                for pn in group:
                    if 0 <= pn < total:
                        w.add_page(reader.pages[pn])
                if not w.pages:
                    continue
                pb = io.BytesIO(); w.write(pb)
                name = (f'pages_{group[0]+1}-{group[-1]+1}.pdf' if len(group) > 1
                        else f'page_{group[0]+1}.pdf')
                zf.writestr(f'part_{i+1}_{name}', pb.getvalue())
        zip_buf.seek(0)
        return send_file(zip_buf, mimetype='application/zip', as_attachment=True,
                         download_name='split.zip')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Delete Pages ──────────────────────────────────────────────────
@app.route('/api/pdf/delete-pages', methods=['POST'])
def api_pdf_delete_pages():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    pages_str = request.form.get('pages', '')
    try:
        reader  = PdfReader(io.BytesIO(f.read()))
        total   = len(reader.pages)
        to_del  = set(parse_page_range(pages_str, total))
        writer  = PdfWriter()
        for i, page in enumerate(reader.pages):
            if i not in to_del:
                writer.add_page(page)
        buf = io.BytesIO(); writer.write(buf); buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}_deleted.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Rearrange Pages ───────────────────────────────────────────────
@app.route('/api/pdf/rearrange', methods=['POST'])
def api_pdf_rearrange():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    order_str = request.form.get('order', '')
    try:
        reader = PdfReader(io.BytesIO(f.read()))
        total  = len(reader.pages)
        order  = [int(x.strip()) - 1 for x in order_str.split(',') if x.strip()]
        writer = PdfWriter()
        for pn in order:
            if 0 <= pn < total:
                writer.add_page(reader.pages[pn])
        buf = io.BytesIO(); writer.write(buf); buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}_rearranged.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Rotate PDF ────────────────────────────────────────────────────
@app.route('/api/pdf/rotate', methods=['POST'])
def api_pdf_rotate():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    angle     = int(request.form.get('angle', 90))
    pages_str = request.form.get('pages', 'all')
    try:
        reader   = PdfReader(io.BytesIO(f.read()))
        total    = len(reader.pages)
        rot_set  = set(range(total)) if pages_str == 'all' else set(parse_page_range(pages_str, total))
        writer   = PdfWriter()
        for i, page in enumerate(reader.pages):
            if i in rot_set:
                page.rotate(angle)
            writer.add_page(page)
        buf = io.BytesIO(); writer.write(buf); buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}_rotated.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Compress PDF ──────────────────────────────────────────────────
@app.route('/api/pdf/compress', methods=['POST'])
def api_pdf_compress():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f     = request.files['file']
    level = request.form.get('level', 'medium')   # low | medium | high
    try:
        data = f.read()
        if PIKEPDF_AVAILABLE:
            with pikepdf.open(io.BytesIO(data)) as pdf:
                buf = io.BytesIO()
                if level == 'high':
                    pdf.save(buf, compress_streams=True,
                             stream_decode_level=pikepdf.StreamDecodeLevel.generalized)
                else:
                    pdf.save(buf, compress_streams=True)
        else:
            reader = PdfReader(io.BytesIO(data))
            writer = PdfWriter()
            for page in reader.pages:
                if level != 'low':
                    page.compress_content_streams()
                writer.add_page(page)
            buf = io.BytesIO(); writer.write(buf)
        buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}_compressed.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Protect PDF ───────────────────────────────────────────────────
@app.route('/api/pdf/protect', methods=['POST'])
def api_pdf_protect():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f        = request.files['file']
    password = request.form.get('password', '').strip()
    if not password:
        return jsonify({'error': 'Password is required'}), 400
    try:
        reader = PdfReader(io.BytesIO(f.read()))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(user_password=password, owner_password=password)
        buf = io.BytesIO(); writer.write(buf); buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}_protected.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Unlock PDF ────────────────────────────────────────────────────
@app.route('/api/pdf/unlock', methods=['POST'])
def api_pdf_unlock():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f        = request.files['file']
    password = request.form.get('password', '').strip()
    try:
        data   = f.read()
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            if not reader.decrypt(password):
                return jsonify({'error': 'Incorrect password or unsupported encryption'}), 400
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        buf = io.BytesIO(); writer.write(buf); buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}_unlocked.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── PDF Watermark ─────────────────────────────────────────────────
@app.route('/api/pdf/watermark', methods=['POST'])
def api_pdf_watermark():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f         = request.files['file']
    text      = request.form.get('text', 'CONFIDENTIAL')
    opacity   = float(request.form.get('opacity', 0.25))
    color     = request.form.get('color', '#ff0000')
    font_size = int(request.form.get('font_size', 52))
    diagonal  = request.form.get('diagonal', 'true').lower() == 'true'

    if not REPORTLAB_AVAILABLE:
        return jsonify({'error': 'reportlab not installed'}), 500

    try:
        rc = int(color[1:3], 16) / 255
        gc = int(color[3:5], 16) / 255
        bc = int(color[5:7], 16) / 255
    except Exception:
        rc, gc, bc = 1, 0, 0

    try:
        reader = PdfReader(io.BytesIO(f.read()))
        writer = PdfWriter()
        for page in reader.pages:
            pw = float(page.mediabox.width)
            ph = float(page.mediabox.height)
            wm = io.BytesIO()
            c  = rl_canvas.Canvas(wm, pagesize=(pw, ph))
            c.setFillColorRGB(rc, gc, bc, alpha=opacity)
            c.setFont('Helvetica-Bold', font_size)
            if diagonal:
                import math
                c.saveState()
                c.translate(pw / 2, ph / 2)
                c.rotate(math.degrees(math.atan2(ph, pw)))
                c.drawCentredString(0, 0, text)
                c.restoreState()
            else:
                c.drawCentredString(pw / 2, ph / 2, text)
            c.save()
            wm.seek(0)
            wm_page = PdfReader(wm).pages[0]
            page.merge_page(wm_page)
            writer.add_page(page)
        buf = io.BytesIO(); writer.write(buf); buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}_watermarked.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Word to PDF ───────────────────────────────────────────────────
@app.route('/api/pdf/word-to-pdf', methods=['POST'])
def api_word_to_pdf():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    filename_lower = (f.filename or '').lower()
    if not (filename_lower.endswith('.docx') or filename_lower.endswith('.doc')):
        return jsonify({'error': 'Only .docx / .doc files are supported'}), 400

    if not MAMMOTH_AVAILABLE:
        return jsonify({'error': 'mammoth library not installed'}), 500
    if not WEASYPRINT_AVAILABLE:
        return jsonify({'error': 'weasyprint library not installed'}), 500

    try:
        data = f.read()
        result = mammoth.convert_to_html(io.BytesIO(data))
        html_body = result.value

        # Wrap with basic styling for a clean PDF
        html_full = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 12pt; line-height: 1.6;
          margin: 2.5cm 2cm; color: #111; }}
  h1,h2,h3,h4,h5,h6 {{ color: #1a1a2e; margin-top: 1.2em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  td, th {{ border: 1px solid #ccc; padding: 6px 10px; }}
  th {{ background: #f0f0f0; font-weight: bold; }}
  img {{ max-width: 100%; height: auto; }}
  p {{ margin: 0.5em 0; }}
</style>
</head>
<body>{html_body}</body>
</html>"""

        pdf_bytes = WeasyprintHTML(string=html_full).write_pdf()
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════
#  AI DRESS SWAP / VIRTUAL TRY-ON
#  Priority:
#    1. HuggingFace AI spaces  – best quality (free, no token, but quota-limited)
#    2. Replicate IDM-VTON     – paid optional fallback (REPLICATE_API_TOKEN)
#    3. LOCAL ENGINE           – unlimited, no token, always works
#       Uses mediapipe body-pose + rembg garment segmentation + CV2 soft-blend
#       so the garment is correctly fitted to the body (not just overlaid).
# ══════════════════════════════════════════════════════════════════

try:
    from gradio_client import Client as GradioClient, handle_file as gradio_handle_file
    GRADIO_CLIENT_AVAILABLE = True
except Exception:
    GRADIO_CLIENT_AVAILABLE = False

try:
    import mediapipe as mp
    _MP_POSE = mp.solutions.pose
    MEDIAPIPE_AVAILABLE = True
except Exception:
    MEDIAPIPE_AVAILABLE = False
    _MP_POSE = None


# ── Shared helpers ────────────────────────────────────────────────

def _prepare_image_for_vton(img_bytes: bytes, target_w: int = 768, target_h: int = 1024) -> bytes:
    """Letterbox-resize to target size for IDM-VTON input."""
    img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w, new_h = int(src_w * scale), int(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new('RGB', (target_w, target_h), (255, 255, 255))
    canvas.paste(img, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    buf = io.BytesIO()
    canvas.save(buf, format='PNG', optimize=False, compress_level=0)
    buf.seek(0)
    return buf.read()


def _finalise_vton_result(raw_bytes: bytes, orig_w: int, orig_h: int) -> bytes:
    """Upscale model result to original resolution and sharpen."""
    out = Image.open(io.BytesIO(raw_bytes)).convert('RGB')
    out = out.resize((orig_w, orig_h), Image.LANCZOS)
    out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=150, threshold=3))
    buf = io.BytesIO()
    out.save(buf, format='PNG', optimize=False, compress_level=0)
    buf.seek(0)
    return buf.read()


try:
    from scipy.interpolate import RBFInterpolator
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

# ── LOCAL ENGINE ──────────────────────────────────────────────────
#
# Full pipeline:
#  1. rembg (u2net_human_seg)  → body silhouette mask
#  2. mediapipe Pose           → shoulder / hip / ankle pixel landmarks
#  3. rembg                    → garment RGBA (clean, no background)
#  4. auto-keypoints           → find shoulder / hip / hem lines on garment
#  5. TPS warp (scipy RBF)     → physically deform garment to body shape
#                                (NOT a resize+overlay — actual mesh deformation)
#  6. body-mask clip           → garment pixels outside body silhouette removed
#  7. LAB lighting match       → garment brightness matched to scene lighting
#  8. Gaussian feather         → soft natural edges
#  9. Composite + sharpen      → final PNG at original resolution

def _extract_body_mask(person_bytes: bytes, person_img: 'Image.Image') -> 'np.ndarray | None':
    """
    Returns a float32 H×W mask [0-1] where 1 = human body, 0 = background.
    Uses rembg (u2net_human_seg preferred, u2net fallback).
    Returns None if rembg is unavailable.
    """
    import numpy as np
    if not REMBG_AVAILABLE:
        return None
    try:
        from rembg import new_session
        # u2net_human_seg gives clean person segmentation
        try:
            session = new_session('u2net_human_seg')
            rgba_bytes = rembg_remove(person_bytes, session=session)
        except Exception:
            rgba_bytes = rembg_remove(person_bytes)          # u2net fallback
        mask = np.array(Image.open(io.BytesIO(rgba_bytes)).convert('RGBA'))[:, :, 3]
        return mask.astype(np.float32) / 255.0
    except Exception as e:
        logger.warning(f'dress-swap: body mask extraction failed ({e})')
        return None


def _pose_landmarks(person_np) -> 'dict | None':
    """
    Run mediapipe Pose and return a dict of named pixel-coordinate landmarks.
    Keys: ls, rs (left/right shoulder), lh, rh (hip), lk, rk (knee), la, ra (ankle).
    Returns None if mediapipe is unavailable or detection fails.
    """
    import numpy as np
    if not (MEDIAPIPE_AVAILABLE and _MP_POSE is not None):
        return None
    ph, pw = person_np.shape[:2]
    try:
        with _MP_POSE.Pose(static_image_mode=True, model_complexity=2,
                           min_detection_confidence=0.3) as pose:
            res = pose.process(person_np)
        if not res.pose_landmarks:
            return None
        lm = res.pose_landmarks.landmark
        def pt(i): return (int(lm[i].x * pw), int(lm[i].y * ph))
        pts = {
            'ls': pt(11), 'rs': pt(12),
            'lh': pt(23), 'rh': pt(24),
            'lk': pt(25), 'rk': pt(26),
            'la': pt(27), 'ra': pt(28),
            'nose': pt(0),
        }
        logger.info(f'dress-swap: pose detected — shoulders {pts["ls"]},{pts["rs"]}  hips {pts["lh"]},{pts["rh"]}')
        return pts
    except Exception as e:
        logger.warning(f'dress-swap: mediapipe pose failed ({e})')
        return None


def _clothing_region(pts: 'dict | None', pw: int, ph: int, category: str):
    """
    Derive the exact target rectangle (x, y, w, h) for the garment on the body.
    Uses pose landmarks when available, proportional fallback otherwise.
    Returns (rx, ry, rw, rh, shoulder_px_width).
    """
    if pts:
        ls, rs = pts['ls'], pts['rs']
        lh, rh = pts['lh'], pts['rh']
        la, ra = pts['la'], pts['ra']

        shoulder_w = abs(rs[0] - ls[0])
        margin_x   = int(shoulder_w * 0.20)   # 20 % outward on each side

        # shoulder_y = the higher (smaller y) of the two shoulder landmarks
        shoulder_y = min(ls[1], rs[1])

        if category == 'upper_body':
            x1 = max(0, min(ls[0], rs[0]) - margin_x)
            x2 = min(pw, max(ls[0], rs[0]) + margin_x)
            # Only go slightly above the shoulder joint (4 %) — never into the face
            y1 = max(0, shoulder_y - int(shoulder_w * 0.04))
            y2 = min(ph, max(lh[1], rh[1]) + int(shoulder_w * 0.10))
        elif category == 'lower_body':
            x1 = max(0, min(lh[0], rh[0]) - margin_x)
            x2 = min(pw, max(lh[0], rh[0]) + margin_x)
            y1 = max(0, min(lh[1], rh[1]) - int(shoulder_w * 0.05))
            y2 = min(ph, max(la[1], ra[1]) + int(shoulder_w * 0.05))
        else:  # full dress
            x1 = max(0, min(ls[0], rs[0]) - margin_x)
            x2 = min(pw, max(ls[0], rs[0]) + margin_x)
            # Only go slightly above the shoulder joint (4 %) — never into the face
            y1 = max(0, shoulder_y - int(shoulder_w * 0.04))
            y2 = min(ph, max(la[1], ra[1]) + int(shoulder_w * 0.05))

        return x1, y1, x2 - x1, y2 - y1, shoulder_w

    # ── Proportional fallback ─────────────────────────────────────
    if category == 'upper_body':
        rx, ry = int(pw*.08), int(ph*.14)
        rw, rh = int(pw*.84), int(ph*.50)
    elif category == 'lower_body':
        rx, ry = int(pw*.10), int(ph*.48)
        rw, rh = int(pw*.80), int(ph*.50)
    else:
        rx, ry = int(pw*.08), int(ph*.12)
        rw, rh = int(pw*.84), int(ph*.86)
    return rx, ry, rw, rh, int(pw * 0.45)


def _clean_garment(garment_bytes: bytes) -> Image.Image:
    """Return garment as RGBA with background cleanly removed."""
    if REMBG_AVAILABLE:
        try:
            return Image.open(io.BytesIO(rembg_remove(garment_bytes))).convert('RGBA')
        except Exception as e:
            logger.warning(f'dress-swap: garment rembg failed ({e})')
    # Fallback: knock out near-white / near-light-grey pixels
    img = Image.open(io.BytesIO(garment_bytes)).convert('RGBA')
    data = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, _ = data[x, y]
            brightness = (r + g + b) / 3
            if brightness > 215 and abs(r - g) < 20 and abs(g - b) < 20:
                data[x, y] = (r, g, b, 0)
    return img


def _resize_garment_to_body(garment_rgba: 'Image.Image',
                             target_w: int, target_h: int) -> 'Image.Image':
    gw, gh = garment_rgba.size
    scale  = max(target_w / gw, target_h / gh)
    return garment_rgba.resize((max(1, int(gw*scale)), max(1, int(gh*scale))), Image.LANCZOS)


# ── Garment keypoint detection ───────────────────────────────────

def _garment_keypoints(gar_np: 'np.ndarray') -> list:
    """
    Auto-detect semantic keypoints on the garment from its alpha channel.
    Returns 9 (x, y) points:
      [left_shoulder, right_shoulder, left_waist, right_waist,
       left_hem, right_hem, top_center, mid_center, bottom_center]
    """
    import numpy as np
    alpha = gar_np[:, :, 3]
    gh, gw = alpha.shape

    rows = np.where(np.any(alpha > 30, axis=1))[0]
    cols = np.where(np.any(alpha > 30, axis=0))[0]
    if len(rows) == 0:
        # no transparency — use corners
        return [[gw//4,0],[3*gw//4,0],[gw//4,gh//2],[3*gw//4,gh//2],
                [gw//4,gh],[3*gw//4,gh],[gw//2,0],[gw//2,gh//2],[gw//2,gh]]

    top, bot = int(rows[0]), int(rows[-1])
    H = bot - top

    def _row_extent(y_frac):
        y = top + int(H * y_frac)
        y = min(y, gh - 1)
        c = np.where(alpha[y] > 30)[0]
        cx = (int(cols[0]) + int(cols[-1])) // 2
        if len(c) < 2:
            return int(cols[0]), int(cols[-1]), cx
        return int(c[0]), int(c[-1]), (int(c[0]) + int(c[-1])) // 2

    sl, sr, sc = _row_extent(0.08)   # shoulder line
    wl, wr, wc = _row_extent(0.55)   # waist line
    hl, hr, hc = _row_extent(0.92)   # hem line
    cy_shoulder = top + int(H * 0.08)
    cy_waist    = top + int(H * 0.55)
    cy_hem      = top + int(H * 0.92)

    return [
        [sl, cy_shoulder], [sr, cy_shoulder],   # 0,1 shoulders
        [wl, cy_waist],    [wr, cy_waist],       # 2,3 waist
        [hl, cy_hem],      [hr, cy_hem],         # 4,5 hem
        [sc, top],                               # 6  top-center
        [wc, cy_waist],                          # 7  mid-center
        [hc, bot],                               # 8  bottom-center
    ]


def _body_keypoints(pts: 'dict | None', pw: int, ph: int, category: str) -> list:
    """
    9 body keypoints in the same semantic order as _garment_keypoints.
    Uses mediapipe landmarks when available, proportional fallback otherwise.
    """
    if pts:
        ls, rs = pts['ls'], pts['rs']
        lh, rh = pts['lh'], pts['rh']
        la, ra = pts['la'], pts['ra']
        sw = abs(rs[0] - ls[0])
        mx = int(sw * 0.18)

        if category == 'upper_body':
            bottom_l = (max(0, min(lh[0],rh[0])-mx),  max(lh[1],rh[1]) + int(sw*0.08))
            bottom_r = (min(pw, max(lh[0],rh[0])+mx), max(lh[1],rh[1]) + int(sw*0.08))
        elif category == 'lower_body':
            ls = lh; rs = rh
            lh = ((lh[0]+la[0])//2, (lh[1]+la[1])//2)
            rh = ((rh[0]+ra[0])//2, (rh[1]+ra[1])//2)
            bottom_l = (la[0]-mx, la[1])
            bottom_r = (ra[0]+mx, ra[1])
        else:
            bottom_l = (la[0]-mx, la[1])
            bottom_r = (ra[0]+mx, ra[1])

        left_sh  = (min(ls[0],rs[0]) - mx, min(ls[1],rs[1]))
        right_sh = (max(ls[0],rs[0]) + mx, min(ls[1],rs[1]))
        left_w   = (min(lh[0],rh[0]) - mx//2, (lh[1]+rh[1])//2)
        right_w  = (max(lh[0],rh[0]) + mx//2, (lh[1]+rh[1])//2)
        cx = (left_sh[0] + right_sh[0]) // 2
        return [
            list(left_sh),  list(right_sh),
            list(left_w),   list(right_w),
            list(bottom_l), list(bottom_r),
            [cx, left_sh[1]],
            [(left_w[0]+right_w[0])//2, left_w[1]],
            [(bottom_l[0]+bottom_r[0])//2, bottom_l[1]],
        ]

    # proportional fallback
    if category == 'upper_body':
        x0,x1,y0,y1 = int(pw*.08),int(ph*.92),int(ph*.14),int(ph*.62)
    elif category == 'lower_body':
        x0,x1,y0,y1 = int(pw*.12),int(pw*.88),int(ph*.48),int(ph*.96)
    else:
        x0,x1,y0,y1 = int(pw*.08),int(pw*.92),int(ph*.12),int(ph*.96)
    cx = (x0+x1)//2
    my = (y0+y1)//2
    return [[x0,y0],[x1,y0],[x0,my],[x1,my],[x0,y1],[x1,y1],
            [cx,y0],[cx,my],[cx,y1]]


# ── TPS warp ──────────────────────────────────────────────────────

def _tps_warp_garment(gar_np: 'np.ndarray', gar_kp: list, body_kp: list,
                      out_h: int, out_w: int) -> 'np.ndarray':
    """
    Warp gar_np (H×W×4 RGBA) so that garment keypoints map to body keypoints
    using Thin Plate Spline interpolation (scipy RBFInterpolator).

    Uses inverse mapping (output coords → source coords) + cv2.remap
    for efficient full-resolution warping.

    Falls back to a simple resize+place when scipy/cv2 not available.
    """
    import numpy as np

    gkp = np.array(gar_kp,  dtype=np.float64)   # N×2  (x,y) on garment
    bkp = np.array(body_kp, dtype=np.float64)   # N×2  (x,y) on output

    gh, gw = gar_np.shape[:2]

    # Add boundary control points so TPS doesn't explode at corners
    bnd_gar = np.array([[0,0],[gw,0],[0,gh],[gw,gh],
                        [gw//2,0],[gw//2,gh],[0,gh//2],[gw,gh//2]], dtype=np.float64)
    bnd_out = np.array([[0,0],[out_w,0],[0,out_h],[out_w,out_h],
                        [out_w//2,0],[out_w//2,out_h],[0,out_h//2],[out_w,out_h//2]], dtype=np.float64)

    src = np.vstack([gkp,  bnd_gar])   # garment coords (what we sample from)
    dst = np.vstack([bkp,  bnd_out])   # output coords  (where we want each point)

    if not (SCIPY_AVAILABLE and CV2_AVAILABLE):
        # Simple resize fallback — no warp
        scaled = Image.fromarray(gar_np).resize((out_w, out_h), Image.LANCZOS)
        return np.array(scaled)

    # Build inverse mapping: output pixel → garment pixel
    rbf_x = RBFInterpolator(dst, src[:, 0], kernel='thin_plate_spline', smoothing=0.5)
    rbf_y = RBFInterpolator(dst, src[:, 1], kernel='thin_plate_spline', smoothing=0.5)

    # Sample on a coarse grid for speed, then upsample with linear interpolation
    step = 8
    ys_c = np.arange(0, out_h, step, dtype=np.float64)
    xs_c = np.arange(0, out_w, step, dtype=np.float64)
    xg, yg = np.meshgrid(xs_c, ys_c)
    query  = np.column_stack([xg.ravel(), yg.ravel()])

    map_x_c = rbf_x(query).reshape(len(ys_c), len(xs_c)).astype(np.float32)
    map_y_c = rbf_y(query).reshape(len(ys_c), len(xs_c)).astype(np.float32)

    map_x = cv2.resize(map_x_c, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    map_y = cv2.resize(map_y_c, (out_w, out_h), interpolation=cv2.INTER_LINEAR)

    warped = cv2.remap(gar_np.astype(np.float32), map_x, map_y,
                       interpolation=cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT,
                       borderValue=(0, 0, 0, 0))
    return warped   # float32 H×W×4


# ── LAB lighting transfer ─────────────────────────────────────────

def _match_lighting(gar_rgb: 'np.ndarray', person_np: 'np.ndarray',
                    gar_alpha: 'np.ndarray',
                    rx: int, ry: int, rw: int, rh: int) -> 'np.ndarray':
    """
    Adjust the garment's LAB lightness channel so it matches the
    average scene lighting in the target clothing region of the person.
    This eliminates the "studio vs outdoor" mismatch that makes overlays obvious.
    Only the L channel is adjusted (colour is preserved).
    """
    if not CV2_AVAILABLE:
        return gar_rgb

    import numpy as np
    try:
        # Convert to LAB (uint8 required for cv2.cvtColor)
        gar_u8   = np.clip(gar_rgb, 0, 255).astype(np.uint8)
        gar_lab  = cv2.cvtColor(gar_u8, cv2.COLOR_RGB2LAB).astype(np.float32)

        person_u8  = np.clip(person_np, 0, 255).astype(np.uint8)
        person_lab = cv2.cvtColor(person_u8, cv2.COLOR_RGB2LAB).astype(np.float32)

        # Mean L in the body region (person's scene lighting)
        ph_h, ph_w = person_np.shape[:2]
        ry2 = min(ry+rh, ph_h); rx2 = min(rx+rw, ph_w)
        scene_L = person_lab[ry:ry2, rx:rx2, 0].mean()

        # Mean L of the garment (where alpha > 0.3)
        strong = gar_alpha > 0.3
        if not strong.any():
            return gar_rgb
        gar_mean_L = gar_lab[:, :, 0][strong].mean()

        # Shift garment L toward scene L (30 % strength — keep garment colour)
        shift = (scene_L - gar_mean_L) * 0.30
        gar_lab[:, :, 0] = np.clip(gar_lab[:, :, 0] + shift, 0, 255)

        adjusted = cv2.cvtColor(gar_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
        return adjusted.astype(np.float32)
    except Exception as e:
        logger.warning(f'dress-swap: lighting match failed ({e})')
        return gar_rgb


# ── Existing-clothing removal ─────────────────────────────────────

def _sample_skin_color(person_np: 'np.ndarray',
                        rx: int, ry: int, rw: int, rh: int,
                        body_mask: 'np.ndarray | None') -> 'np.ndarray':
    """
    Sample the dominant skin colour from exposed skin areas around the clothing region.
    Tries (in order): face/neck strip above region, left/right arm columns, legs below region.
    Falls back to a neutral mid-tone if nothing useful is found.
    Returns a float32 RGB array of shape (3,).
    """
    import numpy as np
    ph_h, ph_w = person_np.shape[:2]
    samples = []

    def _collect(strip):
        if strip.size < 9:
            return
        pixels = strip.reshape(-1, 3).astype(np.float32)
        # Remove very dark (<30) and very bright (>230) pixels and unsaturated greys
        r, g, b = pixels[:, 0], pixels[:, 1], pixels[:, 2]
        brightness = (r + g + b) / 3.0
        saturation = np.max(pixels, axis=1) - np.min(pixels, axis=1)
        skin_like = (brightness > 50) & (brightness < 220) & (saturation > 8) & (r > g) & (r > b)
        if skin_like.sum() > 5:
            samples.append(pixels[skin_like])

    # 1) Neck / face strip — rows above the clothing rect
    neck_h = max(10, int(ph_h * 0.08))
    neck_y1 = max(0, ry - neck_h)
    if neck_y1 < ry:
        _collect(person_np[neck_y1:ry, rx:min(rx + rw, ph_w)])

    # 2) Left arm column — to the left of the clothing rect
    arm_w = max(10, int(ph_w * 0.08))
    if rx > arm_w:
        _collect(person_np[ry:min(ry + rh, ph_h), rx - arm_w:rx])

    # 3) Right arm column — to the right of the clothing rect
    rx2 = min(rx + rw, ph_w)
    if rx2 + arm_w <= ph_w:
        _collect(person_np[ry:min(ry + rh, ph_h), rx2:rx2 + arm_w])

    # 4) Legs — rows below the clothing rect
    leg_h = max(10, int(ph_h * 0.08))
    ry2 = min(ry + rh, ph_h)
    if ry2 + leg_h <= ph_h:
        _collect(person_np[ry2:ry2 + leg_h, rx:min(rx + rw, ph_w)])

    if samples:
        all_samples = np.concatenate(samples, axis=0)
        skin_mean = all_samples.mean(axis=0)
        logger.info(f'dress-swap: skin sample from {int(all_samples.shape[0])} px → RGB {skin_mean.astype(int)}')
        return skin_mean.astype(np.float32)

    # Fallback: neutral warm skin tone
    logger.info('dress-swap: skin sample fallback to default tone')
    return np.array([195.0, 160.0, 130.0], dtype=np.float32)


def _remove_existing_clothing(person_np: 'np.ndarray',
                               rx: int, ry: int, rw: int, rh: int,
                               body_mask: 'np.ndarray | None',
                               pts: 'dict | None' = None) -> 'np.ndarray':
    """
    Erase existing clothing in two phases:

    Phase 1 — Skin-colour pre-fill
    ───────────────────────────────
    Sample the person's exposed skin tone (neck / arms / legs) and flood-fill
    the clothing region with that colour + mild Gaussian noise.  This gives
    cv2.inpaint a realistic reference right inside the region rather than forcing
    it to propagate all the way from the boundary — which fails silently on
    large regions.

    Phase 2 — Multi-scale inpainting for edge smoothing
    ──────────────────────────────────────────────────────
    Run cv2.inpaint at 1/4 scale with radius=25 on the pre-filled image so
    the boundary transitions are smooth, then upscale and soft-blend back.
    """
    if not CV2_AVAILABLE:
        return person_np

    import numpy as np
    try:
        ph_h, ph_w = person_np.shape[:2]
        ry2 = min(ry + rh, ph_h)
        rx2 = min(rx + rw, ph_w)

        # ── Build binary mask = body pixels inside clothing region ──
        mask = np.zeros((ph_h, ph_w), dtype=np.uint8)
        mask[ry:ry2, rx:rx2] = 255
        if body_mask is not None:
            body_u8 = (np.clip(body_mask, 0, 1) * 255).astype(np.uint8)
            mask = cv2.bitwise_and(mask, body_u8)

        # ── Face-protection clamp ──────────────────────────────────
        face_bottom = 0
        if pts is not None and 'nose' in pts:
            nose_y      = pts['nose'][1]
            face_bottom = nose_y + int(ph_h * 0.10)
        elif body_mask is not None:
            body_rows = np.where(np.any(body_mask > 0.2, axis=1))[0]
            if len(body_rows) >= 2:
                body_top    = int(body_rows[0])
                body_h      = int(body_rows[-1]) - body_top
                face_bottom = body_top + int(body_h * 0.15)
        if face_bottom > 0:
            mask[:face_bottom, :] = 0
            logger.info(f'dress-swap: face-protect clamp — cleared rows 0..{face_bottom}')

        # ── Skin-pixel exclusion ───────────────────────────────────
        # Pixels already matching the person's skin tone are EXPOSED SKIN
        # (forearms, hands, bare legs) — do NOT paint over them.
        # Sample skin from areas outside the clothing rectangle (neck/arms/legs edges).
        skin_ref = _sample_skin_color(person_np, rx, ry, rw, rh, body_mask)

        region_pixels = person_np.astype(np.float32)
        # Euclidean distance from each pixel to the sampled skin colour (per-channel)
        skin_diff = np.sqrt(np.sum((region_pixels - skin_ref) ** 2, axis=2))

        # Also accept pixels that are skin-like by hue: reddish/yellowish, not too dark/bright
        r_ch = region_pixels[:, :, 0]
        g_ch = region_pixels[:, :, 1]
        b_ch = region_pixels[:, :, 2]
        brightness  = (r_ch + g_ch + b_ch) / 3.0
        saturation  = np.max(region_pixels, axis=2) - np.min(region_pixels, axis=2)
        skin_hue_ok = (brightness > 60) & (brightness < 230) & (saturation > 8) & (r_ch >= g_ch) & (r_ch >= b_ch)

        # A pixel is "already skin" if it's close in colour to the reference AND has skin hue
        already_skin = ((skin_diff < 55) & skin_hue_ok).astype(np.uint8) * 255

        # Dilate skin mask slightly so clothing right next to skin edge is still erased
        k_dil = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        already_skin_dilated = cv2.dilate(already_skin, k_dil)

        # Remove exposed-skin pixels from the erase mask
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(already_skin_dilated))

        excluded_px = int((already_skin_dilated > 0).sum())
        logger.info(f'dress-swap: skin-exclusion removed {excluded_px} px (arms/hands/legs)')




        # Erode slightly so a thin ring of original pixels remains for blending
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (4, 4))
        mask_eroded = cv2.erode(mask, k)

        if mask_eroded.sum() == 0:
            logger.warning('dress-swap: eroded mask empty')
            return person_np

        covered = int(mask_eroded.sum() // 255)
        logger.info(f'dress-swap: erasing {covered} px² in clothing region…')

        # ── Phase 1: pre-fill with sampled skin colour ──
        skin_color = _sample_skin_color(person_np, rx, ry, rw, rh, body_mask)
        rng        = np.random.default_rng(42)
        pre_filled = person_np.copy().astype(np.float32)
        mask_bool  = mask_eroded > 0

        # Noise: stronger near centre (high-frequency texture removed), softer at edge
        # Use distance-transform to modulate noise magnitude
        dist = cv2.distanceTransform(mask_eroded, cv2.DIST_L2, 5).astype(np.float32)
        max_dist = dist.max() if dist.max() > 0 else 1.0
        noise_scale = 12.0 * (dist / max_dist)  # 0 at edge → 12 at centre

        for c in range(3):
            channel = pre_filled[:, :, c]
            noise   = rng.normal(0, 1, channel.shape).astype(np.float32) * noise_scale
            channel[mask_bool] = np.clip(skin_color[c] + noise[mask_bool], 0, 255)
            pre_filled[:, :, c] = channel

        # ── Phase 2: inpainting at 1/4 scale on the pre-filled image ──
        # At 1/4 scale the boundary ring pixels are close to the centre,
        # so TELEA can smooth transitions without needing to propagate far.
        SCALE = 0.25
        sw = max(8, int(ph_w * SCALE))
        sh = max(8, int(ph_h * SCALE))

        small_pre  = cv2.resize(pre_filled.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_AREA)
        small_mask = cv2.resize(mask_eroded, (sw, sh), interpolation=cv2.INTER_NEAREST)
        _, small_mask = cv2.threshold(small_mask, 30, 255, cv2.THRESH_BINARY)

        # Only inpaint the thin boundary ring at this scale (inner pixels already look fine)
        k_inner    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (8, 8))
        inner_mask = cv2.erode(small_mask, k_inner)
        ring_mask  = cv2.subtract(small_mask, inner_mask)   # just the boundary ring

        small_bgr       = cv2.cvtColor(small_pre, cv2.COLOR_RGB2BGR)
        inpainted_small = cv2.inpaint(small_bgr, ring_mask, inpaintRadius=25, flags=cv2.INPAINT_TELEA)
        inpainted_small = cv2.cvtColor(inpainted_small, cv2.COLOR_BGR2RGB)

        # Upsample smoothed result and blend with the pre-filled version
        filled_ring = cv2.resize(inpainted_small, (ph_w, ph_h), interpolation=cv2.INTER_LINEAR)
        filled_ring = cv2.GaussianBlur(filled_ring, (21, 21), 8)

        # In the centre: pure skin pre-fill; at boundary: inpaint-smoothed
        dist_norm  = np.clip(dist / max(max_dist, 1.0), 0.0, 1.0)
        centre_w   = dist_norm                       # 0 at edge, 1 at centre
        ring_w     = 1.0 - centre_w                  # 1 at edge, 0 at centre
        centre_w3  = np.stack([centre_w] * 3, axis=-1)
        ring_w3    = np.stack([ring_w]   * 3, axis=-1)

        filled = (pre_filled * centre_w3 + filled_ring.astype(np.float32) * ring_w3)

        # Soft-blend filled region back onto original (keeps a thin original ring at boundary)
        alpha_f = mask_eroded.astype(np.float32) / 255.0
        alpha_f = cv2.GaussianBlur(alpha_f, (21, 21), 8)
        alpha3  = np.stack([alpha_f] * 3, axis=-1)
        result  = filled * alpha3 + person_np.astype(np.float32) * (1.0 - alpha3)

        logger.info('dress-swap: existing clothes erased ✓')
        return np.clip(result, 0, 255).astype(np.uint8)

    except Exception as e:
        logger.warning(f'dress-swap: clothing removal failed ({e})')
        return person_np


# ── Main local engine ─────────────────────────────────────────────

def _local_cloth_swap(person_bytes: bytes, garment_bytes: bytes, category: str) -> bytes:
    """
    Full cloth-swap — unlimited, no token, no external API.

    3-zone composite model
    ──────────────────────
    Zone 1  garment footprint   → new garment (100 % opaque at core, feathered edge)
    Zone 2  old-clothes region  → skin colour fill  (covers sleeves, torso, etc.
                                  that the new garment doesn't reach)
    Zone 3  everything else     → original person unchanged (face, hands, bg)
    """
    import numpy as np

    person_img  = Image.open(io.BytesIO(person_bytes)).convert('RGB')
    pw, ph      = person_img.size
    person_np   = np.array(person_img)
    original_np = person_np.copy()          # never mutated — always the clean original
    logger.info(f'dress-swap local: person={pw}x{ph} category={category}')

    body_mask = _extract_body_mask(person_bytes, person_img)
    logger.info(f'dress-swap local: body_mask={"✓" if body_mask is not None else "unavailable"}')

    pts = _pose_landmarks(person_np)

    rx, ry, rw, rh, _ = _clothing_region(pts, pw, ph, category)
    if rw < 20 or rh < 20:
        rx, ry, rw, rh, _ = _clothing_region(None, pw, ph, category)
    logger.info(f'dress-swap local: region x={rx} y={ry} w={rw} h={rh}')

    # ── Zone-2 mask: body pixels inside the clothing rectangle ──────
    # This is the FULL area where old clothes live.  Skin fill is applied
    # here so that sleeves / torso areas not covered by the new garment
    # show skin instead of the original clothing.
    ry2_c = min(ry + rh, ph);  rx2_c = min(rx + rw, pw)
    clothing_mask = np.zeros((ph, pw), dtype=np.float32)
    clothing_mask[ry:ry2_c, rx:rx2_c] = 1.0
    if body_mask is not None:
        clothing_mask *= (body_mask > 0.3).astype(np.float32)

    # Face-protection: never treat face pixels as "clothing"
    face_bottom = 0
    if pts is not None and 'nose' in pts:
        face_bottom = pts['nose'][1] + int(ph * 0.10)
    elif body_mask is not None:
        br = np.where(np.any(body_mask > 0.2, axis=1))[0]
        if len(br) >= 2:
            face_bottom = int(br[0]) + int((int(br[-1]) - int(br[0])) * 0.15)
    if face_bottom > 0:
        clothing_mask[:face_bottom, :] = 0.0

    # Smooth clothing_mask edges so the skin-fill blends naturally
    if CV2_AVAILABLE:
        # Exclude pixels that are already skin-colored (arms, bare legs, hands)
        # so we don't paint skin-fill over already-exposed skin areas
        skin_ref_cm = _sample_skin_color(person_np, rx, ry, rw, rh, body_mask)
        pf = person_np.astype(np.float32)
        skin_diff_cm = np.sqrt(np.sum((pf - skin_ref_cm) ** 2, axis=2))
        r_cm = pf[:,:,0]; g_cm = pf[:,:,1]; b_cm = pf[:,:,2]
        bright_cm = (r_cm + g_cm + b_cm) / 3.0
        sat_cm    = np.max(pf, axis=2) - np.min(pf, axis=2)
        skin_ok_cm = ((bright_cm > 60) & (bright_cm < 230) & (sat_cm > 8)
                      & (r_cm >= g_cm) & (r_cm >= b_cm)).astype(np.float32)
        already_skin_cm = ((skin_diff_cm < 55) * skin_ok_cm).astype(np.uint8)
        k_dil_cm = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        already_skin_cm = cv2.dilate(already_skin_cm, k_dil_cm).astype(np.float32)
        clothing_mask = clothing_mask * (1.0 - already_skin_cm)
        clothing_mask = cv2.GaussianBlur(clothing_mask, (15, 15), 5)
    logger.info(f'dress-swap local: clothing_mask coverage = {int((clothing_mask > 0.1).sum())} px')

    # ── Skin-fill layer (Zone 2 base) ───────────────────────────────
    # person_np_erased = original person with skin colour in the clothing region.
    # Outside the clothing region it is identical to original_np.
    person_np_erased = _remove_existing_clothing(person_np, rx, ry, rw, rh, body_mask, pts)

    # skin_base: skin where old clothes were, original person everywhere else
    cm3      = np.stack([clothing_mask] * 3, axis=-1)
    skin_base = (person_np_erased.astype(np.float32) * cm3
                 + original_np.astype(np.float32)    * (1.0 - cm3))

    # ── Garment warp ────────────────────────────────────────────────
    garment_rgba = _clean_garment(garment_bytes)
    gar_np       = np.array(garment_rgba)
    logger.info(f'dress-swap local: garment size={garment_rgba.size}')

    gar_kp  = _garment_keypoints(gar_np)
    body_kp = _body_keypoints(pts, pw, ph, category)

    warped    = _tps_warp_garment(gar_np, gar_kp, body_kp, ph, pw)
    gar_rgb   = warped[:, :, :3].astype(np.float32)
    gar_alpha = warped[:, :, 3].astype(np.float32) / 255.0
    logger.info('dress-swap local: TPS warp done')

    # Clip garment to body silhouette (don't paint garment on background)
    if body_mask is not None:
        gar_alpha = gar_alpha * (body_mask > 0.3).astype(np.float32)

    # ── Garment alpha: binary core + thin feathered edge ─────────────
    # Use a SMALL erode (4 px) so even compact garments keep their core.
    # The goal is zero background bleed at the core while keeping natural edges.
    if CV2_AVAILABLE:
        garment_bin = (gar_alpha > 0.12).astype(np.uint8)
        covered_px  = int(garment_bin.sum())
        logger.info(f'dress-swap local: garment footprint = {covered_px} px')

        if covered_px < 500:
            # Warp produced almost nothing — fall back to simple resize+centre
            logger.warning('dress-swap local: warp too small, using resize fallback')
            garment_resized = garment_rgba.resize((rw, rh), Image.LANCZOS)
            canvas_rgba = Image.new('RGBA', (pw, ph), (0, 0, 0, 0))
            canvas_rgba.paste(garment_resized, (rx, ry))
            gar_arr   = np.array(canvas_rgba)
            gar_rgb   = gar_arr[:, :, :3].astype(np.float32)
            gar_alpha = gar_arr[:, :, 3].astype(np.float32) / 255.0
            if body_mask is not None:
                gar_alpha = gar_alpha * (body_mask > 0.3).astype(np.float32)
            garment_bin = (gar_alpha > 0.12).astype(np.uint8)

        # Small erode (4 px) → tight core, still large for compact garments
        k_core    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (4, 4))
        core      = cv2.erode(garment_bin, k_core).astype(np.float32)
        edge_ring = garment_bin.astype(np.float32) - core
        edge_soft = cv2.GaussianBlur(edge_ring, (9, 9), 3)
        gar_mask  = np.clip(core + edge_soft, 0.0, 1.0)
        logger.info(f'dress-swap local: core={int(core.sum())} px  edge={int(edge_ring.sum())} px')
    else:
        gar_mask = (gar_alpha > 0.12).astype(np.float32)

    gar_rgb = _match_lighting(gar_rgb, original_np, gar_mask, rx, ry, rw, rh)

    # ── 3-zone final composite ───────────────────────────────────────
    # Zone 1 (garment):       gar_rgb  * gar_mask
    # Zone 2 (skin):          skin_base * (1 − gar_mask)   ← skin where garment doesn't reach
    # Zone 3 (original) is already baked into skin_base outside clothing_mask
    a3        = np.stack([gar_mask] * 3, axis=-1)
    result_np = gar_rgb * a3 + skin_base * (1.0 - a3)

    result = Image.fromarray(np.clip(result_np, 0, 255).astype(np.uint8))
    result = result.filter(ImageFilter.UnsharpMask(radius=1.5, percent=180, threshold=2))

    buf = io.BytesIO()
    result.save(buf, format='PNG', optimize=False, compress_level=0)
    buf.seek(0)
    return buf.read()


# ── HuggingFace Space helpers (bonus quality) ─────────────────────

def _make_gradio_client(space_id: str):
    tok = os.environ.get('HF_TOKEN', '')
    return GradioClient(space_id, hf_token=tok) if tok else GradioClient(space_id)


def _hf_idmvton_raw(person_path, garment_path, description, steps) -> bytes:
    c = _make_gradio_client("yisol/IDM-VTON")
    r = c.predict(
        dict={"background": gradio_handle_file(person_path), "layers": [], "composite": None},
        garm_img=gradio_handle_file(garment_path),
        garment_des=description or "clothing item",
        is_checked=True, is_checked_crop=False, denoise_steps=steps, seed=42,
        api_name="/tryon"
    )
    rp = r[0] if isinstance(r, (list, tuple)) else r
    with open(rp, 'rb') as f: return f.read()


def _hf_nymbo_raw(person_path, garment_path, description, steps) -> bytes:
    c = _make_gradio_client("Nymbo/Virtual-Try-On")
    r = c.predict(
        dict={"background": gradio_handle_file(person_path), "layers": [], "composite": None},
        garm_img=gradio_handle_file(garment_path),
        garment_des=description or "clothing item",
        is_checked=True, is_checked_crop=False, denoise_steps=steps, seed=42,
        api_name="/tryon"
    )
    rp = r[0] if isinstance(r, (list, tuple)) else r
    with open(rp, 'rb') as f: return f.read()


def _try_hf_spaces(person_bytes, garment_bytes, description, steps) -> bytes:
    """Attempt HF AI spaces; raises RuntimeError if all fail."""
    import tempfile, os as _os
    orig_w, orig_h = Image.open(io.BytesIO(person_bytes)).convert('RGB').size
    pp = _prepare_image_for_vton(person_bytes)
    gp = _prepare_image_for_vton(garment_bytes)

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as pf:
        pf.write(pp); person_path = pf.name
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as gf:
        gf.write(gp); garment_path = gf.name

    errs = []
    try:
        for name, fn in [
            ('yisol/IDM-VTON',       lambda: _hf_idmvton_raw(person_path, garment_path, description, steps)),
            ('Nymbo/Virtual-Try-On', lambda: _hf_nymbo_raw(person_path, garment_path, description, steps)),
        ]:
            try:
                logger.info(f'dress-swap: trying HF {name}')
                raw = fn()
                return _finalise_vton_result(raw, orig_w, orig_h)
            except Exception as e:
                errs.append(f'{name}: {e}')
                logger.warning(f'dress-swap: {name} failed — {e}')
        raise RuntimeError(' | '.join(errs))
    finally:
        for p in (person_path, garment_path):
            try: _os.unlink(p)
            except Exception: pass


# ── Route ─────────────────────────────────────────────────────────

@app.route('/api/ai/dress-swap', methods=['POST'])
def api_dress_swap():
    if 'person' not in request.files or 'garment' not in request.files:
        return jsonify({'error': 'Both person and garment images are required'}), 400

    person_bytes  = request.files['person'].read()
    garment_bytes = request.files['garment'].read()
    category      = request.form.get('category', 'upper_body')
    description   = request.form.get('description', '')
    quality       = request.form.get('quality', 'high')
    steps         = 40 if quality == 'high' else 30

    # ── 1. HF AI spaces (best quality, free, quota-limited) ──────
    if GRADIO_CLIENT_AVAILABLE:
        try:
            result = _try_hf_spaces(person_bytes, garment_bytes, description, steps)
            buf = io.BytesIO(result); buf.seek(0)
            return send_file(buf, mimetype='image/png', as_attachment=True,
                             download_name='dress_swap_result.png')
        except Exception as e:
            logger.warning(f'HF spaces unavailable ({e}) — falling back to local engine')

    # ── 2. Replicate (optional paid, REPLICATE_API_TOKEN) ────────
    replicate_token = os.environ.get('REPLICATE_API_TOKEN', '')
    if replicate_token:
        try:
            import replicate as _rep, base64 as _b64, urllib.request as _ureq
            orig_w, orig_h = Image.open(io.BytesIO(person_bytes)).size
            pb64 = 'data:image/png;base64,' + _b64.b64encode(_prepare_image_for_vton(person_bytes)).decode()
            gb64 = 'data:image/png;base64,' + _b64.b64encode(_prepare_image_for_vton(garment_bytes)).decode()
            out  = _rep.Client(api_token=replicate_token).run(
                "cuuupid/idm-vton:c871bb9b046607b680449ecbae55fd8c6d945e0a1948644bf2361b3d021d3ff4",
                input={"human_img": pb64, "garm_img": gb64,
                       "garment_des": description or "clothing item",
                       "is_checked": True, "is_checked_crop": False,
                       "denoise_steps": steps, "seed": 42, "category": category}
            )
            url = str(out) if isinstance(out, str) else out.url
            with _ureq.urlopen(url) as resp: raw = resp.read()
            result = _finalise_vton_result(raw, orig_w, orig_h)
            buf = io.BytesIO(result); buf.seek(0)
            return send_file(buf, mimetype='image/png', as_attachment=True,
                             download_name='dress_swap_result.png')
        except Exception as e:
            logger.warning(f'Replicate failed ({e}) — using local engine')

    # ── 3. Local engine — UNLIMITED, no token, always works ──────
    try:
        logger.info('dress-swap: using local engine (unlimited)')
        result = _local_cloth_swap(person_bytes, garment_bytes, category)
        buf = io.BytesIO(result); buf.seek(0)
        return send_file(buf, mimetype='image/png', as_attachment=True,
                         download_name='dress_swap_result.png')
    except Exception as e:
        logger.exception('dress-swap: local engine failed')
        return jsonify({'error': str(e)}), 500


import base64, json as _json

# ── PDF Editor — render pages as images ──────────────────────────
@app.route('/api/pdf-editor/preview', methods=['POST'])
def api_pdf_editor_preview():
    if not FITZ_AVAILABLE:
        return jsonify({'error': 'PyMuPDF not installed'}), 500
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f        = request.files['file']
    password = request.form.get('password', '')
    try:
        data = f.read()
        doc  = fitz.open(stream=data, filetype='pdf')

        if doc.is_encrypted:
            # Try to authenticate — empty string first, then user-supplied
            ok = doc.authenticate(password)
            if not ok:
                return jsonify({'error': 'password_required', 'needs_password': True}), 401

        pages = []
        for i, page in enumerate(doc):
            mat = fitz.Matrix(1.5, 1.5)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            b64 = base64.b64encode(pix.tobytes('png')).decode()
            pages.append({
                'index':    i,
                'width_pt':  page.rect.width,
                'height_pt': page.rect.height,
                'img':       b64,
            })
        return jsonify({'page_count': len(pages), 'pages': pages})
    except Exception as e:
        logger.exception('pdf-editor/preview error')
        return jsonify({'error': str(e)}), 500


# ── PDF Editor — apply annotations and return filled PDF ─────────
@app.route('/api/pdf-editor/save', methods=['POST'])
def api_pdf_editor_save():
    if not FITZ_AVAILABLE:
        return jsonify({'error': 'PyMuPDF not installed'}), 500
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f        = request.files['file']
    password = request.form.get('password', '')
    try:
        annotations = _json.loads(request.form.get('annotations', '[]'))
    except Exception:
        return jsonify({'error': 'Invalid annotations JSON'}), 400
    try:
        doc = fitz.open(stream=f.read(), filetype='pdf')

        if doc.is_encrypted:
            ok = doc.authenticate(password)
            if not ok:
                return jsonify({'error': 'password_required', 'needs_password': True}), 401

        for ann in annotations:
            page_idx = int(ann.get('page', 0))
            if page_idx < 0 or page_idx >= len(doc):
                continue
            page = doc[page_idx]
            pw, ph = page.rect.width, page.rect.height
            x = float(ann.get('x_pct', 0)) * pw
            y = float(ann.get('y_pct', 0)) * ph

            if ann.get('type') == 'text':
                text = ann.get('text', '').strip()
                if not text:
                    continue
                font_size = float(ann.get('font_size', 12))
                hex_col   = ann.get('color', '#000000').lstrip('#')
                r = int(hex_col[0:2], 16) / 255
                g = int(hex_col[2:4], 16) / 255
                b = int(hex_col[4:6], 16) / 255
                page.insert_text(fitz.Point(x, y), text,
                                 fontsize=font_size, color=(r, g, b))

            elif ann.get('type') == 'signature':
                img_data = ann.get('img_data', '')
                if ',' in img_data:
                    img_data = img_data.split(',', 1)[1]
                img_bytes = base64.b64decode(img_data)
                sig_w = float(ann.get('width_pct',  0.25)) * pw
                sig_h = float(ann.get('height_pct', 0.08)) * ph
                page.insert_image(fitz.Rect(x, y, x + sig_w, y + sig_h),
                                  stream=img_bytes)

            elif ann.get('type') == 'checkbox':
                if ann.get('checked', False):
                    size = float(ann.get('size', 22)) * (pw / 900)
                    size = max(8, min(40, size))
                    p1 = fitz.Point(x,               y + size * 0.50)
                    p2 = fitz.Point(x + size * 0.38, y + size * 0.90)
                    p3 = fitz.Point(x + size,        y + size * 0.10)
                    lw = max(1.0, size * 0.13)
                    page.draw_line(p1, p2, color=(0, 0.35, 0.75), width=lw)
                    page.draw_line(p2, p3, color=(0, 0.35, 0.75), width=lw)

        buf = io.BytesIO()
        # Save without encryption so the filled PDF is freely usable
        doc.save(buf, encryption=fitz.PDF_ENCRYPT_NONE)
        buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}_filled.pdf')
    except Exception as e:
        logger.exception('pdf-editor/save error')
        return jsonify({'error': str(e)}), 500



# ══════════════════════════════════════════════════════════════════
#  CLOTH SWAP DEBUG / TEST ROUTES  (step-by-step visual testing)
#  Frontend: /swap-test
# ══════════════════════════════════════════════════════════════════

@app.route('/swap-test')
def swap_test_page():
    return render_template('swap_test.html')


@app.route('/api/swap-test/step1-extract-human', methods=['POST'])
def swap_test_step1():
    """Step 1: Extract human silhouette using rembg u2net_human_seg.
    Returns the person PNG with transparent background."""
    if 'person' not in request.files:
        return jsonify({'error': 'No person image uploaded'}), 400
    person_bytes = request.files['person'].read()
    try:
        import numpy as np
        person_img = Image.open(io.BytesIO(person_bytes)).convert('RGB')
        pw, ph = person_img.size

        if not REMBG_AVAILABLE:
            return jsonify({'error': 'rembg not installed'}), 500

        from rembg import new_session
        session   = new_session('u2net_human_seg')
        rgba_bytes = rembg_remove(person_bytes, session=session)

        # Also return the body mask as a greyscale for visual inspection
        rgba_img  = Image.open(io.BytesIO(rgba_bytes)).convert('RGBA')
        if rgba_img.size != (pw, ph):
            rgba_img = rgba_img.resize((pw, ph), Image.LANCZOS)

        mask_arr  = np.array(rgba_img)[:, :, 3]           # alpha = body mask
        mask_img  = Image.fromarray(mask_arr, mode='L')    # greyscale mask

        # Encode both as base64 for JSON response
        import base64
        buf_rgba = io.BytesIO(); rgba_img.save(buf_rgba, format='PNG'); buf_rgba.seek(0)
        buf_mask = io.BytesIO(); mask_img.save(buf_mask, format='PNG'); buf_mask.seek(0)

        coverage = float(np.mean(mask_arr > 30) * 100)

        return jsonify({
            'ok': True,
            'size': [pw, ph],
            'body_coverage_pct': round(coverage, 1),
            'rgba_png': 'data:image/png;base64,' + base64.b64encode(buf_rgba.read()).decode(),
            'mask_png': 'data:image/png;base64,' + base64.b64encode(buf_mask.read()).decode(),
        })
    except Exception as e:
        logger.exception('swap-test step1 error')
        return jsonify({'error': str(e)}), 500


@app.route('/api/swap-test/step2-extract-garment', methods=['POST'])
def swap_test_step2():
    """Step 2: Extract garment with transparent background using rembg."""
    if 'garment' not in request.files:
        return jsonify({'error': 'No garment image uploaded'}), 400
    garment_bytes = request.files['garment'].read()
    try:
        import numpy as np, base64
        garment_img = Image.open(io.BytesIO(garment_bytes)).convert('RGB')
        gw, gh = garment_img.size

        garment_rgba = _clean_garment(garment_bytes)
        alpha_arr    = np.array(garment_rgba)[:, :, 3]
        coverage     = float(np.mean(alpha_arr > 30) * 100)

        # Detect garment keypoints
        gar_np  = np.array(garment_rgba)
        gar_kp  = _garment_keypoints(gar_np)

        # Draw keypoints on a preview
        preview = garment_rgba.copy().convert('RGBA')
        draw    = ImageDraw.Draw(preview)
        kp_labels = ['L-shoulder','R-shoulder','L-waist','R-waist',
                     'L-hem','R-hem','top-c','mid-c','bot-c']
        colors = [(255,0,0),(0,200,0),(255,165,0),(0,0,255),
                  (255,0,255),(0,255,255),(200,200,0),(255,128,0),(128,0,255)]
        for i, (kp, lbl, col) in enumerate(zip(gar_kp, kp_labels, colors)):
            x, y = int(kp[0]), int(kp[1])
            draw.ellipse([x-8,y-8,x+8,y+8], fill=col+(220,))
            draw.text((x+10, y-8), lbl, fill=(255,255,255,230))

        buf = io.BytesIO(); preview.save(buf, format='PNG'); buf.seek(0)
        buf2 = io.BytesIO(); garment_rgba.save(buf2, format='PNG'); buf2.seek(0)

        return jsonify({
            'ok': True,
            'size': [gw, gh],
            'garment_coverage_pct': round(coverage, 1),
            'keypoints': gar_kp,
            'garment_png': 'data:image/png;base64,' + base64.b64encode(buf2.read()).decode(),
            'preview_png': 'data:image/png;base64,' + base64.b64encode(buf.read()).decode(),
        })
    except Exception as e:
        logger.exception('swap-test step2 error')
        return jsonify({'error': str(e)}), 500


@app.route('/api/swap-test/step3-detect-pose', methods=['POST'])
def swap_test_step3():
    """Step 3: Detect body pose + clothing region on person photo."""
    if 'person' not in request.files:
        return jsonify({'error': 'No person image uploaded'}), 400
    person_bytes = request.files['person'].read()
    category     = request.form.get('category', 'dresses')
    try:
        import numpy as np, base64
        person_img = Image.open(io.BytesIO(person_bytes)).convert('RGB')
        pw, ph     = person_img.size
        person_np  = np.array(person_img)

        # Get body mask
        body_mask = _extract_body_mask(person_bytes, person_img)

        # Get pose landmarks
        pts = _pose_landmarks(person_np)

        # Get clothing region
        rx, ry, rw, rh, sw = _clothing_region(pts, pw, ph, category)

        # ── Apply face-protection clamp (mirrors _remove_existing_clothing) ──
        # Use nose landmark → chin buffer so the red box never covers the face.
        face_bottom_preview = 0
        if pts is not None and 'nose' in pts:
            face_bottom_preview = pts['nose'][1] + int(ph * 0.10)
        elif body_mask is not None:
            body_rows_p = np.where(np.any(body_mask > 0.2, axis=1))[0]
            if len(body_rows_p) >= 2:
                face_bottom_preview = int(body_rows_p[0]) + int((int(body_rows_p[-1]) - int(body_rows_p[0])) * 0.15)
        if face_bottom_preview > 0 and ry < face_bottom_preview:
            clipped_h = rh - (face_bottom_preview - ry)
            ry = face_bottom_preview
            rh = max(10, clipped_h)

        # Get body keypoints
        body_kp = _body_keypoints(pts, pw, ph, category)

        # Draw on preview
        preview = person_img.copy().convert('RGBA')
        ov      = Image.new('RGBA', preview.size, (0,0,0,0))
        draw    = ImageDraw.Draw(ov)

        # Draw inpaint region (what will be erased)
        draw.rectangle([rx,ry,rx+rw,ry+rh], outline=(255,50,50,230), width=3)
        ov_arr = np.array(ov)
        inpaint_fill = np.zeros_like(ov_arr)
        ry2,rx2 = min(ry+rh,ph), min(rx+rw,pw)
        inpaint_fill[ry:ry2,rx:rx2] = [255,50,50,60]
        if body_mask is not None:
            bm = (body_mask*60).astype(np.uint8)
            inpaint_fill[ry:ry2,rx:rx2,3] = np.minimum(
                inpaint_fill[ry:ry2,rx:rx2,3],
                (body_mask[ry:ry2,rx:rx2]*60).astype(np.uint8))
        ov2 = Image.fromarray(inpaint_fill, 'RGBA')
        preview = Image.alpha_composite(preview, ov2)
        preview = Image.alpha_composite(preview, ov)
        draw2 = ImageDraw.Draw(preview)

        # Draw body keypoints
        kp_labels = ['L-sh','R-sh','L-w','R-w','L-hem','R-hem','top-c','mid-c','bot-c']
        for i, (kp, lbl) in enumerate(zip(body_kp, kp_labels)):
            x, y = int(kp[0]), int(kp[1])
            draw2.ellipse([x-10,y-10,x+10,y+10], fill=(0,220,255,220))
            draw2.text((x+12, y-10), lbl, fill=(255,255,100,255))

        # Draw mediapipe raw landmarks if available
        if pts:
            for name, (lx,ly) in pts.items():
                draw2.ellipse([lx-5,ly-5,lx+5,ly+5], fill=(0,255,0,180))

        buf = io.BytesIO(); preview.convert('RGB').save(buf, format='JPEG', quality=90)
        buf.seek(0)

        return jsonify({
            'ok': True,
            'size': [pw, ph],
            'category': category,
            'region': {'x': rx, 'y': ry, 'w': rw, 'h': rh},
            'shoulder_px': sw,
            'pose_detected': pts is not None,
            'body_mask_ok': body_mask is not None,
            'body_keypoints': body_kp,
            'preview_jpg': 'data:image/jpeg;base64,' + base64.b64encode(buf.read()).decode(),
        })
    except Exception as e:
        logger.exception('swap-test step3 error')
        return jsonify({'error': str(e)}), 500


@app.route('/api/swap-test/step4-inpaint-clothes', methods=['POST'])
def swap_test_step4():
    """Step 4: Erase existing clothing via cv2.inpaint."""
    if 'person' not in request.files:
        return jsonify({'error': 'No person image uploaded'}), 400
    person_bytes = request.files['person'].read()
    category     = request.form.get('category', 'dresses')
    try:
        import numpy as np, base64
        person_img = Image.open(io.BytesIO(person_bytes)).convert('RGB')
        pw, ph     = person_img.size
        person_np  = np.array(person_img)

        body_mask   = _extract_body_mask(person_bytes, person_img)
        pts         = _pose_landmarks(person_np)
        rx,ry,rw,rh,_ = _clothing_region(pts, pw, ph, category)

        # Run inpainting
        cleaned_np  = _remove_existing_clothing(person_np, rx, ry, rw, rh, body_mask, pts)
        cleaned_img = Image.fromarray(cleaned_np.astype(np.uint8))

        # Side-by-side comparison
        comp = Image.new('RGB', (pw*2+4, ph), (40,40,40))
        comp.paste(person_img,  (0, 0))
        comp.paste(cleaned_img, (pw+4, 0))
        draw = ImageDraw.Draw(comp)
        draw.text((10,10),    'BEFORE (original)',  fill=(255,255,100))
        draw.text((pw+14,10), 'AFTER  (clothes erased)', fill=(100,255,100))

        buf = io.BytesIO(); comp.save(buf, format='JPEG', quality=92); buf.seek(0)
        buf2 = io.BytesIO(); cleaned_img.save(buf2, format='PNG'); buf2.seek(0)

        return jsonify({
            'ok': True,
            'region': {'x':rx,'y':ry,'w':rw,'h':rh},
            'inpainted_px': int(rw*rh),
            'comparison_jpg': 'data:image/jpeg;base64,' + base64.b64encode(buf.read()).decode(),
            'cleaned_png':    'data:image/png;base64,'  + base64.b64encode(buf2.read()).decode(),
        })
    except Exception as e:
        logger.exception('swap-test step4 error')
        return jsonify({'error': str(e)}), 500


@app.route('/api/swap-test/step5-full-swap', methods=['POST'])
def swap_test_step5():
    """Step 5: Run the complete local cloth-swap pipeline and return the final PNG."""
    if 'person' not in request.files or 'garment' not in request.files:
        return jsonify({'error': 'Both person and garment images are required'}), 400

    person_bytes  = request.files['person'].read()
    garment_bytes = request.files['garment'].read()
    category      = request.form.get('category', 'dresses')

    try:
        logger.info(f'swap-test step5: full local swap, category={category}')
        result_bytes = _local_cloth_swap(person_bytes, garment_bytes, category)
        buf = io.BytesIO(result_bytes)
        buf.seek(0)
        return send_file(buf, mimetype='image/png',
                         as_attachment=False,
                         download_name='swap_result.png')
    except Exception as e:
        logger.exception('swap-test step5 error')
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=False, host='0.0.0.0', port=port)
