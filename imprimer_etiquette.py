#!/opt/homebrew/bin/python3
"""Imprime le bon d'envoi Chronopost (PDF) sur la Rongta RP425 en 4x6 pouces.

Usage :
    imprimer_etiquette.py [fichier.pdf] [--sans-impression] [--sans-dialogue]
                          [--parties=etiquette,fiche,depot]

Sans fichier : prend le PDF « bon d'envoi » le plus récent de ~/Downloads.
Étapes : repérer le cadre de l'étiquette, générer le ZPL compressé (RLE),
afficher l'aperçu, demander confirmation, imprimer.
"""
import glob
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

W, H, RB = 812, 1218, 102          # 4x6 pouces à 203 dpi, 102 octets par ligne
FILE_PAR_DEFAUT = "_RP425_ZPL_203DPI_"
MARGE_COTE = 24                     # 3 mm à 203 dpi, de chaque côté de l'étiquette
DOSSIER = os.path.dirname(os.path.abspath(__file__))
SORTIE = os.path.join(DOSSIER, "dernier")


def outil(nom):
    chemin = shutil.which(nom) or os.path.join("/opt/homebrew/bin", nom)
    if not os.path.exists(chemin):
        chemin = os.path.join("/usr/local/bin", nom)
    if not os.path.exists(chemin):
        raise SystemExit("Outil introuvable : %s (installer poppler : brew install poppler)" % nom)
    return chemin


def erreur(texte):
    sys.stderr.write(texte + "\n")
    if "--sans-dialogue" not in sys.argv:
        subprocess.run(["osascript", "-e",
                        'display dialog "%s" with title "Étiquette Chronopost RP425" buttons {"OK"} default button "OK" with icon stop'
                        % texte.replace('"', "'")], capture_output=True)
    sys.exit(1)


def trouver_pdf(args):
    for a in args:
        if not a.startswith("--") and a.lower().endswith(".pdf"):
            return a
    candidats = glob.glob(os.path.expanduser("~/Downloads/*.pdf"))
    candidats = [c for c in candidats if re.search(r"chronopost|chrono|envoi|colis", os.path.basename(c), re.I)]
    if not candidats:
        erreur("Aucun bon d'envoi trouvé dans Téléchargements. Glisse le PDF sur l'application.")
    return max(candidats, key=os.path.getmtime)


def pgm(chemin):
    d = open(chemin, "rb").read()
    m = re.match(rb"P5\s+(\d+)\s+(\d+)\s+255\s", d)
    w, h = int(m.group(1)), int(m.group(2))
    return w, h, d[len(d) - w * h:]


def encadré(img, w, h, zx0, zx1, zy0, zy1, min_ligne, min_colonne):
    """Plus grand rectangle tracé dans la zone : (x0, y0, largeur, hauteur) en pixels, ou None."""
    sombre = bytes(1 if i < 200 else 0 for i in range(256))
    lignes = []
    for y in range(zy0, zy1):
        s = img[y * w + zx0:y * w + zx1].translate(sombre)
        if max((len(m.group()) for m in re.finditer(rb"\x01+", s)), default=0) > min_ligne:
            lignes.append(y)
    colonnes, haut, bas = [], h, 0
    for x in range(zx0, zx1):
        s = img[zy0 * w + x:zy1 * w:w].translate(sombre)
        trait = max(re.finditer(rb"\x01+", s), key=lambda m: len(m.group()), default=None)
        if trait and len(trait.group()) > min_colonne:
            colonnes.append(x)
            haut, bas = min(haut, zy0 + trait.start()), max(bas, zy0 + trait.end())
    # La hauteur vient des montants du cadre : un trait horizontal voisin (autre encadré) ne l'allonge pas
    lignes = [y for y in lignes if haut - 2 <= y <= bas + 2]
    if len(lignes) < 2 or len(colonnes) < 2:
        return None
    x0 = min(colonnes)
    return x0, haut, max(colonnes) - x0 + 2, bas - haut + 2


