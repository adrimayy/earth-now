#!/usr/bin/env python3
"""Builds Earth Now's cloud map for the latest hour: clouds.jpg (4096 x 2048, 180 W at the left edge, north up) and
clouds.json (the time it shows).

What goes in, all public and free:
  * NOAA's Global Mosaic of Geostationary Satellite Imagery (GMGSI): one picture an hour of the whole Earth between
    72.7 N and 72.7 S, about 8 km a pixel, blended from GOES-West, GOES-East, Meteosat (0 and 45.5 E) and Himawari, in
    visible light (what an eye would see), long-wave infrared (the temperature of whatever is on top) and short-wave
    infrared.  s3://noaa-gmgsi-pds
  * NOAA's GFS weather model: its cloud for the same hour fills the polar caps the satellites cannot see, and its
    snow and sea ice say where white ground is not cloud.  s3://noaa-gfs-bdp-pds
  * The app's own maps of water and ground colour (tex/water.png, tex/day4k.jpg).

How cloud is read:
  * In daylight, from the visible picture: how much brighter a place is than its clear-sky look, which is the darkest
    it has been at this same hour over the last week (same Sun angle, so glint, haze and ground cancel out).
  * At night, from the infrared pictures: how much colder a place is than the warmest it has been at this hour over
    the last week, turned into brightness with the relation measured on the daylit side of the same picture. Low cloud,
    which is as warm as the ground and so invisible that way, is taken from the model there.
  * The value written is the one the app's shader expects: 0 = clear, else 255*(0.06 + 0.94*c), where c is the cloud
    amount whose brightness the shader draws as c^1.15 * mix(0.5, 0.9, smoothstep(0.2, 0.85, c)).

    python tools/clouds.py --out site            # fetch the latest hour and write site/clouds.jpg, site/clouds.json
"""
import argparse, datetime as dt, io, json, os, re, sys, time, urllib.request
import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None
GMGSI = 'https://noaa-gmgsi-pds.s3.amazonaws.com'
GFS = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'
W, H = 4096, 2048
DAYS = 7                                   # how far back the clear-sky look is taken from
SATS = np.array([-137.0, -75.2, 0.0, 45.5, 140.7])   # where the five satellites sit (degrees east)
UTC = dt.timezone.utc


def log(*a):
    print(*a, flush=True)


def ss(a, b, x):
    t = np.clip((x - a)/(b - a), 0.0, 1.0)
    return t*t*(3.0 - 2.0*t)


# ---------------------------------------------------------------- Sun and satellites
def sun(t):
    """Latitude and longitude (degrees) of the point the Sun is straight above at UTC time t (to about 0.01 degree)."""
    n = (t - dt.datetime(2000, 1, 1, 12, tzinfo=UTC)).total_seconds()/86400.0
    L = np.radians((280.460 + 0.9856474*n) % 360)
    g = np.radians((357.528 + 0.9856003*n) % 360)
    lam = L + np.radians(1.915)*np.sin(g) + np.radians(0.020)*np.sin(2*g)
    eps = np.radians(23.439 - 0.0000004*n)
    dec = np.arcsin(np.sin(eps)*np.sin(lam))
    ra = np.arctan2(np.cos(eps)*np.sin(lam), np.cos(lam))
    gmst = np.radians((280.46061837 + 360.98564736629*n) % 360)
    return float(np.degrees(dec)), float((np.degrees(ra - gmst) + 180) % 360 - 180)


def sun_height(lat, lon, t):
    """Sine of the Sun's height above the horizon on a lat x lon grid (1 = overhead, 0 = on the horizon)."""
    d, l = sun(t)
    la = np.radians(lat)[:, None]
    return (np.sin(la)*np.sin(np.radians(d)) + np.cos(la)*np.cos(np.radians(d))*np.cos(np.radians(lon - l))[None, :]).astype(np.float32)


def sector(lon):
    """Which of the five satellites is nearest in longitude, per column."""
    return np.argmin(np.abs((lon[:, None] - SATS[None, :] + 180) % 360 - 180), axis=1)


