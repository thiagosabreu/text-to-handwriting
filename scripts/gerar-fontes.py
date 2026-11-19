"""
Gera fontes manuscritas "humanizadas" a partir de fontes OFL.

Para cada fonte base:
  1. instancia fontes variáveis (peso Regular);
  2. completa caracteres do teclado ABNT2 que faltarem (¹²³, acentuadas...);
  3. cria 3 variantes de cada letra/dígito (rotação, escala, deslocamento de
     linha de base e um leve "tremido" no traço), cada uma única;
  4. adiciona uma feature `calt` que alterna entre as variantes de forma
     pseudoaleatória, para que letras repetidas nunca fiquem idênticas
     (ex.: "ss" em "pessoa", "rr" em "carro");
  5. renomeia a família e salva em .ttf e .woff2.
"""
import copy
import math
import random
import sys
import unicodedata
from pathlib import Path

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.filterPen import FilterPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

N_ALTS = 3  # variantes além da original

ABNT2 = ("ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑáàâãäéèêëíìîïóòôõöúùûüçñ"
         "ªº°§¹²³£¢¬¨´`^~\"'!@#$%&*()-_=+[]{}<>,.;:/?\\|«»–—…“”‘’€•")

# (arquivo base, nome da nova família, intensidade, cursiva-conectada?)
FONTS = [
    ("Caveat[wght].ttf", "Caderno", 1.0, False),
    ("Kalam-Regular.ttf", "Rascunho", 1.0, False),
    ("PatrickHand-Regular.ttf", "Bilhete", 1.0, False),
    ("IndieFlower-Regular.ttf", "Recado", 1.0, False),
    ("ShadowsIntoLightTwo-Regular.ttf", "Anotacao", 1.0, False),
    ("GochiHand-Regular.ttf", "Lousa", 0.9, False),
    ("ReenieBeanie.ttf", "Garrancho", 1.1, False),
    ("NothingYouCouldDo.ttf", "Diario", 0.9, False),
    ("PlaywriteBR[wght].ttf", "Cursiva BR", 1.5, True),
]


class WobblePen(FilterPen):
    """Desloca cada ponto por um campo de ruído suave (traço levemente tremido)."""

    def __init__(self, outPen, amp, freq, rng):
        super().__init__(outPen)
        self.amp = amp
        self.f = freq
        self.p = [rng.uniform(0, 2 * math.pi) for _ in range(4)]

    def _d(self, pt):
        x, y = pt
        f, p, a = self.f, self.p, self.amp
        dx = a * (math.sin(x * f + p[0]) * math.cos(y * f * 0.7 + p[1]))
        dy = a * (math.cos(x * f * 0.8 + p[2]) * math.sin(y * f + p[3]))
        return (x + dx, y + dy)

    def moveTo(self, pt):
        self._outPen.moveTo(self._d(pt))

    def lineTo(self, pt):
        self._outPen.lineTo(self._d(pt))

    def qCurveTo(self, *pts):
        self._outPen.qCurveTo(*[self._d(p) if p else None for p in pts])

    def curveTo(self, *pts):
        self._outPen.curveTo(*[self._d(p) for p in pts])


class JoinedWarpPen(WobblePen):
    """Para cursiva conectada: deforma o miolo da letra (inclinação, pulo na
    linha de base, escala, tremido) mas deixa as pontas de ligação intactas.
    O peso da deformação vai a zero perto de x=0 e x=avanço."""

    def __init__(self, outPen, adv, matrix, amp, freq, rng, margin):
        super().__init__(outPen, amp, freq, rng)
        self.adv, self.m, self.margin = adv, matrix, margin

    def _w(self, x):
        m = self.margin
        t = min(x - m * 0.4, self.adv - m * 0.4 - x) / m
        t = max(0.0, min(1.0, t))
        return t * t * (3 - 2 * t)  # smoothstep

    def _d(self, pt):
        x, y = pt
        w = self._w(x)
        if w == 0:
            return (x, y)
        a, b, c, d, e, f = self.m
        tx, ty = a * x + c * y + e, b * x + d * y + f
        wx, wy = WobblePen._d(self, (x, y))
        return (x + w * (tx - x + wx - x), y + w * (ty - y + wy - y))


def draw_glyph(font, name, pen):
    gs = font.getGlyphSet()
    rec = DecomposingRecordingPen(gs)
    gs[name].draw(rec)
    rec.replay(pen)


def add_glyph(font, name, glyph, advance, lsb=0):
    order = font.getGlyphOrder()
    if name not in order:
        font.setGlyphOrder(order + [name])
    font["glyf"].glyphs[name] = glyph
    glyph.recalcBounds(font["glyf"])
    font["hmtx"].metrics[name] = (int(round(advance)), getattr(glyph, "xMin", 0) if glyph.numberOfContours else lsb)


