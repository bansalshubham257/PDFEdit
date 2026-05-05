from flask import Flask, render_template, request, jsonify, send_file
from flask_compress import Compress
import os, io, logging, sys, uuid, tempfile, zipfile
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageFont, ImageOps

# ── PDF libraries ──────────────────────────────────────────────────────────
try:
    from pypdf import PdfReader, PdfWriter
    PYPDF_AVAILABLE = True
except Exception:
    PYPDF_AVAILABLE = False

try:
    import fitz          # PyMuPDF
    FITZ_AVAILABLE = True
except Exception:
    FITZ_AVAILABLE = False

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.colors import Color
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except Exception:
    PIKEPDF_AVAILABLE = False

try:
    import mammoth
    MAMMOTH_AVAILABLE = True
except Exception:
    MAMMOTH_AVAILABLE = False

try:
    from rembg import remove as rembg_remove
    REMBG_AVAILABLE = True
except Exception:
    REMBG_AVAILABLE = False
    rembg_remove = None

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except Exception:
    TESSERACT_AVAILABLE = False

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except Exception:
    CV2_AVAILABLE = False

try:
    from weasyprint import HTML as WeasyprintHTML
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False
    WeasyprintHTML = None

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB upload limit
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'imgtools-secret')
app.config['SITE_URL']   = os.environ.get('SITE_URL', 'https://editpdfform.com')

# ── Compression (gzip/brotli) ──────────────────────────────────────────────
app.config['COMPRESS_REGISTER'] = True
app.config['COMPRESS_LEVEL']    = 6          # gzip level (1-9), 6 is good balance
app.config['COMPRESS_MIN_SIZE'] = 500        # only compress responses > 500 bytes
app.config['COMPRESS_MIMETYPES'] = [
    'text/html', 'text/css', 'text/javascript',
    'application/javascript', 'application/json',
    'application/xml', 'text/xml', 'text/plain',
    'image/svg+xml',
]
Compress(app)