def view(lat, lon, t, m):
    """For each place, seen from the satellite nearest in longitude: the sine of the satellite's height above the
    horizon, and the cosine of the angle between the line to the satellite and the Sun's mirror reflection (near 1 = glint).
    m is sun_height for the same grid and time."""
    slon = SATS[sector(lon)]
    r = 42164.0/6378.0
    cg = (np.cos(np.radians(lat))[:, None]*np.cos(np.radians(lon - slon))[None, :]).astype(np.float32)   # up . satellite / r
    dist = np.sqrt(r*r - 2.0*r*cg + 1.0)
    muv = (r*cg - 1.0)/dist
    sd, sl = sun(t)
    s_sat = (r*np.cos(np.radians(sd))*np.cos(np.radians(sl - slon))).astype(np.float32)[None, :]          # sun . satellite
    glint = (2.0*m*r*cg - m - s_sat)/dist
    return muv.astype(np.float32), glint.astype(np.float32)


# ---------------------------------------------------------------- fetching
def http(url, headers=None, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=120) as r:
                return r.read()
        except Exception as e:
            if k == tries - 1 or getattr(e, 'code', 0) in (403, 404):
                raise
            time.sleep(3*(k + 1))


def keys(prefix):
    return sorted(re.findall(r'<Key>([^<]+\.nc)</Key>', http(GMGSI + '/?list-type=2&prefix=' + prefix).decode()))


def mosaic(product, t, want_grid=False):
    """One GMGSI picture (LW, VIS or SW) for the hour t as counts 0-255 (0 = nothing there), or None."""
    import netCDF4
    try:
        k = keys(t.strftime('GMGSI_' + product + '/%Y/%m/%d/%H/'))
        if not k:
            return None
        ds = netCDF4.Dataset('m.nc', memory=http(GMGSI + '/' + k[-1]))
        ds.set_auto_maskandscale(False)
        d = np.asarray(ds.variables['data'][0], dtype=np.float32)
        d[~np.isfinite(d) | (d < 0)] = 0.0
        if want_grid:
            lat = np.asarray(ds.variables['lat'][:, 0], dtype=np.float64)
            lon = np.asarray(ds.variables['lon'][0, :], dtype=np.float64)
            return d, lat, lon
        return d
    except Exception as e:
        log('  no', product, t.strftime('%Y-%m-%d %H'), repr(e)[:120])
        return None