def make_transformed(font, src, dst, transform, wobble=None, advance=None):
    tt = TTGlyphPen(None)
    pen = TransformPen(tt, transform)
    if wobble:
        pen = WobblePen(pen, *wobble)
    draw_glyph(font, src, pen)
    g = tt.glyph()
    add_glyph(font, dst, g, advance if advance is not None else font["hmtx"][src][0])


def fill_missing(font):
    """Completa caracteres ABNT2 ausentes."""
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm
    cap = getattr(font["OS/2"], "sCapHeight", 0) or int(upm * 0.7)
    added = []
    for ch in ABNT2:
        cp = ord(ch)
        if cp in cmap:
            continue
        name = "uni%04X" % cp
        sup = {"¹": "1", "²": "2", "³": "3"}
        if ch in sup and ord(sup[ch]) in cmap:
            base = cmap[ord(sup[ch])]
            s = 0.62
            adv = font["hmtx"][base][0] * s
            make_transformed(font, base, name, (s, 0, 0, s, 0, cap * 0.48), advance=adv)
        else:
            # acentuada = letra base + acento espaçador centralizado por cima
            decomp = unicodedata.decomposition(ch).split()
            if len(decomp) != 2 or decomp[0].startswith("<"):
                print("   !! sem como gerar", ch)
                continue
            base_ch = chr(int(decomp[0], 16))
            spacing = {0x301: "´", 0x300: "`", 0x302: "^", 0x303: "~", 0x308: "¨", 0x327: "¸"}
            acc_ch = spacing.get(int(decomp[1], 16))
            if ord(base_ch) not in cmap or not acc_ch or ord(acc_ch) not in cmap:
                print("   !! sem como gerar", ch)
                continue
            base, acc = cmap[ord(base_ch)], cmap[ord(acc_ch)]
            tt = TTGlyphPen(None)
            draw_glyph(font, base, tt)
            gb = font["glyf"][base]
            ga = font["glyf"][acc]
            gb.recalcBounds(font["glyf"]); ga.recalcBounds(font["glyf"])
            dx = (gb.xMin + gb.xMax) / 2 - (ga.xMin + ga.xMax) / 2
            dy = 0 if base_ch.islower() else cap - (upm * 0.5)
            if int(decomp[1], 16) == 0x327:
                dy = 0
            draw_glyph(font, acc, TransformPen(tt, (1, 0, 0, 1, dx, dy)))
            add_glyph(font, name, tt.glyph(), font["hmtx"][base][0])
        font["cmap"].getcmap(3, 1).cmap[cp] = name
        for t in font["cmap"].tables:
            if t.isUnicode():
                t.cmap[cp] = name
        cmap = font.getBestCmap()
        added.append(ch)
    return added