def repérer(pdf, tmp):
    """Bon Chronopost en A4 paysage, pixels à 288 dpi.
    Étiquette : grand cadre de la moitié droite (rapport ~1,31, tient en largeur dans le 4x6).
    Fiche destinataire : cadre du quart haut gauche, imprimé tourné d'un quart de tour."""
    base = os.path.join(tmp, "page")
    subprocess.run([outil("pdftoppm"), "-r", "288", "-gray", "-singlefile", pdf, base], check=True)
    w, h, img = pgm(base + ".pgm")
    if w < h:
        erreur("Ce PDF n'est pas en paysage : ce n'est pas la mise en page Chronopost attendue. Rien imprimé.")
    etiquette = encadré(img, w, h, int(w * 0.55), w, 0, h, 0.3 * w, 0.5 * h)
    if etiquette is None:
        erreur("Cadre de l'étiquette introuvable : ce PDF n'a pas la mise en page Chronopost attendue.")
    rapport = etiquette[3] / etiquette[2]
    if not 1.2 <= rapport <= H / W:
        erreur("Le cadre détecté n'entre pas dans le 4x6 (rapport %.2f, attendu entre 1,20 et 1,50). Rien imprimé." % rapport)
    fiche = encadré(img, w, h, 0, int(w * 0.35), 0, h // 2, 0.2 * w, 0.3 * h)
    if fiche is None:
        erreur("Cadre de la fiche destinataire introuvable : ce PDF n'a pas la mise en page Chronopost attendue.")
    return etiquette, fiche, repérer_depot(img, w, h, fiche)


def repérer_depot(img, w, h, fiche):
    """Preuve de dépôt : la zone sous la fiche, entre le pointillé horizontal (sous la fiche)
    et le pointillé vertical (à gauche de l'étiquette). Reçu Shop2Shop, aide-mémoire, case
    « Cachet » du relais. Recadrée au plus près de l'encre. None si les pointillés manquent."""
    sombre = bytes(1 if i < 200 else 0 for i in range(256))
    bas_fiche = fiche[1] + fiche[3]
    # Pointillé horizontal : la ligne aux plus nombreuses alternances, juste sous la fiche
    alternances = [(len(re.findall(rb"\x00\x01", img[y * w:y * w + w // 2].translate(sombre))), y)
                   for y in range(bas_fiche + 5, min(h, bas_fiche + 120))]
    n, haut = max(alternances, default=(0, 0))
    # Pointillé vertical : la colonne la plus encrée de la moitié basse, au milieu de la page
    encre = [(img[(h // 2) * w + x::w].translate(sombre).count(1), x) for x in range(int(0.4 * w), int(0.6 * w))]
    m, droite = max(encre, default=(0, 0))
    if n < 20 or m < 0.2 * h:
        return None
    zone = [(x, y) for y in range(haut + 12, h, 2) for x in range(0, droite - 8, 2) if img[y * w + x] < 200]
    if not zone:
        return None
    x0, x1 = min(p[0] for p in zone), max(p[0] for p in zone)
    y0, y1 = min(p[1] for p in zone), max(p[1] for p in zone)
    x0, y0 = max(0, x0 - 12), max(haut + 6, y0 - 12)       # la marge ne remonte pas jusqu'au pointillé
    return x0, y0, min(droite - 8, x1 + 12) - x0, min(h, y1 + 12) - y0


def rendre(pdf, tmp, nom, dpi, x, y, lw, lh):
    base = os.path.join(tmp, nom)
    subprocess.run([outil("pdftoppm"), "-r", repr(dpi), "-x", str(x), "-y", str(y), "-W", str(lw), "-H", str(lh),
                    "-gray", "-singlefile", pdf, base], check=True)
    w, h, img = pgm(base + ".pgm")
    return w, h, img


def binariser(g, gw, gh, seuil, ox=0, oy=0, trame=None):
    """trame=(bas, haut) : les gris de cet intervalle deviennent un point sur quatre,
    pour qu'un texte blanc posé sur un aplat gris reste lisible."""
    b = bytearray(W * H)
    for y in range(min(gh, H - oy)):
        lig = g[y * gw:(y + 1) * gw]
        base = (y + oy) * W + ox
        for x in range(min(gw, W - ox)):
            v = lig[x]
            if trame and trame[0] <= v <= trame[1]:
                b[base + x] = 1 if x % 2 == 0 and y % 2 == 0 else 0
            elif v < seuil:
                b[base + x] = 1
    return b


def tourner_gauche(g, gw, gh):
    """Quart de tour dans le sens inverse des aiguilles d'une montre : (gh, gw, image)."""
    r = bytearray(gw * gh)
    for y in range(gh):
        lig = g[y * gw:(y + 1) * gw]
        for x in range(gw):
            r[(gw - 1 - x) * gh + y] = lig[x]
    return gh, gw, bytes(r)


def cadre_noir(b, x0=0, x1=W, y0=0, y1=H, epaisseur=3):
    for y in range(y0, y1):
        for x in range(x0, x1):
            if x < x0 + epaisseur or x >= x1 - epaisseur or y < y0 + epaisseur or y >= y1 - epaisseur:
                b[y * W + x] = 1


def lignes_hex(b):
    out = []
    for y in range(H):
        r = bytearray()
        for xb in range(RB):
            v = 0
            for k in range(8):
                x = xb * 8 + k
                v = (v << 1) | (b[y * W + x] if x < W else 0)
            r.append(v)
        out.append(r.hex().upper())
    return out


def _nombre(n):
    s = ""
    while n >= 400:
        s += "z"
        n -= 400
    if n >= 20:
        s += chr(ord("g") + n // 20 - 1)
        n %= 20
    if n:
        s += chr(ord("G") + n - 1)
    return s


def _ligne_rle(row):
    if set(row) == {"0"}:
        return ","
    if set(row) == {"F"}:
        return "!"
    queue = ""
    t = row.rstrip("0")
    if len(row) - len(t) > 0 and t:
        row, queue = t, ","
    else:
        t2 = row.rstrip("F")
        if len(row) - len(t2) > 0 and t2:
            row, queue = t2, "!"
    out, i = "", 0
    while i < len(row):
        j = i
        while j < len(row) and row[j] == row[i]:
            j += 1
        n = j - i
        out += (_nombre(n) + row[i]) if n > 1 else row[i]
        i = j
    return out + queue


def decoder(flux):
    """Décodeur indépendant du RLE ZPL, pour vérifier ce qu'on envoie."""
    out, cur, prev, n, i = [], "", "", 0, 0
    while len(out) < H and i < len(flux):
        c = flux[i]
        i += 1
        if c == ":":
            out.append(prev)
            continue
        if c in ",!":
            cur += ("0" if c == "," else "F") * (2 * RB - len(cur))
            out.append(cur)
            prev, cur, n = cur, "", 0
            continue
        if c in "0123456789ABCDEF":
            cur += c * max(n, 1)
            n = 0
        elif "g" <= c <= "z":
            n += 20 * (ord(c) - ord("g") + 1)
        elif "G" <= c <= "Y":
            n += ord(c) - ord("G") + 1
        if len(cur) == 2 * RB:
            out.append(cur)
            prev, cur = cur, ""
    return out


def vers_zpl(b):
    lignes = lignes_hex(b)
    flux, prec = "", None
    for r in lignes:
        flux += ":" if r == prec else _ligne_rle(r)
        prec = r
    if decoder(flux) != lignes:
        erreur("Vérification interne échouée : la compression ZPL ne redonne pas l'image. Rien imprimé.")
    total = RB * H
    return ("^XA\n^MMT\n^PW%d\n^LL%d\n^LS0\n^LH0,0\n^FO0,0^GFA,%d,%d,%d,%s^FS\n^PQ1,0,1,N\n^XZ\n"
            % (W, H, total, total, RB, flux)), flux


def png_1bit(images):
    """Aperçu : plusieurs images 812x1218 côte à côte, séparées de 40 points gris."""
    sep = 40
    largeur = len(images) * W + (len(images) - 1) * sep
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        ligne = bytearray(largeur)
        for k, b in enumerate(images):
            o = k * (W + sep)
            for x in range(W):
                ligne[o + x] = 0 if b[y * W + x] else 1
            for x in range(W, W + sep if k < len(images) - 1 else W):
                if o + x < largeur:
                    ligne[o + x] = 0 if (x - W) % 2 == 0 and y % 2 == 0 else 1
        for xb in range((largeur + 7) // 8):
            v = 0
            for kk in range(8):
                x = xb * 8 + kk
                v = (v << 1) | (ligne[x] if x < largeur else 1)
            raw.append(v)

    def bloc(t, s):
        return struct.pack(">I", len(s)) + t + s + struct.pack(">I", zlib.crc32(t + s) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, H, 1, 0, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(bytes(raw), 9)) + bloc(b"IEND", b""))


def file_par_defaut():
    r = subprocess.run(["lpstat", "-d"], capture_output=True, text=True)
    m = re.search(r":\s*(\S+)\s*$", r.stdout.strip())
    return m.group(1) if m else FILE_PAR_DEFAUT


PARTIES = [("etiquette", "Étiquette"), ("fiche", "Fiche destinataire"), ("depot", "Preuve de dépôt")]


def redresser(pdf, tmp, nom, cadre):
    """Cadre imprimé d'un quart de tour sur le bon : redressé, ajusté dans le 4x6 avec la marge des côtés."""
    x0, y0, cw0, ch0 = cadre
    echelle = min((W - 2 * MARGE_COTE) / ch0, (H - 2 * MARGE_COTE) / cw0)
    g = rendre(pdf, tmp, nom, 288 * echelle, round(x0 * echelle), round(y0 * echelle),
               round(cw0 * echelle), round(ch0 * echelle))
    gw, gh, g = tourner_gauche(g[2], g[0], g[1])
    return binariser(g, gw, gh, 140, ox=MARGE_COTE, oy=MARGE_COTE, trame=(150, 195))


def choisir(disponibles):
    """Liste à cocher : renvoie les clés choisies, ou [] si annulé."""
    noms = [n for k, n in PARTIES if k in disponibles]
    script = ('choose from list {%s} with title "Étiquette Chronopost RP425" '
              'with prompt "Aperçu ouvert. Que faut-il imprimer ? (⌘-clic pour en cocher plusieurs)" '
              'default items {"Étiquette"} with multiple selections allowed') % ", ".join('"%s"' % n for n in noms)
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    sortie = r.stdout.strip()
    if r.returncode != 0 or sortie in ("", "false"):
        return []
    retenus = [s.strip() for s in sortie.split(", ")]
    return [k for k, n in PARTIES if n in retenus]


def main():
    args = sys.argv[1:]
    pdf = trouver_pdf(args)
    os.makedirs(SORTIE, exist_ok=True)
    images = {}
    with tempfile.TemporaryDirectory() as tmp:
        (x0, y0, fw, fh), fiche, depot = repérer(pdf, tmp)

        # Étiquette : sans déformation, centrée, avec une marge sur les côtés.
        # Au ras du papier, la RP425 tronquait le cadre et le texte côté droit (essai du 2026-10-17).
        lw = W - 2 * MARGE_COTE
        dpi = 288 * lw / fw
        lh = min(H, round(fh * dpi / 288))
        haut = (H - lh) // 2
        gw, gh, g = rendre(pdf, tmp, "etiquette", dpi, round(x0 * dpi / 288), round(y0 * dpi / 288), lw, lh)
        images["etiquette"] = binariser(g, gw, gh, 170, ox=MARGE_COTE, oy=haut)
        cadre_noir(images["etiquette"], MARGE_COTE, MARGE_COTE + lw, haut, haut + lh)

        # Fiche destinataire et preuve de dépôt : imprimées d'un quart de tour sur le bon
        images["fiche"] = redresser(pdf, tmp, "fiche", fiche)
        if depot:
            images["depot"] = redresser(pdf, tmp, "depot", depot)

    fichiers = {}
    for k, b in images.items():
        fichiers[k] = os.path.join(SORTIE, {"etiquette": "etiquette", "fiche": "fiche", "depot": "preuve-depot"}[k] + "-4x6.zpl")
        open(fichiers[k], "w").write(vers_zpl(b)[0])
    apercu = os.path.join(SORTIE, "apercu.png")
    open(apercu, "wb").write(png_1bit([images[k] for k, _ in PARTIES if k in images]))
    print("PDF :", pdf)
    for k, f in fichiers.items():
        print("ZPL :", f, os.path.getsize(f), "octets")
    if "depot" not in images:
        print("Preuve de dépôt introuvable sur ce bon : non proposée.")
    print("Aperçu :", apercu)

    if "--sans-impression" in args:
        return
    if any(os.path.getsize(f) > 60000 for f in fichiers.values()):
        erreur("Fichier ZPL trop gros (> 60 Ko) : l'imprimante le tronquerait. Rien imprimé.")

    demande = [a.split("=", 1)[1] for a in args if a.startswith("--parties=")]
    if demande:
        choix = [k for k in demande[0].split(",") if k in images]
        if not choix:
            erreur("--parties : choisir parmi " + ", ".join(images) + ". Rien imprimé.")
    elif "--sans-dialogue" in args:
        choix = ["etiquette"]
    else:
        subprocess.run(["open", "-a", "Preview", apercu])
        choix = choisir(images)
    if not choix:
        print("Annulé, rien imprimé.")
        return
    file_ = file_par_defaut()
    for k in choix:
        r = subprocess.run(["lpr", "-P", file_, "-o", "raw", fichiers[k]], capture_output=True, text=True)
        if r.returncode != 0:
            erreur("L'envoi à l'imprimante a échoué : " + (r.stderr.strip() or "erreur lpr"))
    print("Envoyé à", file_, ":", ", ".join(choix))
    if "--sans-dialogue" not in args:
        subprocess.run(["osascript", "-e",
                        'display notification "%d étiquette(s) envoyée(s) à l\'imprimante" with title "Étiquette Chronopost RP425"'
                        % len(choix)], capture_output=True)


if __name__ == "__main__":
    main()