# ── Cache-Control for static assets ───────────────────────────────────────
@app.after_request
def set_response_headers(response):
    path = request.path
    # Long-lived cache for versioned static files (CSS/JS have ?v= cache-bust)
    if path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    # Short cache for HTML pages
    elif path in ('/', ) or path.startswith('/fill-pdf') or path.startswith('/edit-pdf') or path.startswith('/sign-pdf'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

import time as _time
_STATIC_VER = os.environ.get('STATIC_VERSION', str(int(_time.time())))

@app.context_processor
def inject_static_ver():
    return {'static_ver': _STATIC_VER, 'inline_css': _INLINE_CSS}

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
except Exception:
    PIL_AVAILABLE = False
    logger.warning("Pillow not available")

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:
    HEIF_AVAILABLE = False
    logger.warning("pillow-heif not available – HEIC conversion disabled")

try:
    import cairosvg
    CAIRO_AVAILABLE = True
except Exception:
    CAIRO_AVAILABLE = False
    logger.warning("cairosvg not available – SVG conversion disabled")

# ---------- helpers ----------

IS_PRODUCTION = os.environ.get('FLASK_ENV') == 'production'

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

@app.route('/googlefdd4ba2b0937db58.html')
def google_verify():
    return 'google-site-verification: googlefdd4ba2b0937db58.html', 200, {'Content-Type': 'text/html'}

# ── Minified script.js — built once at startup ───────────────────
try:
    import rjsmin as _rjsmin
    _script_path = os.path.join(app.static_folder, 'script.js')
    with open(_script_path, 'r', encoding='utf-8') as _f:
        _MINIFIED_JS = _rjsmin.jsmin(_f.read())
    logging.info(f'script.js minified: {len(open(_script_path).read())} → {len(_MINIFIED_JS)} bytes')
except Exception as _e:
    _MINIFIED_JS = None
    logging.warning(f'rjsmin unavailable, serving raw script.js: {_e}')

# ── Inline CSS — minified at startup, injected directly into HTML ──────────
# Always inlines the CSS — eliminating the blocking style.css network request.
# Uses rcssmin for minification if available, otherwise inlines raw CSS.
_css_path = os.path.join(app.static_folder, 'style.css')
try:
    import rcssmin as _rcssmin
    with open(_css_path, 'r', encoding='utf-8') as _f:
        _INLINE_CSS = _rcssmin.cssmin(_f.read())
    logging.info(f'style.css minified for inline: {len(open(_css_path).read())} → {len(_INLINE_CSS)} bytes')
except ImportError:
    # rcssmin not installed — inline raw CSS (still eliminates the blocking request)
    with open(_css_path, 'r', encoding='utf-8') as _f:
        _INLINE_CSS = _f.read()
    logging.warning('rcssmin not available — inlining raw style.css (no minification)')
except Exception as _e:
    _INLINE_CSS = None
    logging.warning(f'Could not read style.css for inlining: {_e}')

@app.route('/static/script.js')
def serve_script_js():
    from flask import make_response
    ver = request.args.get('v', '')
    if _MINIFIED_JS:
        resp = make_response(_MINIFIED_JS)
    else:
        with open(os.path.join(app.static_folder, 'script.js'), 'r') as f:
            resp = make_response(f.read())
    resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    resp.headers['ETag'] = _STATIC_VER
    return resp

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
            ok = doc.authenticate(password)
            if not ok:
                return jsonify({'error': 'password_required', 'needs_password': True}), 401

        pages = []
        for i, page in enumerate(doc):
            mat = fitz.Matrix(1.5, 1.5)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            b64 = base64.b64encode(pix.tobytes('png')).decode()

            # Extract text spans for the Edit-Text tool
            text_blocks = []
            try:
                d = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
                pw, ph = page.rect.width, page.rect.height
                for block in d.get("blocks", []):
                    if block.get("type") != 0:   # 0 = text block
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            raw = span.get("text", "")
                            if not raw.strip():
                                continue
                            x0, y0, x1, y1 = span["bbox"]
                            # colour: packed int RGB → hex
                            c = span.get("color", 0)
                            r_c = ((c >> 16) & 0xFF) / 255
                            g_c = ((c >> 8)  & 0xFF) / 255
                            b_c = (c & 0xFF) / 255
                            hex_color = '#{:02x}{:02x}{:02x}'.format(
                                int(r_c*255), int(g_c*255), int(b_c*255))

                            # Parse font name — strip PDF subset prefix (e.g. "ABCDEF+")
                            raw_font = span.get("font", "") or ""
                            clean_font = raw_font.split("+", 1)[-1] if "+" in raw_font else raw_font
                            fl_lower = clean_font.lower()

                            # Detect bold / italic from font name or span flags
                            span_flags = span.get("flags", 0)
                            is_bold   = bool(span_flags & 2**4) or any(x in fl_lower for x in ("bold", "-bd", "heavy", "black", "demi"))
                            is_italic = bool(span_flags & 2**1) or any(x in fl_lower for x in ("italic", "oblique", "-it", "-ob"))

                            # Map to CSS font-family (best effort)
                            if any(x in fl_lower for x in ("times", "roman", "serif", "garamond", "georgia")):
                                css_family = "Georgia, 'Times New Roman', serif"
                            elif any(x in fl_lower for x in ("courier", "mono", "typewriter", "consol")):
                                css_family = "'Courier New', Courier, monospace"
                            elif any(x in fl_lower for x in ("arial", "helvetica", "sans")):
                                css_family = "Arial, Helvetica, sans-serif"
                            elif any(x in fl_lower for x in ("verdana",)):
                                css_family = "Verdana, sans-serif"
                            elif any(x in fl_lower for x in ("calibri",)):
                                css_family = "Calibri, Arial, sans-serif"
                            else:
                                css_family = "Arial, sans-serif"

                            text_blocks.append({
                                'text':       raw,
                                'font_size':  round(span.get("size", 12), 2),
                                'font':       clean_font,
                                'font_raw':   raw_font,
                                'color':      hex_color,
                                'bold':       is_bold,
                                'italic':     is_italic,
                                'css_family': css_family,
                                # normalised coordinates (0-1)
                                'x0': round(x0/pw, 6), 'y0': round(y0/ph, 6),
                                'x1': round(x1/pw, 6), 'y1': round(y1/ph, 6),
                                # raw PDF-pt coords for save
                                'rx0': round(x0,3), 'ry0': round(y0,3),
                                'rx1': round(x1,3), 'ry1': round(y1,3),
                            })
            except Exception:
                pass   # non-fatal — edit-text just won't show existing spans

            pages.append({
                'index':     i,
                'width_pt':  page.rect.width,
                'height_pt': page.rect.height,
                'img':       b64,
                'text_blocks': text_blocks,
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

    def hex_to_rgb(hex_str):
        h = hex_str.lstrip('#')
        if len(h) < 6:
            return (0, 0, 0)
        return (int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255)

    def rgba_css_to_fitz(rgba_str):
        """Parse rgba(r,g,b,a) css string → ((r,g,b), alpha)"""
        import re
        m = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)', rgba_str.strip())
        if not m:
            return (1,1,0), 0.45
        r, g, b = int(m.group(1))/255, int(m.group(2))/255, int(m.group(3))/255
        a = float(m.group(4)) if m.group(4) else 0.45
        return (r, g, b), a

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
            ann_type = ann.get('type', '')

            # ── Point-based annotations ──
            if ann_type in ('text', 'note', 'signature', 'checkbox', 'image'):
                x = float(ann.get('x_pct', 0)) * pw
                y = float(ann.get('y_pct', 0)) * ph

                if ann_type == 'text':
                    text = ann.get('text', '').strip()
                    if not text:
                        continue
                    font_size = float(ann.get('font_size', 12))
                    color     = hex_to_rgb(ann.get('color', '#000000'))
                    # Font family → fitz built-in name mapping (best-effort)
                    font_family = ann.get('font_family', 'Arial')
                    fitz_font = 'helv'
                    fl = font_family.lower()
                    if 'times' in fl or 'serif' in fl:
                        fitz_font = 'tiro'
                    elif 'courier' in fl or 'mono' in fl:
                        fitz_font = 'cour'
                    bold      = ann.get('bold', False)
                    italic    = ann.get('italic', False)
                    if bold and italic:   fitz_font += 'bi' if fitz_font in ('helv','cour','tiro') else ''
                    elif bold:            fitz_font += 'b'  if fitz_font in ('helv','cour','tiro') else ''
                    elif italic:          fitz_font += 'i'  if fitz_font in ('helv','cour','tiro') else ''
                    try:
                        page.insert_text(fitz.Point(x, y), text, fontname=fitz_font, fontsize=font_size, color=color)
                    except Exception:
                        page.insert_text(fitz.Point(x, y), text, fontsize=font_size, color=color)

                elif ann_type == 'note':
                    text = ann.get('text', '').strip()
                    if text:
                        # Draw yellow box then text inside
                        box_w, box_h = 160, 80
                        rect = fitz.Rect(x, y, x + box_w, y + box_h)
                        page.draw_rect(rect, color=(0.97, 0.82, 0.21), fill=(1, 0.99, 0.77), width=1)
                        page.insert_textbox(fitz.Rect(x+4, y+4, x+box_w-4, y+box_h-4),
                                            text, fontsize=9, color=(0.1,0.1,0.1))

                elif ann_type == 'signature':
                    img_data = ann.get('img_data', '')
                    if ',' in img_data:
                        img_data = img_data.split(',', 1)[1]
                    img_bytes = base64.b64decode(img_data)
                    sig_w = float(ann.get('width_pct', 0.25)) * pw
                    sig_h = float(ann.get('height_pct', 0.08)) * ph
                    page.insert_image(fitz.Rect(x, y, x + sig_w, y + sig_h), stream=img_bytes)

                elif ann_type == 'image':
                    img_data = ann.get('img_data', '')
                    if ',' in img_data:
                        img_data = img_data.split(',', 1)[1]
                    img_bytes = base64.b64decode(img_data)
                    img_w = float(ann.get('width_pct', 0.3)) * pw
                    # Approximate height as proportional (will render correctly)
                    img_h = img_w * 0.75
                    page.insert_image(fitz.Rect(x - img_w/2, y - img_h/2, x + img_w/2, y + img_h/2), stream=img_bytes)

                elif ann_type == 'checkbox':
                    if ann.get('checked', False):
                        size = float(ann.get('size', 22)) * (pw / 900)
                        size = max(8, min(40, size))
                        p1 = fitz.Point(x,               y + size * 0.50)
                        p2 = fitz.Point(x + size * 0.38, y + size * 0.90)
                        p3 = fitz.Point(x + size,        y + size * 0.10)
                        lw = max(1.0, size * 0.13)
                        page.draw_line(p1, p2, color=(0, 0.35, 0.75), width=lw)
                        page.draw_line(p2, p3, color=(0, 0.35, 0.75), width=lw)

            # ── Edit existing text (redact original + insert new) ──
            elif ann_type == 'edittext':
                rx0 = float(ann.get('rx0', 0)); ry0 = float(ann.get('ry0', 0))
                rx1 = float(ann.get('rx1', 0)); ry1 = float(ann.get('ry1', 0))
                new_text  = ann.get('text', '').strip()
                font_size = float(ann.get('font_size', 12))
                color     = hex_to_rgb(ann.get('color', '#000000'))
                is_bold   = ann.get('bold',   False)
                is_italic = ann.get('italic', False)
                orig_font = ann.get('font', '') or ''   # clean font name sent from client

                # Map to best-matching built-in PyMuPDF/PDF font preserving bold+italic
                def pick_fitz_font(font_name, bold, italic):
                    fl = font_name.lower()
                    if any(x in fl for x in ('times', 'roman', 'serif', 'georgia', 'garamond')):
                        base = 'tibo' if bold else 'tiit' if italic else 'tiro'
                        if bold and italic: base = 'tibi'
                    elif any(x in fl for x in ('courier', 'mono', 'typewriter', 'consol')):
                        base = 'cobo' if bold else 'coit' if italic else 'cour'
                        if bold and italic: base = 'cobi'
                    else:  # Arial / Helvetica / any sans
                        base = 'hebo' if bold else 'heit' if italic else 'helv'
                        if bold and italic: base = 'hebi'
                    return base

                fitz_font = pick_fitz_font(orig_font, is_bold, is_italic)

                # 1. Redact (cleanly erase) the original text area
                erase_rect = fitz.Rect(rx0 - 1, ry0 - 2, rx1 + 1, ry1 + 2)
                page.add_redact_annot(erase_rect, fill=(1, 1, 1))
                page.apply_redactions()

                # 2. Write replacement text with original style (skip if deleted)
                if new_text:
                    try:
                        page.insert_text(
                            fitz.Point(rx0, ry1 - 1),
                            new_text,
                            fontname=fitz_font,
                            fontsize=font_size,
                            color=color,
                        )
                    except Exception:
                        # Last-resort fallback (no font specified)
                        page.insert_text(
                            fitz.Point(rx0, ry1 - 1),
                            new_text,
                            fontsize=font_size,
                            color=color,
                        )

            # ── Rectangle-based annotations ──
            elif ann_type in ('highlight', 'rect', 'ellipse', 'whiteout'):
                x1 = float(ann.get('x1_pct', 0)) * pw
                y1 = float(ann.get('y1_pct', 0)) * ph
                x2 = float(ann.get('x2_pct', 0)) * pw
                y2 = float(ann.get('y2_pct', 0)) * ph
                rect = fitz.Rect(x1, y1, x2, y2)

                if ann_type == 'highlight':
                    hl_css = ann.get('hl_color', 'rgba(253,230,138,0.55)')
                    (r, g, b), alpha = rgba_css_to_fitz(hl_css)
                    hl = page.add_highlight_annot(rect)
                    hl.set_colors(stroke=(r, g, b))
                    hl.set_opacity(alpha)
                    hl.update()

                elif ann_type == 'rect':
                    color  = hex_to_rgb(ann.get('color', '#3b82f6'))
                    sw     = float(ann.get('stroke_width', 2))
                    page.draw_rect(rect, color=color, fill=color, fill_opacity=0.1, width=sw)

                elif ann_type == 'ellipse':
                    color = hex_to_rgb(ann.get('color', '#3b82f6'))
                    sw    = float(ann.get('stroke_width', 2))
                    page.draw_oval(rect, color=color, fill=color, fill_opacity=0.1, width=sw)

                elif ann_type == 'whiteout':
                    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)

        buf = io.BytesIO()
        doc.save(buf, encryption=fitz.PDF_ENCRYPT_NONE)
        buf.seek(0)
        stem = os.path.splitext(f.filename)[0] if f.filename else 'document'
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f'{stem}_edited.pdf')
    except Exception as e:
        logger.exception('pdf-editor/save error')
        return jsonify({'error': str(e)}), 500




if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    debug = not IS_PRODUCTION
    app.run(debug=debug, host='0.0.0.0', port=port)