def humanize(font, strength, joined, seed):
    rng = random.Random(seed)
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    targets = sorted({cmap[cp] for cp in cmap
                      if chr(cp).isalnum() and not chr(cp).isspace()})
    if joined:
        # a cursiva troca as letras por formas de ligação (a.ful, n.cnt...) no
        # calt original; essas formas também precisam de variantes
        roots = {g.split(".")[0] for g in targets}
        targets = sorted({g for g in font.getGlyphOrder()
                          if g.split(".")[0] in roots and ".h" not in g} | set(targets))
    targets = [g for g in targets if font["glyf"][g].numberOfContours != 0]
    k = strength
    alts = {i: [] for i in range(1, N_ALTS + 1)}
    for g in targets:
        adv = font["hmtx"][g][0]
        gl = font["glyf"][g]
        gl.recalcBounds(font["glyf"])
        cx = (gl.xMin + gl.xMax) / 2
        if joined:
            for i in list(range(1, N_ALTS + 1)) + [0]:
                # i=0 deforma a própria letra padrão (nenhuma sai "perfeita")
                kk = k * (0.6 if i == 0 else 1.0)
                ang = math.radians(rng.uniform(-4.5, 4.5) * kk)
                sh = rng.uniform(-0.07, 0.07) * kk
                sx = 1 + rng.uniform(-0.06, 0.06) * kk
                sy = 1 + rng.uniform(-0.09, 0.09) * kk
                dy = rng.uniform(-0.035, 0.035) * upm * kk
                cy = upm * 0.25
                c, s_ = math.cos(ang), math.sin(ang)
                a, b, cc, d = sx * c, sx * s_, -sy * s_ + sh, sy * c
                mat = (a, b, cc, d, cx - a * cx - cc * cy, cy + dy - b * cx - d * cy)
                tt = TTGlyphPen(None)
                pen = JoinedWarpPen(tt, adv, mat, upm * 0.012 * kk * rng.uniform(0.7, 1.3),
                                    rng.uniform(0.008, 0.014) * 1000 / upm, rng, margin=upm * 0.13)
                draw_glyph(font, g, pen)
                name = g if i == 0 else f"{g}.h{i}"
                add_glyph(font, name, tt.glyph(), adv)
                if i:
                    alts[i].append((g, name))
            continue
        for i in range(1, N_ALTS + 1):
            if True:
                ang = math.radians(rng.uniform(-2.6, 2.6) * k)
                sx = 1 + rng.uniform(-0.035, 0.035) * k
                sy = 1 + rng.uniform(-0.045, 0.045) * k
                dy = rng.uniform(-0.018, 0.018) * upm * k
            c, s = math.cos(ang), math.sin(ang)
            # rotaciona/escala em torno do centro na linha de base
            a, b, cc, d = sx * c, sx * s, -sy * s, sy * c
            e = cx - (a * cx)
            f = dy - (b * cx)
            wob = (upm * 0.007 * k * rng.uniform(0.7, 1.3), rng.uniform(0.010, 0.016) * 1000 / upm, rng)
            new_adv = adv * (1 + (0 if joined else rng.uniform(-0.03, 0.03) * k))
            name = f"{g}.h{i}"
            make_transformed(font, g, name, (a, b, cc, d, e, f), wobble=wob, advance=new_adv)
            alts[i].append((g, name))
    if "GDEF" in font and font["GDEF"].table.GlyphClassDef:
        gcd = font["GDEF"].table.GlyphClassDef.classDefs
        for i in alts:
            for g, n in alts[i]:
                gcd[n] = gcd.get(g, 1)
    return targets, alts


def add_calt(font, targets, alts):
    """Alternância pseudoaleatória: estado(próx) = (estado(ant) + 1 + hash(letra)) % 4."""
    groups = [[g for i, g in enumerate(targets) if (hash_name(g) % 2) == h] for h in (0, 1)]
    states = [targets] + [[n for _, n in alts[i]] for i in range(1, N_ALTS + 1)]
    n_states = N_ALTS + 1
    fea = []
    for h in (0, 1):
        fea.append(f"@D{h} = [{' '.join(groups[h])}];")
    for s in range(n_states):
        fea.append(f"@S{s} = [{' '.join(states[s])}];")
    space = font.getBestCmap().get(32)
    for i in range(1, N_ALTS + 1):
        fea.append(f"lookup H{i} {{")
        fea.append("  " + " ".join(f"sub {g} by {n};" for g, n in alts[i]))
        fea.append(f"}} H{i};")
    fea.append("lookup HUMAN {")
    for s in range(n_states):
        for h in (0, 1):
            nxt = (s + 1 + h) % n_states
            if nxt == 0:
                fea.append(f"  ignore sub @S{s} @D{h}';")
            else:
                fea.append(f"  sub @S{s} @D{h}' lookup H{nxt};")
    if space:
        # 1ª letra da palavra também varia, conforme a letra seguinte
        fea.append(f"  sub {space} @D0' lookup H1 @D0;")
        fea.append(f"  sub {space} @D0' lookup H3 @D1;")
        fea.append(f"  sub {space} @D1' lookup H2 @D0;")
    fea.append("} HUMAN;")
    fea.append("feature calt { lookup HUMAN; } calt;")
    fea_text = "\n".join(fea)

    # Compila numa cópia e anexa as lookups ao GSUB original (preserva liga/calt existentes)
    tmp = copy.deepcopy(font)
    if "GSUB" in tmp:
        del tmp["GSUB"]
    addOpenTypeFeaturesFromString(tmp, fea_text, tables=["GSUB"])
    new = tmp["GSUB"].table
    if "GSUB" not in font:
        font["GSUB"] = tmp["GSUB"]
        return
    gsub = font["GSUB"].table
    off = len(gsub.LookupList.Lookup)
    for lk in new.LookupList.Lookup:
        for st in lk.SubTable:
            for attr in ("SubstLookupRecord",):
                for r in getattr(st, attr, None) or []:
                    r.LookupListIndex += off
            for rs in (getattr(st, "ChainSubClassSet", None) or []):
                for rule in (getattr(rs, "ChainSubClassRule", None) or []):
                    for r in rule.SubstLookupRecord:
                        r.LookupListIndex += off
            for rs in (getattr(st, "ChainSubRuleSet", None) or []):
                for rule in (getattr(rs, "ChainSubRule", None) or []):
                    for r in rule.SubstLookupRecord:
                        r.LookupListIndex += off
        gsub.LookupList.Lookup.append(lk)
    gsub.LookupList.LookupCount = len(gsub.LookupList.Lookup)
    human_idx = [off + fr.Feature.LookupListIndex[0] for fr in new.FeatureList.FeatureRecord][0]

    from fontTools.ttLib.tables import otTables as ot
    calt_indices = [i for i, fr in enumerate(gsub.FeatureList.FeatureRecord) if fr.FeatureTag == "calt"]
    if calt_indices:
        for i in calt_indices:
            f = gsub.FeatureList.FeatureRecord[i].Feature
            f.LookupListIndex.append(human_idx)
            f.LookupCount = len(f.LookupListIndex)
    else:
        fr = ot.FeatureRecord()
        fr.FeatureTag = "calt"
        fr.Feature = ot.Feature()
        fr.Feature.FeatureParams = None
        fr.Feature.LookupListIndex = [human_idx]
        fr.Feature.LookupCount = 1
        gsub.FeatureList.FeatureRecord.append(fr)
        gsub.FeatureList.FeatureCount = len(gsub.FeatureList.FeatureRecord)
        idx = gsub.FeatureList.FeatureCount - 1
        for sr in gsub.ScriptList.ScriptRecord:
            lss = [sr.Script.DefaultLangSys] + [l.LangSys for l in sr.Script.LangSysRecord]
            for ls in lss:
                if ls is None:
                    continue
                ls.FeatureIndex.append(idx)
                ls.FeatureCount = len(ls.FeatureIndex)
        # Ordena FeatureList por tag (exigência da spec) remapeando índices
        recs = gsub.FeatureList.FeatureRecord
        order = sorted(range(len(recs)), key=lambda i: recs[i].FeatureTag)
        remap = {old: new_i for new_i, old in enumerate(order)}
        gsub.FeatureList.FeatureRecord = [recs[i] for i in order]
        for sr in gsub.ScriptList.ScriptRecord:
            lss = [sr.Script.DefaultLangSys] + [l.LangSys for l in sr.Script.LangSysRecord]
            for ls in lss:
                if ls is None:
                    continue
                ls.FeatureIndex = sorted(remap[i] for i in ls.FeatureIndex)
                if ls.ReqFeatureIndex != 0xFFFF:
                    ls.ReqFeatureIndex = remap[ls.ReqFeatureIndex]