def gfs(valid):
    """GFS fields for the hour `valid` on its 0.25-degree grid (rows 90 N to 90 S, columns 0 to 359.75 E), or None."""
    try:
        import pygrib
    except Exception as e:
        log('  no pygrib', e)
        return None
    want = {'cw': ':CWAT:entire atmosphere', 'tc': ':TCDC:entire atmosphere:%d hour fcst', 'lc': ':LCDC:low cloud layer:%d hour fcst', 'snod': ':SNOD:surface:', 'ice': ':ICEC:surface:', 'ts': ':TMP:surface:'}
    now = dt.datetime.now(UTC)
    for k in range(0, 10):
        c = now - dt.timedelta(hours=6*k)
        c = c.replace(hour=c.hour//6*6, minute=0, second=0, microsecond=0)
        f = int(round((valid - c).total_seconds()/3600))
        if f < 1 or f > 120:
            continue
        base = '%s/gfs.%s/%02d/atmos/gfs.t%02dz.pgrb2.0p25.f%03d' % (GFS, c.strftime('%Y%m%d'), c.hour, c.hour, f)
        try:
            lines = http(base + '.idx', tries=1).decode().strip().split('\n')
        except Exception:
            continue
        try:
            offs = [int(l.split(':')[1]) for l in lines]
            out = {}
            for name, pat in want.items():
                pat = pat % f if '%d' in pat else pat
                i = next(i for i, l in enumerate(lines) if pat in l)
                b = http(base, {'Range': 'bytes=%d-%s' % (offs[i], offs[i + 1] - 1 if i + 1 < len(offs) else '')})
                with open('m.grib', 'wb') as fh:
                    fh.write(b)
                g = pygrib.open('m.grib')
                out[name] = np.nan_to_num(np.asarray(np.ma.filled(g[1].values, 0.0), dtype=np.float32))
                g.close()
            os.remove('m.grib')
            log('  model: cycle %s + %d h' % (c.strftime('%Y-%m-%d %H'), f))
            return out
        except Exception as e:
            log('  model cycle', c, 'failed:', repr(e)[:120])
    return None


# ---------------------------------------------------------------- maps
def on_grid(img, lat, lon, lon0=-180.0, lat0=90.0, bilinear=True):
    """An equirectangular map (rows from lat0 southward, columns from lon0 eastward, cell-centred unless it is the
    GFS grid) read at every lat x lon."""
    Hh, Ww = img.shape
    if lon0 == 0.0:                                                         # GFS: grid points on the degrees
        fy = (lat0 - lat)/(180.0/(Hh - 1))
        fx = (lon % 360.0)/(360.0/Ww)
    else:
        fy = (lat0 - lat)/(180.0/Hh) - 0.5
        fx = ((lon - lon0) % 360.0)/(360.0/Ww) - 0.5
    if not bilinear:
        return img[np.clip(np.round(fy).astype(int), 0, Hh - 1)][:, np.round(fx).astype(int) % Ww]
    y0 = np.clip(np.floor(fy).astype(int), 0, Hh - 2)
    ty = np.clip(fy - y0, 0, 1)[:, None].astype(np.float32)
    x0 = np.floor(fx).astype(int)
    tx = (fx - x0)[None, :].astype(np.float32)
    x1 = (x0 + 1) % Ww
    x0 = x0 % Ww
    return (img[y0][:, x0]*(1 - tx) + img[y0][:, x1]*tx)*(1 - ty) + (img[y0 + 1][:, x0]*(1 - tx) + img[y0 + 1][:, x1]*tx)*ty


def statics(tex):
    """Water share (0-1) and red ground brightness (linear 0-1) from the app's own maps."""
    water = np.asarray(Image.open(os.path.join(tex, 'water.png')).convert('L'), dtype=np.float32)/255.0
    c = np.asarray(Image.open(os.path.join(tex, 'day4k.jpg')), dtype=np.float32)[..., 0]/255.0
    red = np.where(c <= 0.04045, c/12.92, ((c + 0.055)/1.055)**2.4).astype(np.float32)
    return water, red


# the app's brightness for a cloud amount c, and its inverse
_c = np.linspace(0.0, 1.0, 2001)
_R = _c**1.15*(0.5 + 0.4*ss(0.2, 0.85, _c))


def amount(R):
    return np.interp(R, _R, _c).astype(np.float32)


def brightness(c):
    return np.interp(c, _c, _R).astype(np.float32)


def both(a, b):
    """Two cloud layers on top of each other."""
    return 1.0 - (1.0 - a)*(1.0 - b)


# ---------------------------------------------------------------- the conversion
NIGHT_LUT = [(0, 0.06), (2, 0.10), (6, 0.19), (13, 0.32), (24, 0.42), (39, 0.47), (57, 0.53), (83, 0.63), (113, 0.71)]      # used if this hour has too little daylight to measure
LOW_LUT = [(0.0, 0.0), (0.1, 0.02), (0.3, 0.05), (0.5, 0.08), (0.7, 0.12), (0.9, 0.18), (1.0, 0.25)]


def convert(t, lat, lon, lw, vis, sw, lw_clear, vis_clear_rho, water, red, model, quiet=False):
    """Cloud brightness (0-0.93, as the app draws it with the Sun overhead) on the mosaic's own grid, and how far each
    value can be trusted (0-1, falling to 0 at the edge of what the satellites see).

    lw, vis, sw: this hour's counts (0 = missing).  lw_clear: the lowest long-wave count (warmest reading) at this hour
    over the last days.  vis_clear_rho: the lowest visible reflectance at this hour over the last days.  water, red,
    model: static maps and model fields already on this grid (model may be None)."""
    say = (lambda *a: None) if quiet else log
    m = sun_height(lat, lon, t)
    muv, glint = view(lat, lon, t, m)
    mm = np.maximum(m, 0.04)

    # ---- daylight: brightness over the clear-sky look
    has_vis = vis is not None
    if has_vis:
        rho = (vis/255.0)**2/mm                                             # counts are 255*sqrt(brightness)
        A = np.minimum(vis_clear_rho, np.where(vis > 0, rho, 9.0))
        # Where it has been cloudy at this hour all week the darkest look is still cloud. Clear sea is known
        # (0.03 to 0.05, more at a low Sun), clear ground roughly from the app's own map; neither can be much brighter
        # unless it is glint, snow or ice.
        sea_cap = 0.062 + 0.007/mm + 1.5*ss(0.80, 0.93, glint)
        land_cap = (0.12 + 0.40*red**0.75)*(1.0 + 0.25/mm)                  # loose: dry ground at a low Sun is bright
        cap = water*sea_cap + (1.0 - water)*land_cap
        white = np.zeros_like(m, dtype=bool)
        soft = np.zeros_like(m)
        if model is not None:
            white = ndimage.maximum_filter(((model['snod'] > 0.01) | (model['ice'] > 0.10)).astype(np.uint8), size=max(3, int(round(len(lon)/4999*9)))) > 0
            cap = np.where(white, 9.0, cap)
            soft = ndimage.gaussian_filter(white.astype(np.float32), 8.0*len(lon)/4999)      # the same, without the model grid's stair-steps
        A = np.minimum(A, cap)
        Rv = (rho - A)/np.maximum(1.0 - 2.0*A + rho*A, 0.25)
        Rv = np.clip(Rv - (0.015 + 0.004/mm), 0.0, 1.0)                     # day-to-day flicker of clear sky, more at a low Sun
        # thick cloud tops read 0.86 with the Sun overhead and 0.6 with it low (measured on the coldest tops)
        Rv = np.clip(Rv/(0.63 + 0.37*np.clip(m, 0, 1)), 0.0, 0.93)
        wv = ss(0.05, 0.20, m)*(vis > 0)
        # Where the clear look is itself white (old snow, ice) a cloud hardly changes the brightness, and over snow at a
        # low Sun two satellites facing each other disagree about what is cloud: leave both to the infrared.
        wv = wv*(1.0 - ss(0.35, 0.55, A))*(1.0 - soft*ss(0.45, 0.30, m))
        del rho
    else:
        Rv = np.zeros_like(m)
        wv = np.zeros_like(m)

    # ---- infrared: colder than the clear-sky reading
    # Clear ground itself runs a few degrees colder than its warmest day of the week (2 counts = 1 K), land more than sea.
    clear = np.minimum(lw_clear, np.where(lw > 0, lw, 255.0))
    rise = np.where(lw > 0, lw - clear, 0.0)
    if model is not None and 'ts' in model:
        # After a cold front the ground itself can be 10 or 20 K colder than on its warmest day of the week. The model
        # knows the ground temperature now (a count is half a kelvin down from 333 K; clear air reads about 3 K below
        # the ground): on land, that much of the cooling is not cloud.
        rise = np.maximum(rise - 2.0*np.clip((333.0 - 0.5*clear) + 3.0 - model['ts'], 0.0, 40.0)*(1.0 - water), 0.0)
    rise = np.maximum(rise - (10.0 - 7.0*water), 0.0)
    lut = NIGHT_LUT
    if has_vis:
        ok = (wv > 0.99) & (m > 0.4) & (lw > 0)
        if ok.sum() > 200000:
            edges = [0, 0.5, 4, 9, 18, 32, 48, 70, 100, 256]
            fit = []
            for a, b in zip(edges[:-1], edges[1:]):
                sel = ok & (rise >= a) & (rise < b)
                if sel.sum() > 2000:
                    fit.append((float(rise[sel].mean()), float(Rv[sel].mean())))
            if len(fit) >= 6 and fit[0][0] < 0.5:
                fit = [(x, max(v for _, v in fit[:i + 1])) for i, (x, y) in enumerate(fit)]              # never falling
                lut = fit
                say('  night relation (counts colder > brightness): ' + ', '.join('%.0f>%.2f' % q for q in lut))
    # what the daylit side shows where the infrared sees nothing (low cloud) is not known at night from temperature
    base = lut[0][1]
    Ri = np.interp(rise, [q[0] for q in lut], [max(q[1] - base, 0.0)/(1.0 - base) for q in lut]).astype(np.float32)
    # Low cloud where there is no usable daylight: its top is about as warm as the ground, so the infrared cannot see
    # it. (The short-wave picture can in principle, but the five satellites disagree by more than the signal.) The
    # weather model knows roughly where the low decks are; how bright its low cloud really looks is measured, as above,
    # on the daylit side of this same hour, where the infrared sees nothing and the visible picture does.
    low = np.zeros_like(m)
    if model is not None and 'lc' in model:
        lc = np.clip(model['lc']/100.0, 0.0, 1.0)
        lutl = LOW_LUT
        if has_vis:
            ok = (wv > 0.99) & (m > 0.4) & (lw > 0) & (rise <= 0.0) & ~white
            if ok.sum() > 100000:
                edges = [0, 0.05, 0.2, 0.4, 0.6, 0.8, 0.95, 1.01]
                fit = []
                for a, b in zip(edges[:-1], edges[1:]):
                    sel = ok & (lc >= a) & (lc < b)
                    if sel.sum() > 2000:
                        fit.append((float(lc[sel].mean()), float(Rv[sel].mean())))
                if len(fit) >= 5 and fit[0][0] < 0.05:
                    fit = [(x, max(v for _, v in fit[:i + 1]) - fit[0][1]) for i, (x, y) in enumerate(fit)]
                    lutl = fit
                    say('  low cloud the model has (share of sky > brightness): ' + ', '.join('%.2f>%.2f' % q for q in lutl))
        low = np.interp(lc, [q[0] for q in lutl], [q[1] for q in lutl]).astype(np.float32)
        low = ndimage.gaussian_filter(low, 6.0*len(lon)/4999)*ss(12.0, 2.0, rise)      # (the model's grid is coarse: no hard edges)
        low = low.astype(np.float32)
    Rn = both(Ri, low)
    if has_vis and white.any():
        # Fresh snow is brighter than the week's darkest look without being cloud. Where the model has snow or ice on
        # the ground, a bright place counts as cloud only if it is also colder than clear ground, or shines at
        # 3.9 micrometres the way water droplets do and snow does not (reflected sunlight: the short-wave picture reads
        # warmer than the long-wave one).
        gate = ss(15.0, 40.0, rise)
        if sw is not None:
            planck = lambda T: 1.0/(np.exp(3689.0/T) - 1.0)                 # 3.9 micrometres; a count is half a kelvin down from 333 K
            r39 = (planck(333.0 - 0.5*sw) - planck(333.0 - 0.5*lw))/(np.maximum(m, 0.05)*2.435e-5)
            gate = np.maximum(gate, ss(0.03, 0.08, np.where((sw > 0) & (lw > 0), r39, 0.0)))
        Rv = Rv + soft*(np.maximum(Ri, Rv*gate) - Rv)
    R = Rv*wv + Rn*(1.0 - wv)
    # ---- how far to trust it: near the edge of a satellite's view the ground is seen at a grazing angle, then not at all
    trust = ss(0.22, 0.34, muv)*(lw > 0)
    return R.astype(np.float32), trust.astype(np.float32), dict(Rv=Rv, wv=wv, Ri=Ri, low=low, m=m)


def deseam(R, lat, lon):
    """Softens the straight joins where the mosaic switches satellite. Two satellites look at the same cloud from
    opposite sides, so one sees its lit flank and the other its shadowed one, and the brightness steps along a
    meridian, most at a low Sun. Each side is scaled toward the other (never brightening clear sky), fully at the join
    and fading out over 6 degrees."""
    rows = max(3, int(round(6.0/(145.0/len(lat)))))                        # averaged over about 6 degrees of latitude
    s = np.sort(SATS)
    for seam in [((a + b)/2.0 + 180) % 360 - 180 for a, b in zip(s, np.r_[s[1:], s[0] + 360.0])]:
        d = (lon - seam + 180) % 360 - 180
        west = (d > -3.5) & (d < -0.3)
        east = (d > 0.3) & (d < 3.5)
        if west.sum() < 4 or east.sum() < 4:
            continue
        mw = ndimage.uniform_filter1d(R[:, west].mean(1), rows, mode='nearest')
        me = ndimage.uniform_filter1d(R[:, east].mean(1), rows, mode='nearest')
        q = np.clip(np.log((mw + 0.05)/(me + 0.05)), -0.5, 0.5).astype(np.float32)        # how much brighter the west side reads
        near = np.abs(d) < 6.0
        w = (0.5*(1.0 - np.abs(d[near])/6.0)*np.where(d[near] < 0, -1.0, 1.0)).astype(np.float32)
        R[:, near] = np.clip(R[:, near]*np.exp(q[:, None]*w[None, :]), 0.0, 0.93)
    return R


def to_map(a, lat, lon):
    """The mosaic grid (Mercator rows from north to south, columns eastward from 180) averaged onto the W x H map
    (rows evenly from 90 N, columns eastward from 180 W). Returns the map and the share of each cell that had data."""
    n, k = a.shape
    # columns first: both grids are even in longitude and start at 180, so cell edges are at whole multiples
    c = np.concatenate([np.zeros((n, 1), np.float32), np.cumsum(a, axis=1, dtype=np.float64).astype(np.float64)], axis=1)
    e = np.arange(W + 1)*(k/W) + 0.5                                         # edges, in source columns (column j spans j-0.5..j+0.5)
    e0 = np.floor(e).astype(int)
    f = e - e0
    tot = c[:, -1:]
    cw = lambda i: c[:, np.mod(i, k)] + tot*(i//k)[None, :]                 # cumulative sum continued round the globe
    ce = cw(e0)*(1 - f)[None, :] + cw(e0 + 1)*f[None, :]
    b = ((ce[:, 1:] - ce[:, :-1])/(k/W)).astype(np.float32)
    # rows: each output row takes the source rows whose latitudes fall inside it
    out_edge = 90.0 - np.arange(H + 1)*(180.0/H)
    pos = np.interp(out_edge, lat[::-1], np.arange(n, dtype=np.float64)[::-1], left=np.nan, right=np.nan) + 0.5
    top = lat[0] + (lat[0] - lat[1])/2.0
    bot = lat[-1] - (lat[-2] - lat[-1])/2.0
    pos = np.where(out_edge >= top, 0.0, np.where(out_edge <= bot, float(n), np.nan_to_num(pos, nan=0.0)))
    pos = np.clip(pos, 0.0, float(n))
    c = np.concatenate([np.zeros((1, W), np.float64), np.cumsum(b, axis=0, dtype=np.float64)], axis=0)
    p0 = np.floor(pos).astype(int).clip(0, n - 1)
    cp = c[p0]*(1 - (pos - p0))[:, None] + c[p0 + 1]*(pos - p0)[:, None]
    span = pos[1:] - pos[:-1]
    out = np.zeros((H, W), np.float32)
    ok = span > 1e-6
    out[ok] = ((cp[1:] - cp[:-1])[ok]/span[ok][:, None]).astype(np.float32)
    # how much of each output row lies inside the mosaic at all
    full = (np.clip(out_edge[:-1], bot, top) - np.clip(out_edge[1:], bot, top))/(180.0/H)
    return out, np.clip(full, 0, 1).astype(np.float32)


def model_cloud(model, R_sat, trust, lat):
    """The model's cloud as brightness, scaled so that it matches the satellites on average where both exist.
    model['cw'] is the water in cloud above each place (kg/m2), model['tc'] how much of the sky is covered (%)."""
    tau = 60.0*np.maximum(model['cw'], 0.0)*np.sqrt(np.clip(model['tc']/100.0, 0.0, 1.0))
    Rm = 0.075*tau/(1.0 + 0.075*tau)
    sel = (trust > 0.99) & (np.abs(lat)[:, None] > 40) & (np.abs(lat)[:, None] < 60)
    k = 1.0
    if sel.sum() > 50000:
        k = float(np.clip(R_sat[sel].mean()/max(Rm[sel].mean(), 1e-3), 0.4, 2.5))
    log('  model cloud scaled by %.2f' % k)
    return np.clip(Rm*k, 0.0, 0.93).astype(np.float32)


def compose(R, trust, lat, lon, model_raw, previous=None):
    """The finished map (uint8, W x H): the satellites where they see, the model beyond, last hour's map if there is
    no model."""
    num, _ = to_map(R*trust, lat, lon)
    den, inside = to_map(trust, lat, lon)
    den = den*inside[:, None]
    num = num*inside[:, None]
    Rs = num/np.maximum(den, 1e-3)
    out_lat = 90.0 - (np.arange(H) + 0.5)*(180.0/H)
    out_lon = -180.0 + (np.arange(W) + 0.5)*(360.0/W)
    if model_raw is not None:
        m = {k: on_grid(v, out_lat, out_lon, lon0=0.0) for k, v in model_raw.items() if k in ('cw', 'tc')}
        other = model_cloud(m, Rs, den, out_lat)
    elif previous is not None:
        c = np.clip((previous.astype(np.float32)/255.0 - 0.06)/0.94, 0.0, 1.0)
        other = brightness(c)
    else:
        other = np.zeros_like(Rs)
    Rf = Rs*den + other*(1.0 - den)
    c = amount(np.clip(Rf, 0.0, 0.93))
    return np.round(255.0*(0.06 + 0.94*np.where(c > 0.03, c, 0.0))).astype(np.uint8)       # clear sky is 15, not 0: kinder to JPEG


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='site')
    ap.add_argument('--tex', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tex'))
    ap.add_argument('--previous', default=None, help='the last published clouds.jpg, used beyond the satellites if the model is missing')
    args = ap.parse_args()
    t = dt.datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    got = None
    for _ in range(8):                                                      # each hour appears about 35 minutes after it starts
        got = mosaic('LW', t, want_grid=True)
        if got is not None:
            break
        t -= dt.timedelta(hours=1)
    if got is None:
        log('no mosaic in the last 8 hours: nothing written')
        return 0
    lw, lat, lon = got
    log('hour', t.strftime('%Y-%m-%d %H:00 UTC'), lw.shape)
    vis = mosaic('VIS', t)
    for _ in range(4):                                                      # the visible picture is posted a few minutes after the infrared one
        if vis is not None:
            break
        time.sleep(60)
        vis = mosaic('VIS', t)
    sw = mosaic('SW', t)
    when = t + dt.timedelta(minutes=5)                                      # the scans take the first ten minutes of the hour
    lw_clear = np.full_like(lw, 255.0)
    vis_clear = np.full_like(lw, 9.0)
    days = 0
    for d in range(1, DAYS + 1):
        td = t - dt.timedelta(days=d)
        a = mosaic('LW', td)
        if a is None or a.shape != lw.shape:
            continue
        days += 1
        np.minimum(lw_clear, np.where(a > 0, a, 255.0), out=lw_clear)
        v = mosaic('VIS', td) if vis is not None else None
        if v is not None and v.shape == lw.shape:
            md = np.maximum(sun_height(lat, lon, td + dt.timedelta(minutes=5)), 0.04)
            np.minimum(vis_clear, np.where(v > 0, (v/255.0)**2/md, 9.0), out=vis_clear)
    log('  clear-sky look from', days, 'earlier days')
    if days < 3:
        log('too little history to tell cloud from ground: nothing written')
        return 0
    # registration between days is good to about a pixel: let the clear look be as bright as its brightest neighbour,
    # or every coast and lake shore would draw as a thin line of cloud
    vis_clear = ndimage.maximum_filter(vis_clear, size=3)
    water, red = statics(args.tex)
    wg, rg = on_grid(water, lat, lon), on_grid(red, lat, lon)
    model_raw = gfs(t)
    model = {k: on_grid(model_raw[k], lat, lon, lon0=0.0) for k in ('snod', 'ice', 'lc', 'ts')} if model_raw else None
    R, trust, _ = convert(when, lat, lon, lw, vis, sw, lw_clear, vis_clear, wg, rg, model)
    R = deseam(R, lat, lon)
    previous = None
    if model_raw is None and args.previous and os.path.exists(args.previous):
        previous = np.asarray(Image.open(args.previous).convert('L').resize((W, H)))
    out = compose(R, trust, lat, lon, model_raw, previous)
    os.makedirs(args.out, exist_ok=True)
    Image.fromarray(out).save(os.path.join(args.out, 'clouds.jpg'), quality=82, optimize=True)
    with open(os.path.join(args.out, 'README.md'), 'w') as f:
        f.write('This branch holds only the latest cloud map for Earth Now. A job on the main branch (tools/clouds.py) replaces it every hour; nothing here is edited by hand.\n')
    with open(os.path.join(args.out, 'clouds.json'), 'w') as f:
        json.dump({'time': when.strftime('%Y-%m-%dT%H:%M:%SZ'), 'made': dt.datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'days': days, 'visible': vis is not None, 'model': model_raw is not None}, f)
    log('written: cloud over %.0f%% of the map' % (100.0*(out > 15).mean()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