def hash_name(n):
    h = 2166136261
    for ch in n.encode():
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h >> 7


def rename(font, family, base_name):
    ps = family.replace(" ", "") + "-Regular"
    nt = font["name"]
    for rec in list(nt.names):
        if rec.nameID in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
            nt.removeNames(nameID=rec.nameID)
    for nid, val in ((1, family), (2, "Regular"), (3, f"{ps};Escrevedor"),
                     (4, f"{family} Regular"), (6, ps)):
        nt.setName(val, nid, 3, 1, 0x409)
        nt.setName(val, nid, 1, 0, 0)
    old = nt.getDebugName(0) or ""
    nt.setName(f"{old} Modified Version: '{family}' derivada de {base_name} "
               "(variantes humanizadas e suporte ABNT2).", 0, 3, 1, 0x409)
    nt.setName("This Font Software is licensed under the SIL Open Font License, Version 1.1.", 13, 3, 1, 0x409)
    nt.setName("https://openfontlicense.org", 14, 3, 1, 0x409)


def main(src_dir, out_dir):
    out = Path(out_dir)
    (out / "ttf").mkdir(parents=True, exist_ok=True)
    for i, (fn, family, strength, joined) in enumerate(FONTS):
        print(f"→ {family}  ({fn})")
        font = TTFont(Path(src_dir) / fn)
        if "fvar" in font:
            font = instancer.instantiateVariableFont(font, {"wght": 400}, updateFontNames=False)
        if font["post"].formatType == 3:
            font["post"].formatType = 2.0
            font["post"].extraNames = []
            font["post"].mapping = {}
        added = fill_missing(font)
        if added:
            print("   adicionados:", "".join(added))
        targets, alts = humanize(font, strength, joined, seed=1000 + i)
        add_calt(font, targets, alts)
        rename(font, family, fn.split("[")[0].split("-")[0].replace(".ttf", ""))
        font["maxp"].recalc(font)
        slug = family.replace(" ", "")
        font.flavor = None
        font.save(out / "ttf" / f"{slug}.ttf")
        font.flavor = "woff2"
        font.save(out / f"{slug}.woff2")
        print(f"   {len(targets)} glifos x {N_ALTS} variantes")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
